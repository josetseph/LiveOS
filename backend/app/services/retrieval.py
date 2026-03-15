import os
import logging
import time
from datetime import datetime
from typing import List
from app.core.config import settings
from app.core.log import get_logger
from app.services.graph import graph_service

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
                logger.debug(f"NODE TYPE: {original.get('type', 'N/A')}")

                # Full summary - not truncated!
                summary = original.get("summary") or original.get("description", "")
                logger.debug(f"FULL SUMMARY ({len(summary)} chars):")
                logger.debug(summary if summary else "(empty)")

                # Isolated context if available
                isolated = original.get("isolated_context", "")
                if isolated:
                    logger.debug(f"ISOLATED CONTEXT ({len(isolated)} chars):")
                    logger.debug(isolated)

            # Linked notes
            linked_notes = doc.get("linked_notes", [])
            if linked_notes:
                logger.debug(f"LINKED NOTES ({len(linked_notes)}):")
                for note in linked_notes[:3]:
                    logger.debug(
                        f"  - {note.get('title', 'Untitled')} ({note.get('id', 'N/A')})"
                    )

            # Full text sent to LLM
            logger.debug(f"TEXT SENT TO LLM ({len(doc.get('text', ''))} chars):")
            logger.debug(
                doc.get("text", "")[:1000] + "..."
                if len(doc.get("text", "")) > 1000
                else doc.get("text", "")
            )

        logger.debug("\n" + "=" * 100 + "\n")

    def _get_node_relationships(self, node: dict, max_relationships: int = 5) -> str:
        """
        Fetch and format 1-hop relationships for a node to provide connection context.

        Args:
            node: Node dict from Neo4j
            max_relationships: Maximum number of relationships to include

        Returns:
            Formatted relationship string, or empty if no relationships found
        """
        from app.services.graph import graph_service

        try:
            node_name = node.get("name", "")
            if not node_name:
                return ""

            label = (
                node.get("labels", ["Entity"])[0]
                if isinstance(node.get("labels"), list)
                else "Entity"
            )

            # Fetch 1-hop relationships
            related_nodes = graph_service.get_related_nodes(
                node_name=node_name, node_label=label, max_depth=1, min_confidence=0.5
            )

            if not related_nodes:
                return ""

            # Format each connected node as natural language so the LLM
            # reads prose rather than notation.
            relationships = []
            for related in related_nodes[:max_relationships]:
                rel_name = related.get("name", "Unknown")
                rel_path = related.get("relationship_path", [])
                context_path = related.get("context_path", [])

                if context_path and context_path[0]:
                    context = context_path[0]
                    rel_str = f'"{rel_name}" ({context})'
                elif rel_path:
                    rel_natural = rel_path[0].replace("_", " ").title()
                    rel_str = f'"{rel_name}" ({rel_natural})'
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

    def _get_node_text(self, node: dict) -> str:
        """
        Extract text content from a node, including atomic facts so the LLM
        can answer fact-specific questions (e.g. "Where is X from?") directly
        from candidate text without needing a separate lookup.

        Args:
            node: Node dict from Neo4j

        Returns:
            Summary text with facts appended when present.
        """
        import json as _json

        summary = node.get("summary") or node.get("description", "")
        facts_raw = node.get("facts")
        if facts_raw:
            try:
                facts = (
                    _json.loads(facts_raw) if isinstance(facts_raw, str) else facts_raw
                )
                if isinstance(facts, list) and facts:
                    facts_text = "; ".join(
                        f"{f['property']}: {f['value']}"
                        for f in facts
                        if isinstance(f, dict) and f.get("property") and f.get("value")
                    )
                    if facts_text:
                        summary = (
                            f"{summary} Facts: {facts_text}" if summary else facts_text
                        )
            except Exception:
                pass
        return summary

    async def hybrid_search(self, query: str, top_k: int = 20) -> List[dict]:
        """
        Vector-First Retrieval Pipeline:

        Uses vector search as the primary entry point, with 1-hop neighbor expansion
        to find related context. This is simpler and more effective than entity name
        matching, which often returns noisy results.

        Flow:
        1. Query Analysis: Extract expected entity types and question attributes via LLM
        2. Vector Search: Find semantically similar nodes (primary entry point)
        3. Neighbor Expansion: Get 1-hop neighbors of top vector results
        4. Scoring: Rank candidates by type match + attribute relevance
        5. Grounding: Minimal note content only if needed for specific quotes

        Returns node summaries as primary evidence, not chunked note snippets.
        """
        from app.services.embedding import embedding_service

        logger.info(f"  [Retrieval] Hybrid Search for: '{query}'")
        t_start = time.perf_counter()
        t_phase_start = time.perf_counter()

        # Query Analysis with LLM structured outputs
        from app.services.llm import llm_service

        query_analysis = llm_service.analyze_query(query)

        # Extract expected entity types for filtering/boosting
        expected_entity_types = query_analysis.get("expected_entity_types", [])
        question_attribute = query_analysis.get("question_attribute", None)
        # The LLM is solely responsible for determining whether the query is temporal.
        # No hardcoded keyword fallback — this keeps the system domain-agnostic.
        is_temporal_query = query_analysis.get("is_temporal", False)

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
            f"Temporal: {is_temporal_query}, "
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
                entity_found = graph_service.find_nodes_by_name(
                    names=query_entities, fuzzy=True
                )
                for node in entity_found:
                    if node["name"] not in node_names_found:
                        node["_source"] = "entity_match"
                        entity_nodes.append(node)
                        node_names_found.add(node["name"])

                # STEP 1.5: NAME VARIANT EXPANSION
                # Search for variants of found names to catch fuller/alternate versions
                # e.g., "Robert Smith" → also find "Robert Smith Jr."
                variant_nodes = []
                for node in entity_found[:10]:  # Top 10 to avoid explosion
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
                            for v in variants[:5]:  # Top 5 variants per name
                                if (
                                    v["name"] not in node_names_found
                                    and v["name"] != node_name
                                ):
                                    v["_source"] = "name_variant"
                                    v["_variant_of"] = node_name
                                    variant_nodes.append(v)
                                    node_names_found.add(v["name"])
                        except Exception as e:
                            logger.debug(f"  [Variant] Failed for {node_name}: {e}")

                if variant_nodes:
                    logger.info(
                        f"  [Entity] Found {len(variant_nodes)} name variants: "
                        f"{[(v['name'], v.get('_variant_of')) for v in variant_nodes]}"
                    )
                    entity_nodes.extend(variant_nodes)

                if entity_nodes:
                    logger.info(
                        f"  [Entity] Found {len(entity_nodes)} nodes by name: "
                        f"{[n['name'] for n in entity_nodes[:10]]}"
                    )
            except Exception as e:
                logger.warning(f"  [Entity] Name matching failed: {e}")
            t_entity = time.perf_counter() - t_entity_start
            logger.info(f"  [⏱️ Timing] Entity name matching: {t_entity:.2f}s")

        # STEP 2: VECTOR SEARCH - Find semantically similar nodes
        # This catches entities the user didn't name explicitly
        t_vector_start = time.perf_counter()
        try:
            # IMPROVEMENT: Reduced top_k (20→12) and increased min_score (0.60→0.70)
            # to reduce noise from qwen3-embedding:0.6b weak matches

            # Search using summary embeddings for semantic coverage
            vector_results = graph_service.search_knowledge_graph(
                full_vector, top_k=12, min_score=0.7
            )

            for vnode in vector_results:
                if vnode["name"] not in node_names_found:
                    vnode["_source"] = "vector"
                    vector_nodes.append(vnode)
                    node_names_found.add(vnode["name"])

            # STEP 2.5: NAME VARIANT EXPANSION for vector-found person entities
            # Catches "Margaret Johnson" → "Margaret Johnson-Williams" for multi-hop queries
            vector_variant_nodes = []
            for vnode in vector_nodes[:10]:  # Check top 10 vector results
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
                        for v in variants[:5]:  # Top 5 variants per name
                            if (
                                v["name"] not in node_names_found
                                and v["name"] != vnode_name
                            ):
                                v["_source"] = "vector_variant"
                                v["_variant_of"] = vnode_name
                                vector_variant_nodes.append(v)
                                node_names_found.add(v["name"])
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
                    f"{[n['name'] for n in vector_nodes[:10]]}"
                )
        except Exception as e:
            logger.warning(f"  [Vector] Vector search failed: {e}")

        t_vector = time.perf_counter() - t_vector_start
        logger.info(f"  [⏱️ Timing] Vector search: {t_vector:.2f}s")

        # Follow IS_SAME_AS and IS_VARIANT_OF links to include canonical/related entities.
        all_primary_nodes = entity_nodes + vector_nodes
        alias_resolved_nodes = []

        if all_primary_nodes:
            logger.info(
                f"  [Alias] Checking {len(all_primary_nodes)} nodes for IS_SAME_AS / IS_VARIANT_OF links"
            )

            for node in all_primary_nodes:
                node_name = node["name"]

                # Follow both IS_SAME_AS (certain identity) and IS_VARIANT_OF (probable identity)
                alias_query = """
                MATCH (alias:Entity {name: $name})-[r:IS_SAME_AS|IS_VARIANT_OF]->(canonical:Entity)
                RETURN canonical.name as canonical_name,
                       canonical.summary as summary,
                       canonical.type as entity_type,
                       canonical.embedding as embedding,
                       r.confidence as alias_confidence,
                       type(r) as rel_type,
                       labels(canonical) as labels
                """

                alias_results = graph_service.execute_query(
                    alias_query, {"name": node_name}
                )

                if alias_results:
                    # Keep the original (alias) node so its own 1-hop neighbors are expanded too
                    alias_resolved_nodes.append(node)

                    canonical_node_names = {n["name"] for n in alias_resolved_nodes}
                    for row in alias_results:
                        canonical_name = row["canonical_name"]
                        alias_confidence = row.get("alias_confidence", 1.0)
                        rel_type = row.get("rel_type", "IS_SAME_AS")

                        logger.info(
                            f"  [Alias] '{node_name}' -{rel_type}-> '{canonical_name}' "
                            f"(confidence: {alias_confidence:.2f})"
                        )

                        if canonical_name not in canonical_node_names:
                            canonical_node = {
                                "name": canonical_name,
                                "summary": row.get("summary"),
                                "entity_type": row.get("entity_type"),
                                "embedding": row.get("embedding"),
                                "labels": row.get("labels", ["Entity"]),
                                "_source": f"{rel_type.lower()}_of_{node_name}",
                                "_alias_confidence": alias_confidence,
                            }
                            alias_resolved_nodes.append(canonical_node)
                            canonical_node_names.add(canonical_name)
                else:
                    # No alias links — keep original node as-is
                    alias_resolved_nodes.append(node)

            added = len(alias_resolved_nodes) - len(all_primary_nodes)
            logger.info(
                f"  [Alias] After alias resolution: {len(alias_resolved_nodes)} nodes "
                f"({added} added via IS_SAME_AS / IS_VARIANT_OF)"
            )

            all_primary_nodes = alias_resolved_nodes

        # Combine all found nodes
        all_found_nodes = entity_nodes + vector_nodes
        all_node_names = [n["name"] for n in all_found_nodes]

        # STEP 4: Community summaries for broad / exploratory queries
        # Use the LLM-determined intent rather than keyword matching to decide.
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
            evidence_results = graph_service.get_linked_evidence(
                all_node_names, limit_per_node=2  # Just 2 per node for grounding
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
        for node in entity_nodes:
            summary = self._get_node_text(node)
            if not summary:
                continue

            entity_type = node.get("entity_type", "") or ""
            _article = (
                "an" if entity_type and entity_type[0].lower() in "aeiou" else "a"
            )
            type_clause = f", {_article} {entity_type}" if entity_type else ""
            rel_context = self._get_node_relationships(node)

            text = f'{node["name"]}{type_clause}, has context "{summary}"{rel_context}'

            # Attach linked notes for reference traceability (case-insensitive lookup)
            linked_notes = node_to_notes.get(node["name"].lower(), [])

            candidates.append(
                {
                    "text": text,
                    "type": "entity_match",
                    "original_obj": node,
                    "is_recent": False,
                    "priority": "primary",  # Entity matches are highest priority
                    "vector_score": 1.0,  # Give entity matches high score
                    "linked_notes": linked_notes,
                }
            )

        # B. Vector Nodes (semantically similar to query)
        for node in vector_nodes:
            vector_score = node.get("score", 0.0)

            # Filter weak semantic matches to reduce noise
            if vector_score < 0.7:
                continue

            summary = self._get_node_text(node)
            if not summary:
                continue

            entity_type = node.get("entity_type", "") or ""
            _article = (
                "an" if entity_type and entity_type[0].lower() in "aeiou" else "a"
            )
            type_clause = f", {_article} {entity_type}" if entity_type else ""
            rel_context = self._get_node_relationships(node)

            text = f'{node["name"]}{type_clause}, has context "{summary}"{rel_context}'

            # Attach linked notes for reference traceability (case-insensitive lookup)
            linked_notes = node_to_notes.get(node["name"].lower(), [])

            candidates.append(
                {
                    "text": text,
                    "type": "vector_match",
                    "original_obj": node,
                    "is_recent": False,
                    "priority": "primary",  # Vector matches are primary
                    "vector_score": vector_score,
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
                    "is_recent": False,
                    "priority": "tertiary",  # Community summaries for context
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
            self._current_query_embedding = None  # Clean up
            return []

        t_ranking_start = time.perf_counter()

        # ============ ENTITY TYPE SCORING ============
        # If we know the expected entity types (e.g., "Person" for nationality questions),
        # boost candidates that match and penalize those that don't
        # Uses LLM-based synonym expansion + embedding similarity for fuzzy matching

        # Cache for type synonyms (avoid repeated LLM calls)
        type_synonym_cache = {}

        def get_type_synonyms(entity_type: str) -> list[str]:
            """Get synonyms for a type using LLM or embedding similarity"""
            if entity_type.lower() in type_synonym_cache:
                return type_synonym_cache[entity_type.lower()]

            # Use LLM to expand synonyms
            synonyms = llm_service.expand_type_synonyms(entity_type)
            type_synonym_cache[entity_type.lower()] = synonyms
            return synonyms

        def get_type_score(candidate) -> float:
            """Score based on entity type match. 1.0 = match, 0.5 = unknown, 0.1 = mismatch

            Uses:
            1. Direct string match
            2. LLM-generated synonyms
            3. Embedding similarity between type names
            """
            if not expected_entity_types:
                return 0.5  # No type filtering

            node = candidate.get("original_obj", {})
            entity_type = node.get("entity_type", None)

            if not entity_type:
                return 0.3  # Unknown type - slight penalty

            # Normalize types for comparison
            entity_type_lower = entity_type.lower()
            expected_lower = [t.lower() for t in expected_entity_types]

            # 1. Direct match
            if entity_type_lower in expected_lower:
                return 1.0

            # 2. LLM-based synonym matching
            for exp_type in expected_lower:
                synonyms = get_type_synonyms(exp_type)
                if entity_type_lower in synonyms:
                    return 0.9  # Synonym match

            # 3. Embedding similarity fallback (for fuzzy matches)
            # Check if entity_type is semantically close to any expected type
            try:
                entity_type_embedding = embedding_service.embed_query(entity_type_lower)
                max_similarity = 0.0

                for exp_type in expected_lower:
                    exp_embedding = embedding_service.embed_query(exp_type)
                    # Cosine similarity
                    from app.services.embedding import compute_cosine_similarity

                    similarity = compute_cosine_similarity(
                        entity_type_embedding, exp_embedding
                    )
                    max_similarity = max(max_similarity, similarity)

                # If embedding similarity is high, consider it a match
                if max_similarity > 0.7:
                    return 0.85  # Semantic match
                elif max_similarity > 0.5:
                    return 0.6  # Weak match
            except Exception as e:
                logger.debug(f"Embedding similarity failed for type scoring: {e}")

            return 0.1  # Type mismatch (heavy penalty)

        def get_attribute_relevance(candidate, query_vector: list[float]) -> float:
            """
            Score based on semantic similarity between the candidate's summary
            and the query. Uses embedding-based cosine similarity for general-purpose
            attribute relevance without hardcoded keywords.

            Also performs CONTEXT-BASED DISAMBIGUATION:
            - If multiple entities share the same name, use query context to pick the right one
            - Example: "Michael Jordan" (basketball) vs "Michael Jordan" (professor)
            """
            node = candidate.get("original_obj", {})
            summary = self._get_node_text(node)

            if not summary or len(summary.strip()) < 10:
                return 0.3  # No meaningful content

            # Use the vector_score if already computed from Neo4j vector search
            # This is the cosine similarity between query and node's stored embedding
            existing_score = candidate.get("vector_score", 0.0)
            if existing_score > 0:
                # Context disambiguation: Boost if query keywords appear in summary
                query_keywords = set(query.lower().split()) - {
                    "what",
                    "where",
                    "when",
                    "who",
                    "how",
                    "the",
                    "is",
                    "was",
                    "are",
                    "were",
                }
                summary_lower = summary.lower()
                keyword_matches = sum(1 for kw in query_keywords if kw in summary_lower)
                keyword_boost = min(
                    keyword_matches / max(len(query_keywords), 1) * 0.2, 0.2
                )

                return min(existing_score + keyword_boost, 1.0)

            # Fallback: compute similarity if not available
            # This handles entity_match candidates that don't have vector scores
            try:
                # Reconstruct the exact text used at ingestion time:
                # f"{title}: {summary} Facts: ..." (see _update_node_summary)
                # so the vector sits in the same embedding space as stored nodes.
                node_title = node.get("title") or ""
                embed_text = f"{node_title}: {summary}" if node_title else summary
                summary_vector = embedding_service.embed_documents([embed_text])[0]
                # Cosine similarity
                dot_product = sum(a * b for a, b in zip(query_vector, summary_vector))
                norm_q = sum(a * a for a in query_vector) ** 0.5
                norm_s = sum(a * a for a in summary_vector) ** 0.5
                if norm_q > 0 and norm_s > 0:
                    base_similarity = dot_product / (norm_q * norm_s)

                    # Context disambiguation boost
                    query_keywords = set(query.lower().split()) - {
                        "what",
                        "where",
                        "when",
                        "who",
                        "how",
                        "the",
                        "is",
                        "was",
                        "are",
                        "were",
                    }
                    summary_lower = summary.lower()
                    keyword_matches = sum(
                        1 for kw in query_keywords if kw in summary_lower
                    )
                    keyword_boost = min(
                        keyword_matches / max(len(query_keywords), 1) * 0.2, 0.2
                    )

                    return min(base_similarity + keyword_boost, 1.0)
            except Exception as e:
                logger.warning(f"Failed to compute semantic similarity: {e}")

            return 0.5  # Neutral if computation fails

        # Score all candidates
        for cand in candidates:
            # Get vector score first (used by semantic scoring)
            cand["vector_score"] = cand.get("vector_score", 0.0)

            # Calculate type score and semantic relevance for each candidate
            cand["type_score"] = get_type_score(cand)
            cand["semantic_score"] = get_attribute_relevance(cand, full_vector)

            # Combined score: type match is now primary (entity type precision matters most),
            # semantic similarity is secondary, vector score is a small tiebreaker.
            # Weights: type (45%), semantic (40%), vector (15%)
            cand["combined_score"] = (
                cand["type_score"] * 0.45
                + cand["semantic_score"] * 0.40
                + cand["vector_score"] * 0.15  # Direct vector score contribution
            )

        # NOTE: Domain boosting removed for nodes (only Notes have domain property)
        # Entity/Concept/Task nodes don't have domain, so boosting was broken
        # If domain filtering needed, implement at Note level or propagate domain to nodes during ingestion

        # Sort by combined score, then by priority
        def sort_key(c):
            priority_order = {"primary": 0, "secondary": 1, "tertiary": 2}
            priority_score = priority_order.get(c.get("priority", "tertiary"), 2)
            combined_score = c.get("combined_score", 0.5)
            # Lower is better: -combined_score puts high matches first
            return (-combined_score, priority_score)

        candidates.sort(key=sort_key)

        # Log expected types for debugging (type scoring still affects ranking)
        if expected_entity_types:
            logger.debug(
                f"  [Type Scoring] Expected types: {expected_entity_types}, "
                f"Attribute: {question_attribute}"
            )

        # R3.1: DISABLED - Neural reranking (too slow, hurts quality)
        # Reranker added 237% latency (31s→104s) and reduced accuracy by 4%
        # Use pure symbolic scoring instead (combined_score already includes domain boost)
        for cand in candidates:
            # Use combined_score (with domain boost) as final score
            cand["final_score"] = cand.get("combined_score", 0.5)
            cand["rerank_score"] = 0.0  # Keep field for compatibility

        # Take top_k candidates (already sorted by combined_score with domain boost)
        combined_results = candidates[:top_k]

        # [Improvement #2] Guarantee every entity-match candidate survives the top_k cut.
        # Explicitly-named entities from the query are high-value anchors — they must not
        # be dropped by scoring rank if there are many high-scoring vector results.
        entity_match_names_in_results = {
            c.get("original_obj", {}).get("name")
            for c in combined_results
            if c.get("type") == "entity_match"
        }
        for cand in candidates[top_k:]:
            if cand.get("type") == "entity_match":
                node_name = cand.get("original_obj", {}).get("name")
                if node_name and node_name not in entity_match_names_in_results:
                    combined_results.append(cand)
                    entity_match_names_in_results.add(node_name)
                    logger.info(
                        f"  [Priority] Force-included entity match outside top_k: {node_name}"
                    )

        # Add boost details for logging
        for cand in combined_results:
            cand["boosts"] = {
                "source": cand.get("type", "unknown"),
                "domain": cand.get("domain_boost", 1.0),
            }

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
        for i, doc in enumerate(combined_results[:10]):
            name = doc.get("original_obj", {}).get("name", "N/A")
            dtype = doc.get("type", "unknown")
            score = doc.get("combined_score", 0)
            semantic_score = doc.get("semantic_score", 0)
            type_score = doc.get("type_score", 0)
            logger.info(
                f"    {i+1}. [{dtype}] {name} (combined: {score:.2f}, semantic: {semantic_score:.2f}, type: {type_score:.2f})"
            )

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

        # Clean up query embedding reference
        self._current_query_embedding = None

        return combined_results

    async def retrieve_with_self_correction(
        self,
        query: str,
        top_k: int = 20,
        max_hops: int = 10,
        filter_docs: bool = True,
    ) -> List[dict]:
        """
        Agentic retrieval loop with self-correction.

        Each hop:
          1. Runs hybrid_search for the current query / bridge entity.
          2. Merges results (deduplicating by node name).
          3. Asks the LLM whether the accumulated context is sufficient to
             answer *query*, or whether a specific bridge entity is missing.
          4. If missing → targeted search for that entity → repeat.
          5. Returns accumulated results once the LLM says sufficient, or
             after max_hops hops.

        filter_docs: if True (default), applies a single batch LLM call after
          all hops to filter the accumulated docs down to the most relevant
          ones before returning.  O(1) extra LLM call instead of O(n).

        The bridge-entity prompt is intentionally brief (context is truncated
        at ~3000 chars) to avoid slow LLM calls on large context windows.
        """
        from app.services.llm import llm_service

        seen_names: set[str] = set()
        accumulated: List[dict] = []
        searched_for: set[str] = {query.lower()}

        def _merge(new_results: List[dict]) -> None:
            for cand in new_results:
                name = (cand.get("original_obj") or {}).get("name") or cand.get(
                    "name", ""
                )
                if name and name not in seen_names:
                    accumulated.append(cand)
                    seen_names.add(name)

        def _build_context_snippet(results: List[dict], max_chars: int = 3000) -> str:
            lines = []
            total = 0
            for r in results[:20]:
                obj = r.get("original_obj") or {}
                name = obj.get("name") or r.get("name", "?")
                summary = obj.get("summary") or r.get("text", "")
                etype = obj.get("entity_type") or obj.get("type", "")
                line = f"- [{etype}] {name}: {summary}"[:200]
                if total + len(line) > max_chars:
                    break
                lines.append(line)
                total += len(line)
            return "\n".join(lines)

        def _check_sufficiency(context: str) -> tuple[bool, str | None]:
            """
            Ask the LLM whether the context is sufficient to answer *query*.

            Expected reply (strict format):
              SUFFICIENT: yes
              MISSING: <entity or concept name>   ← omit or leave blank if sufficient
            """
            prompt = (
                f"You are an intelligent retrieval assistant.\n\n"
                f"QUESTION: {query}\n\n"
                f"AVAILABLE CONTEXT (knowledge graph excerpts):\n{context}\n\n"
                f"Determine if the context above is sufficient to answer the question.\n"
                f"Reply in EXACTLY this format (two lines only):\n"
                f"SUFFICIENT: yes\n"
                f"or\n"
                f"SUFFICIENT: no\n"
                f"MISSING: <name of one key entity or concept that is absent from the context>\n\n"
                f"Reply:"
            )
            try:
                raw = llm_service.reason(prompt) or ""
            except Exception as e:
                logger.warning(f"  [SelfCorrect] LLM check failed: {e}")
                return True, None  # fail-open: don't loop forever

            sufficient = True
            missing_entity: str | None = None

            for line in raw.splitlines():
                line = line.strip()
                if line.lower().startswith("sufficient:"):
                    val = line.split(":", 1)[1].strip().lower()
                    sufficient = val.startswith("y")
                elif line.lower().startswith("missing:"):
                    missing_entity = line.split(":", 1)[1].strip()
                    if not missing_entity:
                        missing_entity = None

            return sufficient, missing_entity

        # ── Hop 0: initial retrieval ──────────────────────────────────────────
        logger.info(f"  [SelfCorrect] Hop 0 — searching for: '{query}'")
        hop0 = await self.hybrid_search(query, top_k=top_k)
        _merge(hop0)

        for hop in range(1, max_hops + 1):
            context_snippet = _build_context_snippet(accumulated)
            sufficient, missing = _check_sufficiency(context_snippet)

            logger.info(
                f"  [SelfCorrect] Hop {hop} check — sufficient={sufficient}, "
                f"missing='{missing}'"
            )

            if sufficient or not missing:
                break

            if missing.lower() in searched_for:
                logger.info(
                    f"  [SelfCorrect] Already searched for '{missing}', stopping."
                )
                break

            searched_for.add(missing.lower())
            logger.info(f"  [SelfCorrect] Hop {hop} — bridge search for: '{missing}'")
            bridge_results = await self.hybrid_search(missing, top_k=top_k // 2)
            _merge(bridge_results)

        logger.info(
            f"  [SelfCorrect] Done after {hop} hops — "
            f"{len(accumulated)} unique nodes accumulated."
        )
        # Return top_k by combined_score (best score first)
        accumulated.sort(key=lambda c: c.get("combined_score", 0.0), reverse=True)
        candidates = accumulated[:top_k]

        # Batch context filter: single LLM call selects the most relevant docs.
        # Reduces synthesis noise without the O(n) cost of per-doc verification.
        keep_k = max(4, top_k // 2)
        if filter_docs and len(candidates) > keep_k:
            logger.info(
                f"  [SelfCorrect] Filtering {len(candidates)} docs → keep={keep_k}"
            )
            candidates = await llm_service.select_relevant_docs(
                candidates, query, keep=keep_k
            )
            logger.info(
                f"  [SelfCorrect] After filter: {len(candidates)} docs"
            )

        return candidates


retrieval_service = RetrievalService()
