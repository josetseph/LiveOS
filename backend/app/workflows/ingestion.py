"""Ingestion workflow: LLM extraction, graph persistence, embedding, and community detection."""

# pylint: disable=too-many-lines,import-outside-toplevel
import asyncio
import re
import threading
import time
import uuid
from collections import defaultdict

from app.core.config import settings
from app.core.log import get_logger
from app.schemas.extraction import Extraction, NoteInput
from app.services.graph import graph_service
from app.services.embedding import embedding_service
from app.services.ingestion_tracker import ingestion_tracker as _tracker
from app.services.llm import llm_service
from app.services.qdrant_service import qdrant_service
from app.services.typesense_service import typesense_service
from app.workflows.agents.ingestion_agent import ingestion_agent

# Hard cap on concurrent ingestion pipelines.
# Each pipeline makes sequential DB calls; capping at 20 keeps peak pool
# usage at ~20 (ingestion) + ~20 (HTTP handlers) = 40, well within the
# pool_size=30 + max_overflow=20 = 50 ceiling set in database.py.
_PROCESS_CONCURRENCY = 20
_process_semaphore = asyncio.Semaphore(_PROCESS_CONCURRENCY)

logger = get_logger("IngestionPipeline")

# Single-flight guard for full community recompute.
# Any newer recompute request supersedes older requests/runs.
_community_run_state_lock = threading.Lock()
_community_run_seq = 0  # pylint: disable=invalid-name
_community_run_active_seq = 0  # pylint: disable=invalid-name
_community_run_running = False  # pylint: disable=invalid-name
# pylint: disable=invalid-name


def clean_rel_type(rel_type: str, source_name: str, target_name: str) -> str:
    """Remove entity name tokens from a relationship predicate.

    LLMs frequently embed the object (or subject) name into the predicate,
    e.g. "plays_corliss_archer" instead of just "plays".  This function
    strips any token that appears verbatim (case-insensitive) in either
    entity name, then collapses consecutive underscores left by the removal.

    Examples:
        clean_rel_type("plays_corliss_archer", "shirley temple", "corliss archer")
        → "plays"
        clean_rel_type("is_directed_by", "film", "director")
        → "is_directed_by"   (no entity tokens present)
    """
    if not rel_type:
        return rel_type

    # Tokenise entity names into individual words (ignore single-char tokens)
    entity_tokens: set[str] = set()
    for name in (source_name, target_name):
        for token in re.split(r"[\s_\-]+", name.lower()):
            if len(token) > 1:
                entity_tokens.add(token)

    if not entity_tokens:
        return rel_type

    # Tokenise the predicate, drop entity tokens, rejoin
    parts = re.split(r"_", rel_type.lower())
    cleaned = [p for p in parts if p not in entity_tokens]
    if not cleaned:
        # Entire predicate was entity names — fall back to "relates_to"
        return "relates_to"
    return "_".join(cleaned)


class EntityLockManager:  # pylint: disable=too-few-public-methods
    """
    Manages per-entity locks to prevent race conditions during summary updates.
    Ensures that multiple notes updating the same entity wait for each other.
    """

    def __init__(self):
        self._locks = defaultdict(asyncio.Lock)

    def get_lock(self, label: str, name: str):
        """Return the asyncio lock for a given (label, name) entity pair."""
        return self._locks[(label, name.lower().strip())]


entity_lock_manager = EntityLockManager()


