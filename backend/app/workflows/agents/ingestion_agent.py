from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from app.services.llm import llm_service
from app.services.embedding import embedding_service
from app.services.multimedia import multimedia_service
from app.schemas.extraction import Extraction, NoteInput
from app.core.logging_config import get_component_logger
import uuid
from datetime import datetime
import asyncio

logger = get_component_logger("IngestionPipeline")

# Global Concurrency Limit: 2 parallel ingestions max to protect Supabase/Ollama
concurrency_limit = asyncio.Semaphore(2)


# 1. Define Agent State
class IngestionState(TypedDict):
    input: NoteInput
    content: str
    extraction: Optional[Extraction]
    embedding: Optional[List[float]]
    note_id: Optional[str]
    created_at: Optional[str]
    errors: List[str]
    status: str  # START, MULTIMEDIA_DONE, EXTRACTED, INDEXED
    logs: List[str]
    is_complex: bool


# 2. Node Functions
async def multimodal_node(state: IngestionState):
    logs = state.get("logs", [])
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] START: Processing Multimedia..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("Processing Multimedia Sources...")

    # Acquire semaphore for the entire workflow (held implicitly by the chain? No, we need to wrap the whole graph execution)
    # Actually, wrapping inside a node only throttles that node.
    # To throttle the whole workflow, we should modify the background runner in `ingestion.py` instead.
    # BUT, we can add it here as a "Gatekeeper" in the first node.
    async with concurrency_limit:
        logger.info(
            f"Sempahore Acquired. (Active: {2 - concurrency_limit._value + 1 if hasattr(concurrency_limit, '_value') else '?'})"
        )
        # Proceed logic...
        content = state["input"].content or ""
    changed = False

    # Unified File Link Parsing [📎 Filename](URL) or [🎤 Voice Recording](URL)
    import re

    # Match both attachment icon and microphone icon
    file_matches = re.findall(r"\[(?:📎|🎤) (.*?)\]\((http.*?|/uploads/.*?)\)", content)
    for filename, url in file_matches:
        logger.info(f"Processing File: {filename} ({url})")
        try:
            lower_url = url.lower()

            # --- AUDIO ---
            if lower_url.endswith((".webm", ".m4a", ".mp3", ".wav", ".ogg", ".mp4")):
                logger.info(f"Detected Audio. Transcribing...")
                transcription = await asyncio.to_thread(
                    multimedia_service.transcribe_audio, url
                )
                snippet = (
                    transcription[:100].replace("\n", " ") + "..."
                    if len(transcription) > 100
                    else transcription
                )
                logger.info(f'Audio Result ({len(transcription)} chars): "{snippet}"')
                content += f"\n\n[Audio Transcript ({filename})]: {transcription}"
                changed = True

            # --- PDF ---
            elif lower_url.endswith(".pdf"):
                logger.info(f"Detected PDF. Extracting text...")
                pdf_text = await asyncio.to_thread(
                    multimedia_service.extract_text_from_pdf, url
                )
                snippet = (
                    pdf_text[:100].replace("\n", " ") + "..."
                    if len(pdf_text) > 100
                    else pdf_text
                )
                logger.info(f'PDF Result ({len(pdf_text)} chars): "{snippet}"')
                content += f"\n\n[PDF Extraction ({filename})]: {pdf_text}"
                changed = True

            # --- IMAGE ---
            elif lower_url.endswith((".jpg", ".jpeg", ".png", ".webp")):
                logger.info(f"Detected Image. Describing...")
                img_desc = await asyncio.to_thread(
                    multimedia_service.describe_image, url
                )
                logger.info(f'Image Description: "{img_desc}"')
                content += f"\n\n[Image Description ({filename})]: {img_desc}"
                changed = True

            else:
                logger.info(f"Skipped (Unsupported Type): {url}")

        except Exception as e:
            logger.error(f"File Processing Failed: {e}")

    # CRITICAL: Sync back to Postgres if content changed (Transcription)
    if changed and state.get("note_id"):
        from app.workflows.ingestion import ingestion_workflow

        logger.info(
            f"Syncing extracted text to Postgres for Note {state['note_id']}..."
        )
        await ingestion_workflow._update_note_content_postgres(
            state["note_id"], content
        )

    # Calculate Complexity for "Refiner" Level
    # Heuristic: If content is very long (>3000 chars), mark as complex.
    is_complex = len(content) > 3000
    if is_complex:
        logs.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] INFO: Note marked as COMPLEX (Tier 2 Refinement Enabled)."
        )

    t_end = time.perf_counter()
    logger.info(f"Multimedia processing took: {t_end - t_start:.4f}s")
    return {
        "content": content.strip(),
        "logs": logs,
        "status": "MULTIMEDIA_DONE",
        "is_complex": is_complex,
    }


