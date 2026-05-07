import logging
import os
import re
import time
from datetime import datetime
from typing import List

from app.core.config import settings
from app.core.log import get_logger
from app.services.graph import graph_service
from app.services.qdrant_service import qdrant_service
from app.services.typesense_service import typesense_service

# Suppress noisy tokenizer warnings
logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)

logger = get_logger("RetrievalService")

# Stopwords to filter from LLM-extracted entities
# These are common words that match everything and provide no signal
ENTITY_STOPWORDS = {
    # Single letters and pronouns
    "i",
    "a",
    "me",
    "my",
    "we",
    "us",
    "you",
    "he",
    "she",
    "it",
    "they",
    "them",
    # Common verbs
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "can",
    "shall",
    "must",
    "need",
    "want",
    "get",
    "got",
    "go",
    "went",
    "gone",
    # Question words
    "what",
    "who",
    "where",
    "when",
    "why",
    "how",
    "which",
    "whom",
    "whose",
    # Articles and prepositions
    "the",
    "an",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "with",
    "from",
    "by",
    "about",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    # Conjunctions and other common words
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "so",
    "as",
    "this",
    "that",
    "these",
    "those",
    "there",
    "here",
    "all",
    "any",
    "some",
    "no",
    "not",
    # Time-related (not entities)
    "time",
    "now",
    "today",
    "yesterday",
    "tomorrow",
    "recently",
    "currently",
    # Generic nouns that match everything
    "thing",
    "things",
    "life",
    "work",
    "way",
    "day",
    "days",
    "year",
    "years",
}


