import os
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI
from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("LLMService")


def compute_cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity score (0 to 1)
    """
    import math

    # Dot product
    dot_product = sum(a * b for a, b in zip(vec1, vec2))

    # Magnitudes
    mag1 = math.sqrt(sum(a * a for a in vec1))
    mag2 = math.sqrt(sum(b * b for b in vec2))

    # Avoid division by zero
    if mag1 == 0 or mag2 == 0:
        return 0.0

    return dot_product / (mag1 * mag2)


class EmbeddingService:
    """
    Provider-agnostic embedding service.

    Supported EMBEDDING_PROVIDER values:
      "ollama"    – Ollama's /v1/embeddings (OpenAI-compatible, no API key)
      "lm_studio" – LM Studio's /v1/embeddings (OpenAI-compatible)
      "auto"      – follows LLM_PROVIDER (defaults to "ollama" for non-lm_studio providers)

    All local providers share the same config keys:
      EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL
    """

    def __init__(self):
        # Resolve effective embedding provider
        configured = settings.EMBEDDING_PROVIDER.lower().strip()
        if configured == "auto":
            self.embedding_provider = (
                "lm_studio"
                if settings.LLM_PROVIDER.lower() == "lm_studio"
                else "ollama"
            )
        else:
            self.embedding_provider = configured

        if self.embedding_provider not in ("ollama", "lm_studio"):
            raise ValueError(
                f"Unsupported EMBEDDING_PROVIDER: '{settings.EMBEDDING_PROVIDER}'. "
                "Supported: 'ollama', 'lm_studio', 'auto'."
            )

        # For LM Studio, attempt to auto-resolve the exact loaded model ID.
        # For Ollama, use the configured model name directly.
        if self.embedding_provider == "lm_studio":
            self.embedding_model = self._resolve_lm_studio_embedding_model(
                settings.EMBEDDING_MODEL
            )
        else:
            self.embedding_model = settings.EMBEDDING_MODEL

        # Both providers speak the OpenAI /v1/embeddings protocol.
        base_url = f"{settings.EMBEDDING_BASE_URL.rstrip('/')}/v1"
        self.embeddings = OpenAIEmbeddings(
            model=self.embedding_model,
            base_url=base_url,
            api_key=settings.EMBEDDING_API_KEY,
            # Disables HuggingFace tokenizer pre-processing so raw text is sent
            # directly to the server (required for LM Studio; harmless for Ollama).
            check_embedding_ctx_length=False,
        )

        logger.info(
            f"[Embedding] Provider: {self.embedding_provider} | "
            f"URL: {base_url} | Model: {self.embedding_model}"
        )

        # Qwen3-Embedding instruction prefix for QUERIES (not documents).
        # Critical for Qwen3 series — omitting it degrades recall significantly.
        # Exact prefix specified in plan: "Instruct: Given a question, retrieve relevant context.\nQuery: "
        self.query_instruction = (
            "Instruct: Given a question, retrieve relevant context.\nQuery: "
        )

        # Detect Qwen3 by leaf model name so MODELS_PATH depth doesn't matter.
        model_name_lower = os.path.basename(self.embedding_model).lower()
        self.is_qwen3 = "qwen3" in model_name_lower

    # ── Model resolution ──────────────────────────────────────────────────────

    def _resolve_lm_studio_embedding_model(self, configured_model: str | None) -> str:
        """
        Resolve common aliases and prefer an available downloaded LM Studio model ID.

        Falls back to the configured value as-is if the server is unreachable.
        """
        if not configured_model:
            raise ValueError(
                "EMBEDDING_MODEL is required when using EMBEDDING_PROVIDER=lm_studio"
            )

        model = configured_model.strip()
        alias_map = {
            "qwen3-embedding:0.6b": "qwen3-embedding-0.6b-dwq",
            "qwen3-embedding-0.6b": "qwen3-embedding-0.6b-dwq",
            "text-embedding-qwen3-embedding-0.6b": "text-embedding-qwen3-embedding-0.6b",
        }
        model = alias_map.get(model, model)
        candidates = [model]
        if model == "qwen3-embedding-0.6b-dwq":
            candidates.append("text-embedding-qwen3-embedding-0.6b")
        if model.startswith("qwen3-embedding-") and model.endswith("-dwq"):
            candidates.append(f"text-embedding-{model.replace('-dwq', '')}")

        try:
            base_url = f"{settings.EMBEDDING_BASE_URL.rstrip('/')}/v1"
            client = OpenAI(
                base_url=base_url,
                api_key=settings.EMBEDDING_API_KEY,
                timeout=30.0,
            )
            available = [m.id for m in client.models.list().data]
            for candidate in candidates:
                if candidate in available:
                    if candidate != configured_model:
                        logger.warning(
                            f"[Embedding] Model '{configured_model}' not found, "
                            f"using '{candidate}'"
                        )
                    return candidate

            # Try quant-suffix variants (e.g. model@4bit)
            prefixed = [
                mid
                for candidate in candidates
                for mid in available
                if mid.startswith(f"{candidate}@")
            ]
            if prefixed:
                logger.warning(
                    f"[Embedding] Model '{configured_model}' not found, "
                    f"using '{prefixed[0]}'"
                )
                return prefixed[0]

            # Substring match
            contains = [
                mid for candidate in candidates for mid in available if candidate in mid
            ]
            if contains:
                logger.warning(
                    f"[Embedding] Model '{configured_model}' not found, "
                    f"using '{contains[0]}'"
                )
                return contains[0]

        except Exception as e:
            logger.warning(f"[Embedding] Could not list models for resolution: {e}")

        logger.warning(f"[Embedding] Using configured model '{configured_model}' as-is")
        return model

    def _raise_lm_studio_embedding_error(self, exc: Exception) -> None:
        """Map opaque LM Studio 400s to an actionable setup error."""
        if self.embedding_provider != "lm_studio":
            return
        if "No models loaded" in str(exc):
            raise RuntimeError(
                "LM Studio returned 'No models loaded' for embeddings. "
                f"Load an embedding model first (e.g. `lms load {self.embedding_model}`), "
                "or load it via the LM Studio Developer page and retry."
            ) from exc

    # ── Public API ────────────────────────────────────────────────────────────

    def embed_query(
        self, text: str, custom_instruction: str | None = None
    ) -> list[float]:
        """
        Embed a search query with instruction prefix for Qwen3 models.

        For Qwen3-Embedding models, prepends an instruction to align the query
        representation with the passage space (the "Instruction Paradox" fix).

        Args:
            text: The query text to embed.
            custom_instruction: Optional LLM-generated instruction (overrides default).
        """
        try:
            if self.is_qwen3:
                instruction = custom_instruction or self.query_instruction
                text = instruction + text
            return self.embeddings.embed_query(text)
        except Exception as exc:
            self._raise_lm_studio_embedding_error(exc)
            raise

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed documents/passages WITHOUT instruction prefix.

        Only queries get the instruction prefix; documents are embedded as-is.
        """
        try:
            return self.embeddings.embed_documents(texts)
        except Exception as exc:
            self._raise_lm_studio_embedding_error(exc)
            raise

    def get_dimension(self) -> int:
        """
        Returns the dimension of the embedding model.

        Uses embed_documents (not embed_query) to avoid instruction prefix noise.
        """
        try:
            dummy_vec = self.embed_documents(["test"])[0]
            return len(dummy_vec)
        except Exception as exc:
            self._raise_lm_studio_embedding_error(exc)
            raise


embedding_service = EmbeddingService()
