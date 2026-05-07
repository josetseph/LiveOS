import asyncio
import uuid
from datetime import datetime
from typing import List, Optional, TypedDict

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

    # This gate limits concurrent multimedia processing calls.
    async with concurrency_limit:
        logger.info(
            f"Sempahore Acquired. (Active: {1 - concurrency_limit._value + 1 if hasattr(concurrency_limit, '_value') else '?'})"
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
                        img_title = await llm_service.generate(
                            img_title_prompt, temperature=0.0
                        )
                        img_title = (img_title or "").strip().strip('"').strip(
                            "'"
                        ) or filename
                    except Exception:
                        img_title = filename

                    content += (
                        f"\n\n[Image: {img_title}]\n"
                        f'The image titled "{img_title}" shows the following: {img_desc}'
                    )

                else:
                    logger.info(f"Skipped (Unsupported Type): {url}")

            except Exception as e:
                logger.error(f"File Processing Failed: {e}")

        # Audio transcripts are synced back to Postgres because audio files are
        # not directly re-readable as text. Other file types can be re-extracted.
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

    # Prepend the user-provided title so the LLM sees it as part of the source
    # text. Auto-generated titles are not included — they don't originate from
    # the note itself and would pollute the extraction.
    extraction_content = state["content"]
    if state["input"].title:
        extraction_content = f"# {state['input'].title}\n\n{extraction_content}"

    prompt = f"""You are a precision knowledge extraction engine. Your sole function is to decompose any input note into a fully structured knowledge graph — extracting every entity, every relationship, and generating an isolated contextual description for each entity as it exists *within the note only*.

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
  - `Organization` — a group, nation, army, institution, or collective body
  - `Event` — a specific occurrence with a defined scope
  - `Thing` — a physical object, document, or artifact
  - `Concept` — an abstract idea, principle, or condition (e.g., "sovereignty", "friendship")
  - `Time Period` — a specific date, duration, era, or recurring time (e.g., "Weekend", "2 March 1896")

### STEP 2 — Relationship Extraction
List every relationship between entities. For each:
- Write a short, verb-driven statement: `[Entity A] -> [verb phrase] -> [Entity B]`
- Indicate directionality: `->` (one directional) or `<->` (mutual)
- Only include what the text explicitly states or directly implies

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
      "type": "string — one of the 7 defined types",
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
      "description": "string — concise verb-phrase description of the relationship"
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
      "context": "Primary School is the educational institution that Ama attends. It is the only institution mentioned in the note and defines Ama's role as a student.",
      "relationships": [
        "Ama attends Primary School"
      ]
    }},
    {{
      "name": "Neighborhood",
      "type": "Place",
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
      "relationships": [
        "Ama plays with Kofi on the Weekend",
        "Weekend follows Ama completing Homework"
      ]
    }},
    {{
      "name": "Homework",
      "type": "Thing",
      "context": "Homework is a recurring obligation that Ama must complete before she is free to play with Kofi on the Weekend. It acts as a precondition to their shared leisure activity.",
      "relationships": [
        "Ama completes Homework before the Weekend",
        "Homework precedes Ama playing with Kofi"
      ]
    }}
  ],
  "relationships": [
    {{"entity1": "Ama", "entity2": "Kofi", "direction": "<->", "description": "are mutual friends"}},
    {{"entity1": "Ama", "entity2": "Primary School", "direction": "->", "description": "attends"}},
    {{"entity1": "Ama", "entity2": "Neighborhood", "direction": "->", "description": "lives in"}},
    {{"entity1": "Kofi", "entity2": "Neighborhood", "direction": "->", "description": "lives and plays in"}},
    {{"entity1": "Ama", "entity2": "Weekend", "direction": "->", "description": "plays with Kofi during"}},
    {{"entity1": "Kofi", "entity2": "Weekend", "direction": "->", "description": "plays with Ama during"}},
    {{"entity1": "Ama", "entity2": "Homework", "direction": "->", "description": "completes before weekend play"}},
    {{"entity1": "Homework", "entity2": "Weekend", "direction": "->", "description": "must be completed before"}}
  ],
  "graph": "Ama <-> Kofi, Ama -> Primary School, Ama -> Neighborhood <- Kofi, Ama -> Weekend <- Kofi, Ama -> Homework -> Weekend"
}}

---

Now apply this entire process to the following note and return only the JSON output, nothing else:

{extraction_content}
"""
    try:
        # Use generate() instead of extract_structured() to bypass Ollama's
        # grammar-constrained JSON sampling, which causes small models (e.g.
        # gemma3:4b) to emit empty `relationships: []` for complex nested arrays.
        raw_response = await llm_service.generate(prompt, temperature=0.1)
        cleaned_json = llm_service._clean_json(raw_response)
        extraction = Extraction.model_validate_json(cleaned_json)
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
                            logger.info(
                                f"  [Rename] Could not recover (response: '{new_name}')"
                            )
                else:
                    logger.warning("  [Rename] Could not parse batch rename response.")
            except Exception as rename_err:
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
                logger.debug(
                    f"  [Rename] Dedup: dropped duplicate node name '{n.name}'"
                )
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
        # 1. Write to Kuzu (The Mind)
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
        f"[{datetime.now().strftime('%H:%M:%S')}] INDEX_CONTEXTS: Updating Node Contexts..."
    )
    import time

    t_start = time.perf_counter()
    logger.info("[Agent] Updating Node Context Indexes (Delta Updates)...")
    from app.workflows.ingestion import ingestion_workflow

    await ingestion_workflow._update_neighborhoods(
        state["extraction"].nodes,
        state["content"],
    )
    t_end = time.perf_counter()
    logger.info(f"  [Perf] Context indexing took: {t_end - t_start:.4f}s")

    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] DONE: Ingestion Complete.")
    return {"logs": logs, "status": "INDEXED"}