class RetrievalService:
    def __init__(self):
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), f"../../{settings.MODELS_PATH}")
        )
        logger.info("RetrievalService initialized")

    def _log_retrieval_details(
        self,
        query: str,
        results: List[dict],
        query_entities: List[str],
        query_concepts: List[str],
    ):
        """
        Log detailed retrieval results to dedicated file for debugging.
        Includes full node summaries, not truncated versions.
        """
        logger.debug("=" * 100)
        logger.debug(f"RETRIEVAL SESSION: {datetime.now().isoformat()}")
        logger.debug(f"QUERY: {query}")
        logger.debug(f"EXTRACTED ENTITIES: {query_entities}")
        logger.debug(f"EXTRACTED CONCEPTS: {query_concepts}")
        logger.debug("=" * 100)

        for i, doc in enumerate(results):
            logger.debug(f"\n--- RESULT {i+1} ---")
            logger.debug(f"TYPE: {doc.get('type', 'unknown')}")
            logger.debug(f"SCORE: {doc.get('final_score', 0):.2f}")
            logger.debug(f"BOOSTS: {doc.get('boosts', {})}")
            logger.debug(f"SYMBOLIC IMMUNE: {doc.get('symbolic_immune', False)}")

            # Get node details from original object
            original = doc.get("original_obj", {})
            if original:
                logger.debug(f"NODE NAME: {original.get('name', 'N/A')}")
                logger.debug(f"NODE LABELS: {original.get('labels', [])}")
                logger.debug(f"NODE TYPE: {original.get('entity_type', 'N/A')}")

                # Full summary - not truncated!
                summary = original.get("summary") or original.get("description") or ""
                logger.debug(f"FULL SUMMARY ({len(summary)} chars):")
                logger.debug(summary if summary else "(empty)")

                # Isolated context if available
                isolated = original.get("isolated_context") or ""
                if isolated:
                    logger.debug(f"ISOLATED CONTEXT ({len(isolated)} chars):")
                    logger.debug(isolated)

            # Linked notes
            linked_notes = doc.get("linked_notes", [])
            if linked_notes:
                logger.debug(f"LINKED NOTES ({len(linked_notes)}):")
                for note in linked_notes:
                    logger.debug(
                        f"  - {note.get('title', 'Untitled')} ({note.get('id', 'N/A')})"
                    )

            # Full text sent to LLM
            logger.debug(f"TEXT SENT TO LLM ({len(doc.get('text', ''))} chars):")
            logger.debug(doc.get("text", ""))

        logger.debug("\n" + "=" * 100 + "\n")

    def _get_node_relationships(self, node: dict, max_relationships: int = 5) -> str:
        """
        Fetch and format 1-hop relationships for a node to provide connection context.

        Args:
            node: Node dict from Kuzu

        Returns:
            Formatted relationship string, or empty if no relationships found
        """
        from app.services.graph import graph_service

        try:
            node_name = node.get("name", "")
            if not node_name:
                return ""

            # All nodes are :Indexable — no label filter needed
            related_nodes = graph_service.get_related_nodes(
                node_name=node_name, node_label=None, max_depth=1, min_confidence=0.5
            )

            if not related_nodes:
                return ""

            # Format each connected node as natural language so the LLM
            # reads prose rather than notation.
            relationships = []
            for related in related_nodes:
                rel_name = related.get("name", "Unknown")
                # Skip relationships with unresolved None targets
                if not rel_name or rel_name == "None":
                    continue
                nl_path = related.get("natural_language_path", [])
                rel_path = related.get("relationship_path", [])
                context_path = related.get("context_path", [])

                if nl_path and nl_path[0]:
                    nl_sentence = nl_path[0]
                    # Skip NL sentences with unresolved None targets from ingestion
                    if " None" in nl_sentence or nl_sentence.endswith("None."):
                        continue
                    rel_str = nl_sentence
                elif context_path and context_path[0]:
                    context = context_path[0]
                    rel_str = f'"{rel_name}" ({context})'
                elif rel_path:
                    rel_natural = rel_path[0].replace("_", " ").lower()
                    rel_str = f"{node_name} {rel_natural} {rel_name}."
                else:
                    rel_str = f'"{rel_name}"'

                relationships.append(rel_str)

            if relationships:
                return " and is connected to " + "; ".join(relationships)

            return ""

        except Exception as e:
            logger.debug(
                f"  [Relationships] Failed to fetch for {node.get('name', 'unknown')}: {e}"
            )
            return ""

    async def _expand_relevant_neighbors(
        self,
        relevant_docs: list[dict],
        question: str,
        surfaced_names: set[str],
    ) -> list[dict]:
        """
        Expand the retrieval frontier from already-relevant nodes.

        For each relevant node, fetch its 1-hop neighbours not yet surfaced.
        Ask the LLM (in natural language format) to select which of those
        relationships provide additional evidence for the question.
        Returns the selected neighbour nodes as standard doc dicts.
        """
        from app.services.llm import llm_service

        relationship_entries: list[dict] = []

        for doc in relevant_docs:
            node = doc.get("original_obj") or {}
            node_name = node.get("name", "")
            if not node_name:
                continue
            # Prefer node_id stored in original_obj; fall back to "id" key
            src_node_id = node.get("node_id") or node.get("id") or ""
            # All nodes are :Indexable — no label filter needed
            try:
                related = graph_service.get_related_nodes(
                    node_name=node_name,
                    node_label=None,
                    max_depth=1,
                    min_confidence=0.5,
                )
            except Exception as e:
                logger.debug(
                    f"  [GraphExpand] get_related_nodes failed for {node_name}: {e}"
                )
                continue

            for r in related:
                neighbor_name = r.get("name", "")
                if not neighbor_name or neighbor_name in surfaced_names:
                    continue
                nl_path = r.get("natural_language_path") or []
                nl_sentence = nl_path[0] if nl_path and nl_path[0] else None
                rel_path = r.get("relationship_path") or []
                rel_type = rel_path[0] if rel_path else "connected_to"
                ctx_path = r.get("context_path") or []
                context = ctx_path[0] if ctx_path else None
                edge_direction = r.get("edge_direction", "outgoing")
                relationship_entries.append(
                    {
                        "source": node_name,
                        "src_node_id": src_node_id,
                        "rel_type": rel_type,
                        "nl_sentence": nl_sentence,
                        "neighbor": r,
                        "context": context,
                        "edge_direction": edge_direction,
                    }
                )

        if not relationship_entries:
            logger.info("  [GraphExpand] No new 1-hop neighbors to evaluate.")
            return []

        # --- Enrich nl_sentence from Qdrant node_relationships ---
        # Kuzu always returns NULL for natural_language_path; the real NL text
        # lives in the Qdrant node_relationships collection, indexed by
        # (source_node_id, target_node_id).  Build a lookup from both directions
        # so we can fill nl_sentence regardless of which end was the anchor.
        try:
            _all_node_ids = list(
                {
                    nid
                    for e in relationship_entries
                    for nid in (e.get("src_node_id"), e["neighbor"].get("node_id"))
                    if nid
                }
            )
            if _all_node_ids:
                _qdrant_rels = qdrant_service.get_relationships_for_node_ids(
                    _all_node_ids
                )
                # Build bidirectional lookup: (src_id, tgt_id) → nl_text
                _nl_lookup: dict[tuple[str, str], str] = {}
                for _qr in _qdrant_rels:
                    _s = _qr.get("source_node_id", "")
                    _t = _qr.get("target_node_id", "")
                    _nl = _qr.get("natural_language", "")
                    if _s and _t and _nl:
                        _nl_lookup[(_s, _t)] = _nl

                for entry in relationship_entries:
                    if entry.get("nl_sentence"):
                        continue  # already set (shouldn't happen with current Kuzu)
                    _src = entry.get("src_node_id", "")
                    _tgt = entry["neighbor"].get("node_id", "")
                    nl = _nl_lookup.get((_src, _tgt)) or _nl_lookup.get((_tgt, _src))
                    if nl:
                        entry["nl_sentence"] = nl
        except Exception as _qdrant_err:
            logger.debug(f"  [GraphExpand] Qdrant NL lookup failed: {_qdrant_err}")

        logger.info(
            f"  [GraphExpand] Evaluating {len(relationship_entries)} 1-hop relationship(s):"
        )
        for _i, _e in enumerate(relationship_entries):
            if _e.get("nl_sentence"):
                _nl = _e["nl_sentence"]
            elif _e.get("edge_direction") == "incoming":
                _nl = f'{_e["neighbor"].get("name", "?")} --[{_e["rel_type"]}]--> {_e["source"]}'
            else:
                _nl = f'{_e["source"]} --[{_e["rel_type"]}]--> {_e["neighbor"].get("name", "?")}'
            logger.info(f"    [{_i}] {_nl}")

        # Enrich neighbor nodes with content from Qdrant before LLM filtering
        _neighbor_ids = [
            e["neighbor"].get("node_id")
            for e in relationship_entries
            if e["neighbor"].get("node_id")
        ]
        if _neighbor_ids:
            try:
                _qdrant_neighbor_content = qdrant_service.get_nodes_content_by_ids(
                    _neighbor_ids
                )
                for entry in relationship_entries:
                    _nid = entry["neighbor"].get("node_id")
                    if _nid and _nid in _qdrant_neighbor_content:
                        _c = _qdrant_neighbor_content[_nid]
                        entry["neighbor"]["description"] = _c.get("description", "")
                        entry["neighbor"]["summary"] = _c.get("description", "")
                        entry["neighbor"]["facts"] = _c.get("facts", [])
                        entry["neighbor"]["isolated_contexts"] = _c.get(
                            "isolated_contexts", []
                        )
            except Exception as _e:
                logger.debug(f"  [GraphExpand] Qdrant neighbor enrichment failed: {_e}")

        selected_indices = await llm_service.select_relevant_relationships(
            relationship_entries, question
        )
        logger.info(
            f"  [GraphExpand] LLM selected {len(selected_indices or [])}/{len(relationship_entries)} "
            f"neighbor relationships"
        )
        if not selected_indices:
            logger.info("  [GraphExpand] No relevant neighbors selected by LLM.")
            return []

        # Build a lookup so we can prepend origin text to each expansion doc
        # before reranking — the reranker scores the full chain, not the
        # neighbour in isolation.
        origin_text_by_name: dict[str, str] = {}
        for doc in relevant_docs:
            _node = doc.get("original_obj", {})
            _name = _node.get("name", "")
            _text = (
                doc.get("text")
                or _node.get("summary")
                or _node.get("description")
                or ""
            ).strip()
            if _name and _text:
                origin_text_by_name[_name] = _text

        selected_neighbor_names: list[str] = []
        result: list[dict] = []
        seen_neighbors: set[str] = set()
        for idx in selected_indices:
            entry = relationship_entries[idx]
            neighbor = entry["neighbor"]
            neighbor_name = neighbor.get("name", "")
            if not neighbor_name or neighbor_name in seen_neighbors:
                continue
            seen_neighbors.add(neighbor_name)
            selected_neighbor_names.append(neighbor_name)
            summary = neighbor.get("summary") or neighbor.get("description", "")
            node_text = self._get_node_text(neighbor)
            # Build a readable link sentence for prompt grouping.
            nl = entry.get("nl_sentence")
            if not nl:
                rel = entry.get("rel_type", "connected_to").replace("_", " ")
                if entry.get("edge_direction") == "incoming":
                    nl = f"{neighbor_name} {rel} {entry['source']}."
                else:
                    nl = f"{entry['source']} {rel} {neighbor_name}."
            # Compose the text the reranker will score: origin + link + neighbour.
            # This lets the reranker judge the full chain of evidence rather than
            # scoring the neighbour node in isolation.
            _origin_text = origin_text_by_name.get(entry["source"], "")
            _neighbour_text = node_text if node_text else neighbor_name
            _rerank_parts = [p for p in [_origin_text, nl, _neighbour_text] if p]
            _rerank_text = "\n".join(_rerank_parts)
            result.append(
                {
                    "text": _neighbour_text,
                    "_rerank_text": _rerank_text,
                    "type": "graph_expansion",
                    "_origin_name": entry["source"],
                    "_link_sentence": nl,
                    "original_obj": {
                        "node_id": neighbor.get("node_id") or neighbor.get("id"),
                        "name": neighbor_name,
                        "summary": summary,
                        "entity_type": neighbor.get("entity_type", ""),
                    },
                    "linked_notes": [],
                }
            )

        # Preserve note provenance for expansion docs so references and retrieval
        # metrics can credit these neighbours as evidence.
        if result and selected_neighbor_names:
            try:
                evidence_rows = graph_service.get_linked_evidence(
                    selected_neighbor_names,
                    limit_per_node=2,
                )
                node_to_notes: dict[str, list[dict]] = {}
                for row in evidence_rows:
                    node_name = (row.get("node_name") or "").lower()
                    evidence = row.get("evidence", [])
                    if node_name and evidence:
                        node_to_notes[node_name] = evidence

                for doc in result:
                    name = ((doc.get("original_obj") or {}).get("name") or "").lower()
                    if name and name in node_to_notes:
                        # Hub-node guard: aggregate nodes (e.g. "United States",
                        # "London") accumulate one fact per source note, so their
                        # node text grows very long and their linked_notes span the
                        # entire corpus.  Keep the text for LLM context but strip
                        # note provenance to prevent unrelated notes from entering
                        # the reference list.  Specific-entity nodes stay under
                        # ~1 000 chars; hub nodes are typically 5-20× larger.
                        if len(doc.get("text", "")) <= 1000:
                            doc["linked_notes"] = node_to_notes[name]
            except Exception as e:
                logger.debug(f"  [GraphExpand] get_linked_evidence failed: {e}")

        if result:
            logger.info(
                f"  [GraphExpand] Added {len(result)} neighbour node(s) via relationship expansion"
            )
        return result

    def _get_node_text(self, node: dict) -> str:
        """
        Extract text content from a node, including atomic facts so the LLM
        can answer fact-specific questions (e.g. "Where is X from?") directly
        from candidate text without needing a separate lookup.

        Args:
            node: Node dict from Kuzu
        """
        import json as _json

        _isolated_list = node.get("isolated_contexts") or []
        _isolated_joined = (
            " ".join(s for s in _isolated_list if s) if _isolated_list else ""
        )
        summary = (
            node.get("summary")
            or node.get("description")
            or node.get("definition")
            or node.get("isolated_context")  # singular string (legacy)
            or _isolated_joined  # plural list (current ingestion)
            or node.get("content", "")
        )
        facts_raw = node.get("facts")
        if facts_raw:
            try:
                facts = (
                    _json.loads(facts_raw) if isinstance(facts_raw, str) else facts_raw
                )
                if isinstance(facts, list) and facts:
                    # Facts are proposition sentences (list[str])
                    facts_text = "; ".join(
                        (
                            f
                            if isinstance(f, str)
                            else f"{f.get('property', '')}: {f.get('value', '')}"
                        )
                        for f in facts
                        if f
                    )
                    if facts_text:
                        summary = (
                            f"{summary} Facts: {facts_text}" if summary else facts_text
                        )
            except Exception:
                pass
        return summary

    async def _search_qdrant_multi_collection(
        self, query_vector: list[float]
    ) -> list[dict]:
        """Search all Qdrant collections and normalize into node-like results.

        Per plan: no result limiting — returns ALL hits above the similarity
        threshold.  A large ceiling (500 per collection) is passed to the
        Qdrant client solely because its API requires a numeric limit; the
        score_threshold is the only real filter.

        Each collection hit carries a ``parent_node_id`` and optionally a
        ``name`` field added at upsert time.  When ``name`` is present it is
        used directly; otherwise the hit is skipped so the caller's dedup
        logic stays consistent.
        """
        hits = qdrant_service.search_all_collections(
            query_vector=query_vector,
            limit=500,  # large ceiling; score_threshold is the real filter
            min_score=settings.VECTOR_SIMILARITY_THRESHOLD,
        )
        if not hits:
            logger.info("  [Qdrant] No hits above similarity threshold.")
            return []
        logger.info(
            f"  [Qdrant] Raw hits from search_all_collections: {len(hits)} "
            f"(threshold={settings.VECTOR_SIMILARITY_THRESHOLD})"
        )
        merged: dict[str, dict] = {}
        unresolved_node_ids: set[str] = set()
        normalized_hits: list[dict] = []
        for hit in hits:
            payload = hit.get("payload", {})
            score = float(hit.get("score", 0.0))
            collection = hit.get("collection", "")
            node_id = (
                payload.get("node_id")
                or payload.get("parent_node_id")
                or payload.get("source_node_id")
                or payload.get("target_node_id")
            )
            name = (payload.get("name") or "").strip()
            if not name and node_id:
                unresolved_node_ids.add(node_id)

            normalized_hits.append(
                {
                    "payload": payload,
                    "score": score,
                    "collection": collection,
                    "node_id": node_id,
                    "name": name,
                }
            )

        resolved_names: dict[str, str] = {}
        if unresolved_node_ids:
            try:
                core_rows = qdrant_service.get_nodes_content_by_ids(
                    list(unresolved_node_ids)
                )
                for _nid, _row in core_rows.items():
                    _name = (_row.get("name") or "").strip()
                    if _name:
                        resolved_names[_nid] = _name
            except Exception as _e:
                logger.debug(f"  [Qdrant] Failed resolving missing hit names: {_e}")

        for entry in normalized_hits:
            payload = entry["payload"]
            score = entry["score"]
            collection = entry["collection"]
            node_id = entry["node_id"]
            name = entry["name"] or resolved_names.get(node_id or "", "")
            if not name:
                continue

            key = name.lower()
            is_relationship_hit = "relationships" in collection
            is_isolated_context_hit = "isolated_context" in collection

            if is_isolated_context_hit:
                # Always accumulate isolated context text — never discard it just
                # because another hit for the same node scored higher. Nodes with
                # an empty description in node_cores would otherwise get an empty
                # summary and be silently filtered out by _get_node_text.
                ctx_text = (payload.get("content") or "").strip()
                if key in merged:
                    existing_summary = merged[key].get("summary") or ""
                    if ctx_text and ctx_text not in existing_summary:
                        merged[key]["summary"] = (
                            existing_summary + " " + ctx_text
                        ).strip()
                    # Keep the best score seen so far
                    if score > merged[key].get("score", 0.0):
                        merged[key]["score"] = score
                else:
                    merged[key] = {
                        "id": node_id,
                        "node_id": node_id,
                        "name": name,
                        "entity_type": payload.get("type") or "",
                        "summary": ctx_text,
                        "score": score,
                        "_source": "qdrant",
                    }
                continue

            current = merged.get(key)
            new_summary = (
                payload.get("natural_language")
                if is_relationship_hit
                else (
                    payload.get("description")
                    or payload.get("content")
                    or payload.get("natural_language", "")
                )
            )
            if current:
                if current.get("score", 0.0) >= score:
                    # Keep existing entry but patch in the summary if it was empty
                    if not current.get("summary") and new_summary:
                        current["summary"] = new_summary
                    continue
                # Higher-scored non-isolated hit: keep its summary only if better
                if not new_summary and current.get("summary"):
                    new_summary = current["summary"]

            merged[key] = {
                "id": node_id,
                "node_id": node_id,
                "name": name,
                "entity_type": (
                    "" if is_relationship_hit else (payload.get("type") or "")
                ),
                "summary": new_summary,
                "score": score,
                "_source": "qdrant",
            }

        result = list(merged.values())
        logger.info(
            f"  [Qdrant] {len(result)} unique nodes after dedup (from {len(hits)} raw hits)"
        )
        return result

    async def _search_typesense_by_keyword(self, query: str) -> list[dict]:
        """Search Typesense full-text index and normalize into node-like results."""
        hits = typesense_service.search_nodes(query=query, limit=100)
        if not hits:
            logger.info("  [Typesense] No BM25 keyword hits.")
            return []
        logger.info(f"  [Typesense] {len(hits)} raw hits from Typesense")

        merged: dict[str, dict] = {}
        for hit in hits:
            payload = hit.get("payload", {})
            score = float(hit.get("score", 0.0))
            name = (payload.get("name") or "").strip()
            if not name:
                continue

            key = name.lower()
            current = merged.get(key)
            if current and current.get("score", 0.0) >= score:
                continue

            merged[key] = {
                "id": payload.get("node_id"),
                "name": name,
                "entity_type": payload.get("type") or "",
                "summary": payload.get("description") or "",
                "score": score,
                "_source": "typesense",
            }

        return list(merged.values())

    def _merge_search_results(
        self, primary: list[dict], secondary: list[dict], seen_names: set[str]
    ) -> list[dict]:
        """Merge and dedupe search results by node name while preserving primary precedence."""
        merged = list(primary)
        for node in secondary:
            name = node.get("name")
            if not name:
                continue
            if name in seen_names:
                continue
            seen_names.add(name)
            merged.append(node)
        return merged

    async def hybrid_search(self, query: str, top_k: int = 50) -> List[dict]:
        """
        Entity-First Retrieval Pipeline:

        Uses entity name matching as the primary entry point, falling back to
        vector/keyword search only when no usable entity content is found.
        1-hop graph expansion from matched nodes is used to surface related context.

        Flow:
        1. Query Analysis: Extract expected entity types and question attributes via LLM
        2. Entity Search: Find nodes by extracted entity names (primary entry point)
           2.5 Name Variant Expansion: catch alternate/fuller name forms for Person entities
        2. Vector+Keyword Fallback: only when entity matching yields no usable content
        3. Community + Note Grounding: community summaries for broad queries; linked-note traceability
        4. Candidate Preparation: build ranked candidate list (no artificial cutoff)

        Returns node summaries as primary evidence, not chunked note snippets.
        """
        from app.services.embedding import embedding_service

        logger.info(
            f"\n{'─'*60}\n"
            f"  [HybridSearch] query='{query}' top_k={top_k}\n"
            f"{'─'*60}"
        )
        t_start = time.perf_counter()
        t_phase_start = time.perf_counter()

        # Query Analysis with LLM structured outputs
        from app.services.llm import llm_service

        logger.info("  [HybridSearch] Calling LLM query analysis...")
        query_analysis = llm_service.analyze_query(query)

        # Extract expected entity types for filtering/boosting
        expected_entity_types = query_analysis.get("expected_entity_types", [])
        question_attribute = query_analysis.get("question_attribute", None)

        # ============ ENTITY EXTRACTION ============
        # The LLM is the sole source of entity names from the query.
        # No regex/TitleCase fallback — the LLM already handles multi-word names.
        llm_entities_raw = query_analysis.get("entities", [])

        # Strip stopwords and single-character tokens that match everything
        filtered_by_length = []
        filtered_by_stopwords = []

        def is_valid_entity(e: str) -> bool:
            e_lower = e.lower().strip()
            if len(e_lower) < 2:
                filtered_by_length.append(e)
                return False
            if e_lower in ENTITY_STOPWORDS:
                filtered_by_stopwords.append(e)
                return False
            return True

        query_entities = [e for e in llm_entities_raw if is_valid_entity(e)]

        if filtered_by_stopwords or filtered_by_length:
            logger.info(f"  [Entity Filter] Raw LLM entities: {llm_entities_raw}")
            if filtered_by_stopwords:
                logger.info(
                    f"  [Entity Filter] Removed by stopwords: {filtered_by_stopwords}"
                )
            if filtered_by_length:
                logger.info(
                    f"  [Entity Filter] Removed by length (<2): {filtered_by_length}"
                )
            logger.info(f"  [Entity Filter] Final entities: {query_entities}")

        logger.info(
            f"  [LLM Analysis] Intent: {query_analysis.get('intent')}, "
            f"Entities: {query_entities}, "
            f"Expected Types: {expected_entity_types}, "
            f"Attribute: {question_attribute}"
        )

        # Generate dynamic embedding instruction for Qwen3 (optional, controlled by config)
        # This creates query-specific instructions like "Retrieve filmography for person mentioned"
        # instead of using the generic PKM instruction
        t_instruction_start = time.perf_counter()
        use_dynamic_instruction = getattr(
            settings, "USE_DYNAMIC_EMBEDDING_INSTRUCTION", False
        )
        custom_instruction = None

        if use_dynamic_instruction:
            custom_instruction = await llm_service.generate_embedding_instruction(query)
            t_instruction = time.perf_counter() - t_instruction_start
            logger.info(
                f"  [⏱️ Timing] Dynamic instruction generation: {t_instruction:.2f}s"
            )

        # Generate query embedding for vector search (with optional dynamic instruction)
        full_vector = embedding_service.embed_query(
            query, custom_instruction=custom_instruction
        )
        # Note: No longer storing query embedding - isolated context filtering disabled
        t_embedding = time.perf_counter() - t_instruction_start
        logger.info(f"  [⏱️ Timing] Total query embedding: {t_embedding:.2f}s")

        # ============ HYBRID RETRIEVAL ============
        # Combines entity name matching (for explicit mentions) with vector search
        # (for semantic similarity). This ensures we find both "Albert Einstein"
        # AND "Marie Curie" in comparison questions.

        t_phase_start = time.perf_counter()
        entity_nodes = []  # Found by name matching
        vector_nodes = []  # Found by vector search
        node_names_found = set()  # Track names to avoid duplicates

        # STEP 1: ENTITY NAME MATCHING - Find nodes by extracted entity names
        # This is critical for comparison questions where we need both entities
        if query_entities:
            t_entity_start = time.perf_counter()
            try:
                # Normalize to lowercase so lookups match stored (lowercase) names
                _normalized_query_entities = [e.lower().strip() for e in query_entities]
                entity_found = graph_service.find_nodes_by_name(
                    names=_normalized_query_entities, fuzzy=True
                )
                # Collect ALL matching nodes first — do NOT dedup by name yet.
                # Multiple graph nodes can share the same name but only one may have
                # Qdrant content. Deduping before enrichment would silently drop the
                # node that has content whenever an empty duplicate appears first.
                _entity_candidates = []
                for node in entity_found:
                    node["_source"] = "entity_match"
                    _entity_candidates.append(node)

                # STEP 1.5: NAME VARIANT EXPANSION
                # Search for variants of found names to catch fuller/alternate versions
                # e.g., "Robert Smith" → also find "Robert Smith Jr."
                _seen_variant_keys: set = set(
                    (n.get("name") or "").lower().strip() for n in _entity_candidates
                )
                variant_nodes = []
                for node in entity_found:  # Top 10 to avoid explosion
                    node_name = node.get("name", "")
                    node_type = (node.get("entity_type") or "").lower()
                    # Only expand Person entities with multi-word names
                    if (
                        node_name
                        and len(node_name.split()) >= 2
                        and node_type == "person"
                    ):
                        try:
                            variants = graph_service.find_name_variants(node_name)
                            for v in variants:  # Top 5 variants per name
                                _v_key = (v["name"] or "").lower().strip()
                                if (
                                    _v_key not in _seen_variant_keys
                                    and _v_key != node_name.lower().strip()
                                ):
                                    v["_source"] = "name_variant"
                                    v["_variant_of"] = node_name
                                    variant_nodes.append(v)
                                    _seen_variant_keys.add(_v_key)
                        except Exception as e:
                            logger.debug(f"  [Variant] Failed for {node_name}: {e}")

                if variant_nodes:
                    logger.info(
                        f"  [Entity] Found {len(variant_nodes)} name variants: "
                        f"{[(v['name'], v.get('_variant_of')) for v in variant_nodes]}"
                    )
                    _entity_candidates.extend(variant_nodes)

                # Enrich ALL candidates with content from Qdrant BEFORE deduplicating.
                # This ensures we can pick the node that actually has content when
                # multiple graph nodes share the same name.
                _enrich_ids = [
                    n.get("node_id") for n in _entity_candidates if n.get("node_id")
                ]
                if _enrich_ids:
                    try:
                        _qdrant_content = qdrant_service.get_nodes_content_by_ids(
                            _enrich_ids
                        )
                        for _n in _entity_candidates:
                            _nid = _n.get("node_id")
                            if _nid and _nid in _qdrant_content:
                                _c = _qdrant_content[_nid]
                                _n["description"] = _c.get("description", "")
                                _n["summary"] = _c.get("description", "")
                                _n["facts"] = _c.get("facts", [])
                                _n["isolated_contexts"] = _c.get(
                                    "isolated_contexts", []
                                )
                    except Exception as _e:
                        logger.debug(
                            f"  [Entity] Qdrant content enrichment failed: {_e}"
                        )

                # NOW dedup by name — keeping the node with the most content so
                # that a populated node wins over an empty duplicate.
                _best_by_name: dict = {}
                for _n in _entity_candidates:
                    _key = (_n.get("name") or "").lower().strip()
                    _text_len = len(_n.get("description", "") or "") + sum(
                        len(s) for s in (_n.get("isolated_contexts") or [])
                    )
                    _best_text_len = (
                        len(_best_by_name[_key].get("description", "") or "")
                        + sum(
                            len(s)
                            for s in (
                                _best_by_name.get(_key, {}).get("isolated_contexts")
                                or []
                            )
                        )
                        if _key in _best_by_name
                        else 0
                    )
                    if _key not in _best_by_name or _text_len > _best_text_len:
                        _best_by_name[_key] = _n

                for _key, _n in _best_by_name.items():
                    entity_nodes.append(_n)
                    node_names_found.add(_key)

                if entity_nodes:
                    logger.info(
                        f"  [Entity] Found {len(entity_nodes)} nodes by name: "
                        f"{[n['name'] for n in entity_nodes]}"
                    )
            except Exception as e:
                logger.warning(f"  [Entity] Name matching failed: {e}")
            t_entity = time.perf_counter() - t_entity_start
            logger.info(f"  [⏱️ Timing] Entity name matching: {t_entity:.2f}s")

        # STEP 2: VECTOR SEARCH FALLBACK (only when entity matching found nothing)
        # Entity-first mode: run vector/keyword only when entity matching produced no
        # usable evidence. Some matched entities can be empty shells (e.g. node_cores
        # entities with no content), so we check for actual text, not just a name match.
        t_vector_start = time.perf_counter()
        _has_usable_entity_content = any(self._get_node_text(n) for n in entity_nodes)
        use_vector_fallback = not _has_usable_entity_content
        if not use_vector_fallback:
            logger.info(
                "  [Vector] Skipped: entity-first mode active and entity matches found"
            )
        else:
            logger.info(
                "  [Vector] Fallback enabled: entity nodes found but have no retrievable content — running vector/keyword search"
            )
            try:
                # Qdrant is the vector source of truth.
                vector_results = await self._search_qdrant_multi_collection(full_vector)
                if vector_results:
                    logger.info(
                        f"  [Vector] Using Qdrant multi-collection search with {len(vector_results)} hits"
                    )
                else:
                    logger.info("  [Vector] Qdrant returned no hits")

                for vnode in vector_results:
                    _vkey = (vnode["name"] or "").lower().strip()
                    if _vkey not in node_names_found:
                        vnode["_source"] = "vector"
                        vector_nodes.append(vnode)
                        node_names_found.add(_vkey)

                # STEP 2.5: NAME VARIANT EXPANSION for vector-found person entities
                # Catches "Margaret Johnson" -> "Margaret Johnson-Williams" for multi-hop queries
                vector_variant_nodes = []
                for vnode in vector_nodes:  # Check top vector results
                    vnode_name = vnode.get("name", "")
                    vnode_type = (vnode.get("entity_type") or "").lower()
                    # Only expand Person entities with multi-word names
                    if (
                        vnode_name
                        and len(vnode_name.split()) >= 2
                        and vnode_type == "person"
                    ):
                        try:
                            variants = graph_service.find_name_variants(vnode_name)
                            for v in variants:  # Top 5 variants per name
                                _vv_key = (v["name"] or "").lower().strip()
                                if (
                                    _vv_key not in node_names_found
                                    and _vv_key != vnode_name.lower().strip()
                                ):
                                    v["_source"] = "vector_variant"
                                    v["_variant_of"] = vnode_name
                                    vector_variant_nodes.append(v)
                                    node_names_found.add(_vv_key)
                        except Exception as e:
                            logger.debug(f"  [Variant] Failed for {vnode_name}: {e}")

                if vector_variant_nodes:
                    logger.info(
                        f"  [Vector] Found {len(vector_variant_nodes)} name variants from vector results: "
                        f"{[(v['name'], v.get('_variant_of')) for v in vector_variant_nodes]}"
                    )
                    vector_nodes.extend(vector_variant_nodes)

                if vector_nodes:
                    logger.info(
                        f"  [Vector] Found {len(vector_nodes)} semantically similar nodes: "
                        f"{[n['name'] for n in vector_nodes]}"
                    )

                # Add keyword results from Typesense and merge with vector candidates.
                keyword_nodes = await self._search_typesense_by_keyword(query)
                if keyword_nodes:
                    vector_nodes = self._merge_search_results(
                        vector_nodes,
                        keyword_nodes,
                        node_names_found,
                    )
                    logger.info(
                        f"  [Keyword] Added {len(keyword_nodes)} Typesense matches"
                    )
            except Exception as e:
                logger.warning(f"  [Vector] Vector fallback search failed: {e}")

        t_vector = time.perf_counter() - t_vector_start
        logger.info(f"  [⏱️ Timing] Vector search: {t_vector:.2f}s")

        # Combine all found nodes
        all_found_nodes = entity_nodes + vector_nodes
        all_node_names = [n["name"] for n in all_found_nodes]

        # STEP 3: Community summaries for broad / exploratory queries
        community_summaries = []
        is_broad_or_exploratory = query_analysis.get("intent") in (
            "summarize",
            "explain",
            "list",
            "recent",
        )

        if is_broad_or_exploratory:
            try:
                # Search for communities semantically relevant to this query rather
                # than blindly returning the most-populated ones.
                community_summaries = graph_service.search_communities(
                    full_vector, top_k=5, min_score=0.55
                )

                if community_summaries:
                    logger.info(
                        f"  [Community] Found {len(community_summaries)} relevant communities: "
                        f"{[c['name'] for c in community_summaries]}"
                    )
            except Exception as e:
                logger.debug(f"  [Community] Failed to fetch communities: {e}")

        # STEP 4: Minimal note grounding (only fetch for linked evidence, not chunking)
        # We don't chunk notes anymore - node summaries ARE the distilled knowledge
        # Build a mapping from node name -> linked notes for reference traceability
        # Use lowercase keys for case-insensitive lookup
        node_to_notes: dict[str, list[dict]] = {}
        grounding_note_ids = set()
        if all_node_names:
            _grounding_id_to_name: dict[str, str] = {}
            for _grounding_node in all_found_nodes:
                _gnid = _grounding_node.get("node_id") or _grounding_node.get("id")
                _gnname = (_grounding_node.get("name") or "").lower().strip()
                if _gnid and _gnname:
                    _grounding_id_to_name[_gnid] = _gnname

            if _grounding_id_to_name:
                evidence_results = graph_service.get_linked_evidence_by_node_ids(
                    list(_grounding_id_to_name.keys()),
                    limit_per_node=2,
                    node_id_to_name=_grounding_id_to_name,
                )
            else:
                evidence_results = graph_service.get_linked_evidence(
                    all_node_names, limit_per_node=2
                )
            for row in evidence_results:
                node_name = row.get("node_name")
                evidence = row.get("evidence", [])
                if node_name and evidence:
                    # Store with lowercase key for case-insensitive lookup
                    node_to_notes[node_name.lower()] = evidence
                for note in evidence:
                    grounding_note_ids.add(note["id"])
            logger.info(
                f"  [Retrieval] Found {len(grounding_note_ids)} grounding notes (for source links)"
            )
            # Debug: log the node→notes mapping
            logger.debug(
                f"  [Retrieval] node_to_notes keys: {list(node_to_notes.keys())}"
            )

        t_candidates = time.perf_counter() - t_phase_start
        logger.info(
            f"  [⏱️ Timing] Retrieval phase: {t_candidates:.2f}s "
            f"({len(entity_nodes)} entity + {len(vector_nodes)} vector nodes)"
        )

        # ============ PREPARE CANDIDATES (NODE SUMMARIES FIRST) ============
        # Node summaries are PRIMARY evidence - they contain distilled, isolated knowledge
        candidates = []

        # A. Entity Nodes (highest priority — direct name matches from query)
        # ── Pre-fetch relationships for all candidate nodes in one pass ──────
        # _get_node_relationships makes a synchronous Kuzu call per node.
        # Batching here avoids N serial Kuzu round-trips in the loops below.
        _all_candidate_nodes = entity_nodes + vector_nodes
        _rel_cache: dict[str, str] = {}
        for _n in _all_candidate_nodes:
            _nname = _n.get("name", "")
            if _nname and _nname not in _rel_cache:
                _rel_cache[_nname] = self._get_node_relationships(_n)

        # A. Entity Nodes (highest priority — direct name matches from query)
        for node in entity_nodes:
            summary = self._get_node_text(node)
            if not summary:
                continue

            entity_type = node.get("entity_type", "") or ""
            if entity_type.lower() in ("indexable", "node"):
                entity_type = ""
            _article = (
                "an" if entity_type and entity_type[0].lower() in "aeiou" else "a"
            )
            type_clause = f" is {_article} {entity_type}." if entity_type else "."
            rel_context = _rel_cache.get(node["name"], "")

            text = f'{node["name"]}{type_clause} {summary}{rel_context}'

            # Attach linked notes for reference traceability (case-insensitive lookup)
            linked_notes = node_to_notes.get(node["name"].lower(), [])

            candidates.append(
                {
                    "text": text,
                    "type": "entity_match",
                    "original_obj": node,
                    "linked_notes": linked_notes,
                }
            )

        # B. Vector Nodes (semantically similar to query)
        for node in vector_nodes:
            summary = self._get_node_text(node)
            if not summary:
                continue

            entity_type = node.get("entity_type", "") or ""
            if entity_type.lower() in ("indexable", "node"):
                entity_type = ""
            _article = (
                "an" if entity_type and entity_type[0].lower() in "aeiou" else "a"
            )
            type_clause = f" is {_article} {entity_type}." if entity_type else "."
            rel_context = _rel_cache.get(node["name"], "")

            text = f'{node["name"]}{type_clause} {summary}{rel_context}'

            # Attach linked notes for reference traceability (case-insensitive lookup)
            linked_notes = node_to_notes.get(node["name"].lower(), [])

            # Community nodes that arrive via vector search should be tagged correctly
            _result_type = (
                "community_summary"
                if entity_type.lower() == "community"
                else "vector_match"
            )

            candidates.append(
                {
                    "text": text,
                    "type": _result_type,
                    "original_obj": node,
                    "linked_notes": linked_notes,
                }
            )

        # C. Community Summaries (high-level context for broad queries)
        # Fetch linked notes for community members
        community_linked_notes: dict[str, list[dict]] = {}
        if community_summaries:
            try:
                community_names = [
                    c.get("name") for c in community_summaries if c.get("name")
                ]
                community_evidence = graph_service.get_community_linked_notes(
                    community_names
                )
                for row in community_evidence:
                    comm_name = row.get("community_name")
                    notes = row.get("notes", [])
                    if comm_name and notes:
                        community_linked_notes[comm_name] = notes
            except Exception as e:
                logger.debug(f"  [Community] Failed to fetch community notes: {e}")

        for community in community_summaries:
            summary = community.get("summary")
            if not summary:
                continue

            name = community.get("name", "Unknown Community")
            domain = community.get("domain", "")
            themes = community.get("themes", [])
            member_count = community.get("member_count", 0)

            themes_str = f", covering {', '.join(themes)}" if themes else ""
            domain_str = f" ({domain})" if domain else ""
            text = (
                f'The "{name}" community{domain_str} has {member_count} members{themes_str}. '
                f"Context: {summary}"
            )

            # Attach linked notes from community members
            linked_notes = community_linked_notes.get(name, [])

            candidates.append(
                {
                    "text": text,
                    "type": "community_summary",
                    "original_obj": community,
                    "linked_notes": linked_notes,
                }
            )

        logger.info(
            f"  [Retrieval] Prepared {len(candidates)} candidates "
            f"({len(entity_nodes)} entity + {len(vector_nodes)} vector + {len(community_summaries)} community)"
        )

        # ============ RANKING ============
        if not candidates:
            logger.warning("  [Retrieval] No candidates found")
            return []

        t_ranking_start = time.perf_counter()

        combined_results = candidates

        t_ranking = time.perf_counter() - t_ranking_start
        logger.info(f"  [⏱️ Timing] Total ranking: {t_ranking:.4f}s")

        # Log what we're sending to LLM
        logger.info(
            f"  [Retrieval] Top {len(combined_results)} results by source: "
            f"entity={sum(1 for c in combined_results if c.get('type') == 'entity_match')}, "
            f"vector={sum(1 for c in combined_results if c.get('type') == 'vector_match')}, "
            f"neighbor={sum(1 for c in combined_results if c.get('type') == 'neighbor_node')}, "
            f"community={sum(1 for c in combined_results if c.get('type') == 'community_summary')}"
        )
        for i, doc in enumerate(combined_results):
            name = doc.get("original_obj", {}).get("name", "N/A")
            dtype = doc.get("type", "unknown")
            logger.info(f"    {i+1}. [{dtype}] {name}")

        # Detailed logging to file (full summaries, not truncated)
        self._log_retrieval_details(
            query,
            combined_results,
            query_entities,
            [],  # Pass extracted entities for logging
        )

        t_total = time.perf_counter() - t_start
        logger.info(
            f"  [⏱️ Timing] Total: {t_total:.2f}s (Embed: {t_embedding:.2f}s | Retrieval: {t_candidates:.2f}s | Ranking: {t_ranking:.4f}s)"
        )

        return combined_results

    async def retrieve_with_self_correction(
        self,
        query: str,
        top_k: int = 50,
        max_hops: int = 10,
        filter_docs: bool = True,
    ) -> tuple[str | None, list[dict]]:
        """Entry-point alias for the primary structured sub-question pipeline.

        The ``max_hops`` and ``filter_docs`` parameters are accepted for call-site
        compatibility but are no longer operative — the primary pipeline
        (``retrieve_with_iterative_loop``) manages its own hop budget and candidate
        filtering internally.  They are retained in the signature so callers do
        not need to be updated when the parameters are eventually removed.
        """
        return await self.retrieve_with_iterative_loop(query, top_k=top_k)

    async def _classify_query_scope(self, query: str) -> str:
        """Classify query as `community` or `specific` using the LLM."""
        from app.services.llm import llm_service

        logger.info(f"  [Classify] Classifying query scope for: '{query}'")
        prompt = (
            "Classify the query as COMMUNITY or SPECIFIC.\n"
            "COMMUNITY = broad overview questions asking for themes, summaries, what I've been learning, or high-level understanding.\n"
            "SPECIFIC = targeted factual/detail questions.\n"
            "Reply with one word only: COMMUNITY or SPECIFIC.\n\n"
            f"QUERY: {query}\n\nCLASSIFICATION:"
        )
        try:
            raw = await llm_service.generate(prompt, temperature=0.0)
            tag = (raw or "").strip().upper()
            logger.debug(
                f"  [Classify] Raw LLM response: '{raw.strip() if raw else ''}' → tag='{tag}'"
            )
            if tag.startswith("COMMUNITY"):
                logger.info("  [Classify] → COMMUNITY")
                return "community"
        except Exception as e:
            logger.debug(f"[Retrieval] query scope classification failed: {e}")
        logger.info("  [Classify] → SPECIFIC")
        return "specific"

    async def _apply_reranker_logging(
        self, query: str, candidates: list[dict], top_n: int | None = None
    ) -> list[dict]:
        """Rank candidates and return the top_n highest-scoring ones.

        When RERANKER_ENABLED is True, scores using the local model
        (``settings.MODEL_RERANKER_LOCAL``).  Falls back to a keyword-overlap
        heuristic when the model is disabled or unavailable.

        Args:
            top_n: After ranking, slice to this many results.  None = no cutoff.
        """
        if not candidates:
            return []

        # Build candidate texts for the reranker.
        # Expansion docs carry _rerank_text = origin + link + neighbour, giving
        # the reranker the full evidence chain to score rather than the
        # neighbour node in isolation.
        texts: list[str] = []
        for candidate in candidates:
            text = (
                candidate.get("_rerank_text") or candidate.get("text") or ""
            ).strip()
            if not text:
                text = self._get_node_text(candidate.get("original_obj") or {})
            texts.append(text)

        use_model = settings.RERANKER_ENABLED
        model_scores: dict[int, float] = {}

        if use_model:
            from app.services.reranker import reranker_service

            results = await reranker_service.rerank(query, texts)
            if results:
                for r in results:
                    model_scores[r["index"]] = r["relevance_score"]
                logger.info(
                    f"  [Reranker] {settings.MODEL_RERANKER_LOCAL} scored {len(model_scores)} "
                    f"candidates (top score: {max(model_scores.values()):.4f})"
                )
            else:
                logger.warning(
                    "  [Reranker] Model returned no scores, falling back to keyword heuristic"
                )
                use_model = False

        # Keyword-overlap fallback (used when model is disabled or unavailable).
        query_tokens = {
            token
            for token in re.findall(r"[a-z0-9][a-z0-9'_-]*", query.lower())
            if len(token) > 2 and token not in ENTITY_STOPWORDS
        }

        for idx, candidate in enumerate(candidates):
            if use_model and idx in model_scores:
                rerank_score = model_scores[idx]
            else:
                text_lower = texts[idx].lower()
                overlap = 0.0
                if query_tokens:
                    overlap = sum(
                        1 for token in query_tokens if token in text_lower
                    ) / len(query_tokens)
                rerank_score = overlap
            candidate["rerank_score"] = rerank_score
            candidate["jina_rank"] = idx + 1
            _name = (candidate.get("original_obj") or {}).get("name", "?")
            _preview = texts[idx].replace("\n", " ")
            logger.debug(
                f"  [Reranker] [{idx + 1}] {_name} rerank={rerank_score:.4f} | text: {_preview!r}"
            )

        candidates.sort(key=lambda c: c.get("rerank_score", 0.0), reverse=True)

        if top_n is not None and len(candidates) > top_n:
            logger.info(
                f"  [Reranker] Ranked {len(candidates)} candidates → keeping top {top_n}"
            )
            candidates = candidates[:top_n]
        else:
            logger.info(f"  [Reranker] Ranked {len(candidates)} candidates (no cutoff)")

        return candidates

    async def retrieve_with_pipeline(
        self,
        query: str,
        top_k: int = 50,
    ) -> tuple[str | None, list[dict]]:
        """
        Sequential sub-question retrieval pipeline.

        Architecture:
          1. LLM classifies scope → community fast-path or sequential sub-Q loop.
          2. LLM decomposes query into ordered sub-questions (dependencies first).
          3. For each sub-question:
               a. Fill placeholders with prior direct answers.
               b. hybrid_search(resolved_q) — all results, no artificial limit.
               c. LLM selects relevant docs with per-doc reasoning (logged).
               d. Graph expansion (_expand_relevant_neighbors) from selected docs.
               e. LLM selects relevant from expanded set (logged).
               f. Dual answer: full contextual answer + short direct answer + reasoning.
               g. Full trace logged at INFO level.
          4. Final synthesis from original question + all sub-Q full+direct answers.
          5. Return only the structured final synthesis result (or no answer).
        """
        import re as _re_sq

        from app.services.llm import llm_service

        _t_pipeline_start = time.perf_counter()
        logger.info(
            f"\n{'='*70}\n"
            f"[Pipeline] START retrieve_with_pipeline\n"
            f"  query='{query}'\n"
            f"{'='*70}"
        )

        # ── Community fast path ───────────────────────────────────────────────
        query_scope = await self._classify_query_scope(query)
        logger.info(f"  [Pipeline] Query scope: {query_scope}")

        if query_scope == "community":
            from app.services.embedding import embedding_service

            query_vector = embedding_service.embed_query(query)
            communities = graph_service.search_communities(
                query_vector,
                top_k=top_k,
                min_score=settings.VECTOR_SIMILARITY_THRESHOLD,
            )
            docs = [
                {
                    "text": f"Community '{c.get('name', 'Unknown')}': {c.get('summary', '')}",
                    "type": "community_summary",
                    "original_obj": c,
                    "priority": "primary",
                    "linked_notes": [],
                }
                for c in communities
                if c.get("summary")
            ]
            logger.info(
                f"  [Pipeline] Community fast-path: {len(docs)} communities — "
                "answer=no (structured synthesis only)"
            )
            return None, docs

        # ── Decompose into ordered sub-questions ─────────────────────────────
        # Also fetch query_attribute here so it can be passed to final synthesis,
        # avoiding a redundant analyze_query call inside final_synthesis_from_sub_results.
        _pipeline_query_attr: str | None = None
        try:
            _pipeline_qa = llm_service.analyze_query(query)
            _pipeline_query_attr = (
                _pipeline_qa.get("question_attribute") or ""
            ).lower() or None
        except Exception as _qa_err:
            logger.debug(
                f"  [Pipeline] analyze_query failed (will retry in synthesis): {_qa_err}"
            )

        sub_questions = await llm_service.identify_information_needs(query)

        role_attr_values = {
            "role",
            "position",
            "occupation",
            "job",
            "title",
            "government_position",
            "office",
            "post",
            "rank",
        }
        role_cues = (
            "position",
            "office",
            "role",
            "title",
            "occupation",
            "job",
            "held",
        )

        query_lower = query.lower()
        asks_for_role_info = (_pipeline_query_attr in role_attr_values) or any(
            cue in query_lower for cue in role_cues
        )
        subquestions_cover_role = any(
            any(cue in sq.lower() for cue in role_cues) for sq in sub_questions
        )

        if sub_questions and asks_for_role_info and not subquestions_cover_role:
            if "government" in query_lower:
                role_follow_up = "What government position did [person] hold?"
            elif "political office" in query_lower:
                role_follow_up = "What political office did [person] hold?"
            elif "office" in query_lower:
                role_follow_up = "What office did [person] hold?"
            else:
                role_follow_up = "What position did [person] hold?"

            if role_follow_up.lower() not in {q.lower() for q in sub_questions}:
                sub_questions.append(role_follow_up)
                logger.info(
                    "  [Pipeline] Added missing role/position hop to decomposition: "
                    f"'{role_follow_up}'"
                )

        logger.info(
            f"  [Pipeline] Decomposed into {len(sub_questions)} sub-question(s):\n"
            + "\n".join(f"    [{i+1}] {q}" for i, q in enumerate(sub_questions))
        )

        def _extract_placeholder_value(answer: str) -> str:
            """Strip verb predicates to get just the key entity for placeholder filling.

            'Shirley Temple portrayed Corliss Archer' -> 'Shirley Temple'
            'Adriana Trigiani' -> 'Adriana Trigiani'
            """
            import re as _re_local

            _verb_pred = _re_local.compile(
                r"\s+(portrayed|played|starred as|appeared as|was|is|were|are|has been|"
                r"had been|directed|wrote|produced|voiced|hosted|starred in|appeared in|"
                r"served as|became|worked as)\b.*",
                _re_local.IGNORECASE,
            )
            stripped = _verb_pred.sub("", answer).strip()
            return stripped or answer

        def _fill_placeholders(text: str, prior_answers: list[str]) -> str:
            """Replace [anything] placeholders with the most recent concrete direct answer.

            If no prior answer is available, strip the brackets so the inner word
            still acts as a search token rather than sending a literal '[ambassador]'
            to the search engine.
            """
            if "[" not in text:
                return text
            if prior_answers:
                return _re_sq.sub(r"\[[^\]]+\]", prior_answers[-1], text)
            # No concrete prior answer — strip brackets to keep the search term usable
            stripped = _re_sq.sub(r"\[([^\]]+)\]", r"\1", text)
            logger.info(
                f"  [Pipeline] Placeholder in sub-question could not be resolved "
                f"(no prior concrete answer). Stripped brackets: '{stripped}'"
            )
            return stripped

        sub_results: list[dict] = []
        prior_direct_answers: list[str] = []
        all_docs: list[dict] = []

        for sq_idx, sq in enumerate(sub_questions):
            resolved_sq = _fill_placeholders(sq, prior_direct_answers)
            step_num = sq_idx + 1

            logger.info(
                f"\n{'─'*60}\n"
                f"  [SubQ {step_num}/{len(sub_questions)}] '{resolved_sq}'\n"
                f"{'─'*60}"
            )

            # ── a. Retrieve: full search, no top_k gating ─────────────────
            raw_docs = await self.hybrid_search(resolved_sq)
            logger.info(
                f"  [SubQ {step_num}] hybrid_search returned {len(raw_docs)} candidates"
            )

            # ── a2. Rerank → top-K cutoff ─────────────────────────────────
            # Rank all candidates with the reranker, then slice to top K.
            # Reduces LLM context burden while keeping the highest-signal docs.
            raw_docs = await self._apply_reranker_logging(
                resolved_sq, raw_docs, top_n=settings.RERANKER_TOP_K
            )
            logger.info(
                f"  [SubQ {step_num}] Reranked → {len(raw_docs)} candidates sent to LLM selection"
            )

            # ── b. Trust reranker ordering — no LLM selection filter ────────
            selected_docs = raw_docs
            logger.info(
                f"  [SubQ {step_num}] Using all {len(selected_docs)} reranked docs"
            )

            # ── c. Graph expansion from selected docs ─────────────────────
            surfaced_names: set[str] = {
                (d.get("original_obj") or {}).get("name", "")
                for d in selected_docs
                if (d.get("original_obj") or {}).get("name")
            }
            expanded: list[dict] = []
            if selected_docs:
                try:
                    expanded = await self._expand_relevant_neighbors(
                        selected_docs, resolved_sq, surfaced_names
                    )
                    logger.info(
                        f"  [SubQ {step_num}] Graph expansion produced {len(expanded)} neighbors"
                    )
                    if expanded:
                        expanded = await self._apply_reranker_logging(
                            resolved_sq, expanded, top_n=settings.RERANKER_TOP_K
                        )
                        logger.info(
                            f"  [SubQ {step_num}] Reranked expanded neighbors → {len(expanded)} kept"
                        )
                except Exception as _exp_err:
                    logger.warning(
                        f"  [SubQ {step_num}] Graph expansion failed: {_exp_err}"
                    )

            # ── d. Trust all expanded neighbors — no LLM selection filter ──
            expanded_selected: list[dict] = expanded
            if expanded_selected:
                logger.info(
                    f"  [SubQ {step_num}] Using all {len(expanded_selected)} expanded neighbors"
                )

            # ── e. Build context pool for this sub-question ───────────────
            context_docs = selected_docs + expanded_selected
            logger.info(
                f"  [SubQ {step_num}] Context pool: {len(context_docs)} docs "
                f"({len(selected_docs)} retrieved + {len(expanded_selected)} expanded)"
            )

            # Accumulate all surfaced docs for final return value
            seen_all = {(d.get("original_obj") or {}).get("name", "") for d in all_docs}
            for d in context_docs:
                n = (d.get("original_obj") or {}).get("name", "")
                if n not in seen_all:
                    all_docs.append(d)
                    seen_all.add(n)

            # ── f. Dual answer: full + direct + reasoning ─────────────────
            full_answer, direct_answer, answer_reasoning = (
                await llm_service.answer_sub_question_dual(resolved_sq, context_docs)
            )

            logger.info(
                f"\n  [SubQ {step_num}] ═══ ANSWER TRACE ═══\n"
                f"    Question:      {resolved_sq}\n"
                f"    Reasoning:     {answer_reasoning}\n"
                f"    Full answer:   {full_answer or 'INSUFFICIENT'}\n"
                f"    Direct answer: {direct_answer or 'INSUFFICIENT'}\n"
                f"    Context docs:  {[((d.get('original_obj') or {}).get('name', '?')) for d in context_docs]}"
            )

            sub_results.append(
                {
                    "question": sq,
                    "resolved_question": resolved_sq,
                    "raw_doc_count": len(raw_docs),
                    "selected_doc_count": len(selected_docs),
                    "expansion_count": len(expanded),
                    "expanded_selected_count": len(expanded_selected),
                    "full_answer": full_answer,
                    "direct_answer": direct_answer,
                    "answer_reasoning": answer_reasoning,
                }
            )

            if direct_answer:
                key_val = _extract_placeholder_value(direct_answer)
                if key_val != direct_answer:
                    logger.info(
                        f"  [SubQ {step_num}] Placeholder value extracted: "
                        f"'{direct_answer}' -> '{key_val}'"
                    )
                prior_direct_answers.append(key_val)

        # ── Final synthesis ───────────────────────────────────────────────────
        logger.info(
            f"\n{'─'*60}\n"
            f"  [Pipeline] Final synthesis from {len(sub_results)} sub-question result(s)\n"
            f"{'─'*60}"
        )
        answer = await llm_service.final_synthesis_from_sub_results(
            query, sub_results, query_attr=_pipeline_query_attr
        )
        if answer:
            logger.info(f"  [Pipeline] Synthesis answer: '{answer}'")

        # ── Fallback: direct synthesis from all accumulated docs ──────────────
        # final_synthesis_from_sub_results reasons over the full sub-question chain
        # and returns None when it determines the chain is incomplete (INSUFFICIENT).
        # That determination is authoritative — do NOT attempt _direct_synthesize as
        # a fallback, because:
        #   a) the structured reasoning already concluded the answer can't be derived
        #   b) the accumulated docs are a superset of noise; the flat synthesis model
        #      will fill gaps from training knowledge, producing hallucinations
        #      (e.g. "Shirley Temple Black" instead of "Chief of Protocol",
        #       or "Mistborn" instead of "Animorphs")
        # We skip direct synthesis entirely and return empty docs so the caller
        # also cannot synthesize from this misleading pool.
        if not answer:
            _all_insufficient = (
                all(
                    not sr.get("full_answer") and not sr.get("direct_answer")
                    for sr in sub_results
                )
                if sub_results
                else True
            )
            logger.info(
                f"  [Pipeline] Structured synthesis returned INSUFFICIENT "
                f"(all_insufficient={_all_insufficient}) — "
                "skipping direct synthesis fallback to prevent hallucination."
            )
            all_docs = []

        # ── Web fallback for context only (no answer synthesis from raw docs) ─
        if not answer and settings.FALLBACK_MODE == "web":
            from app.services.tavily_service import web_search

            logger.info("  [Pipeline] Fallback=web — trying Tavily web search...")
            web_docs = await web_search(query)
            if web_docs:
                all_docs = all_docs + web_docs
                logger.info(
                    "  [Pipeline] Web docs collected, but skipping raw synthesis "
                    "(structured synthesis only)."
                )

        _t_total = time.perf_counter() - _t_pipeline_start
        _doc_types = ", ".join(
            f"{t}={sum(1 for d in all_docs if d.get('type') == t)}"
            for t in sorted({d.get("type", "?") for d in all_docs})
        )
        logger.info(
            f"\n{'='*70}\n"
            f"[Pipeline] COMPLETE in {_t_total:.2f}s\n"
            f"  sub_questions={len(sub_results)}\n"
            f"  answer={'yes (' + str(len(answer)) + ' chars)' if answer else 'NO ANSWER'}\n"
            f"  docs_returned={len(all_docs)}\n"
            f"  doc_types={{ {_doc_types} }}\n"
            f"{'='*70}"
        )
        if answer:
            logger.info(f"  [Pipeline] Answer: '{answer}'")

        return answer, all_docs

    async def retrieve_with_structured_subquestions(
        self,
        query: str,
        top_k: int = 50,
    ) -> tuple[str | None, list[dict]]:
        """
        Structured sub-question retrieval.

        Algorithm:
          1. Decompose query into sub-questions.
          2. For each sub-question: hybrid_search → answer attempt.
             If INSUFFICIENT, the model emits NEED: <query> which triggers a
             targeted follow-up search; this repeats up to 5 times per sub-question.
          3. Final synthesis from all Q/A pairs.
          Returns (final_answer, all_accumulated_docs).
        """
        import re as _re

        from app.services.llm import llm_service

        all_docs: list[dict] = []
        seen_names: set[str] = set()

        def _add_docs(new_docs: list[dict]) -> None:
            for d in new_docs:
                name = (d.get("original_obj") or {}).get("name") or d.get("name", "")
                if name and name not in seen_names:
                    all_docs.append(d)
                    seen_names.add(name)

        _META_QUERY_RE = _re.compile(
            r"\b(previous\s+answer|previous\s+question|from\s+the\s+previous|in\s+the\s+previous)\b",
            _re.IGNORECASE,
        )

        def _fill_placeholders(text: str, prior_answers: list[str]) -> str:
            """Replace [anything] CoT placeholders with the most recent concrete answer.

            If no prior answer is available, strip the brackets so the inner word
            still acts as a search token rather than sending a literal '[entity]'
            to the search engine.
            """
            if "[" not in text:
                return text
            if prior_answers:
                return _re.sub(r"\[[^\]]+\]", prior_answers[-1], text)
            # No concrete prior answer — strip brackets to keep the search term usable
            stripped = _re.sub(r"\[([^\]]+)\]", r"\1", text)
            logger.info(
                f"  [StructSubQ] Placeholder could not be resolved "
                f"(no prior concrete answer). Stripped brackets: '{stripped}'"
            )
            return stripped

        def _clean_for_placeholder(value: str) -> str:
            """Strip role qualifiers and verb predicates to extract the core entity.

            For example: 'Shirley Temple as Corliss Archer' → 'Shirley Temple'
            """
            # Strip "as [character/role]" suffix (e.g. "Shirley Temple as Corliss Archer")
            value = _re.sub(r"\s+as\s+\S.*", "", value, flags=_re.IGNORECASE).strip()
            # Strip verb predicates to isolate the subject
            value = _re.sub(
                r"\s+(portrayed|played|starred as|appeared as|was|is|were|are|"
                r"has been|had been|directed|wrote|produced|voiced|hosted|"
                r"starred in|appeared in|served as|became|worked as)\b.*",
                "",
                value,
                flags=_re.IGNORECASE,
            ).strip()
            return value

        async def _answer_question(question: str) -> str | None:
            """
            Try to produce a one-sentence answer for `question`.
            Per attempt:
              1. LLM filters retrieved docs to relevant subset.
              2. Graph-expand from relevant nodes: 1-hop neighbours not yet
                 surfaced are fetched; LLM selects which are relevant.
              3. Answer generated from expanded context (no redundant filter).
            If INSUFFICIENT, emit NEED: follow-up search and repeat.
            """
            logger.info(f"  [StructSubQ] searching: '{question}'")
            if _META_QUERY_RE.search(question):
                logger.info(f"  [StructSubQ] skipped meta-query: '{question}'")
                return None, None

            docs = await self.hybrid_search(question, top_k=top_k)
            _add_docs(docs)

            filter_redirects = 0
            insufficient_attempts = 0
            attempted_redirects: set[str] = set()
            attempted_follow_ups: set[str] = set()

            while filter_redirects < 3 and insufficient_attempts < 5:
                # Trust the reranker — skip LLM relevancy filter.
                relevant = docs

                if not relevant:
                    # Filter found nothing — generate a redirect query that
                    # targets the specific missing information instead of
                    # falling back to noisy unfiltered context.
                    redirect = await llm_service.generate_redirect_query(docs, question)
                    filter_redirects += 1
                    logger.info(
                        f"  [StructSubQ] filter-fail #{filter_redirects}, "
                        f"redirect: '{redirect}'"
                    )
                    if redirect:
                        normalized_redirect = redirect.strip().lower()
                        if normalized_redirect in attempted_redirects:
                            logger.info(
                                f"  [StructSubQ] repeated redirect '{redirect}' — stopping retries"
                            )
                            break
                        attempted_redirects.add(normalized_redirect)
                        new_docs = await self.hybrid_search(redirect, top_k=top_k)
                        if not new_docs:
                            logger.info(
                                f"  [StructSubQ] redirect '{redirect}' returned no new docs"
                            )
                        _add_docs(new_docs)
                        docs = docs + [d for d in new_docs if d not in docs]
                    continue  # retry filter with expanded doc set

                # Step 2: Graph-expand — LLM selects useful 1-hop neighbours
                surfaced = {
                    (d.get("original_obj") or {}).get("name") or d.get("name", "")
                    for d in docs
                    if (d.get("original_obj") or {}).get("name") or d.get("name", "")
                }
                neighbor_docs = await self._expand_relevant_neighbors(
                    relevant, question, surfaced
                )
                if neighbor_docs:
                    neighbor_docs = await self._apply_reranker_logging(
                        question, neighbor_docs, top_n=settings.RERANKER_TOP_K
                    )
                    logger.info(
                        f"  [StructSubQ] Reranked expanded neighbors → {len(neighbor_docs)} kept"
                    )
                    _add_docs(neighbor_docs)

                # Trust the reranker — use all retrieved + expanded docs.
                final_context = relevant + neighbor_docs

                # Step 4: Answer with pre-filtered + expanded context
                attempt_num = filter_redirects + insufficient_attempts + 1
                answer, follow_up = await llm_service.answer_sub_question(
                    question, final_context, skip_filter=True
                )
                if answer:
                    logger.info(
                        f"  [StructSubQ] answered (attempt {attempt_num}): '{answer}'"
                    )
                    return answer, None  # (concrete_answer, failure_summary)

                insufficient_attempts += 1
                if not follow_up:
                    break
                normalized_follow_up = follow_up.strip().lower()
                if normalized_follow_up in attempted_follow_ups:
                    logger.info(
                        f"  [StructSubQ] repeated NEED '{follow_up}' — stopping retries"
                    )
                    break
                attempted_follow_ups.add(normalized_follow_up)
                logger.info(f"  [StructSubQ] attempt {attempt_num} NEED: '{follow_up}'")
                follow_up_docs = await self.hybrid_search(follow_up, top_k=top_k)
                if not follow_up_docs:
                    logger.info(
                        f"  [StructSubQ] NEED '{follow_up}' returned no new docs"
                    )
                    break
                _add_docs(follow_up_docs)
                # Accumulate — next attempt sees everything found so far
                docs = docs + [d for d in follow_up_docs if d not in docs]

            # All attempts exhausted — produce a one-sentence failure summary so
            # synthesis has informative context rather than a bare "Not found".
            # This is NOT used for CoT placeholder filling — only for final synthesis.
            failure_summary = await llm_service.summarize_search_failure(question, docs)
            logger.info(
                f"  [StructSubQ] failure summary for '{question}': "
                f"'{failure_summary}'"
            )
            return None, failure_summary  # (concrete_answer, failure_summary)

        # Decompose query into sub-questions (single pass)
        decomp = llm_service.decompose_query(query)
        sub_questions = [sq["text"] for sq in decomp.get("sub_questions", [])]

        query_attr = ""
        try:
            qa = llm_service.analyze_query(query)
            query_attr = (qa.get("question_attribute") or "").lower()
        except Exception:
            query_attr = ""

        role_attr_values = {
            "role",
            "position",
            "occupation",
            "job",
            "title",
            "government_position",
            "office",
            "post",
            "rank",
        }
        role_cues = (
            "position",
            "office",
            "role",
            "title",
            "occupation",
            "job",
            "held",
        )
        query_lower = query.lower()
        asks_for_role_info = (query_attr in role_attr_values) or any(
            cue in query_lower for cue in role_cues
        )
        subquestions_cover_role = any(
            any(cue in sq.lower() for cue in role_cues) for sq in sub_questions
        )

        if sub_questions and asks_for_role_info and not subquestions_cover_role:
            if "government" in query_lower:
                role_follow_up = "What government position did [person] hold?"
            elif "political office" in query_lower:
                role_follow_up = "What political office did [person] hold?"
            elif "office" in query_lower:
                role_follow_up = "What office did [person] hold?"
            else:
                role_follow_up = "What position did [person] hold?"

            if role_follow_up.lower() not in {q.lower() for q in sub_questions}:
                sub_questions.append(role_follow_up)
                logger.info(
                    "  [StructSubQ] Added missing role/position hop to decomposition: "
                    f"'{role_follow_up}'"
                )

        logger.info(
            f"  [StructSubQ] Decomposed into {len(sub_questions)} sub-questions: {sub_questions}"
        )

        # Single-hop fall-through: no decomposition needed
        if not sub_questions or not decomp.get("requires_decomposition", False):
            logger.info("  [StructSubQ] Single-hop — direct search")
            answer, fail_ctx = await _answer_question(query)
            result = answer or fail_ctx
            logger.info(f"  [StructSubQ] Single-hop answer: '{result}'")
            return result, all_docs

        # Answer each sub-question sequentially, injecting prior answers
        # into subsequent search queries (CoRAG-style chain-of-thought).
        # prior_values only carries CONCRETE answers (answer is not None) so that
        # failure summaries do not pollute [placeholder] substitution.
        sub_answers: list[dict] = []
        for sq in sub_questions:
            prior_values = [
                _clean_for_placeholder(sa["answer"])
                for sa in sub_answers
                if sa.get("concrete") and sa["answer"] != "Not found in knowledge base"
            ]
            search_query = _fill_placeholders(sq, prior_values)

            answer, fail_ctx = await _answer_question(search_query)
            sub_answers.append(
                {
                    "question": search_query,
                    "answer": answer or fail_ctx or "Not found in knowledge base",
                    # concrete=True only for real answers, not failure summaries;
                    # this prevents failure summaries being used as CoT values.
                    "concrete": answer is not None,
                }
            )

        logger.info(f"  [StructSubQ] {len(sub_answers)} sub-answers collected")

        # Final synthesis
        final_answer, _ = await llm_service.final_synthesis_from_sub_answers(
            query, sub_answers
        )
        if final_answer:
            logger.info(f"  [StructSubQ] Final answer: '{final_answer}'")
        return final_answer, all_docs

    async def retrieve_with_iterative_loop(
        self,
        query: str,
        top_k: int = 50,
    ) -> tuple[str | None, list[dict]]:
        """
        Iterative retrieval loop — one LLM call per iteration.

        Each iteration the LLM either:
          - Provides a NEXT_QUERY to search for, or
          - Outputs CAN_ANSWER with the final bare answer phrase.

        Continues until CAN_ANSWER is produced or MAX_LOOP_ITERATIONS is hit.
        Returns (final_answer, all_accumulated_docs).
        """
        from app.services.llm import llm_service

        _t_start = time.perf_counter()
        logger.info(
            f"\n{'='*70}\n"
            f"[IterLoop] START retrieve_with_iterative_loop\n"
            f"  query='{query}'\n"
            f"{'='*70}"
        )

        accumulated_steps: list[dict] = []
        all_docs: list[dict] = []
        surfaced_names: set[str] = set()
        current_query: str | None = None

        for iteration in range(settings.MAX_LOOP_ITERATIONS):
            logger.info(
                f"  [IterLoop] Iteration {iteration + 1}/{settings.MAX_LOOP_ITERATIONS} "
                f"| current_query={current_query!r}"
            )

            # ── Retrieve docs (skip on first iteration) ───────────────────────
            if current_query is not None:
                raw_docs = await self.hybrid_search(current_query)
                logger.info(
                    f"  [IterLoop] hybrid_search returned {len(raw_docs)} candidates"
                )

                selected_docs = await self._apply_reranker_logging(
                    current_query, raw_docs, top_n=settings.RERANKER_TOP_K
                )
                logger.info(
                    f"  [IterLoop] Reranked → {len(selected_docs)} docs"
                )

                for d in selected_docs:
                    name = (
                        (d.get("original_obj") or {}).get("name") or d.get("name", "")
                    )
                    if name:
                        surfaced_names.add(name)

                # Graph expansion
                expanded: list[dict] = []
                try:
                    expanded = await self._expand_relevant_neighbors(
                        selected_docs, current_query, surfaced_names
                    )
                    logger.info(
                        f"  [IterLoop] Graph expansion: {len(expanded)} neighbors"
                    )
                    if expanded:
                        expanded = await self._apply_reranker_logging(
                            current_query, expanded, top_n=settings.RERANKER_TOP_K
                        )
                        for d in expanded:
                            name = (
                                (d.get("original_obj") or {}).get("name")
                                or d.get("name", "")
                            )
                            if name:
                                surfaced_names.add(name)
                except Exception as _exp_err:
                    logger.warning(
                        f"  [IterLoop] Graph expansion failed: {_exp_err}"
                    )

                docs = selected_docs + expanded

                # Accumulate unique docs into all_docs
                seen_all_names = {
                    (d.get("original_obj") or {}).get("name") or d.get("name", "")
                    for d in all_docs
                }
                for d in docs:
                    name = (
                        (d.get("original_obj") or {}).get("name") or d.get("name", "")
                    )
                    if name not in seen_all_names:
                        all_docs.append(d)
                        seen_all_names.add(name)
            else:
                docs = []

            # ── LLM iterative step ────────────────────────────────────────────
            result = await llm_service.iterative_step(
                original_question=query,
                accumulated_steps=accumulated_steps,
                search_query=current_query,
                docs=docs,
            )

            logger.info(
                f"  [IterLoop] iterative_step result: can_answer={result['can_answer']} "
                f"final_answer={result.get('final_answer')!r} "
                f"next_query={result.get('next_query')!r}"
            )

            # Store step findings for the next iteration's context
            if docs and (result.get("full_answer") or result.get("reasoning")):
                accumulated_steps.append(
                    {
                        "query": current_query,
                        "full_answer": result.get("full_answer", ""),
                        "reasoning": result.get("reasoning", ""),
                    }
                )

            if result["can_answer"]:
                final_answer = result["final_answer"]
                _t_total = time.perf_counter() - _t_start
                logger.info(
                    f"\n{'='*70}\n"
                    f"[IterLoop] COMPLETE in {_t_total:.2f}s\n"
                    f"  iterations={iteration + 1}\n"
                    f"  answer='{final_answer}'\n"
                    f"  docs_accumulated={len(all_docs)}\n"
                    f"{'='*70}"
                )
                return final_answer, all_docs

            next_q = result.get("next_query")
            if not next_q:
                logger.warning(
                    f"  [IterLoop] No NEXT_QUERY at iteration {iteration + 1}, stopping"
                )
                break

            current_query = next_q

        _t_total = time.perf_counter() - _t_start
        logger.info(
            f"\n{'='*70}\n"
            f"[IterLoop] EXHAUSTED in {_t_total:.2f}s — returning None\n"
            f"  docs_accumulated={len(all_docs)}\n"
            f"{'='*70}"
        )
        return None, all_docs


retrieval_service = RetrievalService()
