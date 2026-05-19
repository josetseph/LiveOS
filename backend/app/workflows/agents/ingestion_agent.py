"""LangGraph ingestion agent: multimodal → extraction → refinement → storage → indexing."""

# pylint: disable=import-outside-toplevel,protected-access
import asyncio
import uuid
from datetime import datetime
from typing import Any, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.core.log import get_logger
from app.schemas.extraction import Extraction, NoteInput
from app.services.llm import llm_service
from app.services.multimedia import multimedia_service

logger = get_logger("IngestionPipeline")

# Concurrent LLM call limit for the ingestion agent.
# Default is 1 (sequential) to match the original Gemini rate-limit guard.
# For local providers (Ollama / LM Studio) set INGESTION_AGENT_CONCURRENCY > 1
# in .env to enable real parallelism — measure throughput before and after.
concurrency_limit = asyncio.Semaphore(settings.INGESTION_AGENT_CONCURRENCY)


# 1. Define Agent State
class IngestionState(TypedDict):
    """LangGraph state dictionary for the ingestion agent pipeline."""

    input: NoteInput
    content: str
    extraction: Optional[Extraction]
    note_id: Optional[str]
    created_at: Optional[str]
    errors: List[str]
    status: str  # START, MULTIMEDIA_DONE, EXTRACTED, INDEXED
    logs: List[str]
    workflow: Optional[Any]  # KB-specific IngestionWorkflow instance; None → use global default


# 2. Node Functions
async def multimodal_node(
    state: IngestionState,
):  # pylint: disable=too-many-locals,too-many-statements
    """LangGraph node: extract text from any multimedia attachments in the note."""
    logs = state.get("logs", [])
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] START: Processing Multimedia..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("Processing Multimedia Sources...")

    # This gate limits concurrent multimedia processing calls.
    async with concurrency_limit:
        logger.info(
            f"Sempahore Acquired. (Active: {1 - concurrency_limit._value + 1 if hasattr(concurrency_limit, '_value') else '?'})"  # pylint: disable=line-too-long
        )
        content = state["input"].content or ""
        audio_changed = False  # Audio transcripts must be persisted as text

        # Unified file link parsing: [📎 Filename](URL) or [🎤 Voice Recording](URL)
        import re

        file_matches = re.findall(
            r"\[(?:📎|🎤) (.*?)\]\((http.*?|/uploads/.*?)\)", content
        )
        for filename, url in file_matches:
            logger.info(f"Processing File: {filename} ({url})")
            try:
                lower_url = url.lower()

                # --- AUDIO ---
                if lower_url.endswith(
                    (".webm", ".m4a", ".mp3", ".wav", ".ogg", ".mp4")
                ):
                    logger.info("Detected Audio. Transcribing...")
                    transcription = await asyncio.to_thread(
                        multimedia_service.transcribe_audio, url
                    )
                    snippet = (
                        transcription.replace("\n", " ") + "..."
                        if len(transcription) > 100
                        else transcription
                    )
                    logger.info(
                        f'Audio Result ({len(transcription)} chars): "{snippet}"'
                    )
                    content += f"\n\n[Audio Transcript ({filename})]: {transcription}"
                    audio_changed = True

                # --- PDF ---
                elif lower_url.endswith(".pdf"):
                    logger.info("Detected PDF. Extracting text...")
                    pdf_text = await asyncio.to_thread(
                        multimedia_service.extract_text_from_pdf, url
                    )
                    snippet = (
                        pdf_text.replace("\n", " ") + "..."
                        if len(pdf_text) > 100
                        else pdf_text
                    )
                    logger.info(f'PDF Result ({len(pdf_text)} chars): "{snippet}"')
                    content += f"\n\n[PDF Extraction ({filename})]: {pdf_text}"

                # --- WORD DOCUMENT ---
                elif lower_url.endswith(".docx"):
                    logger.info("Detected Word document. Extracting text...")
                    doc_text = await asyncio.to_thread(
                        multimedia_service.extract_text_from_docx, url
                    )
                    snippet = (
                        doc_text.replace("\n", " ") + "..."
                        if len(doc_text) > 100
                        else doc_text
                    )
                    logger.info(f'Word Result ({len(doc_text)} chars): "{snippet}"')
                    content += f"\n\n[Word Extraction ({filename})]: {doc_text}"

                # --- SPREADSHEETS ---
                elif lower_url.endswith((".xlsx", ".xls", ".csv", ".tsv")):
                    logger.info("Detected spreadsheet. Extracting text...")
                    sheet_text = await asyncio.to_thread(
                        multimedia_service.extract_text_from_spreadsheet, url
                    )
                    snippet = (
                        sheet_text.replace("\n", " ") + "..."
                        if len(sheet_text) > 100
                        else sheet_text
                    )
                    logger.info(
                        f'Spreadsheet Result ({len(sheet_text)} chars): "{snippet}"'
                    )
                    content += (
                        f"\n\n[Spreadsheet Extraction ({filename})]: {sheet_text}"
                    )

                # --- IMAGE ---
                elif lower_url.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    logger.info("Detected Image. Describing...")
                    img_desc = await asyncio.to_thread(
                        multimedia_service.describe_image, url
                    )
                    logger.info(f'Image Description: "{img_desc}"')

                    # Generate a short title so the image becomes a named entity.
                    img_title_prompt = (
                        "Given this image description, provide a concise, specific title "
                        "that would serve as a unique entity name.\n\n"
                        f"Description: {img_desc}\n\n"
                        "Return ONLY the title text, nothing else."
                    )
                    try:
                        img_title = await llm_service.ingestion_generate(
                            img_title_prompt,
                            temperature=0.0,
                        )
                        img_title = (img_title or "").strip().strip('"').strip(
                            "'"
                        ) or filename
                    except Exception:  # pylint: disable=broad-exception-caught
                        img_title = filename

                    content += (
                        f"\n\n[Image: {img_title}]\n"
                        f'The image titled "{img_title}" shows the following: {img_desc}'
                    )

                else:
                    logger.info(f"Skipped (Unsupported Type): {url}")

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(f"File Processing Failed: {e}")

        # Audio transcripts are synced back to Postgres because audio files are
        # not directly re-readable as text. Other file types can be re-extracted.
        if audio_changed and state.get("note_id"):
            from app.workflows.ingestion import ingestion_workflow as _default_wf

            _wf = state.get("workflow") or _default_wf
            logger.info(
                f"Syncing audio transcript to Postgres for Note {state['note_id']}..."
            )
            await _wf._update_note_content_postgres(
                state["note_id"], content
            )

    t_end = time.perf_counter()
    logger.info(f"Multimedia processing took: {t_end - t_start:.4f}s")
    return {
        "content": content.strip(),
        "logs": logs,
        "status": "MULTIMEDIA_DONE",
    }


