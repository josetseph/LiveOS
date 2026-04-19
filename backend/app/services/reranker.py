import os
import asyncio
import torch
from typing import Optional

from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("RerankerService")


class RerankerService:
    def __init__(self):
        self._model = None
        self._load_lock: asyncio.Lock | None = None
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), f"../../{settings.MODELS_PATH}")
        )

    def _get_lock(self) -> asyncio.Lock:
        # Lazy-init so the lock is created in the running event loop.
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        return self._load_lock

    async def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True

        async with self._get_lock():
            if self._model is not None:
                return True

            model_path = os.path.join(self.models_path, settings.MODEL_RERANKER_LOCAL)
            if not os.path.isdir(model_path):
                logger.warning(f"[Reranker] Model directory not found: {model_path}")
                return False

            try:
                from transformers import AutoModel

                def _load():
                    model = AutoModel.from_pretrained(
                        model_path,
                        trust_remote_code=True,
                        torch_dtype="auto",
                    )
                    model.eval()
                    return model

                loop = asyncio.get_event_loop()
                self._model = await loop.run_in_executor(None, _load)
                logger.info(f"[Reranker] Loaded {settings.MODEL_RERANKER_LOCAL} from {model_path}")
                return True
            except Exception as exc:
                logger.error(f"[Reranker] Failed to load model: {exc}")
                return False

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
    ) -> list[dict]:
        """
        Score and rank documents against a query using the local jina-reranker-v3.

        Returns list of ``{index, text, relevance_score}`` sorted by score descending.
        Falls back to an empty list if the model is unavailable or inference fails.
        """
        if not documents:
            return []

        loaded = await self._ensure_loaded()
        if not loaded or self._model is None:
            return []

        model = self._model

        def _run() -> list[dict]:
            with torch.no_grad():
                return model.rerank(query, documents, top_n=top_n)

        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(None, _run)
            results = []
            for r in raw:
                doc = r["document"]
                # v2 wraps text in {"text": ...}; v3 returns a plain string
                text = doc["text"] if isinstance(doc, dict) else doc
                results.append(
                    {
                        "index": r["index"],
                        "text": text,
                        "relevance_score": float(r["relevance_score"]),
                    }
                )
            return results
        except Exception as exc:
            logger.error(f"[Reranker] Inference failed: {exc}")
            return []


reranker_service = RerankerService()
