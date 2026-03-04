import os
from langchain_ollama import OllamaEmbeddings
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
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower()
        configured_embedding_provider = settings.EMBEDDING_PROVIDER.lower().strip()
        if configured_embedding_provider == "auto":
            self.embedding_provider = (
                "lm_studio" if self.provider == "lm_studio" else "ollama"
            )
        else:
            self.embedding_provider = configured_embedding_provider

        self.embedding_model = None

        if self.embedding_provider == "lm_studio":
            embedding_model = self._resolve_lm_studio_embedding_model(
                settings.LM_STUDIO_MODEL_EMBEDDING
            )
            self.embedding_model = embedding_model

            self.embeddings = OpenAIEmbeddings(
                model=embedding_model,
                base_url=f"{settings.LM_STUDIO_BASE_URL.rstrip('/')}/v1",
                api_key=settings.LM_STUDIO_API_KEY,
                # Send raw text to LM Studio embeddings endpoint without
                # tokenizer-based pre-processing (avoids HF tokenizer lookup).
                check_embedding_ctx_length=False,
            )
        elif self.embedding_provider == "ollama":
            # Use Ollama embeddings, independent of chat/reasoning provider.
            # keep_alive=-1 tells Ollama to never unload this model from VRAM
            self.embeddings = OllamaEmbeddings(
                base_url=settings.OLLAMA_BASE_URL,
                model=settings.MODEL_EMBEDDING,
                keep_alive=settings.OLLAMA_KEEP_ALIVE,
            )
            self.embedding_model = settings.MODEL_EMBEDDING
        elif self.embedding_provider == "mlx":
            # MLX local inference — Apple Silicon, no server required.
            # Model lives at MODELS_PATH/MLX_EMBEDDING_MODEL (e.g. models/Qwen3-Embedding-8B-4bit-DWQ)
            self.embedding_model = settings.MLX_EMBEDDING_MODEL
            self._mlx_model_path = os.path.join(
                settings.MODELS_PATH, settings.MLX_EMBEDDING_MODEL
            )
            # Lazy-loaded on first call to avoid slowing startup
            self._mlx_model = None
            self._mlx_tokenizer = None
            self.embeddings = None  # Not used for MLX; direct inference instead
        else:
            raise ValueError(
                f"Unsupported EMBEDDING_PROVIDER: {settings.EMBEDDING_PROVIDER}"
            )

        logger.info(
            f"[Embedding] Provider: {self.embedding_provider} | Model: {self.embedding_model}"
        )

        # Qwen3-Embedding instruction prefix for QUERIES (not documents)
        # This is CRITICAL for Qwen3 series - without it, performance drops significantly
        # Tailored for Personal Knowledge Management (PKM) retrieval
        self.query_instruction = "Instruct: Given a question about personal knowledge, notes, or experiences, retrieve relevant information from the knowledge base that helps answer the question\nQuery: "

        # Check if current model is Qwen3 to apply instruction.
        # Use only the leaf folder/model name (not a full path) so the substring
        # check works regardless of MODELS_PATH depth.
        model_name_lower = os.path.basename(self.embedding_model).lower()
        self.is_qwen3 = "qwen3" in model_name_lower

    def _resolve_lm_studio_embedding_model(self, configured_model: str | None) -> str:
        """Resolve common aliases and prefer an available downloaded LM Studio model ID."""
        if not configured_model:
            raise ValueError(
                "LM_STUDIO_MODEL_EMBEDDING is required when using lm_studio"
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
            client = OpenAI(
                base_url=f"{settings.LM_STUDIO_BASE_URL.rstrip('/')}/v1",
                api_key=settings.LM_STUDIO_API_KEY,
                timeout=30.0,
            )
            available = [m.id for m in client.models.list().data]
            for candidate in candidates:
                if candidate in available:
                    if candidate != model:
                        logger.warning(
                            f"[LM Studio] Embedding model '{configured_model}' not found, using '{candidate}'"
                        )
                    return candidate

            prefixed = []
            for candidate in candidates:
                prefixed.extend(
                    [mid for mid in available if mid.startswith(f"{candidate}@")]
                )
            if prefixed:
                logger.warning(
                    f"[LM Studio] Embedding model '{configured_model}' not found, using '{prefixed[0]}'"
                )
                return prefixed[0]

            contains = []
            for candidate in candidates:
                contains.extend([mid for mid in available if candidate in mid])
            if contains:
                logger.warning(
                    f"[LM Studio] Embedding model '{configured_model}' not found, using '{contains[0]}'"
                )
                return contains[0]
        except Exception as e:
            logger.warning(
                f"[LM Studio] Could not list models for embedding resolution: {e}"
            )

        logger.warning(
            f"[LM Studio] Using configured embedding model '{configured_model}' as-is"
        )
        return model

    def _raise_lm_studio_embedding_error(self, exc: Exception) -> None:
        """Map opaque LM Studio 400s to an actionable setup error."""
        if self.embedding_provider != "lm_studio":
            return
        message = str(exc)
        if "No models loaded" in message:
            raise RuntimeError(
                "LM Studio returned 'No models loaded' for embeddings. "
                f"Load an embedding model first (for example: `lms load {self.embedding_model}`), "
                "or load it in the LM Studio Developer page and retry ingestion."
            ) from exc

    def _mlx_load(self) -> None:
        """Lazy-load the MLX model and tokenizer on first use."""
        if self._mlx_model is None:
            from mlx_lm import load  # type: ignore

            logger.info(
                f"[MLX Embedding] Loading model from '{self._mlx_model_path}'..."
            )
            self._mlx_model, self._mlx_tokenizer = load(self._mlx_model_path)
            logger.info("[MLX Embedding] Model loaded and ready.")

    def _mlx_embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of strings in a single batched MLX forward pass.

        Uses tokenizer padding so all sequences are the same length, then
        extracts the last-token (EOS) hidden state and L2-normalises.
        """
        import mlx.core as mx  # type: ignore
        import numpy as np  # type: ignore

        self._mlx_load()

        # mlx_lm's TokenizerWrapper only supports .encode()/.decode() — it is
        # NOT callable with HuggingFace-style kwargs (padding=True, etc.).
        # We manually encode each text, ensure EOS is present, then left-pad
        # so that index -1 is ALWAYS the true last (EOS) token for every row.
        pad_id = self._mlx_tokenizer.pad_token_id
        if pad_id is None:
            pad_id = self._mlx_tokenizer.eos_token_id  # fallback: pad with EOS

        token_lists = []
        for text in texts:
            tokens = self._mlx_tokenizer.encode(text)
            if tokens[-1] != self._mlx_tokenizer.eos_token_id:
                tokens.append(self._mlx_tokenizer.eos_token_id)
            token_lists.append(tokens)

        # Left-pad to the length of the longest sequence.
        max_len = max(len(t) for t in token_lists)
        padded = np.array(
            [[pad_id] * (max_len - len(t)) + t for t in token_lists],
            dtype=np.int32,
        )

        input_ids = mx.array(padded)  # [batch, seq_len]

        # Forward pass through the transformer backbone.
        # mlx_lm models expose `.model` as the bare transformer (no LM head).
        output = self._mlx_model.model(input_ids)  # [batch, seq_len, dim]

        # Last-token pooling — safe with left-padding because EOS is always
        # at position -1 for every row.
        embeddings = output[:, -1, :]  # [batch, dim]

        # L2 normalise (+ epsilon for numerical stability).
        norm = mx.sqrt(mx.sum(mx.square(embeddings), axis=-1, keepdims=True))
        normalized = embeddings / (norm + 1e-9)  # [batch, dim]

        mx.eval(normalized)
        return normalized.tolist()

    def embed_query(self, text: str, custom_instruction: str = None) -> list[float]:
        """
        Embed a search query with instruction prefix for Qwen3 models.

        For Qwen3-Embedding models, prepends instruction to align query representation
        with passage representation space. This is the "Instruction Paradox" fix.

        Args:
            text: The query text to embed
            custom_instruction: Optional LLM-generated instruction (overrides default)
        """
        try:
            if self.embedding_provider == "mlx":
                if self.is_qwen3:
                    instruction = (
                        custom_instruction
                        if custom_instruction
                        else self.query_instruction
                    )
                    text = instruction + text
                return self._mlx_embed_batch([text])[0]
            if self.is_qwen3:
                instruction = (
                    custom_instruction if custom_instruction else self.query_instruction
                )
                prefixed_text = instruction + text
                return self.embeddings.embed_query(prefixed_text)
            return self.embeddings.embed_query(text)
        except Exception as exc:
            self._raise_lm_studio_embedding_error(exc)
            raise

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed documents/passages WITHOUT instruction prefix.

        Only queries get the instruction prefix, not the documents being indexed.
        """
        try:
            if self.embedding_provider == "mlx":
                return self._mlx_embed_batch(texts)
            return self.embeddings.embed_documents(texts)
        except Exception as exc:
            self._raise_lm_studio_embedding_error(exc)
            raise

    def get_dimension(self) -> int:
        """
        Returns the dimension of the embedding model.
        Note: Uses embed_documents (not embed_query) to avoid instruction prefix in dimension test.
        """
        try:
            dummy_vec = self.embed_documents(["test"])[0]
            return len(dummy_vec)
        except Exception as exc:
            self._raise_lm_studio_embedding_error(exc)
            raise


embedding_service = EmbeddingService()
