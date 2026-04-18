import asyncio
import uuid
from collections import defaultdict
from datetime import datetime

from app.core.config import settings
from app.core.log import get_logger
from app.schemas.extraction import Extraction, NoteInput
from app.services.elasticsearch_service import elasticsearch_service
from app.services.graph import graph_service
from app.services.ingestion_tracker import ingestion_tracker
from app.services.llm import llm_service
from app.services.qdrant_service import qdrant_service
from app.workflows.agents.ingestion_agent import ingestion_agent

# Hard cap on concurrent ingestion pipelines.
# Each pipeline makes sequential DB calls; capping at 20 keeps peak pool
# usage at ~20 (ingestion) + ~20 (HTTP handlers) = 40, well within the
# pool_size=30 + max_overflow=20 = 50 ceiling set in database.py.
_PROCESS_CONCURRENCY = 20
_process_semaphore = asyncio.Semaphore(_PROCESS_CONCURRENCY)

logger = get_logger("IngestionPipeline")


class EntityLockManager:
    """
    Manages per-entity locks to prevent race conditions during summary updates.
    Ensures that multiple notes updating the same entity wait for each other.
    """

    def __init__(self):
        self._locks = defaultdict(asyncio.Lock)

    def get_lock(self, label: str, name: str):
        return self._locks[(label, name.lower().strip())]


entity_lock_manager = EntityLockManager()