async def extraction_node(
    state: IngestionState,
):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """LangGraph node: run structured LLM extraction to produce an Extraction object."""
    logs = state["logs"]
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] EXTRACT: Running Knowledge Architect ({llm_service.models_path})..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("Extracting Metadata (Knowledge Architect)...")

    # Prepend the user-provided title so the LLM sees it as part of the source
    # text. Auto-generated titles are not included — they don't originate from
    # the note itself and would pollute the extraction.
    extraction_content = state["content"]
    if state["input"].title:
        extraction_content = f"# {state['input'].title}\n\n{extraction_content}"

    prompt = f"""You are a precision knowledge extraction engine. Your sole function is to decompose any input note into a fully structured knowledge graph — extracting every entity, every relationship, and generating an isolated contextual description for each entity as it exists *within the note only*.  # pylint: disable=line-too-long

---

## CORE RULES

- Extract **every** entity, no matter how minor. Do not skip implicit or background entities.
- Do **not** use outside knowledge. Every piece of context must be grounded in the note.
- Do **not** hallucinate relationships. If it isn't stated or strongly implied by the text, it doesn't exist.
- Co-reference resolution is mandatory: if "he", "she", "it", "they", "the city", "the war" refers to a named entity, map it back to that entity — do not treat pronouns as separate entities.
- Every relationship must be directional. Use `->` for one-way and `<->` for mutual/bidirectional.
- Entity names must be **canonical** — pick one consistent name per entity (e.g., don't list "Adwa" and "Battle of Adwa" as separate entities if they refer to the same thing).

---

## STEP-BY-STEP PROCESS

Follow these steps in order. Do not skip any.

### STEP 1 — Entity Extraction
Identify every distinct entity in the note. For each, assign:
- `name`: The canonical name of the entity.
- `type`: The following are examples and not an exhaustive list — use your judgment to classify each entity into the most fitting type based on its nature and role in the note:
  - `Person` — a human individual
  - `Place` — a physical or geographic location
  - `Organization` — a group, nation, army, or institution (governments, companies, teams, schools)
  - `Event` — a specific occurrence with a defined scope
  - `Work` — a creative or intellectual work such as a book, film, TV series, album, article, or artwork
  - `Thing` — a physical object, document, or artifact
  - `Concept` — an abstract idea, principle, or condition (e.g., "sovereignty", "friendship")
  - `Time Period` — a specific date, duration, era, or recurring time (e.g., "Weekend", "2 March 1896")
- `type_reasoning`: One sentence explaining why you chose this type for this entity. Be specific — mention the key clue from the note that determined the classification.

### STEP 2 — Relationship Extraction
List every relationship between entities. For each:
- Write a short, verb-driven statement: `[Entity A] -> [verb phrase] -> [Entity B]`
- Indicate directionality: `->` (one directional) or `<->` (mutual)
- Only include what the text explicitly states or directly implies
- `reasoning`: One sentence citing the specific word, phrase, or sentence in the note that supports this relationship

### STEP 3 — Relationship Graph
Represent all relationships as a compact symbolic graph using `->`. Group related clusters together.

### STEP 4 — Entity Context Generation
For each entity, write a tightly focused contextual description using **only information from the note**.
Rules:
- Write in complete sentences
- Stay entity-centric: everything in the description should orbit *this specific entity*
- Include all roles, relationships, attributes, and key factual properties that describe the entity but don't involve another entity
- All context must be drawn from the note — do not add any outside information or assumptions, even if they seem obvious. If it's not in the note, it doesn't exist for the entity's context.
- Do not add assumptions or outside knowledge
- Length: unlimited number of sentences depending on how much the note says about the entity

---

## OUTPUT FORMAT

Return a single JSON object structured exactly like this:

{{
  "title": "string — descriptive title that captures the main subject of this note",
  "entities": [
    {{
      "name": "string — canonical entity name",
      "type": "string — the most fitting type for this entity",
      "type_reasoning": "string — explaining why you chose this type, citing the key clue from the note",
      "context": "string — isolated, entity-centric contextual paragraph drawn entirely from the note",
      "relationships": [
        "string — e.g., 'Ama is friends with Kofi'",
        "string — e.g., 'Ama attends Primary School'"
      ]
    }}
  ],
  "relationships": [
    {{
      "entity1": "string",
      "entity2": "string",
      "direction": "-> or <->",
      "description": "string — concise verb-phrase description of the relationship",
      "reasoning": "string — one sentence citing the specific text that supports this relationship"
    }}
  ],
  "graph": "string — compact symbolic representation of all relationships"
}}

---

## WORKED EXAMPLE

**Input Note:**
"Ama and Kofi are friends. Ama is a girl in primary school. Kofi is a boy who plays in the neighborhood. Ama likes to play with Kofi every weekend after she is done with her homework."

**Output:**
{{
  "title": "Ama and Kofi's Weekend Friendship",
  "entities": [
    {{
      "name": "Ama",
      "type": "Person",
      "type_reasoning": "Ama is explicitly described as a girl, making her a human individual.",
      "context": "Ama is a girl and a student at Primary School. She is mutual friends with Kofi and shares a weekend play routine with him. She lives in the same neighborhood as Kofi. She consistently completes her homework before engaging in play.",
      "relationships": [
        "Ama is friends with Kofi",
        "Ama attends Primary School",
        "Ama lives in the Neighborhood",
        "Ama plays with Kofi on the Weekend",
        "Ama completes Homework before playing"
      ]
    }},
    {{
      "name": "Kofi",
      "type": "Person",
      "type_reasoning": "Kofi is explicitly described as a boy, making him a human individual.",
      "context": "Kofi is a boy who lives in the Neighborhood. He is mutual friends with Ama and plays with her every weekend. His play is situated within the neighborhood.",
      "relationships": [
        "Kofi is friends with Ama",
        "Kofi lives in the Neighborhood",
        "Kofi plays with Ama on the Weekend"
      ]
    }},
    {{
      "name": "Primary School",
      "type": "Place",
      "type_reasoning": "Primary School is an educational institution — a physical location that Ama attends.",
      "context": "Primary School is the educational institution that Ama attends. It is the only institution mentioned in the note and defines Ama's role as a student.",
      "relationships": [
        "Ama attends Primary School"
      ]
    }},
    {{
      "name": "Neighborhood",
      "type": "Place",
      "type_reasoning": "The Neighborhood is a physical geographic area where both Ama and Kofi live and play.",
      "context": "The Neighborhood is a shared residential area where both Ama and Kofi live. It is also where Kofi plays.",
      "relationships": [
        "Ama lives in the Neighborhood",
        "Kofi lives in the Neighborhood",
        "Kofi plays in the Neighborhood"
      ]
    }},
    {{
      "name": "Weekend",
      "type": "Time Period",
      "context": "The Weekend is the recurring time period during which Ama and Kofi play together. It is contingent on Ama finishing her homework first.",
      "type_reasoning": "Weekend is a recurring temporal interval — a defined period of time during which events in the note occur.",
      "relationships": [
        "Ama plays with Kofi on the Weekend",
        "Weekend follows Ama completing Homework"
      ]
    }},
    {{
      "name": "Homework",
      "type": "Thing",
      "type_reasoning": "Homework is a concrete recurring task/artifact that Ama must complete — a physical obligation rather than an abstract concept.",
      "context": "Homework is a recurring obligation that Ama must complete before she is free to play with Kofi on the Weekend. It acts as a precondition to their shared leisure activity.",
      "relationships": [
        "Ama completes Homework before the Weekend",
        "Homework precedes Ama playing with Kofi"
      ]
    }}
  ],
  "relationships": [
    {{"entity1": "Ama", "entity2": "Kofi", "direction": "<->", "description": "are mutual friends", "reasoning": "The note states 'Ama and Kofi are friends'."}},
    {{"entity1": "Ama", "entity2": "Primary School", "direction": "->", "description": "attends", "reasoning": "The note says 'Ama is a girl in primary school'."}},
    {{"entity1": "Ama", "entity2": "Neighborhood", "direction": "->", "description": "lives in", "reasoning": "Implied by Kofi playing 'in the neighborhood' and both sharing the same area."}},
    {{"entity1": "Kofi", "entity2": "Neighborhood", "direction": "->", "description": "lives and plays in", "reasoning": "The note says 'Kofi is a boy who plays in the neighborhood'."}},
    {{"entity1": "Ama", "entity2": "Weekend", "direction": "->", "description": "plays with Kofi during", "reasoning": "The note says 'Ama likes to play with Kofi every weekend'."}},
    {{"entity1": "Kofi", "entity2": "Weekend", "direction": "->", "description": "plays with Ama during", "reasoning": "The note says 'Ama likes to play with Kofi every weekend', making it mutual."}},
    {{"entity1": "Ama", "entity2": "Homework", "direction": "->", "description": "completes before weekend play", "reasoning": "The note says 'after she is done with her homework'."}},
    {{"entity1": "Homework", "entity2": "Weekend", "direction": "->", "description": "must be completed before", "reasoning": "The note says Ama plays 'after she is done with her homework', making homework a precondition to weekend play."}}
  ],
  "graph": "Ama <-> Kofi, Ama -> Primary School, Ama -> Neighborhood <- Kofi, Ama -> Weekend <- Kofi, Ama -> Homework -> Weekend"
}}

---

Now apply this entire process to the following note and return only the JSON output, nothing else:

{extraction_content}
"""
    # Retry loop: local servers (LM Studio / Ollama) occasionally return empty
    # responses when the model fails to allocate output tokens (KV cache pressure).
    # Waiting 30-60s lets the server recover before retrying.
    _MAX_EXTRACTION_ATTEMPTS = 3  # pylint: disable=invalid-name
    for _attempt in range(_MAX_EXTRACTION_ATTEMPTS):
        try:
            # Use generate() instead of extract_structured() to bypass Ollama's
            # grammar-constrained JSON sampling, which causes small models (e.g.
            # gemma3:4b) to emit empty `relationships: []` for complex nested arrays.
            raw_response = await llm_service.ingestion_generate(prompt, temperature=0.1)
            cleaned_json = llm_service._clean_json(raw_response)
            extraction = Extraction.model_validate_json(cleaned_json)
            if not extraction:
                return {"errors": ["LLM returned empty extraction"]}
            break  # success — exit retry loop
        except Exception as _e:  # pylint: disable=broad-exception-caught
            if _attempt < _MAX_EXTRACTION_ATTEMPTS - 1:
                _wait = 30 * (_attempt + 1)  # 30s, then 60s
                logger.warning(
                    f"Extraction attempt {_attempt + 1} failed, "
                    f"retrying in {_wait}s: {_e}"
                )
                await asyncio.sleep(_wait)
            else:
                logger.error(f"Extraction Error: {_e}")
                return {
                    "errors": [
                        f"Extraction failed after {_MAX_EXTRACTION_ATTEMPTS} attempts: {_e}"
                    ],
                    "logs": logs,
                }

    logger.info(f"Extraction Completed: {extraction}")

    # Log per-entity type reasoning for auditability
    for n in extraction.nodes:
        reasoning = (
            n.type_reasoning.strip() if n.type_reasoning else "no reasoning provided"
        )
        logger.info(
            f"  [Entity] name={n.name!r} type={n.type!r} reasoning={reasoning!r}"
        )

    # Log per-relationship reasoning for auditability
    for r in extraction.relationships:
        rel_reasoning = r.reasoning.strip() if r.reasoning else "no reasoning provided"
        logger.info(
            f"  [Relationship] {r.source_name!r} -> {r.target_name!r}"
            f" ({r.relationship_type!r}): {rel_reasoning!r}"
        )

    # GARBAGE NAME HANDLING: nodes with empty/placeholder names but valid context
    # get a recovery rename; nodes with neither are dropped.
    GARBAGE_NAMES = {"untitled", "none", "unknown", ""}  # pylint: disable=invalid-name

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
        import json as _json
        import re as _re

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
            rename_resp = await llm_service.ingestion_generate(
                rename_prompt,
                temperature=0.0,
            )
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
                        logger.info(
                            f"  [Rename] Could not recover (response: '{new_name}')"
                        )
            else:
                logger.warning("  [Rename] Could not parse batch rename response.")
        except Exception as rename_err:  # pylint: disable=broad-exception-caught
            logger.warning(f"  [Rename] Batch rename failed: {rename_err}")

    # Dedup: if recovered names collide with existing clean nodes or with
    # each other, keep only the first occurrence by normalized name.
    _seen_names: set[str] = set()
    deduped_nodes = []
    for n in clean_nodes:
        _key = (n.name or "").strip().lower()
        if _key and _key not in _seen_names:
            _seen_names.add(_key)
            deduped_nodes.append(n)
        elif _key:
            logger.debug(f"  [Rename] Dedup: dropped duplicate node name '{n.name}'")
    extraction.nodes = deduped_nodes

    logger.info(f"Nodes after rename: {[n.name for n in extraction.nodes]}")

    logger.info(
        f"Extracted: {len(extraction.nodes)} nodes, {len(extraction.relationships)} relationships."
    )

    t_end = time.perf_counter()
    logger.info(f"Extraction took: {t_end - t_start:.4f}s")
    return {
        "extraction": extraction,
        "logs": logs,
        "status": "EXTRACTED",
    }


