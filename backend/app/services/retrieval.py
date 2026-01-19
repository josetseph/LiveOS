import os
import logging
from typing import List, Tuple
from app.core.config import settings
from app.core.logging_config import get_component_logger

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
            # rerankers.rank returns a RankedResults object
            results = self.reranker.rank(query=query, docs=documents)

            # Convert to list of (doc, score)
            # results is iteratable of Result(doc_id, text, score, rank)
            ranked_pairs = [(res.text, res.score) for res in results]
            return ranked_pairs

        except Exception as e:
            logger.info(f"Reranking error (Batch): {e}")
            logger.info("  -> Falling back to batch_size=1 (Slow Path)")
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
        Orchestrates Hybrid Search (Double-Fetch Pattern):
        1. Vector Search (Neo4j) -> Get Note IDs.
        2. Postgres Fetch -> Get Content for those IDs.
        3. Graph Expansion -> Get Neighborhood context.
        4. Domain-Aware Boosting -> Prioritize matching domain notes.
        5. Rerank -> Combine and Score.
        """
        import time
        from app.services.embedding import embedding_service
        from app.services.graph import graph_service
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import select

        logger.info(f"  [Retrieval] Hybrid Search for: '{query}'")

        # 1. Embedding
        t_start = time.perf_counter()
        full_vector = embedding_service.embed_query(query)
        t_embed = time.perf_counter()
        logger.info(f"  [Retrieval] Embedding took: {t_embed - t_start:.4f}s")

        # Detect Query Domain (Academic vs Personal)
        query_domain = self._detect_query_domain(query)
        logger.info(f"  [Retrieval] Detected Query Domain: {query_domain}")

        # 2. Vector Search (Neo4j) - Get IDs with domain
        # Note: query_vector returns {id, content, score} but content might be null now
        vector_results = graph_service.query_vector_with_domain(
            full_vector, top_k=top_k
        )
        t_vector = time.perf_counter()
        logger.info(
            f"  [Retrieval] Neo4j Vector Search took: {t_vector - t_embed:.4f}s (Hits: {len(vector_results)})"
        )

        if not vector_results:
            return []

        note_ids = [res["id"] for res in vector_results]

        # 3. Postgres Fetch (Body) - BATCH OPTIMIZED
        # Fetch the actual content from Postgres since Neo4j only has summaries
        db_content_map = {}
        db_title_map = {}
        async with AsyncSessionLocal() as session:
            # Optimize: Select ONLY needed columns to avoid full object overhead
            stmt = select(Note.id, Note.content, Note.title).where(
                Note.id.in_(note_ids)
            )
            result = await session.execute(stmt)
            # Optimize: O(1) Lookup Map
            rows = result.all()
            db_content_map = {row.id: row.content for row in rows}
            db_title_map = {row.id: (row.title or "Untitled Note") for row in rows}

        t_pg = time.perf_counter()
        logger.info(f"  [Retrieval] Postgres Fetch took: {t_pg - t_vector:.4f}s")

        # 4. Graph Context Enrichment (Mind)
        neighborhoods = graph_service.get_note_context(note_ids)
        t_graph = time.perf_counter()
        logger.info(
            f"  [Retrieval] Graph Context Expansion took: {t_graph - t_pg:.4f}s"
        )

        # 5. Aggregate Snippets & Metdata
        all_snippets = []

        # --- NOTES ---
        for res in vector_results:
            nid = res["id"]
            content = db_content_map.get(nid, res.get("content"))  # Fallback
            title = db_title_map.get(nid, "Untitled Note")
            note_domain = res.get("domain", "Personal")

            if content:
                # Domain-aware boosting: boost notes matching query domain
                domain_boost = 1.5 if note_domain == query_domain else 1.0

                all_snippets.append(
                    {
                        "text": f"[Note: {title}]: {content}",
                        "content": content,
                        "type": "note",
                        "note_id": nid,
                        "title": title,
                        "domain": note_domain,
                        "domain_boost": domain_boost,
                    }
                )

        # --- GRAPH ---
        neighborhood_map = {row["note_id"]: row for row in neighborhoods}

        for nid, row in neighborhood_map.items():
            n_title = db_title_map.get(nid, "Untitled Note")

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

        # 6. Rerank
        if not all_snippets:
            return []

        # Soft Cap: Limit to 50 snippets for reranker performance
        # Beyond 50, the probability of finding the "golden answer" is extremely low
        if len(all_snippets) > 50:
            logger.info(
                f"  [Retrieval] Soft-capping from {len(all_snippets)} to 50 snippets for reranker speed."
            )
            all_snippets = all_snippets[:50]

        # Use 'text' key for reranking context
        doc_texts = [s["text"] for s in all_snippets]

        logger.info(f"  [Retrieval] Reranking {len(doc_texts)} snippets...")

        t_pre_rank = time.perf_counter()

        # OFF-THREAD RERANKING
        import asyncio

        loop = asyncio.get_running_loop()
        ranked_pairs = await loop.run_in_executor(None, self.rerank, query, doc_texts)

        t_rank = time.perf_counter()
        logger.info(f"  [Retrieval] Reranking took: {t_rank - t_pre_rank:.4f}s")

        # Map back ranked texts to snippet objects
        # Create lookup map (Text -> List[Snippet] to handle duplicates if any)
        final_docs = []
        snippet_map = {}
        for s in all_snippets:
            snippet_map[s["text"]] = s

        for text, score in ranked_pairs:
            if text in snippet_map:
                s = snippet_map[text].copy()  # Copy to avoid ref issues
                # Apply domain boost to final score
                domain_boost = s.get("domain_boost", 1.0)
                s["score"] = score * domain_boost
                final_docs.append(s)

        # Sort by boosted score
        final_docs.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Return Top N Objects
        return final_docs[:20]

    def _detect_query_domain(self, query: str) -> str:
        """
        Heuristic to detect if query is Academic, Personal, or Professional.

        Academic: mentions concepts, learning, papers, theorems, courses
        Personal: mentions feelings, daily life, relationships, goals
        Professional: mentions work, projects, meetings, career
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

        academic_score = sum(1 for kw in academic_keywords if kw in query_lower)
        personal_score = sum(1 for kw in personal_keywords if kw in query_lower)
        professional_score = sum(1 for kw in professional_keywords if kw in query_lower)

        # Return domain with highest score, default to Personal
        max_score = max(academic_score, personal_score, professional_score)
        if max_score == 0:
            return "Personal"  # Default

        if academic_score == max_score:
            return "Academic"
        elif professional_score == max_score:
            return "Professional"
        else:
            return "Personal"


retrieval_service = RetrievalService()
