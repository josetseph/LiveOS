import os
import logging
from typing import List, Tuple
from app.core.config import settings
from app.core.logging_config import get_component_logger
from app.services.graph import graph_service

# Suppress noisy tokenizer warnings
logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)

logger = get_component_logger("RetrievalService")


class RetrievalService:
    def __init__(self):
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), f"../../{settings.MODELS_PATH}")
        )
        self.reranker = None

        # Load immediately on startup
        self._load_reranker()

    def _load_reranker(self):
        if not self.reranker:
            try:
                from rerankers import Reranker

                model_name = (
                    settings.MODEL_RERANKING_LOCAL or settings.MODEL_RERANKER_HF
                )
                model_path = os.path.join(self.models_path, model_name)

                logger.info(
                    f"Loading Reranker ({settings.MODEL_RERANKER_HF}) from {model_path}..."
                )

                # Check if it's a generative model (mxbai-v2, qwen3) to use 'causal' type or let library infer
                # For mxbai-rerank-large-v2, it's a CausalLM based reranker.
                # We pass the absolute path to the local model folder.

                # Auto-detect behavior:
                # 1. mxbai-v2 (original) -> MxBaiV2Ranker
                # 2. mxbai-v2-seq-cls -> TransformerRanker (CrossEncoder)
                # 3. qwen3 -> MxBaiV2Ranker

                model_type = None
                tokenizer_kwargs = {}

                if "seq-cls" in model_name.lower():
                    # Sequence Classification Model (CrossEncoder)
                    model_type = "TransformerRanker"
                    # Qwen2 tokenizer usually needs explicit pad_token for batching
                    tokenizer_kwargs = {"pad_token": "<|endoftext|>"}
                elif "qwen3" in model_name.lower():
                    model_type = "MxBaiV2Ranker"

                self.reranker = Reranker(
                    model_path,
                    model_type=model_type,
                    device="mps",  # Force MPS for Mac
                    dtype="float32",  # Fix torch_dtype deprecation warning
                    tokenizer_kwargs=tokenizer_kwargs,
                )

                # Explicitly fix Qwen tokenizer padding for batch inference (Validation)
                # DEEP FIX: Must set pad_token_id in MODEL CONFIG and GENERATION CONFIG, not just Tokenizer.
                if self.reranker and hasattr(self.reranker, "tokenizer"):
                    tkn = self.reranker.tokenizer
                    if tkn.pad_token is None:
                        tkn.pad_token = tkn.eos_token
                        logger.info(f"Fixed: Set pad_token to {tkn.pad_token}")

                    if hasattr(self.reranker, "model"):
                        mdl = self.reranker.model
                        if hasattr(mdl, "config"):
                            mdl.config.pad_token_id = tkn.eos_token_id
                        if hasattr(mdl, "generation_config") and mdl.generation_config:
                            mdl.generation_config.pad_token_id = tkn.eos_token_id
                        logger.info(
                            "Fixed: Set pad_token_id in Model Config & Generation Config."
                        )

                logger.info(f"Reranker ({model_name}) loaded successfully.")
            except Exception as e:
                logger.error(f"Warning: Failed to load reranker: {e}")
                logger.error("Falling back to identity ranking.")
                self.reranker = None

    def rerank(self, query: str, documents: List[str]) -> List[Tuple[str, float]]:
        """
        Reranks a list of documents based on relevance to the query.
        Returns pairs of (document, score), sorted by score desc.

        Memory-optimized for MPS backend with aggressive batching and cleanup.
        """
        if not documents:
            return []

        if not self.reranker:
            # Just return documents with score 0
            return [(doc, 0.0) for doc in documents]

        # Hard limit to prevent extreme memory usage (Increased for Snippet Search)
        if len(documents) > 250:
            logger.warning(
                f"Reranker input capped from {len(documents)} to 250 snippets for memory safety"
            )
            documents = documents[:250]

        try:
            results = self.reranker.rank(query=query, docs=documents, batch_size=5)
            ranked_pairs = [(res.text, res.score) for res in results]

            # Clear MPS cache after successful batch
            self._clear_mps_cache()
            return ranked_pairs

        except Exception as e:
            logger.warning(f"Reranking batch failed (VRAM pressure): {e}")
            logger.info("Falling back to micro-batches (batch_size=1)")

            # Clear cache before fallback
            self._clear_mps_cache()

            try:
                # Ultra-conservative fallback
                results = self.reranker.rank(query=query, docs=documents, batch_size=1)
                ranked_pairs = [(res.text, res.score) for res in results]
                self._clear_mps_cache()
                return ranked_pairs

            except Exception as e2:
                logger.error(f"Reranking failed even with batch_size=1: {e2}")
                logger.warning("Returning documents with neutral scores (no reranking)")
                return [(doc, 0.0) for doc in documents]

    def _clear_mps_cache(self):
        """Clear MPS memory cache to prevent fragmentation."""
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:
            pass  # Silent fail if torch not available or MPS not supported

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
        Semantic Snippet Retrieval Pipeline with Weighted Scoring:
        1. Fetch Graph Nodes (The Mind)
        2. Fetch Extended Recent Notes (The Anchor) - e.g., last 20
        3. Fetch Linked Evidence Notes (The Body)
        4. Chunk ALL Note content into Snippets.
        5. Rerank EVERYTHING (Nodes + Snippets).
        6. Filter by Score > 0.6 (lowered threshold).
        7. Apply Weighted Scoring:
           - Base rerank score × recency boost × entity match boost
           - Sort by final weighted score (not rigid categories)
           - Temporal queries get extreme priority; entity queries get semantic priority
        """
        import time
        from app.services.embedding import embedding_service
        from app.services.graph import graph_service
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import select

        logger.info(f"  [Retrieval] Semantic Snippet Search for: '{query}'")
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

        # ============ FETCH CANDIDATES ============
        t_phase_start = time.perf_counter()

        # 1. Graph Nodes
        graph_nodes = graph_service.search_knowledge_graph(
            full_vector, top_k=20, min_score=0.6
        )

        # 2. Recent Notes (Expanded Window)
        recent_notes_meta = graph_service.get_recent_notes(limit=20)
        recent_note_ids = {n["id"] for n in recent_notes_meta}

        # 3. Linked Evidence
        node_names = [n["name"] for n in graph_nodes]
        evidence_note_ids = set()
        if node_names:
            logger.info(
                f"  [DEBUG] Graph found entities: {node_names[:10]}"
            )  # First 10
            evidence_results = graph_service.get_linked_evidence(
                node_names, limit_per_node=3
            )
            for row in evidence_results:
                for note in row.get("evidence", []):
                    evidence_note_ids.add(note["id"])
            logger.info(
                f"  [DEBUG] Evidence retrieval found {len(evidence_note_ids)} notes from {len(node_names)} entities"
            )

        # Combine Note IDs
        all_note_ids = recent_note_ids.union(evidence_note_ids)

        # Fetch Full Content
        note_content_map = {}
        note_meta_map = {}

        if all_note_ids:
            t_db_start = time.perf_counter()
            async with AsyncSessionLocal() as session:
                stmt = select(Note.id, Note.content, Note.title, Note.created_at).where(
                    Note.id.in_(list(all_note_ids))
                )
                result = await session.execute(stmt)
                for row in result:
                    note_content_map[row.id] = row.content
                    note_meta_map[row.id] = {
                        "title": row.title or "Untitled",
                        "created_at": (
                            row.created_at.isoformat() if row.created_at else ""
                        ),
                    }
            t_db = time.perf_counter() - t_db_start
            logger.info(
                f"  [⏱️ Timing] Database fetch ({len(all_note_ids)} notes): {t_db:.2f}s"
            )
            if query_entities:
                logger.info(
                    f"  [DEBUG] Looking for entities {query_entities} in {len(all_note_ids)} notes"
                )

        # ============ PREPARE CANDIDATES ============
        candidates = []

        # A. Graph Nodes
        for node in graph_nodes:
            # Reconstruct text
            text = f"[{node.get('labels', ['Unknown'])[0]}: {node['name']}]: {node.get('summary') or node.get('description', '')}"
            candidates.append(
                {
                    "text": text,
                    "type": "graph_consensus",
                    "original_obj": node,
                    "is_recent": False,
                }
            )

        # B. Note Snippets
        for nid in all_note_ids:
            content = note_content_map.get(nid)
            if not content:
                continue

            meta = note_meta_map.get(nid, {})
            title = meta.get("title", "Untitled")
            created_at = meta.get("created_at", "")
            is_recent = nid in recent_note_ids

            # Chunking
            chunks = self._chunk_text(content)
            for chunk in chunks:
                candidates.append(
                    {
                        "text": chunk,
                        "type": "note",
                        "title": title,
                        "created_at": created_at,
                        "note_id": nid,
                        "is_recent": is_recent,
                    }
                )

        t_candidates = time.perf_counter() - t_phase_start
        logger.info(
            f"  [⏱️ Timing] Candidate collection: {t_candidates:.2f}s ({len(candidates)} candidates)"
        )

        # ============ RELATIONSHIP EXPANSION ============
        # Expand graph nodes with related nodes BEFORE reranking
        # This ensures related concepts are scored by the reranker
        t_expand_start = time.perf_counter()
        expanded_candidates = self._expand_candidates_with_relationships(
            candidates, max_related=3, min_confidence=0.7
        )
        t_expand = time.perf_counter() - t_expand_start
        if len(expanded_candidates) > len(candidates):
            logger.info(
                f"  [Relationships] Expanded {len(candidates)} → {len(expanded_candidates)} candidates (+{len(expanded_candidates) - len(candidates)} related nodes) in {t_expand:.2f}s"
            )

        logger.info(
            f"  [Retrieval] Reranking {len(expanded_candidates)} candidates (Nodes + Related + Snippets)..."
        )

        # ============ RERANKING ============
        if not expanded_candidates:
            return []

        candidate_texts = [c["text"] for c in expanded_candidates]

        # Off-thread reranking
        import asyncio

        t_rerank_start = time.perf_counter()
        loop = asyncio.get_running_loop()
        ranked_pairs = await loop.run_in_executor(
            None, self.rerank, query, candidate_texts
        )
        t_rerank = time.perf_counter() - t_rerank_start
        logger.info(f"  [⏱️ Timing] Reranking: {t_rerank:.2f}s")

        # Map back to objects
        # Note: ranked_pairs is list of (text, score)
        # We need to efficienty lookup. Text usually unique enough, but let's be safe.
        # Actually, since we generated the text list from expanded_candidates, we can just use a dict mapping text -> list[candidate]
        # to handle duplicates (unlikely to have exact duplicate chunks from different notes, but possible).

        text_to_candidates = {}
        for c in expanded_candidates:
            t = c["text"]
            if t not in text_to_candidates:
                text_to_candidates[t] = []
            text_to_candidates[t].append(c)

        # ============ WEIGHTED SCORING ============
        all_results = []
        processed_candidates_set = set()

        # Lower threshold for better recall
        score_threshold = 0.6

        # Early stopping: stop after finding N high-quality results
        high_quality_threshold = 0.8
        high_quality_count = 0
        early_stop_target = 50

        # DEBUG: Log score distribution
        if ranked_pairs:
            scores = [score for _, score in ranked_pairs]
            logger.info(
                f"  [DEBUG] Reranker score stats: min={min(scores):.4f}, max={max(scores):.4f}, median={sorted(scores)[len(scores)//2]:.4f}"
            )
            logger.info(
                f"  [DEBUG] Scores above threshold ({score_threshold}): {sum(1 for s in scores if s >= score_threshold)}/{len(scores)}"
            )

        for text, score in ranked_pairs:
            # EARLY STOPPING: If we have enough high-quality results, stop reranking
            if high_quality_count >= early_stop_target:
                logger.info(
                    f"  [Retrieval] Early stopping: Found {high_quality_count} high-quality results"
                )
                break

            # SEMANTIC GATEKEEPER: Score > 0.6 (lowered from 0.75)
            if score < score_threshold:
                continue

            matched_cands = text_to_candidates.get(text, [])
            for cand in matched_cands:
                cand_id = id(cand)
                if cand_id in processed_candidates_set:
                    continue
                processed_candidates_set.add(cand_id)

                # Attach base rerank score
                cand["rerank_score"] = score
                cand["score"] = score  # Keep for backward compatibility

                # Calculate weighted final score
                final_score = score

                # 1. Recency Boost (1.0 - 2.0x for recent notes)
                recency_boost = 1.0
                if cand.get("created_at"):
                    recency_boost = self._calculate_recency_boost(cand["created_at"])
                    final_score *= recency_boost

                # 2. Entity Match Boost (2.0x if result mentions query entities)
                entity_boost = 1.0
                if query_entities:
                    text_lower = cand["text"].lower()
                    matched_entities = [
                        e for e in query_entities if e.lower() in text_lower
                    ]
                    if matched_entities:
                        entity_boost = 2.0
                        final_score *= entity_boost
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                f"  [Entity Match] Boosted by 2.0x for entities: {matched_entities} in text: {cand['text'][:100]}"
                            )

                # 3. Keyword/Exact Match Boost (3.0x if exact query terms appear)
                keyword_boost = 1.0
                keyword_boost = self._calculate_keyword_boost(query, cand["text"])
                if keyword_boost > 1.0:
                    final_score *= keyword_boost

                # 4. Temporal Query Extreme Boost (3.0x for recent notes on temporal queries)
                temporal_boost = 1.0
                if is_temporal_query and cand.get("is_recent", False):
                    temporal_boost = 3.0
                    final_score *= temporal_boost

                # Store all boost factors for debugging
                cand["final_score"] = final_score
                cand["boosts"] = {
                    "recency": recency_boost,
                    "entity_match": entity_boost,
                    "keyword_match": keyword_boost,
                    "temporal_query": temporal_boost,
                }

                all_results.append(cand)

                # Track high-quality results for early stopping
                if score >= high_quality_threshold:
                    high_quality_count += 1

        logger.info(
            f"  [Retrieval] Filtered > {score_threshold}: {len(all_results)} total results"
        )

        # ============ FINAL RANKING ============
        # Sort by final weighted score (not rigid categories)
        all_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

        # Apply dynamic cutoff to filter low-quality results before feeding to LLM
        cutoff_score = self._get_cutoff_score(
            is_temporal_query, query_entities, all_results
        )
        filtered_results = [
            r for r in all_results if r.get("final_score", 0) >= cutoff_score
        ]

        logger.info(
            f"  [Retrieval] Applied cutoff {cutoff_score:.2f}: {len(all_results)} → {len(filtered_results)} results"
        )

        # Apply diversity constraint: limit snippets per note in top results
        final_list = self._apply_diversity_constraint(filtered_results, max_per_note=3)

        # Apply hard limit on results sent to LLM (prevent context overload)
        if len(final_list) > top_k:
            logger.info(
                f"  [Retrieval] Limiting results from {len(final_list)} to {top_k} (top_k)"
            )
            final_list = final_list[:top_k]

        # Log Top Results with detailed scoring
        logger.info(f"  [Retrieval] Final Selection (Total {len(final_list)}):")
        for i, doc in enumerate(final_list[:20]):
            display_text = doc["text"][:80].replace("\n", " ")
            boosts = doc.get("boosts", {})
            logger.info(
                f"    {i+1}. [Score: {doc.get('final_score', 0):.4f}] (Rerank: {doc.get('rerank_score', 0):.2f} × R:{boosts.get('recency', 1.0):.2f} × E:{boosts.get('entity_match', 1.0):.1f} × K:{boosts.get('keyword_match', 1.0):.1f} × T:{boosts.get('temporal_query', 1.0):.1f}) {display_text}..."
            )

        logger.info(
            f"  [⏱️ Timing] Total Pipeline Time: {time.perf_counter() - t_start:.2f}s (Embedding: {t_embedding:.2f}s | Candidates: {t_candidates:.2f}s | DB: {t_db if all_note_ids else 0:.2f}s | Reranking: {t_rerank:.2f}s | Scoring: {time.perf_counter() - t_start - t_embedding - t_candidates - t_rerank:.2f}s)"
        )
        return final_list

    def _calculate_recency_boost(self, created_at_str: str) -> float:
        """
        Calculate recency boost based on note age.
        - Today: 2.0x boost
        - 1 month ago: ~1.5x boost
        - 1 year ago: ~1.1x boost
        """
        from datetime import datetime, timezone

        try:
            # Parse ISO timestamp and calculate age in days
            dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now = datetime.now(dt.tzinfo or timezone.utc)
            days_old = max(0, (now - dt).days)
            # Decay factor: 1.0 for today, 0.5 for 30 days, 0.1 for 1 year
            decay = 1.0 / (1.0 + (days_old / 30.0))
            return 1.0 + decay  # Range: [1.0, 2.0]
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{created_at_str}': {e}")
            return 1.5  # Default fallback

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

    def _get_cutoff_score(
        self,
        is_temporal_query: bool,
        query_entities: List[str],
        results: List[dict],
    ) -> float:
        """
        Determine dynamic cutoff score based on query type and result distribution.

        Strategy:
        - Entity queries: Higher cutoff (7.0) for precision
        - Temporal queries: Lower cutoff (5.0) for broader context
        - General queries: Balanced cutoff (6.0)
        - Adaptive: If top score is low, lower the bar proportionally

        Returns cutoff score (minimum 0.6)
        """
        if not results:
            return 0.6  # Minimum threshold

        top_score = results[0].get("final_score", 0)

        # Tiered cutoffs based on query type
        if query_entities:
            # Entity queries: High precision needed
            base_cutoff = 7.0
        elif is_temporal_query:
            # Temporal queries: Broader context is better
            base_cutoff = 5.0
        else:
            # General queries: Balanced approach
            base_cutoff = 6.0

        # Adaptive: If top score is low, lower the bar to avoid returning nothing
        if top_score < base_cutoff:
            adaptive_cutoff = max(0.6, top_score * 0.6)  # 60% of top score, minimum 0.6
            return adaptive_cutoff

        return base_cutoff

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
        Ensure no single note dominates top results.
        Limit snippets per note while maintaining score order.
        """
        note_counts = {}
        diverse_results = []

        for result in results:
            # Graph nodes don't have note_id, always include
            if result.get("type") == "graph_consensus":
                diverse_results.append(result)
                continue

            # For notes, track count per note_id
            note_id = result.get("note_id")
            if note_id:
                count = note_counts.get(note_id, 0)
                if count < max_per_note:
                    diverse_results.append(result)
                    note_counts[note_id] = count + 1
            else:
                diverse_results.append(result)

        return diverse_results

    def _expand_candidates_with_relationships(
        self, candidates: List[dict], max_related: int = 3, min_confidence: float = 0.7
    ) -> List[dict]:
        """
        Expand candidates by adding related nodes from the knowledge graph BEFORE reranking.

        This allows the reranker to score related concepts for relevance, ensuring only
        the most relevant related nodes make it to the final results.

        Args:
            candidates: Initial candidate list (graph nodes + note snippets)
            max_related: Maximum related nodes to add per graph node
            min_confidence: Minimum relationship confidence threshold

        Returns:
            Expanded candidate list (original + related nodes as new candidates)
        """
        expanded = list(candidates)  # Start with original candidates
        added_nodes = set()  # Track to avoid duplicates

        for candidate in candidates:
            # Only expand graph nodes (not note snippets)
            if candidate.get("type") != "graph_consensus":
                continue

            node = candidate.get("original_obj", {})
            node_name = node.get("name")
            node_label = node.get("labels", ["Entity"])[0]

            if not node_name:
                continue

            try:
                # Get related nodes up to 2 hops away
                related_nodes = graph_service.get_related_nodes(
                    node_name=node_name,
                    node_label=node_label,
                    max_depth=2,
                    min_confidence=min_confidence,
                )

                # Limit to top N most relevant
                if len(related_nodes) > max_related:
                    # Sort by depth (closer is better) and confidence
                    related_nodes.sort(
                        key=lambda x: (
                            x.get("depth", 999),
                            -max([c for c in x.get("confidence_path", [0.5])]),
                        )
                    )
                    related_nodes = related_nodes[:max_related]

                # Add related nodes as new candidates for reranking
                for rn in related_nodes:
                    rn_name = rn.get("name")
                    if not rn_name or rn_name in added_nodes:
                        continue  # Skip duplicates

                    # Create candidate from related node
                    rel_path = " → ".join(rn.get("relationship_path", []))
                    summary = rn.get("summary") or rn.get("description", "")
                    text = f"[{rn.get('label')}: {rn_name}] (via {rel_path} from {node_name}): {summary}"

                    expanded.append(
                        {
                            "text": text,
                            "type": "related_node",
                            "original_obj": rn,
                            "is_recent": False,
                            "parent_node": node_name,
                            "relationship_path": rn.get("relationship_path", []),
                        }
                    )
                    added_nodes.add(rn_name)

            except Exception as e:
                logger.debug(f"[Relationships] Could not expand '{node_name}': {e}")
                continue

        return expanded

    def enrich_with_relationships(
        self, results: List[dict], max_related: int = 3, min_confidence: float = 0.7
    ) -> List[dict]:
        """
        DEPRECATED: Relationship enrichment now happens BEFORE reranking inside hybrid_search().

        This method is kept for backward compatibility but just returns results unchanged.
        Related nodes are now added as candidates before reranking for better relevance scoring.

        Args:
            results: List of search results from hybrid_search
            max_related: Maximum number of related nodes to include per result
            min_confidence: Minimum relationship confidence to include

        Returns:
            Results unchanged (enrichment now happens in hybrid_search)
        """
        logger.debug(
            "[Relationships] enrich_with_relationships called but enrichment already done in hybrid_search"
        )
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
