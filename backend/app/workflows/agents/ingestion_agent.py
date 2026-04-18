from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from app.services.llm import llm_service
from app.services.multimedia import multimedia_service
from app.schemas.extraction import Extraction, NoteInput
from app.core.log import get_logger
from app.core.config import settings
import uuid
from datetime import datetime
import asyncio

logger = get_logger("IngestionPipeline")

# Global Concurrency Limit: 1 (sequential) to prevent Gemini API rate limiting/slowdown
concurrency_limit = asyncio.Semaphore(1)


# 1. Define Agent State
class IngestionState(TypedDict):
    input: NoteInput
    content: str
    extraction: Optional[Extraction]
    note_id: Optional[str]
    created_at: Optional[str]
    errors: List[str]
    status: str  # START, MULTIMEDIA_DONE, EXTRACTED, INDEXED
    logs: List[str]


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
            f"Sempahore Acquired. (Active: {1 - concurrency_limit._value + 1 if hasattr(concurrency_limit, '_value') else '?'})"
        )
        # Proceed logic...
        content = state["input"].content or ""
    changed = False
    audio_changed = False  # Audio transcripts must be persisted — text is the only form

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
                audio_changed = (
                    True  # Transcript must be saved — audio file is not re-readable
                )

            # --- PDF ---
            elif lower_url.endswith(".pdf"):
                logger.info("Detected PDF. Extracting text...")
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

            # --- WORD DOCUMENT ---
            elif lower_url.endswith(".docx"):
                logger.info("Detected Word document. Extracting text...")
                doc_text = await asyncio.to_thread(
                    multimedia_service.extract_text_from_docx, url
                )
                snippet = (
                    doc_text[:100].replace("\n", " ") + "..."
                    if len(doc_text) > 100
                    else doc_text
                )
                logger.info(f'Word Result ({len(doc_text)} chars): "{snippet}"')
                content += f"\n\n[Word Extraction ({filename})]: {doc_text}"
                changed = True

            # --- SPREADSHEETS ---
            elif lower_url.endswith((".xlsx", ".xls", ".csv", ".tsv")):
                logger.info("Detected spreadsheet. Extracting text...")
                sheet_text = await asyncio.to_thread(
                    multimedia_service.extract_text_from_spreadsheet, url
                )
                snippet = (
                    sheet_text[:100].replace("\n", " ") + "..."
                    if len(sheet_text) > 100
                    else sheet_text
                )
                logger.info(
                    f'Spreadsheet Result ({len(sheet_text)} chars): "{snippet}"'
                )
                content += f"\n\n[Spreadsheet Extraction ({filename})]: {sheet_text}"
                changed = True

            # --- IMAGE ---
            elif lower_url.endswith((".jpg", ".jpeg", ".png", ".webp")):
                logger.info("Detected Image. Describing...")
                img_desc = await asyncio.to_thread(
                    multimedia_service.describe_image, url
                )
                logger.info(f'Image Description: "{img_desc}"')
                # Generate a short title for the image so it becomes a named entity
                img_title_prompt = (
                    f"Given this image description, provide a concise, specific title "
                    f"(3-7 words) that would serve as a unique entity name.\n\n"
                    f"Description: {img_desc}\n\n"
                    f"Return ONLY the title text, nothing else."
                )
                try:
                    img_title = await llm_service.generate(img_title_prompt, temperature=0.0)
                    img_title = (img_title or "").strip().strip('"').strip("'") or filename
                except Exception:
                    img_title = filename
                logger.info(f'Image Title: "{img_title}"')
                # Format image as a standalone entity so extraction creates a node for it
                content += (
                    f"\n\n[Image: {img_title}]\n"
                    f"The image titled \"{img_title}\" shows the following: {img_desc}"
                )
                changed = True

            else:
                logger.info(f"Skipped (Unsupported Type): {url}")

        except Exception as e:
            logger.error(f"File Processing Failed: {e}")

    # Audio transcripts are synced back to Postgres because the audio file cannot
    # be re-read as text later — the transcript IS the readable content.
    # PDF, document, image, and spreadsheet extractions are NOT synced: the source
    # file remains in MinIO and can always be re-extracted, so the original note
    # preserves its file-link-only format.
    if audio_changed and state.get("note_id"):
        from app.workflows.ingestion import ingestion_workflow

        logger.info(
            f"Syncing audio transcript to Postgres for Note {state['note_id']}..."
        )
        await ingestion_workflow._update_note_content_postgres(
            state["note_id"], content
        )

    t_end = time.perf_counter()
    logger.info(f"Multimedia processing took: {t_end - t_start:.4f}s")
    return {
        "content": content.strip(),
        "logs": logs,
        "status": "MULTIMEDIA_DONE",
    }