async def extraction_node(state: IngestionState):
    logs = state["logs"]
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] EXTRACT: Running Knowledge Architect ({llm_service.models_path})..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("Extracting Metadata (Knowledge Architect)...")
    prompt = f"""
    Analyze the following user note and extract structured metadata.
    
    DOMAIN CATEGORIZATION (Choose ONE - CRITICAL):
    Classify based on the PRIMARY SUBJECT MATTER, not the writing style or tone.
    
    - "Academic": The main content is learning material, concepts, theories, research, or educational topics
      Examples: explaining algorithms, discussing papers, studying theories, learning new concepts
      
    - "Professional": The main content is about work, projects, business decisions, or professional activities  
      Examples: team meetings, project updates, technical architecture decisions, work tasks
      
    - "Personal": The main content is personal reflections, emotions, life events, or relationships
      Examples: journal entries about feelings, personal goals unrelated to work/study, daily life reflections

    - "Creative": Poems, song lyrics, or fictional sketches.
      * RULE: Do NOT extract literal Tasks or Entities from metaphors (e.g., "carrying the sun" is not a task).
      * RULE: Extract 'Persona' traits based on the emotional subtext and themes.
      * RULE: Save the full text as an 'ExternalReference':
        - type: "Poem"
        - title: [Original Title or Generated Essence]
        - content: [Full Text]
        - source: "User"

    - "Dreams": Dream journals, nightmares, subconscious imagery, or recurring dream patterns.
      * RULE: Extract symbolic Entities (people, places, objects) that appeared in the dream
      * RULE: Extract Concepts for recurring themes or symbols (e.g., "flying", "water", "chase")
      * RULE: Do NOT extract Tasks from dream narratives (dreams are not actionable)
      * RULE: Extract Persona traits reflecting emotional states during/after the dream
      * FOCUS: Capture symbolic imagery, emotional tone, and recurring patterns
    
    IMPORTANT: A note written in first person ("I learned about X") that explains academic concepts should be classified as Academic, not Personal. Similarly, "We decided in the meeting to use X" should be Professional, not Personal. Look at WHAT the note is about, not HOW it's written.
    
    RULES:
    1. Return ONLY a single valid JSON object. 
    2. ENTITY TYPES: Person, Place, Tool, Organization.
    3. CONCEPT: Abstract themes, topics, or emotional states. EXAMPLES: "Health", "Work", "Productivity", "Stochastic Processes", "Machine Learning".
    4. TASK: Specific actionable goals mentioned.
       - STATUS: Use ONLY these standardized values: "Todo", "Complete", "In Progress", "Cancelled"
       - Do NOT use: "done", "pending", "finished", "open", or any other variations
       - If status is unclear, use "Todo"
    5. PERSONA: Traits about the user's state (for Personal domain only).
    6. REFERENCES: For Academic/Professional domains - extract external citations, quotes, papers, books.
       - type: "Paper", "Book", "Quote", "Video", "Song"
       - title: REQUIRED - Full title of the work (cannot be empty)
       - content: The actual quote or key excerpt (if applicable)
       - source: Author/Artist/Creator name
    7. CRITICAL: Extract text snippets exactly as they appear. Do NOT wrap values in extra quotes. 
       Example: {{"quote": "I am happy"}}, NOT {{"quote": ""I am happy""}}.
    8. NO COMMENTARY: Do not explain your errors or apologize. Return ONLY valid JSON.
    9. ENGLISH ONLY: All output keys and values MUST be in English.

    CONTENT:
    "{state['content']}"

    """
    try:
        extraction = await asyncio.to_thread(
            llm_service.extract_structured, prompt, Extraction
        )
        if not extraction:
            return {"errors": ["LLM returned empty extraction"]}

        # FILTER: Remove garbage entities/concepts
        extraction.entities = [
            e
            for e in extraction.entities
            if e.name
            and e.name.strip().lower() not in ["untitled", "none", "unknown", ""]
        ]
        extraction.concepts = [
            c
            for c in extraction.concepts
            if c.name
            and c.name.strip().lower() not in ["untitled", "none", "unknown", ""]
        ]

        # VALIDATION: Standardize extracted data to prevent quality issues
        from app.utils.data_validation import standardize_extraction

        extraction = standardize_extraction(extraction)

        logger.info(
            f"Extracted: {len(extraction.entities)} entities, {len(extraction.concepts)} concepts, {len(extraction.references)} references."
        )
        logger.info(f"Domain: {extraction.domain}")
        t_end = time.perf_counter()
        logger.info(f"Extraction took: {t_end - t_start:.4f}s")
        return {"extraction": extraction, "logs": logs, "status": "EXTRACTED"}
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        logs.append(f"ERROR: Extraction failed: {e}")
        return {"errors": [f"Extraction failed: {str(e)}"], "logs": logs}


