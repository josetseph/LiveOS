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
        """
        if not documents:
            return []

        if not self.reranker:
            # Just return documents with score 0
            return [(doc, 0.0) for doc in documents]

        try:
            # UPGRADE: Added batch_size=5 to prevent memory buffer errors
            # This ensures the GPU processes snippets in manageable chunks.
            results = self.reranker.rank(query=query, docs=documents, batch_size=5)

            # Convert to list of (doc, score)
            # results is iteratable of Result(doc_id, text, score, rank)
            ranked_pairs = [(res.text, res.score) for res in results]
            return ranked_pairs

        except Exception as e:
            logger.warning(f"Reranking batch failed (likely VRAM pressure): {e}")
            logger.info("Falling back to sequential processing (Slow Path)")
            try:
                # Fallback: Process one by one
                results = self.reranker.rank(query=query, docs=documents, batch_size=1)
                ranked_pairs = [(res.text, res.score) for res in results]
                return ranked_pairs
            except Exception as e2:
                logger.error(f"Reranking error (Single): {e2}")
                return [(doc, 0.0) for doc in documents]

    async def hybrid_search(self, query: str, top_k: int = 50) -> List[str]:
        """
        Graph-First Hybrid Retrieval with 4-Phase Architecture:

        Phase 1: Temporal Anchor - Get 5 most recent notes (Short-Term Memory)
        Phase 2: Graph Consensus - Search distilled knowledge nodes (Long-Term Wisdom)
        Phase 3: Grounding - Fetch source notes from graph nodes (Evidence)
        Phase 4: Semantic Fallback - Traditional vector search on notes (Coverage)

        Then merge, deduplicate, rerank with domain + recency boosts.
        """
        import time
        from app.services.embedding import embedding_service
        from app.services.graph import graph_service
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import select

        logger.info(f"  [Retrieval] Graph-First Hybrid Search for: '{query}'")
        t_start = time.perf_counter()

        # Check if this is a temporal query (recent/latest/newest)
        if self._is_temporal_query(query):
            logger.info(
                "  [Retrieval] Detected TEMPORAL query - using timestamp-based retrieval"
            )
            return await self._temporal_search(query, top_k=min(top_k, 10))

        # Generate query embedding once (used in Phases 2 & 4)
        full_vector = embedding_service.embed_query(query)
        t_embed = time.perf_counter()
        logger.info(f"  [Retrieval] Embedding took: {t_embed - t_start:.4f}s")

        # Detect Query Domain for boosting
        query_domain = self._detect_query_domain(query)
        logger.info(f"  [Retrieval] Detected Query Domain: {query_domain}")

        all_note_ids = set()
        all_snippets = []
        note_phase_map = (
            {}
        )  # Track which phase each note came from for priority scoring

        # ============ PHASE 1: TEMPORAL ANCHOR (Short-Term Memory) ============
        logger.info("  [Phase 1] Fetching Temporal Anchors (10 most recent notes)...")
        temporal_notes = graph_service.get_recent_notes(limit=10)
        temporal_ids = [n["id"] for n in temporal_notes]
        all_note_ids.update(temporal_ids)
        for nid in temporal_ids:
            note_phase_map[nid] = "temporal"

        t_temporal = time.perf_counter()
        logger.info(
            f"  [Phase 1] Temporal Anchor: {len(temporal_ids)} notes in {t_temporal - t_embed:.4f}s"
        )

        # ============ PHASE 2: GRAPH CONSENSUS (Long-Term Wisdom) ============
        logger.info("  [Phase 2] Searching Knowledge Graph (Distilled Summaries)...")
        graph_nodes = graph_service.search_knowledge_graph(
            full_vector, top_k=25, min_score=0.6
        )

        t_graph = time.perf_counter()
        logger.info(
            f"  [Phase 2] Graph Search: {len(graph_nodes)} knowledge nodes in {t_graph - t_temporal:.4f}s"
        )

        # Extract graph snippets (consensus summaries)
        for node in graph_nodes:
            node_labels = node.get("labels", [])
            # Filter out :Indexable label to get actual type
            node_type = next(
                (label for label in node_labels if label != "Indexable"), "Unknown"
            )

            # Get the appropriate text based on node type
            if "Concept" in node_labels and node.get("summary"):
                text = f"[Concept: {node['name']}]: {node['summary']}"
                content = node["summary"]
            elif "Entity" in node_labels and node.get("summary"):
                text = f"[Entity: {node['name']} ({node.get('entity_type', 'Unknown')})]: {node['summary']}"
                content = node["summary"]
            elif "Task" in node_labels:
                text = f"[Task: {node.get('description', node.get('name', ''))} (Status: {node.get('status', 'Unknown')})]"
                content = node.get("description", node.get("name", ""))
            elif "Persona" in node_labels and node.get("summary"):
                text = f"[Personality: {node.get('trait', node.get('name', ''))}]: {node['summary']}"
                content = node["summary"]
            elif "Reference" in node_labels:
                text = f"[Reference: {node['name']}]: {node.get('summary', node.get('content', ''))}"
                content = node.get("summary", node.get("content", ""))
            else:
                # Fallback for unknown types
                text = f"[{node_type}: {node.get('name', 'Unknown')}]: {node.get('summary', node.get('description', ''))}"
                content = node.get("summary", node.get("description", ""))

            if content:
                all_snippets.append(
                    {
                        "text": text,
                        "content": content,
                        "type": f"graph_{node_type.lower()}",
                        "score": node.get("score", 0)
                        * 2.0,  # High priority for consensus knowledge
                        "domain_boost": 1.0,  # No domain boost for graph nodes (already filtered by relevance)
                    }
                )

        # ============ PHASE 3: GROUNDING (Fetch Evidence Notes) ============
        logger.info("  [Phase 3] Grounding - Fetching source notes from graph nodes...")
        if graph_nodes:
            node_names = [n["name"] for n in graph_nodes if n.get("name")]
            node_labels = []
            for n in graph_nodes:
                labels = n.get("labels", [])
                # Get primary label (not Indexable)
                primary_label = next(
                    (label for label in labels if label != "Indexable"), "Concept"
                )
                node_labels.append(primary_label)

            if node_names:
                source_notes = graph_service.get_node_source_notes(
                    node_names, node_labels
                )
                source_note_ids = [
                    sn["note_id"] for sn in source_notes if sn.get("note_id")
                ]
                # Get unique note IDs (duplicates = same note referenced by multiple graph nodes)
                unique_source_ids = list(set(source_note_ids))
                all_note_ids.update(unique_source_ids)
                for nid in unique_source_ids:
                    note_phase_map[nid] = "graph_source"

                t_grounding = time.perf_counter()
                logger.info(
                    f"  [Phase 3] Grounding: {len(unique_source_ids)} unique source notes ({len(source_note_ids)} total references) in {t_grounding - t_graph:.4f}s"
                )

        # ============ PHASE 4: SEMANTIC FALLBACK (Safety Net) ============
        # Only run if Phases 1-3 didn't find enough context
        t_vector = time.perf_counter()
        if len(all_note_ids) < 15:
            logger.info(
                f"  [Phase 4] SAFETY NET: Only {len(all_note_ids)} notes so far, running vector search fallback..."
            )
            vector_results = graph_service.query_vector_with_domain(
                full_vector, top_k=top_k
            )
            vector_note_ids = [res["id"] for res in vector_results]
            for nid in vector_note_ids:
                if (
                    nid not in note_phase_map
                ):  # Don't override if already found in earlier phase
                    note_phase_map[nid] = "vector_fallback"
            all_note_ids.update(vector_note_ids)
            logger.info(
                f"  [Phase 4] Vector Search: {len(vector_results)} notes in {time.perf_counter() - t_vector:.4f}s"
            )
        else:
            logger.info(
                f"  [Phase 4] SKIPPED: Already have {len(all_note_ids)} notes from graph-first retrieval"
            )

        # ============ POSTGRES FETCH (Get Full Content) ============
        logger.info(
            f"  [Retrieval] Fetching content for {len(all_note_ids)} unique notes from Postgres..."
        )
        note_ids_list = list(all_note_ids)

        db_content_map = {}
        db_title_map = {}
        db_created_at_map = {}

        async with AsyncSessionLocal() as session:
            stmt = select(Note.id, Note.content, Note.title, Note.created_at).where(
                Note.id.in_(note_ids_list)
            )
            result = await session.execute(stmt)
            rows = result.all()
            db_content_map = {row.id: row.content for row in rows}
            db_title_map = {row.id: (row.title or "Untitled Note") for row in rows}
            db_created_at_map = {row.id: row.created_at.isoformat() for row in rows}

        t_pg = time.perf_counter()
        logger.info(
            f"  [Retrieval] Postgres Fetch: {len(db_content_map)} notes in {t_pg - t_vector:.4f}s"
        )

        # ============ GRAPH CONTEXT ENRICHMENT ============
        neighborhoods = graph_service.get_note_context(note_ids_list)
        t_graph_context = time.perf_counter()
        logger.info(
            f"  [Retrieval] Graph Context Expansion: {t_graph_context - t_pg:.4f}s"
        )

        # ============ BUILD NOTE SNIPPETS ============
        for nid in note_ids_list:
            content = db_content_map.get(nid)
            if not content:
                continue

            title = db_title_map.get(nid, "Untitled Note")
            created_at = db_created_at_map.get(nid, "")

            # Recency boost
            recency_boost = (
                self._calculate_recency_boost(created_at) if created_at else 1.0
            )

            # Phase priority boost (graph > temporal > vector fallback)
            phase = note_phase_map.get(nid, "unknown")
            if phase == "graph_source":
                phase_boost = 1.5  # Highest - notes that formed graph consensus
            elif phase == "temporal":
                phase_boost = 1.2  # Medium - recent context
            elif phase == "vector_fallback":
                phase_boost = 0.9  # Lowest - safety net results
            else:
                phase_boost = 1.0  # Unknown

            all_snippets.append(
                {
                    "text": f"[Note: {title}]: {content}",
                    "content": content,
                    "type": "note",
                    "note_id": nid,
                    "title": title,
                    "recency_boost": recency_boost,
                    "phase_boost": phase_boost,
                    "created_at": created_at,
                }
            )

        # ============ ADD GRAPH NEIGHBORHOOD CONTEXT ============
        neighborhood_map = {row["note_id"]: row for row in neighborhoods}
        for nid, row in neighborhood_map.items():
            n_title = db_title_map.get(nid, "Untitled Note")

            # Concepts
            for concept in row.get("concepts", []):
                if concept.get("name") and concept.get("summary"):
                    all_snippets.append(
                        {
                            "text": f"[Theme: {concept['name']}]: {concept['summary']}",
                            "content": concept["summary"],
                            "type": "concept",
                            "note_id": nid,
                            "title": n_title,
                        }
                    )

            # Entities
            for entity in row.get("entities", []):
                if entity.get("name"):
                    all_snippets.append(
                        {
                            "text": f"[Entity: {entity['name']} ({entity['type']})]",
                            "content": f"{entity['name']} ({entity['type']})",
                            "type": "entity",
                            "note_id": nid,
                            "title": n_title,
                        }
                    )

            # Tasks
            for task in row.get("tasks", []):
                if task.get("description"):
                    all_snippets.append(
                        {
                            "text": f"[Task: {task['description']} (Status: {task['status']})]",
                            "content": task["description"],
                            "type": "task",
                            "note_id": nid,
                            "title": n_title,
                        }
                    )

            # Persona traits
            for persona in row.get("persona_traits", []):
                if persona.get("trait"):
                    all_snippets.append(
                        {
                            "text": f"[Persona: {persona['trait']}] Evidence: \"{persona.get('quote', '')}\"",
                            "content": f"{persona['trait']}: {persona.get('quote', '')}",
                            "type": "persona_trait",
                            "note_id": nid,
                            "title": n_title,
                        }
                    )

        # ============ RERANKING ============
        if not all_snippets:
            return []

        # Soft cap for reranker performance
        if len(all_snippets) > 50:
            logger.info(
                f"  [Retrieval] Soft-capping from {len(all_snippets)} to 50 snippets for reranker"
            )
            # Sort by pre-computed scores first to keep highest quality
            all_snippets.sort(key=lambda x: x.get("score", 0), reverse=True)
            all_snippets = all_snippets[:50]

        doc_texts = [s["text"] for s in all_snippets]
        logger.info(f"  [Retrieval] Reranking {len(doc_texts)} snippets...")

        t_pre_rank = time.perf_counter()

        # Off-thread reranking
        import asyncio

        loop = asyncio.get_running_loop()
        ranked_pairs = await loop.run_in_executor(None, self.rerank, query, doc_texts)

        t_rank = time.perf_counter()
        logger.info(f"  [Retrieval] Reranking took: {t_rank - t_pre_rank:.4f}s")

        # ============ FINAL SCORING & RANKING ============
        final_docs = []
        snippet_map = {s["text"]: s for s in all_snippets}

        for text, rerank_score in ranked_pairs:
            if text in snippet_map:
                s = snippet_map[text].copy()

                # Get all boost factors
                recency_boost = s.get("recency_boost", 1.0)
                phase_boost = s.get("phase_boost", 1.0)
                pre_score = s.get("score", 0)

                # If snippet already has a score (from Phase 2 graph consensus), use it
                if pre_score > 0:
                    # Graph consensus snippets get priority
                    s["score"] = pre_score * rerank_score
                else:
                    # Notes get boost calculation: Recency × Phase Priority
                    s["score"] = rerank_score * recency_boost * phase_boost

                final_docs.append(s)

        # Sort by final boosted score
        final_docs.sort(key=lambda x: x.get("score", 0), reverse=True)

        logger.info(f"  [Retrieval] Total time: {time.perf_counter() - t_start:.4f}s")

        # Return top 10
        return final_docs[:10]

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

    def _is_temporal_query(self, query: str) -> bool:
        """
        Detect if query is asking for recent/latest/newest notes.
        """
        query_lower = query.lower()
        temporal_keywords = [
            "most recent",
            "latest",
            "newest",
            "last note",
            "recent note",
            "new note",
            "today",
            "yesterday",
            "this week",
        ]
        return any(kw in query_lower for kw in temporal_keywords)

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
