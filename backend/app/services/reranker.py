"""Qwen3-based generative reranker that scores document relevance via yes/no logits."""
# pylint: disable=import-outside-toplevel
import asyncio
import os
from typing import Optional

import torch
from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("RerankerService")

# Qwen3-Reranker prompt format (generative reranker: scores via yes/no logits)
_SYSTEM_PROMPT = (
    "Judge whether the Document meets the requirements based on the Query and the "
    'Instruct provided. Note that the answer can only be "yes" or "no".'
)
_INSTRUCTION = "Given a question, retrieve relevant passages that answer the question"

_PROMPT_TEMPLATE = (
    "<|im_start|>system\n{system}\n<|im_end|>\n"
    "<|im_start|>user\n"
    "<Instruct>: {instruction}\n"
    "<Query>: {query}\n\n"
    "<Document>: {document}\n"
    "<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n"
)


class RerankerService:  # pylint: disable=too-few-public-methods
    """Qwen3-0.6b generative reranker: scores candidate documents via yes/no token logits."""
    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._yes_token_id: int | None = None
        self._no_token_id: int | None = None
        self._load_lock: asyncio.Lock | None = None
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), f"../../{settings.MODELS_PATH}")
        )

    def _get_lock(self) -> asyncio.Lock:
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
                from transformers import AutoModelForCausalLM, AutoTokenizer

                def _load():
                    tokenizer = AutoTokenizer.from_pretrained(model_path)
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
                        dtype=(
                            torch.float16
                            if torch.cuda.is_available()
                            else torch.float32
                        ),
                    )
                    model.eval()
                    # Resolve yes/no token IDs once at load time
                    yes_id = tokenizer.encode("yes", add_special_tokens=False)[-1]
                    no_id = tokenizer.encode("no", add_special_tokens=False)[-1]
                    return tokenizer, model, yes_id, no_id

                loop = asyncio.get_event_loop()
                self._tokenizer, self._model, self._yes_token_id, self._no_token_id = (
                    await loop.run_in_executor(None, _load)
                )
                logger.info(
                    f"[Reranker] Loaded {settings.MODEL_RERANKER_LOCAL} from {model_path} "
                    f"(yes={self._yes_token_id}, no={self._no_token_id})"
                )
                return True
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(f"[Reranker] Failed to load model: {exc}")
                return False

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
    ) -> list[dict]:
        """
        Score and rank documents against a query using the local qwen3-reranker.

        Uses generative yes/no logit scoring (qwen3-reranker-0.6b style).
        Returns list of ``{index, text, relevance_score}`` sorted by score descending.
        Falls back to an empty list if the model is unavailable or inference fails.
        """
        if not documents:
            return []

        loaded = await self._ensure_loaded()
        if not loaded or self._model is None:
            return []

        tokenizer = self._tokenizer
        model = self._model
        yes_id = self._yes_token_id
        no_id = self._no_token_id

        def _run() -> list[dict]:
            results = []
            with torch.no_grad():
                for idx, doc in enumerate(documents):
                    prompt = _PROMPT_TEMPLATE.format(
                        system=_SYSTEM_PROMPT,
                        instruction=_INSTRUCTION,
                        query=query,
                        document=doc[:1500],  # cap to avoid OOM on long docs
                    )
                    inputs = tokenizer(
                        prompt,
                        return_tensors="pt",
                        truncation=True,
                        max_length=2048,
                    )
                    outputs = model(**inputs)
                    # Score is probability of "yes" at the next token position
                    last_logits = outputs.logits[0, -1, :]  # (vocab_size,)
                    yes_no_logits = torch.stack(
                        [last_logits[yes_id], last_logits[no_id]]
                    )
                    probs = torch.softmax(yes_no_logits, dim=0)
                    score = float(probs[0])  # P(yes)
                    results.append(
                        {"index": idx, "text": doc, "relevance_score": score}
                    )

            results.sort(key=lambda r: r["relevance_score"], reverse=True)
            if top_n is not None:
                results = results[:top_n]
            return results

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _run)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(f"[Reranker] Inference failed: {exc}")
            return []


reranker_service = RerankerService()