async def embedding_node(state: IngestionState):
    if state.get("errors"):
        return {}
    logs = state["logs"]
    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] EMBED: Generating Vectors...")
    import time

    t_start = time.perf_counter()
    from app.core.config import settings

    logger.info(f"Generating {settings.EMBEDDING_DIMENSIONS}-dim Embedding...")
    full_vector = await asyncio.to_thread(
        embedding_service.embed_query, state["content"]
    )
    t_end = time.perf_counter()
    logger.info(f"Embedding took: {t_end - t_start:.4f}s")
    return {"embedding": full_vector, "logs": logs, "status": "EMBEDDED"}


async def storage_node(state: IngestionState):
    if state.get("errors") or not state.get("extraction"):
        return {"errors": state.get("errors") or ["Missing extraction data"]}

    logs = state["logs"]
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] STORE: Writing to Graph & Postgres..."
    )

    import time

    t_start = time.perf_counter()
    note_id = state.get("note_id") or str(uuid.uuid4())
    created_at = state.get("input").created_at or datetime.now().isoformat()

    from app.workflows.ingestion import ingestion_workflow

    try:
        # 1. Write to Neo4j (The Mind)
        title = await asyncio.to_thread(
            ingestion_workflow._write_ontology,
            note_id,
            state["content"],
            state["extraction"],
            state["embedding"],
            created_at,
        )

        # 2. Sync to Postgres (The Body)
        # Sync Title
        if title:
            await ingestion_workflow._update_note_title_postgres(note_id, title)

        # Sync Domain
        if state["extraction"].domain:
            await ingestion_workflow._update_note_domain_postgres(
                note_id, state["extraction"].domain
            )

        t_end = time.perf_counter()
        logger.info(f"  [Perf] Graph Storage took: {t_end - t_start:.4f}s")
        return {"note_id": note_id, "created_at": created_at}
    except Exception as e:
        logs.append(f"ERROR: Storage failed: {e}")
        return {"errors": [f"Storage failed: {str(e)}"], "logs": logs}


