import os
import logging
from typing import List
from app.core.config import settings
from app.core.logging_config import get_component_logger
from app.services.graph import graph_service

# Suppress noisy tokenizer warnings
logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)

logger = get_component_logger("RetrievalService")

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
        Graph-First Retrieval Pipeline (True GraphRAG):

        The knowledge graph IS the primary source of truth. Node summaries contain
        isolated, deduplicated knowledge about each entity. Notes are only used
        for grounding when specific evidence is needed.

        Flow:
        1. Query Analysis: Extract entities/concepts via LLM
        2. Graph Entry: Find matching nodes by name (not vectors!)
        3. Primary Evidence: Node summaries (isolated context)
        4. Expansion: Related nodes + their summaries via graph traversal
        5. Multi-Hop: Paths connecting query entities (if multiple mentioned)
        6. Fallback: Vector search only if entity lookup fails
        7. Grounding: Minimal note content only if needed for specific quotes

        Returns node summaries as primary evidence, not chunked note snippets.
        """
        import time
        from app.services.embedding import embedding_service
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import select

        logger.info(f"  [Retrieval] Graph-First Search for: '{query}'")
        t_start = time.perf_counter()
        t_phase_start = time.perf_counter()

        # Query Analysis with LLM structured outputs
        from app.services.llm import llm_service

        query_analysis = llm_service.analyze_query(query)

        # Use LLM analysis as primary source, with heuristic fallback
        is_temporal_query = query_analysis.get(
            "is_temporal", False
        ) or self._is_temporal_query(query)

        # Combine entities from LLM with heuristic extraction for comprehensive coverage
        llm_entities = query_analysis.get("entities", [])
        llm_concepts = query_analysis.get("concepts", [])
        heuristic_entities = self._extract_query_entities(query)

        # Filter out stopwords and short entities to prevent garbage matches
        # e.g., "i", "does", "the" were causing 2x boosts on everything
        def is_valid_entity(e: str) -> bool:
            e_lower = e.lower().strip()
            return len(e_lower) >= 2 and e_lower not in ENTITY_STOPWORDS

        llm_entities = [e for e in llm_entities if is_valid_entity(e)]
        heuristic_entities = [e for e in heuristic_entities if is_valid_entity(e)]

        # Merge all entities and concepts (LLM entities take priority, add unique heuristic ones)
        query_entities = llm_entities + [
            e for e in heuristic_entities if e not in llm_entities
        ]
        query_concepts = llm_concepts

        logger.info(
            f"  [LLM Analysis] Intent: {query_analysis.get('intent')}, "
            f"Temporal: {is_temporal_query}, "
            f"Entities: {query_entities}, "
            f"Concepts: {query_concepts}"
        )

        # Generate query embedding
        full_vector = embedding_service.embed_query(query)
        t_embedding = time.perf_counter() - t_phase_start
        logger.info(f"  [⏱️ Timing] Query embedding: {t_embedding:.2f}s")

        # ============ ADAPTIVE GRAPH DEPTH ============
        # Determine traversal depth based on query characteristics
        query_intent = query_analysis.get("intent", "search")

        # Base depth on query complexity and intent
        # - More entities = need deeper paths to connect them
        # - Exploratory queries ("how", "why", "connected") = deeper exploration
        # - Specific queries ("what is", "list") = shallower, more focused
        exploratory_keywords = [
            "how",
            "why",
            "connected",
            "related",
            "relationship",
            "evolved",
            "changed",
        ]
        is_exploratory = any(kw in query.lower() for kw in exploratory_keywords)

        if len(query_entities) >= 3 or is_exploratory:
            multi_hop_depth = 4  # Deep exploration for complex queries
            expansion_depth = 2  # 2-hop neighbors
        elif len(query_entities) >= 2:
            multi_hop_depth = 3  # Standard multi-entity query
            expansion_depth = 2
        else:
            multi_hop_depth = 2  # Simple query
            expansion_depth = 1  # Just immediate neighbors

        logger.info(
            f"  [Adaptive Depth] Exploratory: {is_exploratory}, "
            f"Multi-hop: {multi_hop_depth}, Expansion: {expansion_depth}"
        )

        # ============ MULTI-HOP REASONING ============
        # If query mentions multiple entities, find paths connecting them in the graph
        multi_hop_paths = []
        multi_hop_note_ids = set()
        if len(query_entities) >= 2:
            t_multihop_start = time.perf_counter()
            try:
                # Find paths between query entities
                multi_hop_paths = graph_service.find_paths_between_nodes(
                    node_names=query_entities,
                    max_depth=multi_hop_depth,  # Adaptive based on query complexity
                    min_confidence=0.5,
                )
                if multi_hop_paths:
                    logger.info(
                        f"  [Multi-Hop] Found {len(multi_hop_paths)} paths connecting {query_entities}"
                    )
                    # Get notes linked to nodes along these paths
                    path_node_names = set()
                    for path in multi_hop_paths:
                        path_node_names.update(path.get("path_nodes", []))
                    if path_node_names:
                        path_evidence = graph_service.get_linked_evidence(
                            list(path_node_names), limit_per_node=2
                        )
                        for row in path_evidence:
                            for note in row.get("evidence", []):
                                multi_hop_note_ids.add(note["id"])
                        logger.info(
                            f"  [Multi-Hop] Found {len(multi_hop_note_ids)} notes from path nodes"
                        )
            except Exception as e:
                logger.warning(f"  [Multi-Hop] Path finding failed: {e}")
            t_multihop = time.perf_counter() - t_multihop_start
            logger.info(f"  [⏱️ Timing] Multi-hop reasoning: {t_multihop:.2f}s")

        # ============ FETCH CANDIDATES ============
        t_phase_start = time.perf_counter()

        # ============ GRAPH-FIRST RETRIEVAL ============
        # The knowledge graph IS the primary source. Node summaries contain isolated,
        # deduplicated knowledge. We enter via entity names, not vectors.

        graph_nodes = []
        entity_found_nodes = []
        related_nodes = []

        # STEP 1: Look up query entities BY NAME (true GraphRAG entry point)
        if query_entities:
            entity_found_nodes = graph_service.find_nodes_by_name(
                names=query_entities, fuzzy=True
            )
            if entity_found_nodes:
                logger.info(
                    f"  [GraphRAG] Found {len(entity_found_nodes)} nodes by entity name: "
                    f"{[n['name'] for n in entity_found_nodes[:5]]}"
                )
                graph_nodes.extend(entity_found_nodes)

        # STEP 2: Get related nodes via graph traversal (neighbors, not vectors)
        node_names_found = {n["name"] for n in graph_nodes}
        if graph_nodes:
            for node in graph_nodes[:10]:  # Limit to top 10 to avoid explosion
                try:
                    neighbors = graph_service.get_related_nodes(
                        node_name=node["name"],
                        node_label=node.get("labels", ["Entity"])[0],
                        max_depth=expansion_depth,
                        min_confidence=0.6,
                    )
                    # Filter duplicates and add
                    for neighbor in neighbors[:5]:  # Top 5 per node
                        if neighbor["name"] not in node_names_found:
                            related_nodes.append(neighbor)
                            node_names_found.add(neighbor["name"])
                except Exception:
                    pass

            if related_nodes:
                logger.info(
                    f"  [GraphRAG] Expanded to {len(related_nodes)} related nodes via traversal"
                )

        # STEP 3: Vector fallback ONLY if entity lookup found nothing
        vector_fallback_nodes = []
        if not graph_nodes:
            logger.info(
                "  [Fallback] No entities found by name, using vector search..."
            )
            vector_fallback_nodes = graph_service.search_knowledge_graph(
                full_vector, top_k=20, min_score=0.6
            )
            graph_nodes.extend(vector_fallback_nodes)

        all_node_names = [n["name"] for n in graph_nodes + related_nodes]

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

        if is_broad_query or is_exploratory:
            try:
                # Get communities that contain our query entities
                if query_entities:
                    community_summaries = graph_service.get_communities_for_query(
                        query_entities
                    )
                else:
                    # For very broad queries, get all communities
                    community_summaries = graph_service.get_all_communities()[
                        :5
                    ]  # Top 5

                if community_summaries:
                    logger.info(
                        f"  [GraphRAG] Found {len(community_summaries)} relevant communities"
                    )
            except Exception as e:
                logger.debug(f"  [Community] Failed to fetch communities: {e}")

        # STEP 5: Minimal note grounding (only fetch for linked evidence, not chunking)
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
                f"  [GraphRAG] Found {len(grounding_note_ids)} grounding notes (for source links)"
            )
            # Debug: log the node→notes mapping
            logger.debug(
                f"  [GraphRAG] node_to_notes keys: {list(node_to_notes.keys())}"
            )

        t_candidates = time.perf_counter() - t_phase_start
        logger.info(
            f"  [⏱️ Timing] Graph lookup: {t_candidates:.2f}s "
            f"({len(graph_nodes)} primary + {len(related_nodes)} related nodes)"
        )

        # ============ PREPARE CANDIDATES (NODE SUMMARIES FIRST) ============
        # Node summaries are PRIMARY evidence - they contain distilled, isolated knowledge
        # Label as "Consensus" to help LLM recognize these as Distilled Wisdom
        candidates = []

        # A. Primary Graph Nodes (direct entity matches)
        node_names_for_lookup = [
            node["name"]
            for node in graph_nodes
            if node.get("summary") or node.get("description")
        ]
        logger.debug(f"  [GraphRAG] Looking up nodes: {node_names_for_lookup}")

        for node in graph_nodes:
            summary = node.get("summary") or node.get("description", "")
            if not summary:
                continue  # Skip nodes without summaries

            label = (
                node.get("labels", ["Entity"])[0]
                if isinstance(node.get("labels"), list)
                else "Entity"
            )
            # Use [Consensus: Name] to signal this is distilled knowledge, not a raw note
            text = f"[Consensus - {label}: {node['name']}]: {summary}"

            # Attach linked notes for reference traceability (case-insensitive lookup)
            linked_notes = node_to_notes.get(node["name"].lower(), [])
            if linked_notes:
                logger.debug(
                    f"  [GraphRAG] Node '{node['name']}' has {len(linked_notes)} linked notes"
                )

            candidates.append(
                {
                    "text": text,
                    "type": "graph_consensus",
                    "original_obj": node,
                    "is_recent": False,
                    "priority": "primary",  # Direct entity match
                    "linked_notes": linked_notes,
                }
            )

        # B. Related Nodes (via graph traversal)
        for node in related_nodes:
            summary = node.get("summary") or node.get("description", "")
            if not summary:
                continue

            label = node.get("label", "Entity")
            rel_path = " → ".join(node.get("relationship_path", []))

            # Include relationship context if available (the "Why" behind the link)
            context_path = node.get("context_path", [])
            rel_context = ""
            if context_path:
                # Filter out None values and join
                contexts = [c for c in context_path if c]
                if contexts:
                    rel_context = (
                        f" Context: {'; '.join(contexts[:2])}"  # Limit to 2 contexts
                    )

            text = f"[Related - {label}: {node['name']}] (via {rel_path}){rel_context}: {summary}"

            # Attach linked notes for reference traceability (case-insensitive lookup)
            linked_notes = node_to_notes.get(node["name"].lower(), [])

            candidates.append(
                {
                    "text": text,
                    "type": "related_node",
                    "original_obj": node,
                    "is_recent": False,
                    "priority": "secondary",  # Graph expansion
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
                    "priority": "primary",  # Community summaries are high-value for broad queries
                    "linked_notes": linked_notes,
                }
            )

        # D. Multi-Hop Paths (connections between query entities)
        for path in multi_hop_paths:
            path_nodes = path.get("path_nodes", [])
            path_labels = path.get("path_labels", [])
            path_summaries = path.get("path_summaries", [])
            rel_types = path.get("relationship_types", [])

            # Build path description
            path_parts = []
            for i, (name, label, summary) in enumerate(
                zip(path_nodes, path_labels, path_summaries)
            ):
                node_desc = f"[{label}: {name}]"
                if summary:
                    node_desc += (
                        f" ({summary[:100]}...)"
                        if len(summary) > 100
                        else f" ({summary})"
                    )
                path_parts.append(node_desc)

            # Interleave with relationship types
            if rel_types:
                path_text = ""
                for i, part in enumerate(path_parts):
                    path_text += part
                    if i < len(rel_types):
                        path_text += f" --{rel_types[i]}--> "
            else:
                path_text = " → ".join(path_parts)

            text = f"[Multi-Hop Path]: {path.get('source_name')} connects to {path.get('target_name')}: {path_text}"

            # Collect linked notes from all nodes in the path (case-insensitive lookup)
            path_linked_notes = []
            for node_name in path_nodes:
                path_linked_notes.extend(node_to_notes.get(node_name.lower(), []))
            # Deduplicate by note id
            seen_ids = set()
            unique_notes = []
            for note in path_linked_notes:
                if note.get("id") not in seen_ids:
                    seen_ids.add(note.get("id"))
                    unique_notes.append(note)

            candidates.append(
                {
                    "text": text,
                    "type": "multi_hop_path",
                    "original_obj": path,
                    "is_recent": False,
                    "path_depth": path.get("depth", 0),
                    "priority": "secondary",
                    "linked_notes": unique_notes[:5],  # Limit to 5 notes per path
                }
            )

        logger.info(
            f"  [GraphRAG] Prepared {len(candidates)} candidates from graph "
            f"(no note chunking - summaries are primary)"
        )

        # ============ SYMBOLIC RANKING (No Reranker) ============
        # In a symbolic knowledge graph, we don't need a statistical reranker.
        # When you ask about "Ceruba", the node literally named "Ceruba" is relevant.
        # Rerankers can "drown out" exact matches with semantically similar but irrelevant content.

        if not candidates:
            logger.warning("  [Retrieval] No candidates found from graph")
            return []

        t_ranking_start = time.perf_counter()

        # Score candidates based on symbolic priority
        all_results = []
        for cand in candidates:
            # Base score by priority tier
            if cand.get("priority") == "primary":
                # Direct entity matches (from find_nodes_by_name) - highest priority
                base_score = 100.0
                cand["symbolic_immune"] = True
            else:
                # Related nodes, community summaries, multi-hop paths
                base_score = 50.0

            final_score = base_score

            # Entity Match Boost (if result mentions query entities)
            entity_boost = 1.0
            if query_entities:
                text_lower = cand["text"].lower()
                matched_entities = [
                    e for e in query_entities if e.lower() in text_lower
                ]
                if matched_entities:
                    entity_boost = 1.0 + (0.5 * len(matched_entities))  # +0.5 per match
                    final_score *= entity_boost

            # Keyword Boost (exact query terms in the text)
            keyword_boost = self._calculate_keyword_boost(query, cand["text"])
            if keyword_boost > 1.0:
                final_score *= keyword_boost

            cand["final_score"] = final_score
            cand["rerank_score"] = 0.0  # No reranker used
            cand["boosts"] = {
                "priority": base_score,
                "entity_match": entity_boost,
                "keyword_match": keyword_boost,
            }
            all_results.append(cand)

        t_ranking = time.perf_counter() - t_ranking_start
        logger.info(f"  [⏱️ Timing] Symbolic ranking: {t_ranking:.4f}s")

        # ============ FINAL RANKING ============
        all_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        # Apply limit (no cutoff needed - symbolic matches are already high quality)
        filtered_results = all_results[:top_k]

        # Log Top Results
        logger.info(f"  [Retrieval] Final Selection ({len(filtered_results)} results):")
        for i, doc in enumerate(filtered_results[:10]):
            display_text = doc["text"][:80].replace("\n", " ")
            boosts = doc.get("boosts", {})
            immune_flag = "🔒" if doc.get("symbolic_immune", False) else ""
            logger.info(
                f"    {i+1}. [{doc.get('type')}]{immune_flag} Score: {doc.get('final_score', 0):.1f} "
                f"(P:{boosts.get('priority', 0):.0f} × E:{boosts.get('entity_match', 1.0):.1f} × K:{boosts.get('keyword_match', 1.0):.1f}) "
                f"{display_text}..."
            )

        t_total = time.perf_counter() - t_start
        logger.info(
            f"  [⏱️ Timing] Total: {t_total:.2f}s (Embed: {t_embedding:.2f}s | Graph: {t_candidates:.2f}s | Ranking: {t_ranking:.4f}s)"
        )
        return filtered_results

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
