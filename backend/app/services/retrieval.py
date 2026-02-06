import os
import logging
from datetime import datetime
from typing import List
from app.core.config import settings
from app.core.logging_config import get_component_logger
from app.services.graph import graph_service

# Suppress noisy tokenizer warnings
logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)

logger = get_component_logger("RetrievalService")

# Create a dedicated retrieval debug logger that writes full details to file
retrieval_debug_logger = logging.getLogger("retrieval_debug")
retrieval_debug_logger.setLevel(logging.DEBUG)
# Only add handler if not already present
if not retrieval_debug_logger.handlers:
    # Create logs directory if needed
    logs_dir = os.path.join(os.path.dirname(__file__), "../../logs")
    os.makedirs(logs_dir, exist_ok=True)
    # File handler for detailed retrieval logs
    retrieval_log_path = os.path.join(logs_dir, "retrieval_debug.log")
    file_handler = logging.FileHandler(retrieval_log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    retrieval_debug_logger.addHandler(file_handler)
    logger.info(f"Retrieval debug logging enabled: {retrieval_log_path}")

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
        # No reranker needed - using pure symbolic ranking for GraphRAG
        logger.info("RetrievalService initialized (symbolic ranking mode)")

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
        retrieval_debug_logger.debug("=" * 100)
        retrieval_debug_logger.debug(f"RETRIEVAL SESSION: {datetime.now().isoformat()}")
        retrieval_debug_logger.debug(f"QUERY: {query}")
        retrieval_debug_logger.debug(f"EXTRACTED ENTITIES: {query_entities}")
        retrieval_debug_logger.debug(f"EXTRACTED CONCEPTS: {query_concepts}")
        retrieval_debug_logger.debug("=" * 100)

        for i, doc in enumerate(results):
            retrieval_debug_logger.debug(f"\n--- RESULT {i+1} ---")
            retrieval_debug_logger.debug(f"TYPE: {doc.get('type', 'unknown')}")
            retrieval_debug_logger.debug(f"SCORE: {doc.get('final_score', 0):.2f}")
            retrieval_debug_logger.debug(f"BOOSTS: {doc.get('boosts', {})}")
            retrieval_debug_logger.debug(
                f"SYMBOLIC IMMUNE: {doc.get('symbolic_immune', False)}"
            )

            # Get node details from original object
            original = doc.get("original_obj", {})
            if original:
                retrieval_debug_logger.debug(
                    f"NODE NAME: {original.get('name', 'N/A')}"
                )
                retrieval_debug_logger.debug(
                    f"NODE LABELS: {original.get('labels', [])}"
                )
                retrieval_debug_logger.debug(
                    f"NODE TYPE: {original.get('type', 'N/A')}"
                )

                # Full summary - not truncated!
                summary = original.get("summary") or original.get("description", "")
                retrieval_debug_logger.debug(f"FULL SUMMARY ({len(summary)} chars):")
                retrieval_debug_logger.debug(summary if summary else "(empty)")

                # Isolated context if available
                isolated = original.get("isolated_context", "")
                if isolated:
                    retrieval_debug_logger.debug(
                        f"ISOLATED CONTEXT ({len(isolated)} chars):"
                    )
                    retrieval_debug_logger.debug(isolated)

            # Linked notes
            linked_notes = doc.get("linked_notes", [])
            if linked_notes:
                retrieval_debug_logger.debug(f"LINKED NOTES ({len(linked_notes)}):")
                for note in linked_notes[:3]:
                    retrieval_debug_logger.debug(
                        f"  - {note.get('title', 'Untitled')} ({note.get('id', 'N/A')})"
                    )

            # Full text sent to LLM
            retrieval_debug_logger.debug(
                f"TEXT SENT TO LLM ({len(doc.get('text', ''))} chars):"
            )
            retrieval_debug_logger.debug(
                doc.get("text", "")[:1000] + "..."
                if len(doc.get("text", "")) > 1000
                else doc.get("text", "")
            )

        retrieval_debug_logger.debug("\n" + "=" * 100 + "\n")

    def _chunk_text(
        self, text: str, chunk_size: int = 400, overlap: int = 100
    ) -> List[str]:
        """
        Split text into overlapping chunks for granular retrieval.
        Using character-based windowing for simplicity.
        """
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i : i + chunk_size]
            if len(chunk) > 50:  # Ignore tiny scraps
                chunks.append(chunk)
            if i + chunk_size >= len(text):
                break
        return chunks

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
        import time
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
        is_temporal_query = query_analysis.get(
            "is_temporal", False
        ) or self._is_temporal_query(query)

        # ============ ENTITY EXTRACTION ============
        # Extract named entities from query using the same logic as ingestion
        # This ensures we can find explicitly named entities like "Albert Einstein"
        llm_entities = query_analysis.get("entities", [])

        # Also extract proper names using Title Case pattern detection
        proper_names = self._extract_proper_names(query)

        # Filter out stopwords and short entities
        def is_valid_entity(e: str) -> bool:
            e_lower = e.lower().strip()
            return len(e_lower) >= 2 and e_lower not in ENTITY_STOPWORDS

        llm_entities = [e for e in llm_entities if is_valid_entity(e)]

        # Merge proper names with LLM entities (proper names may catch multi-word names LLM splits)
        query_entities = list(set(llm_entities))
        for pn in proper_names:
            if pn.lower() not in [e.lower() for e in query_entities]:
                query_entities.append(pn)

        logger.info(
            f"  [LLM Analysis] Intent: {query_analysis.get('intent')}, "
            f"Temporal: {is_temporal_query}, "
            f"Entities: {query_entities}, "
            f"Expected Types: {expected_entity_types}, "
            f"Attribute: {question_attribute}"
        )

        # Generate query embedding for vector search
        full_vector = embedding_service.embed_query(query)
        t_embedding = time.perf_counter() - t_phase_start
        logger.info(f"  [⏱️ Timing] Query embedding: {t_embedding:.2f}s")

        # ============ HYBRID RETRIEVAL ============
        # Combines entity name matching (for explicit mentions) with vector search
        # (for semantic similarity). This ensures we find both "Albert Einstein"
        # AND "Marie Curie" in comparison questions.

        t_phase_start = time.perf_counter()
        entity_nodes = []  # Found by name matching
        vector_nodes = []  # Found by vector search
        neighbor_nodes = []  # Found by neighbor expansion
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
                for node in entity_found[:5]:  # Top 5 to avoid explosion
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
                            for v in variants[:3]:  # Top 3 variants per name
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
            vector_results = graph_service.search_knowledge_graph(
                full_vector, top_k=20, min_score=0.60  # Wider net for vector search
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
                        for v in variants[:2]:  # Top 2 variants per name
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

        # STEP 3: NEIGHBOR EXPANSION - Get 1-hop neighbors of top results
        # Expand from both entity matches and vector matches
        # This finds related context (e.g., "Albert Einstein" → "Princeton")
        all_primary_nodes = entity_nodes + vector_nodes
        if all_primary_nodes:
            t_expand_start = time.perf_counter()
            for node in all_primary_nodes[:15]:  # Top 15 primary results
                try:
                    label = (
                        node.get("labels", ["Entity"])[0]
                        if isinstance(node.get("labels"), list)
                        else "Entity"
                    )
                    neighbors = graph_service.get_related_nodes(
                        node_name=node["name"],
                        node_label=label,
                        max_depth=1,  # Only 1-hop neighbors
                        min_confidence=0.5,
                    )
                    # Filter duplicates and add
                    for neighbor in neighbors[:3]:  # Top 3 neighbors per node
                        if neighbor["name"] not in node_names_found:
                            neighbor["_source"] = "neighbor"
                            neighbor["_expanded_from"] = node["name"]
                            neighbor_nodes.append(neighbor)
                            node_names_found.add(neighbor["name"])
                except Exception as e:
                    logger.debug(f"  [Neighbor] Failed to expand {node['name']}: {e}")

            if neighbor_nodes:
                logger.info(
                    f"  [Neighbor] Expanded to {len(neighbor_nodes)} 1-hop neighbors: "
                    f"{[n['name'] for n in neighbor_nodes[:10]]}"
                )
            t_expand = time.perf_counter() - t_expand_start
            logger.info(f"  [⏱️ Timing] Neighbor expansion: {t_expand:.2f}s")

        # Combine all found nodes
        all_found_nodes = entity_nodes + vector_nodes + neighbor_nodes
        all_node_names = [n["name"] for n in all_found_nodes]

        # STEP 4: Community summaries for broad queries
        # If query is exploratory ("what have I learned", "what's happening with X")
        # fetch relevant community summaries for high-level context
        community_summaries = []
        broad_query_keywords = [
            "what have",
            "tell me about",
            "summarize",
            "overview",
            "lately",
            "recently",
            "all about",
        ]
        is_broad_query = any(kw in query.lower() for kw in broad_query_keywords)
        exploratory_keywords = ["how", "why", "connected", "related", "relationship"]
        is_exploratory = any(kw in query.lower() for kw in exploratory_keywords)

        if is_broad_query or is_exploratory:
            try:
                # For broad queries, get top communities
                community_summaries = graph_service.get_all_communities()[:5]  # Top 5

                if community_summaries:
                    logger.info(
                        f"  [Vector] Found {len(community_summaries)} relevant communities"
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
            f"({len(entity_nodes)} entity + {len(vector_nodes)} vector + {len(neighbor_nodes)} neighbor nodes)"
        )

        # ============ PREPARE CANDIDATES (NODE SUMMARIES FIRST) ============
        # Node summaries are PRIMARY evidence - they contain distilled, isolated knowledge
        # Label as "Consensus" to help LLM recognize these as Distilled Wisdom
        candidates = []

        # A. Entity Nodes (highest priority - direct name matches from query)
        for node in entity_nodes:
            summary = node.get("summary") or node.get("description", "")
            if not summary:
                continue  # Skip nodes without summaries

            label = (
                node.get("labels", ["Entity"])[0]
                if isinstance(node.get("labels"), list)
                else "Entity"
            )
            # Use [Consensus: Name] to signal this is distilled knowledge
            text = f"[Consensus - {label}: {node['name']}]: {summary}"

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
            summary = node.get("summary") or node.get("description", "")
            if not summary:
                continue  # Skip nodes without summaries

            label = (
                node.get("labels", ["Entity"])[0]
                if isinstance(node.get("labels"), list)
                else "Entity"
            )
            vector_score = node.get("score", 0.0)
            # Use [Consensus: Name] to signal this is distilled knowledge, not a raw note
            text = f"[Consensus - {label}: {node['name']}] (similarity: {vector_score:.2f}): {summary}"

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

        # C. Neighbor Nodes (1-hop expansion from entity/vector results)
        for node in neighbor_nodes:
            summary = node.get("summary") or node.get("description", "")
            if not summary:
                continue

            label = node.get("label", "Entity")
            expanded_from = node.get("_expanded_from", "")
            rel_path = " → ".join(node.get("relationship_path", []))

            # Include relationship context if available (the "Why" behind the link)
            context_path = node.get("context_path", [])
            rel_context = ""
            if context_path:
                # Filter out None values and join
                contexts = [c for c in context_path if c]
                if contexts:
                    rel_context = f" Context: {'; '.join(contexts[:2])}"

            if expanded_from:
                text = f"[Neighbor - {label}: {node['name']}] (expanded from {expanded_from}): {summary}"
            else:
                text = f"[Neighbor - {label}: {node['name']}] (via {rel_path}){rel_context}: {summary}"

            # Attach linked notes for reference traceability (case-insensitive lookup)
            linked_notes = node_to_notes.get(node["name"].lower(), [])

            candidates.append(
                {
                    "text": text,
                    "type": "neighbor_node",
                    "original_obj": node,
                    "is_recent": False,
                    "priority": "secondary",  # Neighbor expansion
                    "relationship_path": node.get("relationship_path", []),
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

            themes_str = f" Themes: {', '.join(themes[:3])}" if themes else ""
            text = f"[Community - {domain}: {name}] ({member_count} members){themes_str}: {summary}"

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
            f"({len(entity_nodes)} entity + {len(vector_nodes)} vector + {len(neighbor_nodes)} neighbor + {len(community_summaries)} community)"
        )

        # ============ RANKING ============
        if not candidates:
            logger.warning("  [Retrieval] No candidates found")
            return []

        t_ranking_start = time.perf_counter()

        # ============ ENTITY TYPE SCORING ============
        # If we know the expected entity types (e.g., "Person" for nationality questions),
        # boost candidates that match and penalize those that don't
        def get_type_score(candidate) -> float:
            """Score based on entity type match. 1.0 = match, 0.5 = unknown, 0.0 = mismatch"""
            if not expected_entity_types:
                return 0.5  # No type filtering

            node = candidate.get("original_obj", {})
            entity_type = node.get("entity_type", None)

            if not entity_type:
                return 0.3  # Unknown type - slight penalty

            # Normalize types for comparison
            entity_type_lower = entity_type.lower()
            expected_lower = [t.lower() for t in expected_entity_types]

            # Direct match
            if entity_type_lower in expected_lower:
                return 1.0

            # Handle synonyms (e.g., "Film" == "Movie")
            type_synonyms = {
                "film": ["movie", "cinema"],
                "movie": ["film", "cinema"],
                "person": ["actor", "director", "writer", "musician", "artist"],
                "venue": ["arena", "stadium", "theater", "place"],
                "place": ["venue", "location", "city", "country"],
                "organization": ["company", "corporation", "institution"],
            }

            for exp_type in expected_lower:
                synonyms = type_synonyms.get(exp_type, [])
                if entity_type_lower in synonyms or exp_type in type_synonyms.get(
                    entity_type_lower, []
                ):
                    return 0.9  # Synonym match

            return 0.1  # Type mismatch

        def get_attribute_relevance(candidate, query_vector: list[float]) -> float:
            """
            Score based on semantic similarity between the candidate's summary
            and the query. Uses embedding-based cosine similarity for general-purpose
            attribute relevance without hardcoded keywords.
            """
            node = candidate.get("original_obj", {})
            summary = node.get("summary") or node.get("description") or ""

            if not summary or len(summary.strip()) < 10:
                return 0.3  # No meaningful content

            # Use the vector_score if already computed from Neo4j vector search
            # This is the cosine similarity between query and node's stored embedding
            existing_score = candidate.get("vector_score", 0.0)
            if existing_score > 0:
                return existing_score

            # Fallback: compute similarity if not available
            # This handles entity_match candidates that don't have vector scores
            try:
                summary_vector = embedding_service.embed_query(
                    summary[:500]
                )  # Limit for performance
                # Cosine similarity
                dot_product = sum(a * b for a, b in zip(query_vector, summary_vector))
                norm_q = sum(a * a for a in query_vector) ** 0.5
                norm_s = sum(a * a for a in summary_vector) ** 0.5
                if norm_q > 0 and norm_s > 0:
                    return dot_product / (norm_q * norm_s)
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

            # Combined score: semantic similarity is primary, type match is secondary
            # Weights: semantic (50%), type (30%), source priority (20% via sort)
            # Vector score is already factored into semantic_score
            cand["combined_score"] = (
                cand["semantic_score"] * 0.5
                + cand["type_score"] * 0.3
                + cand["vector_score"] * 0.2  # Direct vector score contribution
            )

        # Sort by combined score, then by priority
        def sort_key(c):
            priority_order = {"primary": 0, "secondary": 1, "tertiary": 2}
            priority_score = priority_order.get(c.get("priority", "tertiary"), 2)
            combined_score = c.get("combined_score", 0.5)
            # Lower is better: -combined_score puts high matches first
            return (-combined_score, priority_score)

        candidates.sort(key=sort_key)

        # Log type filtering if active
        if expected_entity_types:
            logger.info(
                f"  [Type Filter] Expected types: {expected_entity_types}, "
                f"Attribute: {question_attribute}"
            )
            # Log top matches with their type scores
            for cand in candidates[:5]:
                node = cand.get("original_obj", {})
                logger.debug(
                    f"    - {node.get('name', 'N/A')} | "
                    f"Type: {node.get('entity_type', 'N/A')} | "
                    f"Score: {cand.get('type_score', 0):.2f}"
                )

        # Take top_k candidates
        combined_results = candidates[:top_k]

        # Add simple scores for logging
        for cand in combined_results:
            cand["final_score"] = cand.get("combined_score", 0.5)
            cand["rerank_score"] = 0.0
            cand["boosts"] = {"source": cand.get("type", "unknown")}

        t_ranking = time.perf_counter() - t_ranking_start
        logger.info(f"  [⏱️ Timing] Ranking: {t_ranking:.4f}s")

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
        return combined_results

    def _calculate_keyword_boost(self, query: str, text: str) -> float:
        """
        Calculate keyword match boost for exact/close matches.
        Returns 3.0x boost if exact query terms appear in text.
        Handles case-insensitive matching and word variations.
        """
        import re

        # Normalize both query and text
        query_lower = query.lower()
        text_lower = text.lower()

        # Remove common stopwords from query to focus on meaningful terms
        stopwords = {
            "what",
            "how",
            "where",
            "when",
            "why",
            "who",
            "which",
            "is",
            "are",
            "the",
            "and",
            "or",
            "my",
            "your",
            "their",
            "a",
            "an",
            "in",
            "on",
            "at",
        }

        # Extract meaningful words from query (3+ chars, not stopwords)
        query_words = [w.strip(".,!?;:\"'") for w in query_lower.split()]
        meaningful_words = [
            w for w in query_words if len(w) >= 3 and w not in stopwords
        ]

        if not meaningful_words:
            return 1.0

        # Count how many meaningful query words appear in text
        matches = 0
        for word in meaningful_words:
            # Use word boundary regex for better matching
            pattern = rf"\b{re.escape(word)}"
            if re.search(pattern, text_lower):
                matches += 1

        # Calculate boost based on match ratio
        match_ratio = matches / len(meaningful_words)

        # 3.0x boost if 80%+ of query terms match
        if match_ratio >= 0.8:
            return 3.0
        # 2.0x boost if 50%+ match
        elif match_ratio >= 0.5:
            return 2.0
        # 1.5x boost if 30%+ match
        elif match_ratio >= 0.3:
            return 1.5
        else:
            return 1.0

    def _is_temporal_query(self, query: str) -> bool:
        """
        Detect if query is explicitly asking for recent/latest/newest notes.
        Only returns True for queries that clearly want temporal priority.
        """
        query_lower = query.lower()
        temporal_keywords = [
            "recent",
            "latest",
            "newest",
            "last",
            "new",
            "today",
            "yesterday",
            "this week",
            "this month",
            "lately",
            "currently",
        ]
        # Must contain temporal keyword AND not be asking about specific entities
        has_temporal_keyword = any(kw in query_lower for kw in temporal_keywords)

        # Don't treat as temporal if asking about specific work/projects
        entity_indicators = ["at", "with", "about", "regarding", "concerning"]
        has_entity_focus = any(ind in query_lower for ind in entity_indicators)

        # Temporal query = has temporal keyword AND either no entity focus OR explicitly asks "what are my recent..."
        if has_temporal_keyword:
            if "what are my recent" in query_lower or "what have i" in query_lower:
                return True
            if not has_entity_focus:
                return True

        return False

    def _extract_proper_names(self, query: str) -> List[str]:
        """
        Extract proper names from query by finding consecutive Title Case words.
        This catches multi-word names like "Albert Einstein", "New York City", "The Great Gatsby".

        Returns list of proper names found in query.
        """
        import re

        proper_names = []

        # Clean query - remove punctuation except apostrophes within words
        clean_query = re.sub(r"[^\w\s\'-]", " ", query)
        words = clean_query.split()

        # Skip these words when they appear between capitalized words
        # (e.g., "Lord of the Rings" - "of" and "the" connect title case words)
        connectors = {"and", "of", "the", "in", "for", "on", "at", "to", "vs", "or"}

        # Common question starters to skip at position 0
        question_starters = {
            "what",
            "where",
            "when",
            "who",
            "which",
            "how",
            "why",
            "is",
            "are",
            "was",
            "were",
            "do",
            "does",
            "did",
            "can",
            "could",
        }

        i = 0
        while i < len(words):
            word = words[i]
            # Strip quotes from word
            clean_word = word.strip("\"'")

            # Skip question starters at beginning
            if i == 0 and clean_word.lower() in question_starters:
                i += 1
                continue

            # Check if this word starts a proper name (Title Case)
            if clean_word and clean_word[0].isupper() and len(clean_word) >= 2:
                # Start collecting a potential multi-word name
                name_parts = [clean_word]
                j = i + 1

                while j < len(words):
                    next_word = words[j].strip("\"'")
                    next_lower = next_word.lower()

                    # If it's a connector, peek ahead to see if another Title Case word follows
                    if next_lower in connectors and j + 1 < len(words):
                        peek_word = words[j + 1].strip("\"'")
                        if peek_word and peek_word[0].isupper():
                            name_parts.append(next_word)
                            j += 1
                            continue

                    # If it's another Title Case word, add it
                    if next_word and next_word[0].isupper() and len(next_word) >= 2:
                        name_parts.append(next_word)
                        j += 1
                    else:
                        break

                # Only keep if it's a multi-word name (single words handled elsewhere)
                if len(name_parts) >= 2:
                    full_name = " ".join(name_parts)
                    proper_names.append(full_name)

                i = j
            else:
                i += 1

        return proper_names

    def _extract_query_entities(self, query: str) -> List[str]:
        """
        Extract potential entity names from query for entity-match boosting.
        Improved heuristic with case-insensitive matching and variation handling.
        """
        import re

        entities = []

        # Extract quoted terms
        quoted = re.findall(r'["\']([^"\'\n]+)["\']', query)
        entities.extend(quoted)

        # Extract capitalized words (likely proper nouns)
        # But exclude common words at sentence start
        words = query.split()
        common_starts = {
            "what",
            "how",
            "where",
            "when",
            "why",
            "who",
            "which",
            "is",
            "are",
            "can",
            "do",
            "does",
        }

        for i, word in enumerate(words):
            # Remove punctuation for checking
            clean_word = re.sub(r"[^a-zA-Z0-9]", "", word)
            if clean_word and clean_word[0].isupper():
                # Skip if it's the first word and a common question starter
                if i == 0 and clean_word.lower() in common_starts:
                    continue
                entities.append(clean_word)

        # Also look for words after "at", "with", "about" as they're likely entities
        entity_markers = [
            "at",
            "with",
            "about",
            "for",
            "regarding",
            "concerning",
            "working",
        ]
        for marker in entity_markers:
            pattern = rf"\b{marker}\s+(\w+)"
            matches = re.findall(pattern, query, re.IGNORECASE)
            entities.extend([m for m in matches if len(m) > 2])

        # Remove duplicates and common words
        stopwords = {
            "the",
            "and",
            "or",
            "but",
            "my",
            "your",
            "their",
            "this",
            "that",
            "these",
            "those",
            "work",
            "job",
        }
        entities = list(set([e for e in entities if e.lower() not in stopwords]))

        # Normalize to lowercase for case-insensitive matching later
        # Store both original and lowercase versions to handle variations
        normalized_entities = []
        for e in entities:
            normalized_entities.append(e.lower())

        return normalized_entities

    def _apply_diversity_constraint(
        self, results: List[dict], max_per_note: int = 3
    ) -> List[dict]:
        """
        DEPRECATED: No longer used in Graph-First retrieval.

        Graph-First retrieval returns node summaries, not note snippets,
        so per-note diversity is no longer relevant.
        """
        return results

    def _expand_candidates_with_relationships(
        self, candidates: List[dict], max_related: int = 3, min_confidence: float = 0.7
    ) -> List[dict]:
        """
        DEPRECATED: Relationship expansion now happens inline in hybrid_search().

        Related nodes are fetched via graph traversal in the main search flow,
        not as a post-processing step. This method is kept for backward compatibility.
        """
        return candidates  # No-op

    def enrich_with_relationships(
        self, results: List[dict], max_related: int = 3, min_confidence: float = 0.7
    ) -> List[dict]:
        """
        DEPRECATED: Relationship enrichment now happens inline in hybrid_search().

        This method is kept for backward compatibility but just returns results unchanged.
        """
        return results

    def _detect_query_domain(self, query: str) -> str:
        """
        Heuristic to detect if query is Academic, Personal, Professional, or Creative.

        Academic: mentions concepts, learning, papers, theorems, courses
        Personal: mentions feelings, daily life, relationships, goals
        Professional: mentions work, projects, meetings, career
        Creative: mentions poems, lyrics, metaphors, creative writing
        """
        query_lower = query.lower()

        # Academic keywords
        academic_keywords = [
            "learn",
            "study",
            "concept",
            "theorem",
            "paper",
            "book",
            "course",
            "lecture",
            "understand",
            "explain",
            "theory",
            "research",
            "academic",
            "mathematics",
            "science",
            "proof",
            "definition",
            "algorithm",
        ]

        # Personal keywords
        personal_keywords = [
            "feel",
            "feeling",
            "emotion",
            "happy",
            "sad",
            "anxious",
            "worried",
            "relationship",
            "friend",
            "family",
            "daily",
            "today",
            "yesterday",
            "personal",
            "goal",
            "dream",
            "hope",
            "fear",
            "love",
            "hate",
        ]

        # Professional keywords
        professional_keywords = [
            "work",
            "project",
            "meeting",
            "career",
            "job",
            "task",
            "deadline",
            "professional",
            "team",
            "client",
            "manager",
            "office",
            "business",
        ]

        # Creative keywords
        creative_keywords = [
            "poem",
            "poetry",
            "verse",
            "lyric",
            "lyrics",
            "song",
            "metaphor",
            "stanza",
            "rhyme",
            "creative",
            "fiction",
            "story",
            "prose",
            "writing",
        ]

        # Dreams keywords
        dreams_keywords = [
            "dream",
            "dreamt",
            "dreamed",
            "nightmare",
            "subconscious",
            "recurring",
            "symbol",
            "sleep",
            "woke",
            "vision",
        ]

        academic_score = sum(1 for kw in academic_keywords if kw in query_lower)
        personal_score = sum(1 for kw in personal_keywords if kw in query_lower)
        professional_score = sum(1 for kw in professional_keywords if kw in query_lower)
        creative_score = sum(1 for kw in creative_keywords if kw in query_lower)
        dreams_score = sum(1 for kw in dreams_keywords if kw in query_lower)

        # Return domain with highest score, default to Personal
        max_score = max(
            academic_score,
            personal_score,
            professional_score,
            creative_score,
            dreams_score,
        )
        if max_score == 0:
            return "Personal"  # Default

        if academic_score == max_score:
            return "Academic"
        elif professional_score == max_score:
            return "Professional"
        elif creative_score == max_score:
            return "Creative"
        elif dreams_score == max_score:
            return "Dreams"
        else:
            return "Personal"

    async def _temporal_search(self, query: str, top_k: int = 50) -> List[str]:
        """
        Retrieve notes based on timestamp (most recent first).
        Used for queries like "what's my latest note?" or "most recent entry".

        Singular queries ("most recent note", "last note") return exactly 1 note.
        Plural queries ("recent notes", "latest entries") return top_k notes.
        """
        import time
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import select

        logger.info(f"  [Retrieval] Temporal Search for: '{query}'")
        t_start = time.perf_counter()

        # Stricter limit for singular "most recent note" queries
        query_lower = query.lower()
        singular_keywords = [
            "most recent note",
            "last note",
            "latest note",
            "newest note",
            "my most recent",
            "my last note",
        ]
        if any(kw in query_lower for kw in singular_keywords):
            logger.info(
                "  [Retrieval] Detected SINGULAR temporal query - limiting to 1 note"
            )
            top_k = 1

        # Get recent notes from Neo4j (has timestamps)
        recent_notes = graph_service.get_recent_notes(limit=top_k)
        t_graph = time.perf_counter()
        logger.info(
            f"  [Retrieval] Neo4j Temporal Query took: {t_graph - t_start:.4f}s (Hits: {len(recent_notes)})"
        )

        if not recent_notes:
            return []

        # Fetch full content from Postgres
        note_ids = [note["id"] for note in recent_notes]
        async with AsyncSessionLocal() as session:
            stmt = select(Note.id, Note.content, Note.title).where(
                Note.id.in_(note_ids)
            )
            result = await session.execute(stmt)
            rows = result.all()
            content_map = {row.id: row.content for row in rows}
            title_map = {row.id: (row.title or "Untitled Note") for row in rows}

        t_pg = time.perf_counter()
        logger.info(f"  [Retrieval] Postgres Fetch took: {t_pg - t_graph:.4f}s")

        # Build context snippets in chronological order (newest first)
        snippets = []
        for note in recent_notes:
            nid = note["id"]
            content = content_map.get(nid, "")
            title = title_map.get(nid, "Untitled Note")
            domain = note.get("domain", "Personal")
            created_at = note.get("created_at", "Unknown")

            if content:
                snippets.append(
                    {
                        "text": f"[Note: {title}] (Created: {created_at}, Domain: {domain})\n{content}",
                        "content": content,
                        "type": "note",
                        "note_id": nid,
                        "title": title,
                        "domain": domain,
                    }
                )

        logger.info(
            f"  [Retrieval] Total Temporal Search took: {time.perf_counter() - t_start:.4f}s"
        )
        return snippets


retrieval_service = RetrievalService()