async def summarization_node(state: IngestionState):
    if state.get("errors") or not state.get("extraction"):
        return {}
    logs = state["logs"]
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] SUMMARIZE: Updating Neighborhoods..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("[Agent] Updating Neighborhood Summaries (Delta Updates)...")
    logger.info("[Agent] Updating Neighborhood Summaries (Delta Updates)...")
    from app.workflows.ingestion import ingestion_workflow

    await ingestion_workflow._update_neighborhoods(
        state["extraction"].concepts,
        state["extraction"].entities,
        state["extraction"].tasks,
        state["extraction"].persona_traits,
        state["extraction"].references,
        state["content"],
    )
    t_end = time.perf_counter()
    logger.info(f"  [Perf] Summarization took: {t_end - t_start:.4f}s")

    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] DONE: Ingestion Complete.")
    return {"logs": logs, "status": "INDEXED"}


# 3. Router logic
def should_continue(state: IngestionState):
    if state.get("errors"):
        return "end"
    return "continue"


async def refinement_node(state: IngestionState):
    """
    Tier 2: The Refiner (Reasoning Model)
    Only runs for "Complex" notes.
    Checks for consistencies/conflicts (Simulated for now, can be expanded to RAG).
    """
    if not state.get("is_complex") or not state.get("extraction"):
        return {}  # Skip

    logs = state["logs"]
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Running Reasoning Engine (Tier 2)..."
    )
    logger.info("[Agent] Refinement (Reasoning) triggered...")

    # In a full impl, we would RAG here. For now, we ask it to self-reflect on the extraction quality.
    prompt = f"""
    AUDIT CHECK:
    You are a Quality Assurance Auditor. Review the Extraction below against the Source Text.
    Identify any CRITICAL missing Entities (People, Places, Organizations) that were overlooked.
    
    SOURCE TEXT: 
    "{state['content'][:3000]}..."
    
    CURRENTLY EXTRACTED:
    {[e.name for e in state['extraction'].entities]}
    
    INSTRUCTIONS:
    1. specificy ONLY new/missing entities in the `entities` list.
    2. Leave other fields (summary, concepts) empty unless strictly necessary.
    3. Return valid JSON.
    """
    try:
        # Use DeepSeek-R1 (Architect) to find what it missed
        patch = await asyncio.to_thread(
            llm_service.extract_structured, prompt, Extraction
        )

        if patch and patch.entities:
            # Merge Logic: Prevent duplicates
            existing_names = {e.name.lower() for e in state["extraction"].entities}
            added_count = 0

            for e in patch.entities:
                if e.name and e.name.strip() and e.name.lower() not in existing_names:
                    state["extraction"].entities.append(e)
                    existing_names.add(e.name.lower())
                    added_count += 1

            if added_count > 0:
                logger.info(
                    f"  [Refiner] 🛠️ Patched Extraction: Added {added_count} new entities."
                )
                logs.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Added {added_count} missing entities."
                )
            else:
                logs.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: No new entities found."
                )
        else:
            logs.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Audit passed (No changes)."
            )

    except Exception as e:
        logs.append(f"WARN: Refinement failed: {e}")

    return {"logs": logs, "status": "REFINED", "extraction": state["extraction"]}


def should_refine(state: IngestionState):
    if state.get("errors"):
        return "end"
    if state.get("is_complex"):
        return "refine"
    return "skip"


# 3. Build Graph
workflow = StateGraph(IngestionState)

# Add Nodes
workflow.add_node("multimodal", multimodal_node)
workflow.add_node("extraction", extraction_node)
workflow.add_node("refinement", refinement_node)  # NEW
workflow.add_node("embedding", embedding_node)
workflow.add_node("storage", storage_node)
workflow.add_node("summarization", summarization_node)

# Define Edges
workflow.set_entry_point("multimodal")
workflow.add_edge("multimodal", "extraction")

# Conditional Logic for Tier 2
workflow.add_conditional_edges(
    "extraction",
    should_refine,
    {"refine": "refinement", "skip": "embedding", "end": END},
)
workflow.add_edge("refinement", "embedding")  # After refinement, go to embedding

workflow.add_edge("embedding", "storage")
workflow.add_edge("storage", "summarization")
workflow.add_edge("summarization", END)

# Compile
ingestion_agent = workflow.compile()