class IngestionWorkflow:
    """Orchestrates full ingestion: multimedia → LLM extraction → graph → embeddings → communities."""

    async def process_note(self, note_input: NoteInput, note_id: str = None):
        """Run the full ingestion pipeline for a single note."""
        if not note_id:
            note_id = str(uuid.uuid4())

        # Register with the tracker BEFORE the semaphore so the community-detection
        # idle timer never fires while tasks are queued waiting for a slot.
        await _tracker.begin_ingestion()

        # Wait for a pipeline slot.  Without this cap, sending 990 notes at once
        # spawns 990 concurrent coroutines that all hit the DB pool simultaneously.
        async with _process_semaphore:
            logger.info(
                f"\n{'='*70}\n"
                f"[Ingestion] START note_id={note_id}\n"
                f"  content_length={len(note_input.content or '')} chars\n"
                f"  title='{note_input.title or '(auto-generate)'}'\n"
                f"{'='*70}"
            )

            # Trigger the LangGraph Agent
            initial_state = {
                "input": note_input,
                "content": "",
                "extraction": None,
                "note_id": note_id,
                "created_at": None,
                "errors": [],
            }

            # Use ainvoke because the graph contains async nodes (multimodal_node)
            t_start = time.perf_counter()
            try:
                final_state = await ingestion_agent.ainvoke(initial_state)
                t_end = time.perf_counter()

                if final_state["errors"]:
                    logger.error(
                        f"[Ingestion] FAILURE note_id={note_id}: {final_state['errors']}"
                    )
                    raise RuntimeError(
                        f"Ingestion Agent Failed: {final_state['errors']}"
                    )

                extraction = final_state.get("extraction")
                if extraction:
                    logger.info(
                        f"[Ingestion] Agent complete — extracted "
                        f"{len(getattr(extraction, 'nodes', []))} nodes, "
                        f"{len(getattr(extraction, 'relationships', []))} relationships"
                    )
                    for n in getattr(extraction, "nodes", []):
                        logger.debug(f"  [Extraction] node: '{n.name}' type='{n.type}'")
                    for r in getattr(extraction, "relationships", []):
                        logger.debug(
                            f"  [Extraction] rel: '{r.source_name}' --[{r.relationship_type}]--> '{r.target_name}' "
                            f"(strength={r.strength}, confidence={r.confidence}, relevance={r.relevance})"
                        )

                # Mark as processed in Postgres
                await self._mark_note_processed(note_id)
                await self._queue_leiden_recompute_if_due(note_id)

                duration = t_end - t_start
                logger.info(
                    f"\n{'='*70}\n"
                    f"[Ingestion] SUCCESS note_id={note_id} in {duration:.2f}s\n"
                    f"{'='*70}"
                )

                return {
                    "note_id": final_state["note_id"],
                    "extraction": final_state["extraction"].model_dump(),
                    "status": "success",
                    "processed_content": final_state["content"],
                }

            except Exception:
                await self._mark_note_failed(note_id)
                raise

            finally:
                # Always decrement the active counter and potentially schedule
                # community recompute, regardless of success or failure.
                await _tracker.end_ingestion(self.rebuild_leiden_communities)

    # Internal helpers reused by the Agent
    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _update_note_content_postgres(self, note_id: str, content: str):
        """
        Updates the Note content in Postgres (The Body).
        Called by Agent when new text (transcription/OCR) is found.
        """
        from sqlalchemy import update

        from app.core.database import AsyncSessionLocal
        from app.models.note import Note

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(content=content)
                )
                await session.commit()
                logger.info(f"[Ingestion] Updated Postgres Content for Note {note_id}")
            except Exception as e:
                logger.error(f"Error updating Postgres content: {e}")
                raise e  # Re-raise for tenacity

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _update_note_title_postgres(self, note_id: str, title: str):
        """
        Updates the Note title in Postgres.
        """
        from sqlalchemy import update

        from app.core.database import AsyncSessionLocal
        from app.models.note import Note

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(title=title)
                )
                await session.commit()
                logger.info(
                    f"[Ingestion] Updated Postgres Title for Note {note_id}: '{title}'"
                )
            except Exception as e:
                logger.error(f"Error updating Postgres title: {repr(e)}")
                raise e

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _mark_note_processed(self, note_id: str):
        """
        Sets processed = True in Postgres to prevent re-runs.
        """
        from sqlalchemy import update

        from app.core.database import AsyncSessionLocal
        from app.models.note import Note

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(processed=True)
                )
                await session.commit()
                logger.info(f"[Ingestion] Marked Note {note_id} as Processed.")
            except Exception as e:
                logger.error(f"Error marking note processed: {e}")
                raise e

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _mark_note_failed(self, note_id: str):
        """
        Sets failed = True in Postgres so callers can distinguish a permanent
        failure from a note that is still being processed.
        """
        from sqlalchemy import update

        from app.core.database import AsyncSessionLocal
        from app.models.note import Note

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(failed=True)
                )
                await session.commit()
                logger.info(f"[Ingestion] Marked Note {note_id} as Failed.")
            except Exception as e:
                logger.error(f"Error marking note failed: {e}")
                raise e

    def _write_ontology(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self,
        note_id: str,
        content: str,
        extraction: Extraction,
        _created_at: str,
        custom_title: str = None,
    ):
        logger.info(f"[Ontology] Writing ontology for note {note_id}")
        # 0. Resolve title: user-provided > extracted by LLM during extraction > separate LLM call
        if custom_title:
            title = custom_title
            logger.info(f"[Ontology] Using provided title: '{title}'")
        elif extraction.title:
            title = extraction.title
            logger.info(f"[Ontology] Using extracted title: '{title}'")
        else:
            title = llm_service.generate_title(
                content,
                model=llm_service._get_ingestion_model(),  # pylint: disable=protected-access
            )
            logger.info(f"[Ontology] Generated title: '{title}'")
        # Base Note Node — structural node in Kuzu with kind='note'.
        query_note = """
        MERGE (n:Node {id: $id}) ON CREATE SET n.kind = 'note'
        """
        graph_service.execute_query(
            query_note,
            {"id": note_id},
        )

        # Helper to normalize names: strip # prefix, extra whitespace, and lowercase
        def normalize_name(name: str) -> str:
            if not name:
                return ""
            return name.lstrip("#").strip().lower()

        # 1. NODES (Batch — unified single type)
        name_to_id: dict[str, str] = (
            {}
        )  # populated below; declared here so it's always bound
        if extraction.nodes:
            # Build deduplicated (norm_name, text) pairs first, then embed in one shot.
            _embed_keys: list[str] = []
            _embed_texts: list[str] = []
            _seen_embed: set[str] = set()
            for n in extraction.nodes:
                norm_name = normalize_name(n.name)
                if not norm_name or norm_name in _seen_embed:
                    continue
                _seen_embed.add(norm_name)
                _embed_keys.append(norm_name)
                _embed_texts.append(
                    f"{norm_name} ({n.type}): {(n.isolated_context or '')}"
                )

            # For Qwen3 models embed_query prepends an instruction prefix;
            # replicate that here so we can use the batched embed_documents path.
            if embedding_service.is_qwen3 and _embed_texts:
                _prefixed = [
                    embedding_service.query_instruction + t for t in _embed_texts
                ]
            else:
                _prefixed = _embed_texts

            _vectors = embedding_service.embed_documents(_prefixed) if _prefixed else []
            node_embeddings: dict[str, list[float]] = dict(zip(_embed_keys, _vectors))

            # Resolve or assign stable IDs: batch-look up Qdrant for ALL unique names
            # in a single query, then assign fresh UUIDs to whichever aren't found.
            # seen_in_batch deduplicates within this extraction — the same entity
            # name can appear more than once in a single note's extraction result,
            # and Qdrant won't have it yet for the first occurrence, so without this
            # both occurrences would mint independent UUIDs.
            _unique_names: list[str] = list(
                dict.fromkeys(
                    normalize_name(n.name)
                    for n in extraction.nodes
                    if normalize_name(n.name)
                )
            )
            _batch_id_map: dict[str, str | None] = (
                qdrant_service.find_node_ids_by_names(_unique_names)
                if _unique_names
                else {}
            )

            node_data = []
            seen_in_batch: dict[str, str] = {}  # norm_name → assigned_id
            for node in extraction.nodes:
                norm_name = normalize_name(node.name)
                if not norm_name:
                    continue
                if norm_name in seen_in_batch:
                    # Same entity appeared twice in this extraction — reuse the
                    # first-assigned ID and skip appending a duplicate entry.
                    logger.debug(
                        f"  [Ontology] node '{norm_name}' — duplicate within batch, "
                        f"reusing id={seen_in_batch[norm_name]}"
                    )
                    continue
                existing_id = _batch_id_map.get(norm_name)
                is_new = existing_id is None
                assigned_id = existing_id or f"node_{str(uuid.uuid4())}"
                seen_in_batch[norm_name] = assigned_id
                node_type = ((node.type or "").strip().lower()) or "thing"
                node_data.append(
                    {
                        "id": assigned_id,
                        "name": norm_name,
                        "type": node_type,
                        "embedding": node_embeddings.get(norm_name),
                        "is_new": is_new,
                    }
                )
                logger.info(
                    f"  [Ontology] node '{norm_name}' type='{node_type}' "
                    f"id={assigned_id} ({'NEW' if is_new else 'EXISTING'})"
                )

            # Build name→ID map for relationship creation below
            name_to_id: dict[str, str] = {d["name"]: d["id"] for d in node_data}
            _new_count = sum(1 for d in node_data if d["is_new"])
            logger.info(
                f"[Ontology] {len(node_data)} nodes resolved ({_new_count} new) — writing to Kuzu"
            )

            # Write bare structural nodes to Kuzu (id only — no content)
            query_nodes = """
            MERGE (note:Node {id: $note_id}) ON CREATE SET note.kind = 'note'
            WITH note
            UNWIND $data AS item
            MERGE (n:Node {id: item.id}) ON CREATE SET n.kind = 'indexable'
            MERGE (note)-[r:REFERENCES]->(n)
            SET r.note_id = $note_id
            """

            if node_data:
                graph_service.execute_query(
                    query_nodes,
                    {"data": [{"id": d["id"]} for d in node_data], "note_id": note_id},
                )

                # Seed Qdrant node_cores stubs for NEW nodes so that
                # _update_node_summary (running immediately after) finds the
                # correct ID via find_node_id_by_name instead of minting a
                # second different ID.  The stub is overwritten moments later
                # by _update_node_summary with the real description + embedding.
                for d in node_data:
                    if d["is_new"] and d["embedding"]:
                        qdrant_service.upsert_node_core(
                            node_id=d["id"],
                            name=d["name"],
                            node_type=d["type"],
                            description_vector=d["embedding"],
                        )
                logger.info(
                    f"[Ontology] Seeded Qdrant stubs for "
                    f"{sum(1 for d in node_data if d['is_new'])} new node(s)"
                )

        # 6. RELATIONSHIPS (New - Inter-node connections)
        if extraction.relationships:
            logger.info(
                f"[Ingestion] Creating {len(extraction.relationships)} relationships..."
            )

            # All nodes are :Indexable — no type mapping needed

            # Pre-collect all relationship endpoint names that aren't already in
            # name_to_id (i.e. they reference nodes from previous ingestion runs)
            # and batch-resolve them in one Qdrant query instead of one per rel.
            _rel_missing_names: set[str] = set()
            for _rel in extraction.relationships:
                if not _rel.source_name or not _rel.target_name:
                    continue
                _sn = _rel.source_name.lower().strip()
                _tn = _rel.target_name.lower().strip()
                if _sn and _sn not in name_to_id:
                    _rel_missing_names.add(_sn)
                if _tn and _tn not in name_to_id:
                    _rel_missing_names.add(_tn)
            _rel_fallback_ids: dict[str, str | None] = (
                qdrant_service.find_node_ids_by_names(list(_rel_missing_names))
                if _rel_missing_names
                else {}
            )
            logger.debug(
                f"[Relationship] Batch-resolved {len(_rel_missing_names)} fallback name(s) "
                f"({sum(1 for v in _rel_fallback_ids.values() if v)} found)"
            )

            # Collect all graph results first; batch-embed the new/evolved NL texts afterwards.
            _qdrant_rel_pending: list[tuple[dict, str, str, str]] = (
                []
            )  # (result, nl_text, src_id, tgt_id)

            # Diagnostics counters for end-of-note summary log.
            _rel_total = len(extraction.relationships)
            _rel_written = 0
            _rel_skip_no_name = 0
            _rel_skip_no_source = 0
            _rel_skip_no_target = 0
            for rel in extraction.relationships:
                try:
                    # Validate required fields
                    if not rel.source_name or not rel.target_name:
                        logger.warning(
                            f"[Relationship] Skipping - missing source or target name: "
                            f"{rel.source_name} -> {rel.target_name}"
                        )
                        _rel_skip_no_name += 1
                        continue

                    # Default to "relates_to" if no relationship type provided
                    rel_type = (
                        rel.relationship_type.strip() if rel.relationship_type else ""
                    )
                    if not rel_type:
                        rel_type = "relates_to"
                        logger.warning(
                            f"[Relationship] No type provided for {rel.source_name} -> {rel.target_name}, "
                            f"defaulting to 'relates_to'"
                        )

                    # Strip entity name tokens from the predicate.
                    # LLMs sometimes embed the object into the verb, e.g.
                    # "plays_corliss_archer" → should be just "plays".
                    cleaned_rel_type = clean_rel_type(
                        rel_type, rel.source_name, rel.target_name
                    )
                    if cleaned_rel_type != rel_type:
                        logger.debug(
                            f"[Relationship] Predicate cleaned: '{rel_type}' → '{cleaned_rel_type}' "
                            f"({rel.source_name} → {rel.target_name})"
                        )
                        rel_type = cleaned_rel_type

                    source_label = "Indexable"
                    target_label = "Indexable"

                    # Normalize names to lowercase to match node storage
                    source_name_normalized = rel.source_name.lower().strip()
                    target_name_normalized = rel.target_name.lower().strip()

                    # Look up IDs from the name_to_id map (built from node_data above)
                    # falling back to the pre-batched Qdrant results for cross-run nodes.
                    src_node_id = (
                        name_to_id.get(source_name_normalized)
                        or _rel_fallback_ids.get(source_name_normalized)
                        or ""
                    )
                    tgt_node_id = (
                        name_to_id.get(target_name_normalized)
                        or _rel_fallback_ids.get(target_name_normalized)
                        or ""
                    )

                    if not src_node_id:
                        logger.warning(
                            f"  [Ontology] Relationship skipped — source '{source_name_normalized}' "
                            f"not found in name_to_id or Qdrant"
                        )
                        _rel_skip_no_source += 1
                        continue
                    if not tgt_node_id:
                        logger.warning(
                            f"  [Ontology] Relationship skipped — target '{target_name_normalized}' "
                            f"not found in name_to_id or Qdrant"
                        )
                        _rel_skip_no_target += 1
                        continue

                    logger.debug(
                        f"  [Ontology] Creating rel: '{source_name_normalized}' "
                        f"--[{rel_type}]--> '{target_name_normalized}' "
                        f"(strength={rel.strength}, confidence={rel.confidence}, relevance={rel.relevance}) "
                        f"NL: '{(rel.natural_language or '')}'"
                    )

                    # Create or update relationship with bi-temporal support
                    result = graph_service.create_or_update_relationship(
                        source_name=source_name_normalized,
                        source_label=source_label,
                        target_name=target_name_normalized,
                        target_label=target_label,
                        relationship_type=rel_type,
                        confidence=rel.confidence,
                        strength=rel.strength,
                        relevance=rel.relevance,
                        natural_language=(rel.natural_language or "").replace("_", " "),
                        note_id=note_id,
                        source_id=src_node_id,
                        target_id=tgt_node_id,
                    )

                    # Queue new/evolved rels for batch Qdrant embedding below.
                    if (
                        result.get("action") in ("created", "evolved")
                        and src_node_id
                        and tgt_node_id
                    ):
                        # Fall back to just the predicate (not a full sentence)
                        # so the stored NL never contains entity names that
                        # would be doubled when _build_node_text wraps it with
                        # "{name} {nl} {neighbour}".
                        nl_text = result.get("natural_language") or rel_type.replace(
                            "_", " "
                        )
                        # Ensure natural language never contains underscores.
                        nl_text = nl_text.replace("_", " ")
                        _qdrant_rel_pending.append(
                            (result, nl_text, src_node_id, tgt_node_id)
                        )

                    logger.info(
                        f"  [Ontology] Rel {result['action'].upper()}: "
                        f"'{source_name_normalized}' --[{rel_type}]--> '{target_name_normalized}'"
                    )
                    _rel_written += 1

                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error(
                        f"[Relationship] Failed to create relationship "
                        f"{rel.source_name}->{rel.target_name}: {e}"
                    )
                    continue

            # Batch-embed all new/evolved relationship NL texts in one round-trip.
            if _qdrant_rel_pending:
                _nl_batch = [item[1] for item in _qdrant_rel_pending]
                _nl_vectors = embedding_service.embed_documents(_nl_batch)
                for (result, nl_text, src_node_id, tgt_node_id), nl_vector in zip(
                    _qdrant_rel_pending, _nl_vectors
                ):
                    qdrant_service.upsert_node_relationship(
                        relationship_id=result["relationship_id"],
                        natural_language=nl_text,
                        nl_vector=nl_vector,
                        source_node_id=src_node_id,
                        target_node_id=tgt_node_id,
                    )
                    logger.debug(f"  [Ontology] Qdrant rel written: '{nl_text}'")

            # Emit a compact per-note relationship summary for observability.
            _rel_skip_total = (
                _rel_skip_no_name + _rel_skip_no_source + _rel_skip_no_target
            )
            logger.info(
                f"[Relationship] note_id={note_id} total={_rel_total} "
                f"written={_rel_written} skipped={_rel_skip_total} "
                f"(no_name={_rel_skip_no_name} "
                f"no_source={_rel_skip_no_source} "
                f"no_target={_rel_skip_no_target})"
            )

        return title

    async def _queue_leiden_recompute_if_due(self, note_id: str) -> None:
        rows = graph_service.execute_query(
            """
            MATCH (:Node {id: $note_id})-[*1]-(n:Node)
            WHERE n.kind = 'indexable' AND n.id IS NOT NULL
            RETURN DISTINCT n.id AS node_id
            """,
            {"note_id": note_id},
        )
        node_ids = [row["node_id"] for row in rows if row.get("node_id")]
        if not node_ids:
            return

        _, queue_size = await _tracker.queue_nodes_for_community_recompute(node_ids)
        logger.info(
            f"[Community] Queued {len(node_ids)} node IDs for Leiden recompute "
            f"(queue size: {queue_size}) — IDs: {node_ids}{'...' if len(node_ids) > 10 else ''}"
        )

    async def _update_neighborhoods(self, nodes, new_content: str):
        """
        Refreshes isolated contexts for all nodes affected by this note.
        Runs with concurrency=4 and uses entity-level locks to prevent races
        when multiple ingestion runs touch the same node.

        Groups by node name so each unique node is processed once per ingestion run.
        No description/facts/questions are generated here — only isolated contexts
        are accumulated and embedded.
        """
        # Group unique contexts per node name.
        name_to_contexts: dict[str, list[str]] = {}
        name_to_type: dict[str, str] = {}
        name_ctx_seen: dict[str, set[str]] = {}

        for node in nodes or []:
            name = (node.name or "").lstrip("#").strip().lower()
            if not name:
                continue
            context = getattr(node, "isolated_context", "") or new_content
            ntype = (getattr(node, "type", "") or "").lower().strip() or "thing"
            ctx_key = (context or "").strip()
            if name not in name_to_contexts:
                name_to_contexts[name] = []
                name_to_type[name] = ntype
                name_ctx_seen[name] = set()
            if ctx_key and ctx_key not in name_ctx_seen[name]:
                name_ctx_seen[name].add(ctx_key)
                name_to_contexts[name].append(context)

        nodes_to_update = [
            (name, ctxs, name_to_type[name]) for name, ctxs in name_to_contexts.items()
        ]

        if nodes_to_update:
            _sem = asyncio.Semaphore(4)

            async def _run_summary(name, new_contexts, ntype):
                async with _sem:
                    await self._update_node_summary(
                        "Indexable", name, new_contexts, node_type=ntype
                    )

            logger.info(
                f"[Neighborhood] Updating {len(nodes_to_update)} unique node summaries "
                f"(concurrency=4)…"
            )
            await asyncio.gather(
                *[_run_summary(n, c, t) for n, c, t in nodes_to_update]
            )
            logger.info(
                f"[Neighborhood] {len(nodes_to_update)} node context updates complete."
            )

    async def _update_node_summary(  # pylint: disable=too-many-locals,too-many-statements
        self,
        label: str,
        name: str,
        new_contexts: list[str],
        node_type: str = "",
    ):
        """
        Updates a node by accumulating isolated contexts only.

        This path intentionally does NOT generate description/facts/questions.
        Ingestion stores verbatim isolated contexts and their embeddings, and keeps
        structural nodes + relationships in the graph.

        Args:
            label: Node label (Entity, Concept, Task, etc.)
            name: Node identifier
            new_contexts: Contexts extracted for this node in the current ingestion run
        """
        async with entity_lock_manager.get_lock(label, name):
            loop = asyncio.get_running_loop()

            # 1. Resolve node_id. Qdrant is the primary lookup, but if it misses
            # while Kuzu already has a structural node with this name, reuse that
            # existing graph ID to avoid minting duplicate same-name nodes.
            def _get_existing():
                return qdrant_service.find_node_id_by_name(name)

            node_id: str | None = await loop.run_in_executor(None, _get_existing)
            existing_contexts: list[str] = []

            if node_id:
                # Fetch existing isolated_contexts from Qdrant
                def _get_qdrant_contexts():
                    _content = qdrant_service.get_node_content_by_id(node_id)
                    return _content or {}

                _existing_content = await loop.run_in_executor(
                    None, _get_qdrant_contexts
                )
                existing_contexts = _existing_content.get("isolated_contexts", [])
                logger.info(
                    f"  [NodeSummary] '{name}' EXISTING id={node_id} "
                    f"— {len(existing_contexts)} prior context(s) fetched from Qdrant"
                )
            else:

                def _find_existing_graph_id():
                    _matches = graph_service.find_nodes_by_name([name], fuzzy=False)
                    _candidates = [
                        m.get("node_id")
                        for m in _matches
                        if (
                            m.get("node_id")
                            and (m.get("labels") or [""])[0] == "indexable"
                        )
                    ]
                    if not _candidates:
                        return None
                    return sorted(_candidates)[0]

                _graph_existing_id = await loop.run_in_executor(
                    None, _find_existing_graph_id
                )
                if _graph_existing_id:
                    node_id = _graph_existing_id
                    logger.warning(
                        f"  [NodeSummary] '{name}' missing in Qdrant node_cores but present in Kuzu "
                        f"(id={node_id}) — reusing existing graph ID to prevent duplicate node creation"
                    )

                    # Fetch any existing isolated_contexts from Qdrant (the node may
                    # have contexts in node_isolated_contexts even without a node_cores
                    # entry). Without this, existing_contexts stays [] and the
                    # subsequent Typesense upsert would silently wipe stored contexts.
                    def _get_kuzu_node_contexts():
                        content = qdrant_service.get_node_content_by_id(node_id)
                        return (content or {}).get("isolated_contexts", [])

                    existing_contexts = await loop.run_in_executor(
                        None, _get_kuzu_node_contexts
                    )
                    if existing_contexts:
                        logger.info(
                            f"  [NodeSummary] '{name}' fetched {len(existing_contexts)} "
                            f"prior context(s) via Kuzu ID fallback"
                        )
                else:
                    # Truly new node — mint an ID and ensure structural Kuzu node exists
                    node_id = f"node_{str(uuid.uuid4())}"
                    logger.info(
                        f"  [NodeSummary] '{name}' NEW id={node_id} — minting and writing structural Kuzu node"
                    )

                    def _merge_node():
                        graph_service.execute_query(
                            "MERGE (n:Node {id: $node_id}) ON CREATE SET n.kind = 'indexable'"
                            " SET n.name = $name, n.type = $type",
                            {
                                "node_id": node_id,
                                "name": name,
                                "type": node_type or "unknown",
                            },
                        )

                    await loop.run_in_executor(None, _merge_node)

            # 2. Append all new contexts that aren't already stored (dedup against existing).
            # Collecting all of them before the LLM call means one summary generation
            # per ingestion run regardless of how many contexts this node received.
            _existing_stripped = {c.strip() for c in existing_contexts if c}
            _contexts_to_add: list[str] = []
            for _nc in new_contexts or []:
                _nc_stripped = _nc.strip() if _nc else ""
                if _nc_stripped and _nc_stripped not in _existing_stripped:
                    existing_contexts.append(_nc)
                    _existing_stripped.add(_nc_stripped)
                    _contexts_to_add.append(_nc)
            logger.debug(
                f"  [NodeSummary] '{name}' context count after append: {len(existing_contexts)} "
                f"({len(_contexts_to_add)} new, {len(new_contexts or []) - len(_contexts_to_add)} duplicate(s) skipped)"
            )

            # 3. Resolve semantic node type from Qdrant (or fall back to caller-supplied type)
            def _get_node_type():
                _content = qdrant_service.get_node_content_by_id(node_id)
                if _content and _content.get("type"):
                    return _content["type"]
                return (node_type or "thing").lower().strip() or "thing"

            _node_type_val = await loop.run_in_executor(None, _get_node_type)
            node_type = _node_type_val

            logger.info(
                f"  [NodeSummary] '{name}' generating embeddings for "
                f"{len(_contexts_to_add)} new isolated context(s)"
            )

            # 4. Generate embeddings for Qdrant writes
            def _generate_embeddings():
                # Embed only new isolated contexts (existing are already persisted).
                _new_ctx_texts = [c for c in _contexts_to_add if c and c.strip()]
                vectors = (
                    embedding_service.embed_documents(_new_ctx_texts)
                    if _new_ctx_texts
                    else []
                )

                new_ctx_pairs: list[tuple[str, list[float]]] = []
                for t, v in zip(_new_ctx_texts, vectors):
                    new_ctx_pairs.append((t, v))

                return new_ctx_pairs

            new_ctx_pairs = await loop.run_in_executor(None, _generate_embeddings)
            logger.debug(
                f"  [NodeSummary] '{name}' embeddings generated: "
                f"new_ctx={len(new_ctx_pairs)}"
            )

            # 5. Ensure the Kuzu structural node exists with this ID and carry
            # name + type so the graph endpoint never needs Qdrant for display labels.
            def _save_update():
                graph_service.execute_query(
                    "MERGE (n:Node {id: $node_id}) ON CREATE SET n.kind = 'indexable'"
                    " SET n.name = $name, n.type = $type",
                    {"node_id": node_id, "name": name, "type": node_type or "unknown"},
                )

            await loop.run_in_executor(None, _save_update)
            logger.debug(f"  [NodeSummary] '{name}' Kuzu structural MERGE done")

            # 6. Write to Qdrant (append new contexts).
            def _write_qdrant():
                # Append each new context — existing ones stay in Qdrant untouched
                for _ctx_text, _ctx_vector in new_ctx_pairs:
                    qdrant_service.append_node_item(
                        collection_name=settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,
                        node_id=node_id,
                        content=_ctx_text,
                        vector=_ctx_vector,
                    )

            await loop.run_in_executor(None, _write_qdrant)
            logger.info(
                f"  [NodeSummary] '{name}' Qdrant write complete — "
                f"ctx_appended({len(new_ctx_pairs)})"
            )

            # 6b. Write merged-context vector to node_cores.
            # Joining all accumulated contexts into a single passage and embedding
            # it lets vector search match multi-constraint queries against the full
            # node content at once, rather than scoring each sentence in isolation.
            # Documents are embedded without the query instruction prefix (asymmetric
            # design required by Qwen3-Embedding).
            merged_ctx_text = " ".join(c for c in existing_contexts if c and c.strip())
            if merged_ctx_text:

                def _write_node_core():
                    merged_vec = embedding_service.embed_documents([merged_ctx_text])[0]
                    qdrant_service.upsert_node_core(
                        node_id=node_id,
                        name=name,
                        node_type=node_type,
                        description_vector=merged_vec,
                        description=merged_ctx_text,
                    )

                await loop.run_in_executor(None, _write_node_core)
                logger.debug(
                    f"  [NodeSummary] '{name}' node_cores merged vector written "
                    f"({len(existing_contexts)} context(s) merged)"
                )

            # 7. Write to Typesense
            def _write_es():
                # Fetch relationship NL sentences from Qdrant (not Kuzu)
                rel_qdrant = qdrant_service.get_relationships_for_node_ids([node_id])
                rel_nl = " ".join(
                    r.get("natural_language", "")
                    for r in rel_qdrant
                    if r.get("natural_language")
                )
                contexts_text = " ".join(
                    ctx for ctx in existing_contexts if ctx and ctx.strip()
                )
                # Defense-in-depth: if we somehow ended up with no contexts, fetch
                # what Typesense already has so we don't wipe it with a blank upsert.
                if not contexts_text:
                    try:
                        existing_ts = (
                            typesense_service.client.collections[
                                settings.TYPESENSE_COLLECTION_NAME
                            ]
                            .documents[node_id]
                            .retrieve()
                        )
                        contexts_text = existing_ts.get("isolated_contexts", "")
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass
                typesense_service.index_node(
                    node_id=node_id,
                    name=name,
                    node_type=node_type,
                    isolated_contexts_text=contexts_text,
                    relationship_natural_language=rel_nl,
                )

            await loop.run_in_executor(None, _write_es)
            logger.info(f"  [NodeSummary] '{name}' Typesense index complete")

            logger.info(
                f"  [NodeSummary] ✓ COMPLETE: '{name}' (type='{node_type}', id={node_id})"
            )

    @staticmethod
    def _parse_name_summary(raw: str) -> tuple[str | None, str | None]:
        """Parse ``NAME: ...\nSUMMARY: ...`` LLM output into (name, summary)."""
        name: str | None = None
        summary_lines: list[str] = []
        in_summary = False
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("NAME:") and not in_summary:
                name = stripped.split(":", 1)[1].strip()
            elif stripped.upper().startswith("SUMMARY:"):
                in_summary = True
                first = stripped.split(":", 1)[1].strip()
                if first:
                    summary_lines.append(first)
            elif in_summary:
                summary_lines.append(stripped)
        summary = " ".join(s for s in summary_lines if s) or None
        return name, summary

    @staticmethod
    def _is_generic_community_name(  # pylint: disable=too-many-return-statements
        name: str | None,
    ) -> bool:
        """Heuristic guardrail for low-quality community names.

        Rejects template-like names that are not useful to end users.
        """
        if not name:
            return True

        normalized = re.sub(r"\s+", " ", name.strip()).lower()
        if not normalized:
            return True

        if re.fullmatch(r"community\s+l\d+[-\s]?\d+", normalized):
            return True
        if normalized.startswith("community "):
            return True

        banned_phrases = (
            "isolated conceptual node cluster",
            "isolated conceptual cluster",
            "isolated conceptual fragment",
            "isolated conceptual echo",
            "isolated conceptual echoes",
            "isolated conceptual anomaly",
            "isolated conceptual collection",
            "isolated conceptual core",
            "isolated node community",
            "isolated node cluster",
            "isolated core node cluster",
            "isolated single node community",
            "isolated concept",
            "potential anomaly",
            "initial state",
            "provisional",
            "minimal connection",
        )
        if any(phrase in normalized for phrase in banned_phrases):
            return True

        # Names made only of generic words are not user-friendly.
        generic_tokens = {
            "isolated",
            "conceptual",
            "node",
            "nodes",
            "cluster",
            "community",
            "core",
            "collection",
            "fragment",
            "echo",
            "echoes",
            "anomaly",
            "pair",
            "transient",
            # Additional filler words the LLM uses for empty/thin clusters:
            "temporal",
            "reflection",
            "reflections",
            "potential",
            "seeds",
            "seed",
            "observation",
            "observations",
            "silent",
            "silence",
            "unresolved",
            "statistical",
            "minimal",
            "interest",
            "inquiry",
            "shadow",
            "shadows",
            "whisper",
            "whispers",
            "remnant",
            "remnants",
            "trace",
            "traces",
            "fleeting",
            "ephemeral",
            "abstract",
            "nascent",
            "liminal",
        }
        words = [w for w in re.split(r"[^a-z0-9]+", normalized) if w]
        if words and all(w in generic_tokens for w in words):
            return True

        return False

    @staticmethod
    def _derive_fallback_community_name(member_rows: list[dict]) -> str:
        """Create a readable deterministic fallback from member names."""
        member_names = [row.get("name") for row in member_rows if row.get("name")]
        if not member_names:
            return "Related knowledge topics"
        if len(member_names) == 1:
            return f"About {member_names[0]}"
        if len(member_names) == 2:
            return f"{member_names[0]} and {member_names[1]}"
        return f"{member_names[0]} and related topics"

    @staticmethod
    def _format_member_context(rows: list[dict]) -> str:
        """Format member node rows into a bulleted context string for LLM prompts."""
        lines = []
        for row in rows:
            name = row.get("name", "")
            label = (row.get("labels") or ["Node"])[0]
            contexts = row.get("isolated_contexts") or []
            if contexts:
                context_text = " | ".join(contexts)
                lines.append(f"- {name} ({label}): {context_text}")
            else:
                lines.append(f"- {name} ({label})")
        return "\n".join(lines)

    def _build_community_summary(
        self,
        member_rows: list[dict],
        community_level: int,
        strict_naming: bool = False,
    ) -> tuple[str | None, str | None]:
        """Generate a community name and summary in a single LLM call.

        All member descriptions are passed at once — no chunking.  The LLM context
        window is large enough to handle even the biggest L2 communities (~220 nodes).
        L1 and L0 summaries should use ``_build_rollup_summary`` instead, which rolls
        up from child community summaries rather than raw node descriptions.
        """
        context = self._format_member_context(member_rows)
        prompt = (
            "The following entities are closely related based on how they appear across a knowledge graph.\n\n"
            f"Cluster level: {community_level}  [L2 = most fine-grained → L1 = mid-level → L0 = broadest]\n"
            f"Entities ({len(member_rows)} total):\n{context}\n\n"
            "Generate:\n"
            "1. A short descriptive name that captures what ties these entities together\n"
            "2. A thorough summary covering the key themes, notable connections, relationships, and any "
            "meaningful patterns or distinctions among these entities. Write as many sentences as needed.\n\n"
            "Name rules:\n"
            "- Use plain, natural language\n"
            "- Anchor the name in concrete topics drawn from the entities themselves\n"
            "- Do NOT use meta-labels like 'Node Cluster', 'Isolated Group', 'Cluster L2-14', or any variant\n"
            "- Do NOT use the words isolated / node / cluster / community / group as the central theme\n\n"
            "Reply in EXACTLY this format — no preamble, no trailing text:\n"
            "NAME: <name>\n"
            "SUMMARY: <summary>"
        )
        if strict_naming:
            prompt += (
                "\n\nThis is a retry because the previous name was too generic. "
                "The NAME must be specific and user-facing."
            )
        raw = (
            llm_service.reason(
                prompt, model=llm_service._get_ingestion_model()
            )  # pylint: disable=protected-access
            or ""
        )
        return self._parse_name_summary(raw)

    def _build_rollup_summary(
        self,
        child_community_rows: list[dict],
        community_level: int,
        strict_naming: bool = False,
    ) -> tuple[str | None, str | None]:
        """Generate a community name and summary by rolling up from child community summaries.

        Used for L1 (rolls up L2 descriptions) and L0 (rolls up L1 descriptions).
        All child summaries are passed in a single LLM call — no chunking.
        """
        if not child_community_rows:
            return None, None
        context = "\n".join(
            f"- {row['name']}: {row['summary']}"
            for row in child_community_rows
            if row.get("summary")
        )
        if not context:
            return None, None
        prompt = (
            f"The following are descriptions of {len(child_community_rows)} related groups "
            "that together form a broader connected topic.\n\n"
            f"Cluster level: {community_level}  [L2 = most fine-grained → L1 = mid-level → L0 = broadest]\n\n"
            "Groups:\n"
            f"{context}\n\n"
            "Synthesize:\n"
            "1. A short descriptive name capturing the overarching theme across all groups\n"
            "2. A thorough summary covering the shared themes, what connects the groups, major patterns, "
            "and the big-picture significance. Write as many sentences as needed.\n\n"
            "Name rules:\n"
            "- Use plain, natural language\n"
            "- Anchor the name in concrete topics drawn from the group descriptions\n"
            "- Do NOT use meta-labels like 'Node Cluster', 'Isolated Group', or any variant\n"
            "- Do NOT use the words isolated / node / cluster / community / group as the central theme\n\n"
            "Reply in EXACTLY this format — no preamble, no trailing text:\n"
            "NAME: <name>\n"
            "SUMMARY: <summary>"
        )
        if strict_naming:
            prompt += (
                "\n\nThis is a retry because the previous name was too generic. "
                "The NAME must be specific and user-facing."
            )
        raw = (
            llm_service.reason(
                prompt, model=llm_service._get_ingestion_model()
            )  # pylint: disable=protected-access
            or ""
        )
        return self._parse_name_summary(raw)

    def rebuild_leiden_communities(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self,
    ) -> int:
        """Run a full 3-level Leiden recomputation and rebuild community nodes.

        Cooperative cancellation: checks ``_tracker.cancel_recompute`` between every
        cluster summary.  When set, the run exits early (returning the count built so far) so a
        pending ingestion can proceed.  The tracker resets the flag and reschedules the full run
        after the next idle window.
        """

        global _community_run_seq, _community_run_active_seq, _community_run_running  # pylint: disable=global-statement

        # Register this as the newest requested run. If another run is active, request
        # cancellation and wait for handoff. Only the newest request is allowed to start.
        with _community_run_state_lock:
            _community_run_seq += 1
            requested_seq = _community_run_seq
            had_active_run = _community_run_running
            active_seq = _community_run_active_seq
            if had_active_run:
                _tracker.cancel_recompute.set()

        if had_active_run:
            logger.info(
                "[Community] New recompute requested while run "
                f"#{active_seq} is active — signalling cancel and waiting for handoff."
            )

        while True:
            with _community_run_state_lock:
                if requested_seq != _community_run_seq:
                    logger.info(
                        "[Community] Recompute request superseded by a newer request "
                        f"(request #{requested_seq}) — skipping."
                    )
                    return 0
                if not _community_run_running:
                    _community_run_running = True
                    _community_run_active_seq = requested_seq
                    break
            time.sleep(0.25)

        # Start with a clean cancellation state for this newly claimed run.
        _tracker.cancel_recompute.clear()
        # If ingestion became active during claim handoff, preserve the cancel signal.
        if _tracker.has_active_ingestions():
            _tracker.cancel_recompute.set()

        try:
            logger.info(
                f"\n{'='*70}\n"
                f"[Community] Starting full Leiden community recompute\n"
                f"{'='*70}"
            )

            nodes = graph_service.get_indexable_nodes_for_communities()
            if not nodes:
                logger.warning(
                    "[Community] No indexable nodes found — aborting Leiden recompute."
                )
                return 0

            logger.info(f"[Community] {len(nodes)} indexable nodes fetched from Kuzu")

            # Enrich structural node rows with content from Qdrant (description, facts)
            _node_ids_for_leiden = [n["node_id"] for n in nodes if n.get("node_id")]
            if _node_ids_for_leiden:
                _qdrant_content_map = qdrant_service.get_nodes_content_by_ids(
                    _node_ids_for_leiden
                )
                for n in nodes:
                    _nid = n.get("node_id")
                    if _nid and _nid in _qdrant_content_map:
                        _c = _qdrant_content_map[_nid]
                        n["isolated_contexts"] = _c.get("isolated_contexts", [])
                _enriched = sum(1 for n in nodes if n.get("isolated_contexts"))
                logger.info(
                    f"[Community] Qdrant content enrichment: {_enriched}/{len(nodes)} nodes "
                    f"enriched with isolated contexts"
                )

            old_community_ids = graph_service.clear_all_communities()
            logger.info(
                f"[Community] Cleared {len(old_community_ids)} old community nodes "
                f"(Kuzu + Qdrant + Typesense)"
            )
            for old_community_id in old_community_ids:
                qdrant_service.delete_node(old_community_id)
                typesense_service.delete_node(old_community_id)

            node_ids = [node["node_id"] for node in nodes]
            node_lookup = {node["node_id"]: node for node in nodes}

            # ─── True hierarchical community building ─────────────────────────────
            # All three levels use embedding similarity clustering (agglomerative,
            # cosine distance, average linkage) with progressively looser thresholds:
            #   L2 (finest):  distance_threshold=0.25  — only closely related entities
            #   L1 (mid):     distance_threshold=0.50  — moderate thematic overlap
            #   L0 (broadest):distance_threshold=0.75  — broad topic grouping
            # L2 clusters all entities. L1 clusters L2 communities. L0 clusters L1 communities.
            # ──────────────────────────────────────────────────────────────────────
            level_assignments: dict[str, dict[int, str]] = (
                {}
            )  # entity_node_id → {level → community_id}
            community_summaries: dict[str, str] = {}  # community_id → summary text
            community_names: dict[str, str] = {}  # community_id → display name
            community_entity_members: dict[str, list[str]] = (
                {}
            )  # community_id → entity node IDs
            created = 0

            # ── Local helpers ────────────────────────────────────────────────────

            def _embedding_cluster(
                item_ids: list[str],
                item_texts: list[str],
                distance_threshold: float = 0.35,
            ) -> list[list[str]]:
                """Cluster items by embedding cosine similarity.

                Uses agglomerative clustering with average linkage on cosine distance.
                distance_threshold=0.35 means items need cosine similarity ≥ ~0.65
                to be grouped together. No need to pre-specify cluster count.
                """
                import numpy as np
                from sklearn.cluster import AgglomerativeClustering

                if not item_ids:
                    return []
                if len(item_ids) == 1:
                    return [list(item_ids)]

                # Embed all texts in one batched call.
                vectors = embedding_service.embed_documents(item_texts)
                arr = np.array(vectors, dtype=np.float32)

                # L2-normalise so cosine distance = 1 − cosine_similarity.
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                arr /= norms

                clustering = AgglomerativeClustering(
                    n_clusters=None,
                    distance_threshold=distance_threshold,
                    metric="cosine",
                    linkage="average",
                )
                labels = clustering.fit_predict(arr)

                clusters: dict[int, list[str]] = {}
                for item_id, label in zip(item_ids, labels):
                    clusters.setdefault(int(label), []).append(item_id)
                return list(clusters.values())

            def _commit_community(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
                community_level: int,
                member_entity_ids: list[str],
                rollup_rows: list[dict],
                cluster_label: str,
            ) -> str | None:
                """Summarise, name, and persist one community node.

                ``rollup_rows`` is non-empty for L1/L0 (summaries of child communities +
                orphan descriptions).  Empty list triggers direct node-description
                summarisation (L2).  Returns the new community_id, or None if skipped.
                """
                nonlocal created

                if not member_entity_ids:
                    return None
                if len(member_entity_ids) == 1:
                    logger.debug(
                        f"[Community] Skipping {cluster_label}: singleton entity cluster "
                        f"({node_lookup.get(member_entity_ids[0], {}).get('name', member_entity_ids[0])})"
                    )
                    return None
                if rollup_rows and len(rollup_rows) == 1:
                    logger.debug(
                        f"[Community] Skipping {cluster_label}: only 1 rollup input "
                        f"('{rollup_rows[0].get('name', '?')}')"
                    )
                    return None

                member_rows = [
                    node_lookup[nid] for nid in member_entity_ids if nid in node_lookup
                ]
                name: str | None = None
                summary: str | None = None
                try:
                    if not rollup_rows:
                        name, summary = self._build_community_summary(
                            member_rows, community_level
                        )
                    else:
                        name, summary = self._build_rollup_summary(
                            rollup_rows, community_level
                        )
                except Exception as _summ_err:  # pylint: disable=broad-exception-caught
                    logger.warning(
                        f"[Community] Summary failed for {cluster_label}: {_summ_err}"
                    )
                    return None

                # Reject generic names and retry up to 2 times.
                for retry_idx in range(2):
                    if name and not self._is_generic_community_name(name):
                        break
                    if _tracker.cancel_recompute.is_set():
                        return None
                    logger.warning(
                        f"[Community] {cluster_label}: rejecting generic name "
                        f"'{name or '(empty)'}' (retry {retry_idx + 1}/2)"
                    )
                    try:
                        if rollup_rows:
                            rn, rs = self._build_rollup_summary(
                                rollup_rows, community_level, strict_naming=True
                            )
                        else:
                            rn, rs = self._build_community_summary(
                                member_rows, community_level, strict_naming=True
                            )
                        if rn:
                            name = rn
                        if rs:
                            summary = rs
                    except (
                        Exception
                    ) as _retry_err:  # pylint: disable=broad-exception-caught
                        logger.warning(
                            f"[Community] {cluster_label}: name retry failed: {_retry_err}"
                        )

                if not name:
                    name = self._derive_fallback_community_name(member_rows)
                elif self._is_generic_community_name(name):
                    logger.warning(
                        f"[Community] {cluster_label}: using fallback name after generic output '{name}'"
                    )
                    name = self._derive_fallback_community_name(member_rows)
                if not summary:
                    summary = (
                        f"Community at level {community_level} containing "
                        f"{len(member_entity_ids)} related nodes."
                    )

                community_id = f"community_l{community_level}_{uuid.uuid4().hex}"

                graph_service.create_leiden_community(
                    community_id=community_id,
                    community_level=community_level,
                    name=name,
                    summary=summary,
                    member_node_ids=member_entity_ids,
                )
                logger.debug(
                    f"  [Community] Kuzu community node created: '{name}' id={community_id}"
                )

                typesense_service.index_node(
                    node_id=community_id,
                    name=name,
                    node_type="community",
                    community_level=community_level,
                )

                # Write membership NL sentences to Qdrant (flagged is_community_rel=True).
                try:
                    _nl_texts = [
                        f"{node_lookup.get(nid, {}).get('name') or nid} is a member of the '{name}' community."
                        for nid in member_entity_ids
                        if nid in node_lookup
                    ]
                    _nl_vectors = (
                        embedding_service.embed_documents(_nl_texts)
                        if _nl_texts
                        else []
                    )
                    _valid_nids = [
                        nid for nid in member_entity_ids if nid in node_lookup
                    ]
                    for nid, nl_text, nl_vec in zip(
                        _valid_nids, _nl_texts, _nl_vectors
                    ):
                        qdrant_service.upsert_node_relationship(
                            relationship_id=f"community_rel_{community_id}_{nid}",
                            natural_language=nl_text,
                            nl_vector=nl_vec,
                            source_node_id=nid,
                            target_node_id=community_id,
                            is_community_rel=True,
                        )
                    logger.debug(
                        f"  [Community] Qdrant NL sentences written: {len(_nl_texts)} "
                        f"for community '{name}'"
                    )
                except Exception as _rel_err:  # pylint: disable=broad-exception-caught
                    logger.warning(
                        f"[Community] Membership NL write failed for {community_id}: {_rel_err}"
                    )

                logger.info(
                    f"  [Community] ✓ Created L{community_level} community '{name}' "
                    f"(id={community_id}, {len(member_entity_ids)} members)"
                )
                graph_service.set_node_community_membership(
                    member_entity_ids, community_id, community_level
                )
                for nid in member_entity_ids:
                    level_assignments.setdefault(nid, {})[
                        community_level
                    ] = community_id
                community_summaries[community_id] = summary
                community_names[community_id] = name
                community_entity_members[community_id] = list(member_entity_ids)
                created += 1
                return community_id

            # ─── Level 2: embedding cluster on raw entity nodes ────────────────────
            l2_entity_texts: list[str] = []
            for _nid in node_ids:
                _n = node_lookup[_nid]
                _ctxs = " | ".join(_n.get("isolated_contexts") or [])
                l2_entity_texts.append(
                    f"{_n.get('name') or _nid}: {_ctxs}"
                    if _ctxs
                    else (_n.get("name") or _nid)
                )
            logger.info(
                f"[Community] Embedding {len(node_ids)} entities for L2 similarity clustering"
            )
            l2_clusters = _embedding_cluster(
                node_ids, l2_entity_texts, distance_threshold=0.25
            )
            logger.info(
                f"[Community] L2 embedding clusters: {len(l2_clusters)} clusters | "
                f"sizes: min={min(len(c) for c in l2_clusters)}, "
                f"max={max(len(c) for c in l2_clusters)}, "
                f"avg={sum(len(c) for c in l2_clusters) / len(l2_clusters):.1f}"
            )

            entity_to_l2: dict[str, str] = {}  # entity_node_id → L2 community_id
            l2_community_ids: list[str] = []
            for cluster_index, member_node_ids in enumerate(l2_clusters):
                if _tracker.cancel_recompute.is_set():
                    logger.info(
                        f"[Community] Recompute cancelled at L2 cluster "
                        f"{cluster_index + 1}/{len(l2_clusters)} — "
                        "ingestion/newer run arrived; will restart after next idle window."
                    )
                    return created
                logger.info(
                    f"[Community] Summarising L2 cluster {cluster_index + 1}/{len(l2_clusters)} "
                    f"({len(member_node_ids)} members)"
                )
                cid = _commit_community(
                    2,
                    member_node_ids,
                    [],
                    f"L2 cluster {cluster_index + 1}/{len(l2_clusters)}",
                )
                if cid:
                    l2_community_ids.append(cid)
                    for nid in member_node_ids:
                        entity_to_l2[nid] = cid

            l2_orphan_ids = [nid for nid in node_ids if nid not in entity_to_l2]
            logger.info(
                f"[Community] L2 complete: {len(l2_community_ids)} communities, "
                f"{len(l2_orphan_ids)} orphan entity nodes"
            )

            # ─── Level 1: embedding cluster on L2 communities only ─────────────
            # Orphan entities (not in any L2 community) are excluded — they weren't
            # clusterable at L2 and would only bloat higher levels.
            l1_super_ids = l2_community_ids
            l1_super_texts: list[str] = [
                (
                    f"{community_names.get(_sid, _sid)}: {community_summaries[_sid]}"
                    if _sid in community_summaries
                    else _sid
                )
                for _sid in l1_super_ids
            ]
            logger.info(
                f"[Community] Embedding {len(l1_super_ids)} L2 communities for L1 similarity clustering"
            )
            l1_clusters = _embedding_cluster(l1_super_ids, l1_super_texts)
            logger.info(
                f"[Community] L1 embedding clusters: {len(l1_clusters)} clusters"
            )

            entity_to_l1: dict[str, str] = {}
            l1_community_ids: list[str] = []
            for cluster_index, super_cluster in enumerate(l1_clusters):
                if _tracker.cancel_recompute.is_set():
                    logger.info(
                        f"[Community] Recompute cancelled at L1 cluster "
                        f"{cluster_index + 1}/{len(l1_clusters)} — "
                        "ingestion/newer run arrived; will restart after next idle window."
                    )
                    return created

                # Resolve super-nodes → entity IDs and build rollup inputs.
                l1_member_entity_ids: list[str] = []
                l1_rollup_rows: list[dict] = []
                for super_id in super_cluster:
                    if super_id in community_entity_members:
                        # L2 community: expand to its entity members.
                        l1_member_entity_ids.extend(community_entity_members[super_id])
                        if super_id in community_summaries:
                            l1_rollup_rows.append(
                                {
                                    "name": community_names[super_id],
                                    "summary": community_summaries[super_id],
                                }
                            )

                logger.info(
                    f"[Community] Summarising L1 cluster {cluster_index + 1}/{len(l1_clusters)} "
                    f"({len(l1_member_entity_ids)} entity members from {len(super_cluster)} super-nodes)"
                )
                cid = _commit_community(
                    1,
                    l1_member_entity_ids,
                    l1_rollup_rows,
                    f"L1 cluster {cluster_index + 1}/{len(l1_clusters)}",
                )
                if cid:
                    l1_community_ids.append(cid)
                    for nid in l1_member_entity_ids:
                        entity_to_l1[nid] = cid

            logger.info(f"[Community] L1 complete: {len(l1_community_ids)} communities")

            # ─── Level 0: embedding cluster on L1 communities only ─────────────────
            # Only L1 communities feed L0 — unabsorbed L2s and orphan entities are
            # excluded to keep the hierarchy a true compression at each level.
            l0_super_ids = l1_community_ids
            l0_super_texts: list[str] = [
                (
                    f"{community_names.get(_sid, _sid)}: {community_summaries[_sid]}"
                    if _sid in community_summaries
                    else _sid
                )
                for _sid in l0_super_ids
            ]
            logger.info(
                f"[Community] Embedding {len(l0_super_ids)} L1 communities for L0 similarity clustering"
            )
            l0_clusters = _embedding_cluster(
                l0_super_ids, l0_super_texts, distance_threshold=0.75
            )
            logger.info(
                f"[Community] L0 embedding clusters: {len(l0_clusters)} clusters"
            )

            for cluster_index, super_cluster in enumerate(l0_clusters):
                if _tracker.cancel_recompute.is_set():
                    logger.info(
                        f"[Community] Recompute cancelled at L0 cluster "
                        f"{cluster_index + 1}/{len(l0_clusters)} — "
                        "ingestion/newer run arrived; will restart after next idle window."
                    )
                    return created

                l0_member_entity_ids: list[str] = []
                l0_rollup_rows: list[dict] = []
                for super_id in super_cluster:
                    if super_id in community_entity_members:
                        # L1 community: expand to its entity members.
                        l0_member_entity_ids.extend(community_entity_members[super_id])
                        if super_id in community_summaries:
                            l0_rollup_rows.append(
                                {
                                    "name": community_names[super_id],
                                    "summary": community_summaries[super_id],
                                }
                            )
                    elif super_id in node_lookup:
                        # Orphan entity node: contribute directly.
                        l0_member_entity_ids.append(super_id)
                        _n = node_lookup[super_id]
                        l0_rollup_rows.append(
                            {
                                "name": _n.get("name") or super_id,
                                "summary": (
                                    f"A {_n.get('type', 'node')} named {_n.get('name') or super_id}."
                                ),
                            }
                        )

                logger.info(
                    f"[Community] Summarising L0 cluster {cluster_index + 1}/{len(l0_clusters)} "
                    f"({len(l0_member_entity_ids)} entity members from {len(super_cluster)} super-nodes)"
                )
                _commit_community(
                    0,
                    l0_member_entity_ids,
                    l0_rollup_rows,
                    f"L0 cluster {cluster_index + 1}/{len(l0_clusters)}",
                )

            # Refresh ES relationship_natural_language for nodes whose membership changed.
            # Community fields are no longer stored on regular nodes — only the NL sentence
            # written above carries that signal for retrieval.
            for node_id in level_assignments:
                payload = graph_service.get_node_storage_payload(node_id)
                if not payload:
                    continue
                relationship_nl = payload.get("relationship_natural_language") or []
                typesense_service.update_node_community(
                    node_id=node_id,
                    relationship_natural_language=" ".join(
                        sentence for sentence in relationship_nl if sentence
                    ),
                    name=payload.get("name") or "",
                )

            # ── Compute & store 3D positions for the new layout ──────────────────
            try:
                from app.utils.graph_layout import compute_spring_layout_3d

                # After Leiden has created communities, rerun spring layout so
                # community nodes are pulled into the correct positions by their members.
                spring_node_ids, spring_edges = (
                    graph_service.get_all_node_ids_and_edges()
                )
                positions = compute_spring_layout_3d(spring_node_ids, spring_edges)
                graph_service.store_node_positions(positions)
                logger.info(
                    f"[Community] Spring layout recomputed after Leiden: "
                    f"{len(positions)} nodes, {len(spring_edges)} edges"
                )
            except Exception as _layout_err:  # pylint: disable=broad-exception-caught
                logger.warning(
                    f"[Community] 3D layout computation failed (non-fatal): {_layout_err}"
                )

            logger.info(
                f"\n{'='*70}\n"
                f"[Community] Embedding recompute COMPLETE: {created} community nodes rebuilt\n"
                f"  Entities: {len(node_ids)}\n"
                f"  Levels: L2 → L1 → L0 (embedding similarity hierarchy)\n"
                f"{'='*70}"
            )
            return created
        finally:
            # Always release single-flight ownership so a newer queued request can proceed.
            with _community_run_state_lock:
                if _community_run_active_seq == requested_seq:
                    _community_run_running = False
                    _community_run_active_seq = 0


ingestion_workflow = IngestionWorkflow()