async def storage_node(state: IngestionState):
    """LangGraph node: persist the validated extraction to the graph and vector stores."""
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

    from app.workflows.ingestion import ingestion_workflow as _default_wf

    _wf = state.get("workflow") or _default_wf
    try:
        # 1. Write to Kuzu (The Mind)
        title = await asyncio.to_thread(
            _wf._write_ontology,
            note_id,
            state["content"],
            state["extraction"],
            created_at,
            custom_title,  # Pass custom title if provided
        )

        # 2. Sync to Postgres (The Body)
        # Sync Title
        if title:
            await _wf._update_note_title_postgres(note_id, title)

        t_end = time.perf_counter()
        logger.info(f"  [Perf] Graph Storage took: {t_end - t_start:.4f}s")
        return {"note_id": note_id, "created_at": created_at}
    except Exception as e:  # pylint: disable=broad-exception-caught
        logs.append(f"ERROR: Storage failed: {e}")
        return {"errors": [f"Storage failed: {str(e)}"], "logs": logs}


async def summarization_node(state: IngestionState):
    """LangGraph node: update per-node context summaries and mark ingestion complete."""
    if state.get("errors") or not state.get("extraction"):
        return {}
    logs = state["logs"]
    logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] INDEX_CONTEXTS: Updating Node Contexts..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("[Agent] Updating Node Context Indexes (Delta Updates)...")
    from app.workflows.ingestion import ingestion_workflow as _default_wf

    _wf = state.get("workflow") or _default_wf
    await _wf._update_neighborhoods(
        state["extraction"].nodes,
        state["content"],
    )
    t_end = time.perf_counter()
    logger.info(f"  [Perf] Context indexing took: {t_end - t_start:.4f}s")

    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] DONE: Ingestion Complete.")
    return {"logs": logs, "status": "INDEXED"}


def should_route_after_extraction(state: IngestionState):
    """Route the graph after extraction: 'end' on error, 'store' otherwise."""
    if state.get("errors"):
        return "end"
    return "store"


# 3. Build Graph
workflow = StateGraph(IngestionState)

# Add Nodes
workflow.add_node("multimodal", multimodal_node)
workflow.add_node("extraction", extraction_node)
workflow.add_node("storage", storage_node)
workflow.add_node("summarization", summarization_node)

# Define Edges
workflow.set_entry_point("multimodal")
workflow.add_edge("multimodal", "extraction")
workflow.add_conditional_edges(
    "extraction",
    should_route_after_extraction,
    {"store": "storage", "end": END},
)

workflow.add_edge("storage", "summarization")
workflow.add_edge("summarization", END)

# Compile
ingestion_agent = workflow.compile()