async def extraction_node(state: IngestionState):
    logs = state["logs"]
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] EXTRACT: Running Knowledge Architect ({llm_service.models_path})..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("Extracting Metadata (Knowledge Architect)...")

    if settings.BENCHMARK_MODE:
        prompt = f"""<system_role>
You are the "Knowledge Architect" — a structured information extraction engine for encyclopedic and reference material.
</system_role>

<domain>Academic — encyclopedic/Wikipedia-style reference content.</domain>

<node_extraction>
Each node: {{"name": "...", "type": "...", "isolated_context": "..."}}

- name: Exact string from source. Do NOT abbreviate.
  Disambiguate same names with qualifier: "Muhammad (Emir, 1041–1057)" vs "Muhammad (Prophet)".
- type: Free-form specific type from context. Examples: "person", "kingdom", "tournament",
  "song", "film", "organization", "place", "event", "concept", "dynasty". Never "thing".
- isolated_context: Complete verbatim sentence(s) mentioning this node.
  List records with no surrounding sentence → copy verbatim (e.g. "Nuh: 1013/4–1041/2").
  Must contain a finite verb OR be a verbatim list record.

EXHAUSTIVE extraction — every named person, place, organization, event, kingdom, dynasty,
tournament, award, work, abstract concept relevant for multi-hop reasoning.
LIST-FORMAT: every item in a list/table/lineage is a SEPARATE node. Do NOT collapse.
</node_extraction>

<relationship_extraction>
BRIDGE RELATIONSHIPS FIRST (one node connecting two others).
All factual connections where both source_name and target_name exist in nodes above.

Each relationship:
{{
  "source_name": "...",   ← must match a node name exactly
  "target_name": "...",   ← must match a node name exactly
  "relationship_type": "born_in",  ← snake_case verb phrase
  "strength": 8,      ← 1–10: how direct/strong this link is
  "confidence": 8,    ← 1–10: how certain this relationship is from the text
  "relevance": 7,     ← 1–10: how important for multi-hop queries
  "natural_language": "X was born in Y.",
  "context": "verbatim snippet"
}}

Relationship types: born_in, died_in, ruled, led, founded, member_of, part_of, located_in,
succeeded_by, preceded_by, son_of, married_to, fought_against, participated_in, won,
created, directed, wrote, composed, recorded, performed_in, and any specific verb from text.
</relationship_extraction>

<zero_tolerance>
- Copy all dates, numbers, ranges EXACTLY. "1013/4–1041/2" stays "1013/4–1041/2".
- Copy proper nouns verbatim. Do NOT abbreviate.
- isolated_context must be verbatim from source. Never paraphrase.
- No nested quotes: {{"context": "text here"}}, NOT {{"context": ""text here""}}.
- English only.
</zero_tolerance>

<source_text>
{state['content']}
</source_text>
"""
    else:
        prompt = f"""<system_role>
You are the "Knowledge Architect" — analyze user notes and extract a structured knowledge graph.
</system_role>

<domain_categorization>
Set "domain" to the PRIMARY subject matter:
- "Academic": Learning material, concepts, theories, research.
- "Professional": Work, projects, business decisions.
- "Personal": Personal reflections, emotions, life events, relationships.
- "Creative": Poems, song lyrics, fiction.
- "Dreams": Dream journals, nightmares, subconscious imagery.
</domain_categorization>

<node_extraction>
Each node: {{"name": "...", "type": "...", "isolated_context": "..."}}

- name: The entity/concept/task/trait/reference as it appears.
- type: Free-form. Examples: "person", "place", "concept", "task", "emotion",
  "organization", "tool", "event", "book", "song", "persona trait". LLM sets freely.
- isolated_context: ALL verbatim sentences about this node including pronoun-resolved
  follow-up sentences. Track pronouns across paragraphs.

PRONOUN TRACKING EXAMPLE:
"I saw John today. He was happy about his math test."
→ name="John", type="person", isolated_context="I saw John today. He was happy about his math test."

Extract: named people, places, tools, organizations, events, abstract themes,
actionable tasks, emotional traits, external references (books/songs/quotes).
</node_extraction>

<relationship_extraction>
Each relationship:
{{
  "source_name": "...",   ← must match a node name exactly
  "target_name": "...",   ← must match a node name exactly
  "relationship_type": "knows",
  "strength": 7,      ← 1–10
  "confidence": 8,    ← 1–10
  "relevance": 6,     ← 1–10
  "natural_language": "John knows Mary.",
  "context": "verbatim snippet"
}}
CRITICAL: Both source_name and target_name must appear in the nodes list above.
</relationship_extraction>

<zero_tolerance>
- Copy all dates, times, numbers EXACTLY. Do NOT round or paraphrase.
- Copy proper nouns verbatim.
- isolated_context must be copied verbatim. Never paraphrase.
- No nested quotes.
- English only.
</zero_tolerance>

<source_text>
{state['content']}
</source_text>
"""
    try:
        extraction = await asyncio.to_thread(
            llm_service.extract_structured, prompt, Extraction
        )
        if not extraction:
            return {"errors": ["LLM returned empty extraction"]}

        logger.info(f"Extraction Completed: {extraction}")

        # GARBAGE NAME HANDLING: nodes with empty/placeholder names but valid context
        # get a recovery rename; nodes with neither are dropped.
        GARBAGE_NAMES = {"untitled", "none", "unknown", ""}

        clean_nodes = []
        renameable = []
        for n in extraction.nodes:
            val = (n.name or "").strip().lower()
            if val not in GARBAGE_NAMES:
                clean_nodes.append(n)
            elif n.isolated_context:
                renameable.append(n)
            # else: no name and no context — silently drop

        if renameable:
            import json as _json, re as _re

            batch_lines = "\n".join(
                f'{i+1}. (type={n.type}) "{n.isolated_context}"'
                for i, n in enumerate(renameable)
            )
            rename_prompt = (
                "For each numbered excerpt below, provide the most specific descriptive name "
                "for the node it describes (1–5 words each).\n\n"
                "Return null if an excerpt has insufficient information to name specifically.\n\n"
                "Return ONLY a JSON array: "
                '[{"index": 1, "name": "Name Here"}, {"index": 2, "name": null}, ...]\n\n'
                f"{batch_lines}\n\n"
                'Return ONLY: [{"index": 1, "name": "..."}, ...]'
            )
            try:
                rename_resp = await llm_service.generate(rename_prompt, temperature=0.0)
                match = _re.search(r"\[.*?\]", rename_resp, _re.DOTALL)
                if match:
                    name_list = _json.loads(match.group())
                    name_map = {
                        e["index"]: e.get("name")
                        for e in name_list
                        if isinstance(e, dict) and "index" in e
                    }
                    for i, node in enumerate(renameable):
                        new_name = name_map.get(i + 1)
                        if (
                            isinstance(new_name, str)
                            and new_name.strip()
                            and new_name.strip().lower() not in GARBAGE_NAMES
                            and 2 < len(new_name.strip()) <= 80
                        ):
                            node.name = new_name.strip()
                            logger.info(f"  [Rename] Recovered → '{node.name}'")
                            clean_nodes.append(node)
                        else:
                            logger.info(f"  [Rename] Could not recover (response: '{new_name}')")
                else:
                    logger.warning("  [Rename] Could not parse batch rename response.")
            except Exception as rename_err:
                logger.warning(f"  [Rename] Batch rename failed: {rename_err}")

        extraction.nodes = clean_nodes
        logger.info(f"Nodes after rename: {[n.name for n in extraction.nodes]}")
        logger.info(
            f"Extracted: {len(extraction.nodes)} nodes, {len(extraction.relationships)} relationships. Domain: {extraction.domain}"
        )

        t_end = time.perf_counter()
        logger.info(f"Extraction took: {t_end - t_start:.4f}s")
        return {
            "extraction": extraction,
            "logs": logs,
            "status": "EXTRACTED",
        }
    except Exception as e:
        logger.error(f"Extraction Error: {e}")
        logs.append(f"ERROR: Extraction failed: {e}")
        return {"errors": [f"Extraction failed: {str(e)}"], "logs": logs}


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
    custom_title = state.get("input").title  # May be None

    from app.workflows.ingestion import ingestion_workflow

    try:
        # 1. Write to Neo4j (The Mind)
        title = await asyncio.to_thread(
            ingestion_workflow._write_ontology,
            note_id,
            state["content"],
            state["extraction"],
            created_at,
            custom_title,  # Pass custom title if provided
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
    from app.workflows.ingestion import ingestion_workflow

    await ingestion_workflow._update_neighborhoods(
        state["extraction"].nodes,
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
    Tier 2: The Refiner — always runs, iterative audit passes (max 10).
    Each pass shows the model what has been extracted so far and asks what was
    missed. Stops early as soon as a pass finds nothing new.
    """
    if not state.get("extraction"):
        return {}  # Nothing to refine

    logs = state["logs"]
    logger.info("[Agent] Refinement (iterative audit) starting...")

    def _build_audit_prompt(extraction, pass_num):
        existing_names = [n.name for n in extraction.nodes]
        if settings.BENCHMARK_MODE:
            return f"""<system_role>
You are a Named Entity Completeness Auditor running pass {pass_num} of an iterative extraction loop.
Review the already-extracted nodes against the Source Text and identify anything missed.
</system_role>

<audit_tasks>
TASK 1 — MISSING NODES:
Identify any named entity, concept, or work not yet in <already_extracted>.
Especially items in lists, tables, ranked sequences, or dynasty lineages — each is a separate node.
Format: {{"name": "...", "type": "...", "isolated_context": "verbatim sentence(s)"}}
Do NOT repeat already-extracted names.

TASK 2 — MISSING RELATIONSHIPS:
Check for unextracted relationships between ALL nodes (including new ones from TASK 1).
source_name and target_name must EXACTLY match a node name.
Format: {{"source_name": "...", "target_name": "...", "relationship_type": "...",
  "strength": 8, "confidence": 8, "relevance": 7, "natural_language": "...", "context": "..."}}

TASK 3 — THIN CONTEXT ENRICHMENT:
For already-extracted nodes with no finite verb in isolated_context (and not a verbatim list record),
enrich by copying surrounding verbatim sentences. Return as nodes with the same name.
</audit_tasks>

<zero_tolerance>
- Copy all dates, numbers, ranges EXACTLY.
- Copy proper nouns verbatim.
- isolated_context must be verbatim. Never paraphrase.
</zero_tolerance>

<already_extracted>
{existing_names}
</already_extracted>

<source_text>
{state['content']}
</source_text>
"""
        else:
            return f"""<system_role>
You are a Quality Assurance Auditor running pass {pass_num} of an iterative extraction loop.
Review the already-extracted nodes against the Source Text and identify anything missed.
</system_role>

<audit_tasks>
Identify overlooked nodes: people, places, tools, organizations, events, abstract themes,
actionable tasks, emotional traits, external references. Each node:
{{"name": "...", "type": "...", "isolated_context": "verbatim sentence(s)"}}
Do NOT repeat already-extracted names.

Also identify any missing relationships between nodes (including new nodes from this pass).
source_name and target_name must match a node name exactly.
</audit_tasks>

<zero_tolerance>
- Copy all dates, times, numbers EXACTLY.
- Copy proper nouns verbatim.
- isolated_context must be verbatim. Never paraphrase.
</zero_tolerance>

<already_extracted>
{existing_names}
</already_extracted>

<source_text>
{state['content']}
</source_text>
"""

    def _merge_patch(extraction, patch):
        """Merge a patch extraction into the running extraction, deduplicating by name."""
        added = 0
        existing_names = {n.name.lower() for n in extraction.nodes}

        for n in patch.nodes or []:
            if n.name and n.name.strip() and n.name.lower() not in existing_names:
                extraction.nodes.append(n)
                existing_names.add(n.name.lower())
                added += 1

        for rel in patch.relationships or []:
            extraction.relationships.append(rel)

        return added

    extraction = state["extraction"]
    MAX_PASSES = 10
    for pass_num in range(1, MAX_PASSES + 1):
        logs.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Pass {pass_num} (max {MAX_PASSES})..."
        )
        try:
            prompt = _build_audit_prompt(extraction, pass_num)
            patch = await asyncio.to_thread(
                llm_service.extract_structured, prompt, Extraction
            )
            if patch:
                added = _merge_patch(extraction, patch)
                if added > 0:
                    logger.info(
                        f"  [Refiner] Pass {pass_num}: +{added} new nodes — continuing."
                    )
                    logs.append(
                        f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Pass {pass_num} added {added} nodes."
                    )
                else:
                    logger.info(f"  [Refiner] Pass {pass_num}: nothing new — stopping.")
                    logs.append(
                        f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Pass {pass_num} — nothing new, done."
                    )
                    break
            else:
                logs.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Pass {pass_num} — no response, stopping."
                )
                break
        except Exception as e:
            logs.append(f"WARN: Refinement pass {pass_num} failed: {e}")
            logger.warning(f"  [Refiner] Pass {pass_num} failed: {e}")
            break

    return {"logs": logs, "status": "REFINED", "extraction": extraction}


def should_refine(state: IngestionState):
    if state.get("errors"):
        return "end"
    return "refine"


# 3. Build Graph
workflow = StateGraph(IngestionState)

# Add Nodes
workflow.add_node("multimodal", multimodal_node)
workflow.add_node("extraction", extraction_node)
workflow.add_node("refinement", refinement_node)
workflow.add_node("storage", storage_node)
workflow.add_node("summarization", summarization_node)

# Define Edges
workflow.set_entry_point("multimodal")
workflow.add_edge("multimodal", "extraction")

# Refinement always runs (3-pass audit); errors short-circuit to END
workflow.add_conditional_edges(
    "extraction",
    should_refine,
    {"refine": "refinement", "end": END},
)
workflow.add_edge("refinement", "storage")

workflow.add_edge("storage", "summarization")
workflow.add_edge("summarization", END)

# Compile
ingestion_agent = workflow.compile()