class IngestionWorkflow:
    async def _update_note_domain_postgres(self, note_id: str, domain: str):
        """
        Syncs the extracted domain to Postgres.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(domain=domain)
                )
                await session.commit()
                logger.info(
                    f"[Ingestion] Updated Postgres Domain for Note {note_id}: '{domain}'"
                )
            except Exception as e:
                logger.error(f"Error updating Postgres domain: {e}")
                raise e

    async def process_note(self, note_input: NoteInput, note_id: str = None):
        if not note_id:
            note_id = str(uuid.uuid4())

        # Register with the tracker BEFORE the semaphore so the community-detection
        # idle timer never fires while tasks are queued waiting for a slot.
        await ingestion_tracker.begin_ingestion()

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
            import time

            t_start = time.perf_counter()
            try:
                final_state = await ingestion_agent.ainvoke(initial_state)
                t_end = time.perf_counter()

                if final_state["errors"]:
                    logger.error(
                        f"[Ingestion] FAILURE note_id={note_id}: {final_state['errors']}"
                    )
                    raise Exception(f"Ingestion Agent Failed: {final_state['errors']}")

                extraction = final_state.get("extraction")
                if extraction:
                    logger.info(
                        f"[Ingestion] Agent complete — extracted "
                        f"{len(getattr(extraction, 'nodes', []))} nodes, "
                        f"{len(getattr(extraction, 'relationships', []))} relationships"
                    )
                    for n in getattr(extraction, 'nodes', []):
                        logger.debug(f"  [Extraction] node: '{n.name}' type='{n.type}'")
                    for r in getattr(extraction, 'relationships', []):
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

            except Exception as exc:
                await self._mark_note_failed(note_id)
                raise

            finally:
                # Always decrement the active counter and potentially schedule
                # community recompute, regardless of success or failure.
                await ingestion_tracker.end_ingestion(self.rebuild_leiden_communities)

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
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

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
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

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
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

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
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

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

    def _write_ontology(
        self,
        note_id: str,
        content: str,
        extraction: Extraction,
        created_at: str,
        custom_title: str = None,
    ):
        logger.info(f"[Ontology] Writing ontology for note {note_id}")
        # 0. Generate or use provided Title & Summary
        if custom_title:
            title = custom_title
            logger.info(f"[Ontology] Using provided title: '{title}'")
        else:
            title = llm_service.generate_title(content)
            logger.info(f"[Ontology] Generated title: '{title}'")
        summary = llm_service.summarize(content)
        logger.debug(f"[Ontology] Summary ({len(summary or '')} chars): {(summary or '')[:120]}...")

        # Base Note Node — bare structural node in Neo4j with :Note label.
        # All content (title, summary, domain) lives in Qdrant node_cores.
        query_note = """
        MERGE (n:Note:Indexable {id: $id})
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
        if extraction.nodes:
            from app.services.embedding import embedding_service

            node_embeddings = {}
            for n in extraction.nodes:
                norm_name = normalize_name(n.name)
                if not norm_name:
                    continue
                text_to_embed = f"{norm_name} ({n.type}): {(n.isolated_context or '')[:200]}"
                node_embeddings[norm_name] = embedding_service.embed_query(text_to_embed)

            # Resolve or assign stable IDs: look up Qdrant first so we reuse
            # existing IDs for known nodes and generate fresh ones for new nodes.
            node_data = []
            for node in extraction.nodes:
                norm_name = normalize_name(node.name)
                if not norm_name:
                    continue
                existing_id = qdrant_service.find_node_id_by_name(norm_name)
                is_new = existing_id is None
                assigned_id = existing_id or f"node_{str(uuid.uuid4())}"
                node_data.append({
                    "id": assigned_id,
                    "name": norm_name,
                    "type": (node.type or "thing").lower().strip(),
                    "embedding": node_embeddings.get(norm_name),
                    "is_new": is_new,
                })
                logger.info(
                    f"  [Ontology] node '{norm_name}' type='{(node.type or 'thing').lower()}' "
                    f"id={assigned_id} ({'NEW' if is_new else 'EXISTING'})"
                )

            # Build name→ID map for relationship creation below
            name_to_id: dict[str, str] = {d["name"]: d["id"] for d in node_data}
            logger.info(f"[Ontology] {len(node_data)} nodes resolved ({sum(1 for d in node_data if not qdrant_service.find_node_id_by_name(d['name']) is not None)} new) — writing to Neo4j")

            # Write bare structural nodes to Neo4j (id only — no content)
            query_nodes = """
            MERGE (note:Indexable {id: $note_id})
            WITH note
            UNWIND $data AS item
            MERGE (n:Indexable {id: item.id})
            MERGE (note)-[r:REFERENCES]->(n)
            SET r.note_id = $note_id,
                r.is_active = true
            """

            if node_data:
                graph_service.execute_query(
                    query_nodes,
                    {"data": [{"id": d["id"]} for d in node_data], "note_id": note_id},
                )

                self._detect_and_create_similarities(
                    nodes=[
                        {
                            "name": d["name"],
                            "entity_type": d["type"],
                            "context": next(
                                (n.isolated_context for n in extraction.nodes
                                 if normalize_name(n.name) == d["name"]),
                                "",
                            ),
                            "embedding": d["embedding"],
                            "node_id": d["id"],
                        }
                        for d in node_data
                    ],
                    note_id=note_id,
                    node_label="Indexable",
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
                            description="",
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

            for rel in extraction.relationships:
                try:
                    # Validate required fields
                    if not rel.source_name or not rel.target_name:
                        logger.warning(
                            f"[Relationship] Skipping - missing source or target name: "
                            f"{rel.source_name} -> {rel.target_name}"
                        )
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

                    source_label = "Indexable"
                    target_label = "Indexable"

                    # Normalize names to lowercase to match node storage
                    source_name_normalized = rel.source_name.lower().strip()
                    target_name_normalized = rel.target_name.lower().strip()

                    # Look up IDs from the name_to_id map (built from node_data above)
                    # falling back to Qdrant for nodes not created in this ingestion pass.
                    src_node_id = (
                        name_to_id.get(source_name_normalized)
                        or qdrant_service.find_node_id_by_name(source_name_normalized)
                        or ""
                    )
                    tgt_node_id = (
                        name_to_id.get(target_name_normalized)
                        or qdrant_service.find_node_id_by_name(target_name_normalized)
                        or ""
                    )

                    if not src_node_id:
                        logger.warning(
                            f"  [Ontology] Relationship skipped — source '{source_name_normalized}' "
                            f"not found in name_to_id or Qdrant"
                        )
                        continue
                    if not tgt_node_id:
                        logger.warning(
                            f"  [Ontology] Relationship skipped — target '{target_name_normalized}' "
                            f"not found in name_to_id or Qdrant"
                        )
                        continue

                    logger.debug(
                        f"  [Ontology] Creating rel: '{source_name_normalized}' "
                        f"--[{rel_type}]--> '{target_name_normalized}' "
                        f"(strength={rel.strength}, confidence={rel.confidence}, relevance={rel.relevance}) "
                        f"NL: '{(rel.natural_language or '')[:80]}'"
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
                        natural_language=rel.natural_language or "",
                        note_id=note_id,
                        source_id=src_node_id,
                        target_id=tgt_node_id,
                    )

                    # Write relationship to Qdrant node_relationships on new/evolved rels.
                    if result.get("action") in ("created", "evolved") and src_node_id and tgt_node_id:
                        from app.services.embedding import embedding_service as _emb

                        nl_text = result.get("natural_language") or (
                            f"{source_name_normalized} "
                            f"{rel_type.replace('_', ' ')} "
                            f"{target_name_normalized}"
                        )
                        nl_vector = _emb.embed_documents([nl_text])[0]
                        qdrant_service.upsert_node_relationship(
                            relationship_id=result["relationship_id"],
                            natural_language=nl_text,
                            nl_vector=nl_vector,
                            source_node_id=src_node_id,
                            target_node_id=tgt_node_id,
                        )
                        logger.debug(
                            f"  [Ontology] Qdrant rel written: '{nl_text[:100]}'"
                        )

                    logger.info(
                        f"  [Ontology] Rel {result['action'].upper()}: "
                        f"'{source_name_normalized}' --[{rel_type}]--> '{target_name_normalized}'"
                    )

                except Exception as e:
                    logger.error(
                        f"[Relationship] Failed to create relationship "
                        f"{rel.source_name}->{rel.target_name}: {e}"
                    )
                    continue

        return title

    def _detect_and_create_similarities(
        self,
        nodes: list,
        note_id: str,
        node_label: str = "Indexable",
        entity_embeddings: dict = None,
        min_confidence: float = 0.8,
        cosine_threshold: float = 0.70,
    ):
        """
        4-gate similarity detection run after nodes are stored.

        Gate 1 — name similarity  : find_similar_entities (name containment / token overlap)
        Gate 2 — type match       : built into find_similar_entities query
        Gate 3 — embedding cosine : ≥ 0.60 between new node and candidate embeddings
        Gate 4 — LLM verification : detect_similarity returns (has_relationship, confidence, rel_type)

        On success writes a typed relationship such as IS_SHORTENED_TITLE or IS_CANONICAL_NAME_VARIANT.

        Args:
            nodes           : Either extraction entity objects (with .name/.type/.isolated_context)
                              OR dicts with keys: name, entity_type, context, embedding
            note_id         : Note being ingested (written to similarity relationship)
            node_label      : Neo4j label to operate on (Entity, Task, Persona, Concept, Reference)
            entity_embeddings: Legacy {normalised_name: vector} dict — used when nodes are objects
            min_confidence  : Gate 4 minimum confidence threshold
        """
        import math

        from app.services.llm import llm_service

        def _cosine(a: list[float], b: list[float]) -> float:
            if not a or not b or len(a) != len(b):
                return 0.0
            dot = sum(x * y for x, y in zip(a, b))
            mag_a = math.sqrt(sum(x * x for x in a))
            mag_b = math.sqrt(sum(x * x for x in b))
            if mag_a == 0 or mag_b == 0:
                return 0.0
            return dot / (mag_a * mag_b)

        def normalize_name(name: str) -> str:
            if not name:
                return ""
            return name.lstrip("#").strip().lower()

        # Normalize input to dicts regardless of whether objects or dicts were passed
        def _to_dict(n) -> dict:
            if isinstance(n, dict):
                return n
            # Legacy entity object path
            raw_name = normalize_name(getattr(n, "name", ""))
            return {
                "name": raw_name,
                "entity_type": getattr(n, "type", ""),
                "context": getattr(n, "isolated_context", "") or "",
                "embedding": (entity_embeddings or {}).get(raw_name),
            }

        # Skip single-word names — too many false positives
        candidates = [
            _to_dict(n)
            for n in nodes
            if len(
                normalize_name(
                    n.get("name", "") if isinstance(n, dict) else getattr(n, "name", "")
                ).split()
            )
            >= 2
        ]

        if not candidates:
            return

        logger.info(
            f"[Similarity] Checking {len(candidates)} {node_label} nodes for potential similarities..."
        )

        for node in candidates:
            entity_name = normalize_name(node["name"])
            entity_type = node.get("entity_type", "")
            entity_vec = node.get("embedding")
            entity_context = node.get("context", "")

            try:
                potential_aliases = graph_service.find_similar_entities(
                    entity_name=entity_name,
                    entity_type=entity_type,
                    limit=10,
                    node_label=node_label,
                )

                if not potential_aliases:
                    continue

                existing_aliases = {
                    a["name"]
                    for a in graph_service.get_similar_entities(
                        entity_name, node_label=node_label
                    )
                }

                gate3_survivors = []
                for potential in potential_aliases:
                    potential_name = potential.get("name", "")
                    if not potential_name or potential_name in existing_aliases:
                        continue

                    candidate_vec = potential.get("embedding")
                    if entity_vec and candidate_vec:
                        sim = _cosine(entity_vec, candidate_vec)
                        if sim < cosine_threshold:
                            logger.debug(
                                f"[Similarity] Gate3 fail: '{entity_name}' <-> "
                                f"'{potential_name}' cosine={sim:.3f}"
                            )
                            continue
                        logger.debug(
                            f"[Similarity] Gate3 pass: '{entity_name}' <-> "
                            f"'{potential_name}' cosine={sim:.3f}"
                        )
                    gate3_survivors.append(potential)

                if not gate3_survivors:
                    continue

                logger.info(
                    f"[Similarity] {len(gate3_survivors)} gate-3 survivors for "
                    f"'{entity_name}': {[p['name'] for p in gate3_survivors]}"
                )

                entity_facts = ""
                # Use the node_id from the dict if present (populated from name_to_id),
                # otherwise fall back to Qdrant name lookup.
                _enid = node.get("node_id") or qdrant_service.find_node_id_by_name(entity_name)
                if _enid:
                    _content = qdrant_service.get_node_content_by_id(_enid)
                    if _content:
                        facts_raw = _content.get("facts") or []
                        entity_facts = " ".join(facts_raw) if isinstance(facts_raw, list) else (facts_raw or "")

                for potential in gate3_survivors:
                    potential_name = potential.get("name", "")
                    potential_summary = potential.get("summary", "") or ""
                    potential_facts = potential.get("facts", "") or ""
                    # Enrich candidate with Qdrant content if not already present
                    _pot_node_id = potential.get("node_id")
                    if _pot_node_id and not potential_summary and not potential_facts:
                        _pot_content = qdrant_service.get_node_content_by_id(_pot_node_id)
                        if _pot_content:
                            potential_summary = _pot_content.get("description", "") or ""
                            facts_raw = _pot_content.get("facts") or []
                            potential_facts = " ".join(facts_raw) if isinstance(facts_raw, list) else (facts_raw or "")

                    is_same, confidence, rel_type = llm_service.detect_similarity(
                        name1=entity_name,
                        name2=potential_name,
                        context1=entity_context,
                        context2=potential_summary,
                        facts1=entity_facts,
                        facts2=potential_facts,
                    )

                    if is_same and confidence >= min_confidence:
                        rel_sentence = (
                            f"{entity_name} {(rel_type or 'RELATED_TO').lower().replace('_', ' ')} {potential_name}."
                        )
                        _src_id = qdrant_service.find_node_id_by_name(entity_name) or ""
                        _tgt_id = qdrant_service.find_node_id_by_name(potential_name) or ""
                        graph_service.create_or_update_relationship(
                            source_name=entity_name,
                            source_label=node_label,
                            target_name=potential_name,
                            target_label=node_label,
                            relationship_type=rel_type or "RELATED_TO",
                            confidence=round(confidence * 10, 1),
                            strength=5.0,
                            relevance=5.0,
                            natural_language=rel_sentence,
                            note_id=note_id,
                            source_id=_src_id,
                            target_id=_tgt_id,
                        )
                        logger.info(
                            f"[Similarity] RELATIONSHIP CREATED: '{entity_name}' "
                            f"-[{rel_type}]-> '{potential_name}' confidence={confidence:.2f}"
                        )
                    else:
                        logger.debug(
                            f"[Similarity] Rejected: '{entity_name}' <-> '{potential_name}' "
                            f"(has_rel={is_same}, confidence={confidence:.2f})"
                        )

            except Exception as e:
                logger.warning(
                    f"[Similarity] Failed to check similarity for '{entity_name}': {e}"
                )
                continue

    async def _queue_leiden_recompute_if_due(self, note_id: str) -> None:
        rows = graph_service.execute_query(
            """
            MATCH (:Indexable {id: $note_id})-[*1]-(n:Indexable)
            WHERE NOT n:Note AND NOT n:Community AND n.id IS NOT NULL
            RETURN DISTINCT n.id AS node_id
            """,
            {"note_id": note_id},
        )
        node_ids = [row["node_id"] for row in rows if row.get("node_id")]
        if not node_ids:
            return

        _, queue_size = await ingestion_tracker.queue_nodes_for_community_recompute(node_ids)
        logger.info(
            f"[Community] Queued {len(node_ids)} node IDs for Leiden recompute "
            f"(queue size: {queue_size}) — IDs: {node_ids[:10]}{'...' if len(node_ids) > 10 else ''}"
        )

    async def _update_neighborhoods(self, nodes, new_content: str):
        """
        Refreshes the summaries of all nodes affected by this note.
        Parallelizes updates to reduce total latency.
        """
        tasks_list = []

        for node in nodes or []:
            name = (node.name or "").lstrip("#").strip().lower()
            if not name:
                continue
            context = getattr(node, "isolated_context", "") or new_content
            ntype = (getattr(node, "type", "") or "").lower().strip() or "thing"
            tasks_list.append(self._update_node_summary("Indexable", name, context, node_type=ntype))

        if tasks_list:
            logger.info(f"[Neighborhood] Updating {len(tasks_list)} node summaries in parallel…")
            await asyncio.gather(*tasks_list)
            logger.info(f"[Neighborhood] {len(tasks_list)} node summaries update complete.")

    async def _update_node_summary(
        self,
        label: str,
        name: str,
        isolated_context: str,
        identifier_key: str = "name",
        node_type: str = "",
    ):
        """
        Updates a node's summary by accumulating ALL isolated contexts.

        APPROACH:
        1. Append new isolated_context to node's isolated_contexts list
        2. Generate fresh summary from ALL accumulated contexts
        3. Store both the list (for raw context retrieval) and summary (for distilled retrieval)

        This allows A/B testing: raw contexts vs LLM summaries.

        Args:
            label: Node label (Entity, Concept, Task, etc.)
            name: Node identifier
            isolated_context: Pre-isolated context from LLM extraction (already filtered)
            identifier_key: Property to match on (name, description, trait, title)
        """
        async with entity_lock_manager.get_lock(label, name):
            loop = asyncio.get_running_loop()

            # 1. Get node_id from Qdrant (name is authoritative there), not from Neo4j.
            def _get_existing():
                return qdrant_service.find_node_id_by_name(name)

            node_id: str | None = await loop.run_in_executor(None, _get_existing)
            existing_contexts: list[str] = []

            existing_facts_set: set[str] = set()
            existing_questions_set: set[str] = set()

            if node_id:
                # Fetch existing isolated_contexts, facts, and questions from Qdrant
                def _get_qdrant_contexts():
                    _content = qdrant_service.get_node_content_by_id(node_id)
                    return _content or {}

                _existing_content = await loop.run_in_executor(None, _get_qdrant_contexts)
                existing_contexts = _existing_content.get("isolated_contexts", [])
                existing_facts_set = set(_existing_content.get("facts", []))
                existing_questions_set = set(_existing_content.get("potential_questions", []))
                logger.info(
                    f"  [NodeSummary] '{name}' EXISTING id={node_id} "
                    f"— {len(existing_contexts)} prior context(s), "
                    f"{len(existing_facts_set)} facts, {len(existing_questions_set)} questions fetched from Qdrant"
                )
            else:
                # New node — mint an ID and ensure the structural node exists in Neo4j
                node_id = f"node_{str(uuid.uuid4())}"
                logger.info(
                    f"  [NodeSummary] '{name}' NEW id={node_id} — minting and writing structural Neo4j node"
                )

                def _merge_node():
                    graph_service.execute_query(
                        f"MERGE (n:{label} {{id: $node_id}})",
                        {"node_id": node_id},
                    )

                await loop.run_in_executor(None, _merge_node)

            # 2. Append new context to list
            existing_contexts.append(isolated_context)
            logger.debug(
                f"  [NodeSummary] '{name}' context count after append: {len(existing_contexts)}"
            )

            # 3. Generate description from ALL contexts joined together
            all_contexts_text = "\n\n".join(existing_contexts)
            logger.info(
                f"  [NodeSummary] '{name}' calling LLM to generate description from "
                f"{len(existing_contexts)} context(s) ({len(all_contexts_text)} total chars)"
            )

            summary_data = await llm_service.generate_entity_summary_async(
                all_contexts_text,
                name,
                label,
            )
            description = summary_data["description"]
            logger.info(
                f"  [NodeSummary] '{name}' description generated: {len(description or '')} chars"
            )
            logger.debug(
                f"  [NodeSummary] '{name}' description preview: {(description or '')[:160]}..."
            )

            # Fetch the actual LLM-assigned semantic type for this node.
            # For existing nodes, read from Qdrant. For new nodes, use the type
            # supplied by the caller (from extraction output), defaulting to "thing".
            def _get_node_type():
                _content = qdrant_service.get_node_content_by_id(node_id)
                if _content and _content.get("type"):
                    return _content["type"]
                return (node_type or "thing").lower().strip() or "thing"

            _node_type_val = await loop.run_in_executor(None, _get_node_type)

            node_type = _node_type_val

            # Extract atomic facts as proposition sentences
            def _extract_facts():
                return llm_service.extract_atomic_facts(all_contexts_text, name, label)

            facts_list: list[str] = await loop.run_in_executor(None, _extract_facts)
            import json as _json

            facts_json = _json.dumps(facts_list) if facts_list else "[]"
            logger.info(
                f"  [NodeSummary] '{name}' extracted {len(facts_list)} atomic fact(s)"
            )
            for _fi, _fact in enumerate(facts_list or []):
                logger.debug(f"    [NodeSummary] fact[{_fi}]: {_fact}")

            # Generate potential questions
            def _gen_questions():
                return llm_service.generate_potential_questions(
                    name=name,
                    node_type=node_type,
                    description=description,
                    facts_list=facts_list or [],
                )

            potential_questions: list[str] = await loop.run_in_executor(
                None, _gen_questions
            )
            logger.info(
                f"  [NodeSummary] '{name}' generated {len(potential_questions)} potential question(s)"
            )
            for _qi, _q in enumerate(potential_questions or []):
                logger.debug(f"    [NodeSummary] question[{_qi}]: {_q}")

            # Merge new facts with existing ones — union, deduplicated by lowercased text.
            # This ensures re-ingestion never loses facts from prior ingestions.
            if existing_facts_set:
                _existing_lower = {f.lower() for f in existing_facts_set}
                _merged_facts = list(existing_facts_set)
                for _f in facts_list:
                    if _f.strip() and _f.strip().lower() not in _existing_lower:
                        _merged_facts.append(_f.strip())
                        _existing_lower.add(_f.strip().lower())
                facts_list = _merged_facts
                logger.info(
                    f"  [NodeSummary] '{name}' facts after merge: {len(facts_list)} total "
                    f"({len(existing_facts_set)} prior + new)"
                )

            # Merge new questions with existing ones — same dedup strategy.
            if existing_questions_set:
                _existing_q_lower = {q.lower() for q in existing_questions_set}
                _merged_questions = list(existing_questions_set)
                for _q in potential_questions:
                    if _q.strip() and _q.strip().lower() not in _existing_q_lower:
                        _merged_questions.append(_q.strip())
                        _existing_q_lower.add(_q.strip().lower())
                potential_questions = _merged_questions
                logger.info(
                    f"  [NodeSummary] '{name}' questions after merge: {len(potential_questions)} total "
                    f"({len(existing_questions_set)} prior + new)"
                )

            logger.info(
                f"  [NodeSummary] '{name}' generating embeddings for description + "
                f"{len(facts_list or [])} facts + {len(potential_questions)} questions + "
                f"{len(existing_contexts)} contexts"
            )

            # 4. Generate embeddings for Qdrant writes
            from app.services.embedding import embedding_service

            def _generate_embeddings():
                # Embed description for node_cores
                desc_vector = embedding_service.embed_documents([description])[0]

                # Embed each proposition fact sentence
                fact_items = []
                for fact_sentence in facts_list or []:
                    vec = embedding_service.embed_documents([fact_sentence])[0]
                    fact_items.append({"content": fact_sentence, "vector": vec})

                # Embed each potential question
                question_items = []
                for q in potential_questions:
                    vec = embedding_service.embed_documents([q])[0]
                    question_items.append({"content": q, "vector": vec})

                # Embed each isolated context
                context_items = []
                for ctx in existing_contexts:
                    if ctx and ctx.strip():
                        vec = embedding_service.embed_documents([ctx])[0]
                        context_items.append({"content": ctx, "vector": vec})

                return (
                    desc_vector,
                    fact_items,
                    question_items,
                    context_items,
                )

            (
                desc_vector,
                fact_items,
                question_items,
                context_items,
            ) = await loop.run_in_executor(None, _generate_embeddings)
            logger.debug(
                f"  [NodeSummary] '{name}' embeddings generated: "
                f"desc=1, facts={len(fact_items)}, questions={len(question_items)}, contexts={len(context_items)}"
            )

            # 5. Ensure the Neo4j structural node exists with this ID and carry
            # name + type so the graph endpoint never needs Qdrant for display labels.
            def _save_update():
                graph_service.execute_query(
                    f"MERGE (n:{label} {{id: $node_id}}) SET n.name = $name, n.type = $type",
                    {"node_id": node_id, "name": name, "type": node_type or "unknown"},
                )

            await loop.run_in_executor(None, _save_update)
            logger.debug(f"  [NodeSummary] '{name}' Neo4j structural MERGE done")

            # 6. Write to Qdrant (description → node_cores; items → sub-collections)
            def _write_qdrant():
                qdrant_service.upsert_node_core(
                    node_id=node_id,
                    name=name,
                    node_type=node_type,
                    description=description,
                    description_vector=desc_vector,
                )
                qdrant_service.upsert_node_items(
                    collection_name=settings.QDRANT_COLLECTION_NODE_FACTS,
                    node_id=node_id,
                    items=fact_items,
                )
                qdrant_service.upsert_node_items(
                    collection_name=settings.QDRANT_COLLECTION_NODE_QUESTIONS,
                    node_id=node_id,
                    items=question_items,
                )
                qdrant_service.upsert_node_items(
                    collection_name=settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,
                    node_id=node_id,
                    items=context_items,
                )

            await loop.run_in_executor(None, _write_qdrant)
            logger.info(
                f"  [NodeSummary] '{name}' Qdrant write complete — "
                f"node_cores(1) + facts({len(fact_items)}) + "
                f"questions({len(question_items)}) + contexts({len(context_items)})"
            )

            # 7. Write to Elasticsearch
            def _write_es():
                # Fetch relationship NL sentences from Qdrant (not Neo4j)
                rel_qdrant = qdrant_service.get_relationships_for_node_ids([node_id])
                rel_nl = " ".join(
                    r.get("natural_language", "") for r in rel_qdrant if r.get("natural_language")
                )
                facts_text = " ".join(facts_list or [])
                questions_text = " ".join(potential_questions)
                contexts_text = " ".join(
                    ctx for ctx in existing_contexts if ctx and ctx.strip()
                )
                elasticsearch_service.index_node(
                    node_id=node_id,
                    name=name,
                    node_type=node_type,
                    description=description,
                    facts_text=facts_text,
                    questions_text=questions_text,
                    isolated_contexts_text=contexts_text,
                    relationship_natural_language=rel_nl,
                )

            await loop.run_in_executor(None, _write_es)
            logger.info(
                f"  [NodeSummary] '{name}' Elasticsearch index complete"
            )

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
    def _format_member_context(rows: list[dict]) -> str:
        """Format member node rows into a bulleted context string for LLM prompts."""
        lines = [
            f"- {row.get('name')} ({(row.get('labels') or ['Node'])[0]}): "
            f"{row.get('description') or ''}"
            for row in rows
            if row.get("description")
        ]
        if not lines:
            lines = [
                f"- {row.get('name')} ({(row.get('labels') or ['Node'])[0]})"
                for row in rows
            ]
        return "\n".join(lines)

    def _build_community_summary(
        self,
        member_rows: list[dict],
        community_level: int,
    ) -> tuple[str | None, str | None]:
        """Generate a community name and summary in a single LLM call.

        All member descriptions are passed at once — no chunking.  The LLM context
        window is large enough to handle even the biggest L2 communities (~220 nodes).
        L1 and L0 summaries should use ``_build_rollup_summary`` instead, which rolls
        up from child community summaries rather than raw node descriptions.
        """
        context = self._format_member_context(member_rows)
        prompt = (
            "These knowledge-graph nodes form a community discovered by graph clustering.\n\n"
            f"Community level: {community_level}\n"
            f"Members ({len(member_rows)} total):\n{context}\n\n"
            "Give this community:\n"
            "1. A short descriptive name (3-8 words)\n"
            "2. A thorough summary covering what connects the members, key themes, "
            "notable relationships, and any important patterns or distinctions. "
            "Write as many sentences as needed — do not artificially constrain length.\n\n"
            "Reply in EXACTLY this format:\n"
            "NAME: <name>\n"
            "SUMMARY: <summary>"
        )
        raw = llm_service.reason(prompt) or ""
        return self._parse_name_summary(raw)

    def _build_rollup_summary(
        self,
        child_community_rows: list[dict],
        community_level: int,
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
            "You are summarizing a high-level knowledge-graph community.\n\n"
            f"Community level: {community_level} (higher level = more specific; "
            "lower level = broader and more abstract)\n\n"
            f"The following are summaries of {len(child_community_rows)} sub-communities "
            "that together make up this parent community:\n\n"
            f"{context}\n\n"
            "Synthesize a unified description for this parent community:\n"
            "1. A short descriptive name (3-8 words) capturing the overarching theme\n"
            "2. A thorough summary covering the overarching themes, what connects all "
            "sub-communities, major patterns, and the big-picture significance. "
            "Write as many sentences as needed.\n\n"
            "Reply in EXACTLY this format:\n"
            "NAME: <name>\n"
            "SUMMARY: <summary>"
        )
        raw = llm_service.reason(prompt) or ""
        return self._parse_name_summary(raw)

    def rebuild_leiden_communities(self) -> int:
        """Run a full 3-level Leiden recomputation and rebuild community nodes.

        Cooperative cancellation: checks ``ingestion_tracker.cancel_recompute`` between every
        cluster summary.  When set, the run exits early (returning the count built so far) so a
        pending ingestion can proceed.  The tracker resets the flag and reschedules the full run
        after the next 2-minute idle window.
        """
        import igraph as ig
        import leidenalg

        from app.services.embedding import embedding_service
        from app.services.ingestion_tracker import ingestion_tracker as _tracker

        logger.info(
            f"\n{'='*70}\n"
            f"[Community] Starting full Leiden community recompute\n"
            f"{'='*70}"
        )

        nodes = graph_service.get_indexable_nodes_for_communities()
        if not nodes:
            logger.warning("[Community] No indexable nodes found — aborting Leiden recompute.")
            return 0

        logger.info(f"[Community] {len(nodes)} indexable nodes fetched from Neo4j")

        # Enrich structural node rows with content from Qdrant (description, facts)
        _node_ids_for_leiden = [n["node_id"] for n in nodes if n.get("node_id")]
        if _node_ids_for_leiden:
            _qdrant_content_map = qdrant_service.get_nodes_content_by_ids(_node_ids_for_leiden)
            for n in nodes:
                _nid = n.get("node_id")
                if _nid and _nid in _qdrant_content_map:
                    _c = _qdrant_content_map[_nid]
                    n["description"] = _c.get("description", "")
                    n["facts"] = _c.get("facts", [])
            _enriched = sum(1 for n in nodes if n.get("description"))
            logger.info(
                f"[Community] Qdrant content enrichment: {_enriched}/{len(nodes)} nodes "
                f"enriched with description"
            )

        edges = graph_service.get_weighted_relationships_for_communities()
        logger.info(
            f"[Community] {len(edges)} weighted edges fetched from Neo4j for igraph"
        )
        old_community_ids = graph_service.clear_all_communities()
        logger.info(
            f"[Community] Cleared {len(old_community_ids)} old community nodes "
            f"(Neo4j + Qdrant + ES)"
        )
        for old_community_id in old_community_ids:
            qdrant_service.delete_node(old_community_id)
            elasticsearch_service.delete_node(old_community_id)

        node_ids = [node["node_id"] for node in nodes]
        node_lookup = {node["node_id"]: node for node in nodes}
        node_index = {node_id: idx for idx, node_id in enumerate(node_ids)}

        graph = ig.Graph()
        graph.add_vertices(len(node_ids))
        graph.vs["name"] = node_ids

        edge_list = []
        weights = []
        for edge in edges:
            source_node_id = edge.get("source_node_id")
            target_node_id = edge.get("target_node_id")
            if source_node_id not in node_index or target_node_id not in node_index:
                continue
            edge_list.append((node_index[source_node_id], node_index[target_node_id]))
            weights.append(float(edge.get("weight") or 1.0))

        if edge_list:
            graph.add_edges(edge_list)
            if weights:
                graph.es["weight"] = weights

        logger.info(
            f"[Community] igraph built: {graph.vcount()} vertices, {graph.ecount()} edges "
            f"({len(edge_list)} weighted edges added)"
        )

        # Process L2 first (most specific), then L1, then L0.
        # L1 summaries roll up from L2 child community summaries.
        # L0 summaries roll up from L1 child community summaries.
        # This guarantees every community has a real LLM description, not a placeholder.
        resolutions = [
            (2, 0.01),    # Mid — 50-100 communities, specific topics
            (1, 0.001),   # Broad — 10-20 communities, major topic clusters
            (0, 0.0001),  # Very broad — 3-5 massive communities, highest level themes
        ]
        logger.info(f"[Community] Running CPMVertexPartition at {len(resolutions)} resolution levels (L2→L1→L0)")

        level_assignments: dict[str, dict[int, str]] = {}  # node_id → {level → community_id}
        # Track summaries and names as we build L2 → L1 → L0 so higher levels can roll up
        community_summaries: dict[str, str] = {}   # community_id → summary text
        community_names: dict[str, str] = {}       # community_id → display name
        created = 0

        for community_level, resolution in resolutions:
            if graph.ecount() > 0:
                partition = leidenalg.find_partition(
                    graph,
                    leidenalg.CPMVertexPartition,
                    weights=weights,
                    resolution_parameter=resolution,
                )
                membership = partition.membership
                cluster_map: dict[int, list[str]] = {}
                for idx, cluster_id in enumerate(membership):
                    cluster_map.setdefault(cluster_id, []).append(node_ids[idx])
                clusters = list(cluster_map.values())
            else:
                clusters = [[node_id] for node_id in node_ids]

            logger.info(
                f"[Community] Leiden level {community_level} (resolution={resolution}) produced "
                f"{len(clusters)} clusters | sizes: min={min(len(c) for c in clusters)}, "
                f"max={max(len(c) for c in clusters)}, "
                f"avg={sum(len(c) for c in clusters)/len(clusters):.1f}"
            )

            # Determine which child level to roll up from for L0/L1
            child_level = community_level + 1  # L1→L2, L0→L1

            for cluster_index, member_node_ids in enumerate(clusters):
                # Yield to a pending ingestion if one has arrived.
                if _tracker.cancel_recompute.is_set():
                    logger.info(
                        f"[Community] Recompute cancelled at L{community_level} "
                        f"cluster {cluster_index + 1}/{len(clusters)} — "
                        "ingestion arrived; will restart after next idle window."
                    )
                    return created

                member_rows = [
                    node_lookup[node_id]
                    for node_id in member_node_ids
                    if node_id in node_lookup
                ]
                if not member_rows:
                    continue

                logger.info(
                    f"[Community] Summarizing L{community_level} cluster "
                    f"{cluster_index + 1}/{len(clusters)} ({len(member_rows)} members)"
                )
                try:
                    if community_level == 2:
                        # L2: summarize directly from member node descriptions
                        name, summary = self._build_community_summary(member_rows, community_level)
                    else:
                        # L1/L0: roll up from child community summaries
                        child_community_ids = {
                            level_assignments[nid].get(child_level)
                            for nid in member_node_ids
                            if nid in level_assignments and level_assignments[nid].get(child_level)
                        }
                        child_rows = [
                            {"name": community_names.get(cid, cid), "summary": community_summaries[cid]}
                            for cid in child_community_ids
                            if cid in community_summaries
                        ]
                        if child_rows:
                            logger.info(
                                f"[Community] L{community_level} cluster {cluster_index + 1}: "
                                f"rolling up from {len(child_rows)} child L{child_level} summaries"
                            )
                            name, summary = self._build_rollup_summary(child_rows, community_level)
                        else:
                            # Fallback: no child summaries available (e.g. first run edge case)
                            logger.warning(
                                f"[Community] L{community_level} cluster {cluster_index + 1}: "
                                "no child summaries found — falling back to member node descriptions"
                            )
                            name, summary = self._build_community_summary(member_rows, community_level)
                except Exception as _summ_err:
                    logger.warning(
                        f"[Community] Skipping L{community_level} cluster "
                        f"{cluster_index + 1} — summary failed: {_summ_err}"
                    )
                    name, summary = None, None

                if not name:
                    name = f"Community L{community_level}-{cluster_index + 1}"
                if not summary:
                    summary = f"Community at level {community_level} containing {len(member_node_ids)} related nodes."

                themes = [row.get("name") for row in member_rows[:5] if row.get("name")]
                # Communities only get a description per plan — no potential_questions.
                community_id = f"community_l{community_level}_{uuid.uuid4().hex}"
                updated_at = datetime.utcnow().isoformat()

                graph_service.create_leiden_community(
                    community_id=community_id,
                    community_level=community_level,
                    name=name,
                    summary=summary,
                    member_node_ids=member_node_ids,
                )
                logger.debug(
                    f"  [Community] Neo4j community node created: '{name}' id={community_id}"
                )

                elasticsearch_service.index_node(
                    node_id=community_id,
                    name=name,
                    node_type="community",
                    description=summary,
                    community_level=community_level,
                )
                logger.debug(
                    f"  [Community] ES indexed community: '{name}'"
                )

                # Write community membership NL sentences to Qdrant node_relationships
                # flagged is_community_rel=True so they are bulk-deleted on next recompute.
                try:
                    _nl_texts = [
                        f"{node_lookup.get(nid, {}).get('name') or nid} is a member of the '{name}' community."
                        for nid in member_node_ids
                        if nid in node_lookup
                    ]
                    _nl_vectors = embedding_service.embed_documents(_nl_texts) if _nl_texts else []
                    _nl_written = 0
                    for nid, nl_text, nl_vec in zip(
                        [n for n in member_node_ids if n in node_lookup],
                        _nl_texts,
                        _nl_vectors,
                    ):
                        qdrant_service.upsert_node_relationship(
                            relationship_id=f"community_rel_{community_id}_{nid}",
                            natural_language=nl_text,
                            nl_vector=nl_vec,
                            source_node_id=nid,
                            target_node_id=community_id,
                            is_community_rel=True,
                        )
                        _nl_written += 1
                    logger.debug(
                        f"  [Community] Qdrant membership NL sentences written: {_nl_written} "
                        f"for community '{name}'"
                    )
                except Exception as _rel_err:
                    logger.warning(f"[Community] Membership NL write failed for {community_id}: {_rel_err}")

                logger.info(
                    f"  [Community] ✓ Created L{community_level} community '{name}' "
                    f"(id={community_id}, {len(member_node_ids)} members)"
                )
                graph_service.set_node_community_membership(
                    member_node_ids, community_id, community_level
                )
                for node_id in member_node_ids:
                    level_assignments.setdefault(node_id, {})[community_level] = community_id

                # Record summary + name so higher-level passes can roll up from them
                community_summaries[community_id] = summary
                community_names[community_id] = name

                created += 1

        from app.services.embedding import embedding_service

        # Refresh ES relationship_natural_language for nodes whose membership changed.
        # Community fields are no longer stored on regular nodes — only the NL sentence
        # written above carries that signal for retrieval.
        for node_id in level_assignments:
            payload = graph_service.get_node_storage_payload(node_id)
            if not payload:
                continue
            description = payload.get("description") or ""
            if not description:
                continue
            relationship_nl = payload.get("relationship_natural_language") or []
            elasticsearch_service.update_node_community(
                node_id=node_id,
                description=description,
                relationship_natural_language=" ".join(
                    sentence for sentence in relationship_nl if sentence
                ),
            )

        # ── Compute & store 3D positions for the new layout ──────────────────
        try:
            from app.utils.graph_layout import compute_spring_layout_3d

            # After Leiden has created communities, rerun spring layout so
            # community nodes are pulled into the correct positions by their members.
            spring_node_ids, spring_edges = graph_service.get_all_node_ids_and_edges()
            positions = compute_spring_layout_3d(spring_node_ids, spring_edges)
            graph_service.store_node_positions(positions)
            logger.info(
                f"[Community] Spring layout recomputed after Leiden: "
                f"{len(positions)} nodes, {len(spring_edges)} edges"
            )
        except Exception as _layout_err:
            logger.warning(f"[Community] 3D layout computation failed (non-fatal): {_layout_err}")

        logger.info(
            f"\n{'='*70}\n"
            f"[Community] Leiden recompute COMPLETE: {created} community nodes rebuilt\n"
            f"  Nodes in graph: {len(node_ids)}\n"
            f"  Edges in graph: {len(edge_list)}\n"
            f"  Levels: {list(resolutions.keys())}\n"
            f"{'='*70}"
        )
        return created


ingestion_workflow = IngestionWorkflow()