# 3. Router logic
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


TASK 2 — MISSING RELATIONSHIPS (PRIMARY FOCUS):
⚠️ REQUIRED: Extract ALL factual connections between nodes in <already_extracted> plus any new nodes.
This is the most important task — the first pass likely missed many relationships.
Check every pair of nodes: if there is any factual link in the text, create a relationship.
source_name and target_name must EXACTLY match a node name.
Format: {{"source_name": "...", "target_name": "...", "relationship_type": "snake_case_verb",
  "strength": 8, "confidence": 8, "relevance": 7, "natural_language": "X did Y.", "context": "verbatim"}}
Relationship types: born_in, directed, wrote, starred_in, located_in, part_of, succeeded_by,
married_to, founded, member_of, participated_in, and any specific verb from the text.

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
TASK 1 — MISSED NODES:
Identify overlooked nodes: people, places, tools, organizations, events, abstract themes,
actionable tasks, emotional traits, external references. Each node:
{{"name": "...", "type": "...", "isolated_context": "verbatim sentence(s)"}}
Do NOT repeat already-extracted names.


TASK 2 — MISSING RELATIONSHIPS (PRIMARY FOCUS):
⚠️ REQUIRED: Extract ALL factual connections between the nodes listed in <already_extracted>
plus any new nodes from Task 1. The first pass likely missed most relationships — find them all.
source_name and target_name must match a node name exactly.
Format: {{"source_name": "...", "target_name": "...", "relationship_type": "snake_case_verb",
  "strength": 7, "confidence": 8, "relevance": 6, "natural_language": "X does Y.", "context": "verbatim"}}
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
        added_nodes = 0
        added_rels = 0
        existing_names = {n.name.lower() for n in extraction.nodes}

        for n in patch.nodes or []:
            if n.name and n.name.strip() and n.name.lower() not in existing_names:
                extraction.nodes.append(n)
                existing_names.add(n.name.lower())
                added_nodes += 1

        for rel in patch.relationships or []:
            extraction.relationships.append(rel)
            added_rels += 1

        return added_nodes, added_rels

    extraction = state["extraction"]
    MAX_PASSES = 1
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
                added_nodes, added_rels = _merge_patch(extraction, patch)
                logger.info(
                    f"  [Refiner] Pass {pass_num}: +{added_nodes} nodes, +{added_rels} relationships."
                )
                logs.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Pass {pass_num} "
                    f"+{added_nodes} nodes, +{added_rels} rels."
                )
                if added_nodes == 0 and added_rels == 0:
                    logger.info(f"  [Refiner] Pass {pass_num}: nothing new — stopping.")
                    break
            else:
                logs.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] REFINE: Pass {pass_num} — no response."
                )
                break
        except Exception as e:
            logs.append(f"WARN: Refinement pass {pass_num} failed: {e}")
            logger.warning(f"  [Refiner] Pass {pass_num} failed: {e}")
            break

    return {"logs": logs, "status": "REFINED", "extraction": extraction}


def should_continue_after_extraction(state: IngestionState):
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

# Single-prompt extraction path: no second LLM refinement pass.
workflow.add_conditional_edges(
    "extraction",
    should_continue_after_extraction,
    {"store": "storage", "end": END},
)

workflow.add_edge("storage", "summarization")
workflow.add_edge("summarization", END)

# Compile
ingestion_agent = workflow.compile()
