from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_KUZU_DB_PATH = str(REPO_ROOT / "data" / "kuzu" / "kuzu_graph")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    PROJECT_NAME: str = "LiveOS Brain"
    API_V1_STR: str = "/api/v1"

    # ── Kuzu (embedded graph database) ──────────────────────────────────────
    KUZU_DB_PATH: str = DEFAULT_KUZU_DB_PATH

    # ── LLM Provider ──────────────────────────────────────────────────────────
    # "ollama", "lm_studio", "openai", "gemini", "anthropic", "huggingface"
    LLM_PROVIDER: str = "ollama"
    LLM_FALLBACK_PROVIDER: str | None = None  # Optional fallback if primary fails

    # Local / OpenAI-compatible LLM (Ollama, LM Studio, or any v1 endpoint)
    # These are used when LLM_PROVIDER is "ollama" or "lm_studio".
    LLM_BASE_URL: str = (
        "http://127.0.0.1:11434"  # LM Studio default: http://127.0.0.1:1234
    )
    LLM_API_KEY: str = "ollama"  # LM Studio default: "lm-studio"
    LLM_MODEL: str = "gemma4:latest"  # LM Studio example: "google/gemma-3-4b"
    # Separate model for ingestion (extraction, entity reasoning). If None, falls back to LLM_MODEL.
    # gemma3:4b works well for structured extraction; gemma4 is better for chat/retrieval.
    INGESTION_LLM_MODEL: str | None = "gemma3:4b"
    # Gemini-specific ingestion model override. If None, falls back to GEMINI_MODEL.
    # e.g. use "gemini-2.0-flash" for ingestion vs "gemini-2.5-pro" for chat.
    INGESTION_GEMINI_MODEL: str | None = None
    LLM_KEEP_ALIVE: str = "10m"  # Keep model loaded for 20 minutes after last request
    # Response format for local JSON extraction ("text", "json_object", "auto").
    # LM Studio no longer accepts "json_object" (returns 400) — use "text".
    LLM_RESPONSE_FORMAT: str = "text"

    # ── Embeddings ────────────────────────────────────────────────────────────
    # "ollama", "lm_studio", or "auto" (follows LLM_PROVIDER)
    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_BASE_URL: str = (
        "http://localhost:11434"  # LM Studio: http://127.0.0.1:1234
    )
    EMBEDDING_API_KEY: str = "ollama"  # LM Studio: "lm-studio"
    EMBEDDING_MODEL: str = (
        "qwen3-embedding:0.6b"  # LM Studio: "text-embedding-qwen3-embedding-8b"
    )
    EMBEDDING_DIMENSIONS: int = 1024

    # ── Retrieval / Pipeline Controls ────────────────────────────────────────
    VECTOR_SIMILARITY_THRESHOLD: float = 0.50
    # When the reranker is enabled, vector hits above this score are passed to
    # the reranker. Using the original natural-language question for embedding
    # (not the reformulated sub-query) means 0.45 safely includes the target
    # node while keeping the candidate pool small enough for fast reranking.
    VECTOR_PRE_RERANK_THRESHOLD: float = 0.45
    COMMUNITY_RECOMPUTE_BATCH_SIZE: int = 100
    RERANKER_ENABLED: bool = True
    RERANKER_TOP_K: int = 10  # Candidates passed to LLM after reranking
    MAX_POTENTIAL_QUESTIONS: int = 10
    MAX_LOOP_ITERATIONS: int = 10
    FALLBACK_MODE: str = "none"  # "none" | "web" | "self"
    TAVILY_API_KEY: str | None = None

    # ── Qdrant ───────────────────────────────────────────────────────────────
    QDRANT_HOST: str = "127.0.0.1"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION_NODE_CORES: str = "node_cores"
    QDRANT_COLLECTION_NODE_RELATIONSHIPS: str = "node_relationships"
    QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS: str = "node_isolated_contexts"

    # ── Typesense ─────────────────────────────────────────────────────────────
    TYPESENSE_HOST: str = "127.0.0.1"
    TYPESENSE_PORT: int = 8108
    TYPESENSE_API_KEY: str = "liveos-dev-key"
    TYPESENSE_COLLECTION_NAME: str = "liveos_nodes"

    # ── Vision / Audio Models ─────────────────────────────────────────────────
    MODEL_FLORENCE_HF: str = "microsoft/Florence-2-large"
    MODEL_FLORENCE_LOCAL: str = "florence-2-large"
    MODEL_WHISPER_HF: str = "openai/whisper-large-v3-turbo"
    MODEL_WHISPER_LOCAL: str = "whisper-large-v3-turbo"
    # MODEL_RERANKER_LOCAL: str = "jina-reranker-v2-base-multilingual"
    MODEL_RERANKER_LOCAL: str = "qwen3-reranker-0.6b"

    # Model storage path (relative to backend root)
    MODELS_PATH: str = "models"

    # ── Cloud LLM Providers ───────────────────────────────────────────────────
    # OpenAI
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str | None = None  # e.g. "gpt-4o-2024-08-06"
    OPENAI_MODEL_REASONING: str | None = None  # e.g. "o1-mini"

    # Google Gemini
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str | None = None  # e.g. "gemini-2.5-pro"

    # Anthropic Claude
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str | None = None  # e.g. "claude-3-5-sonnet-20241022"

    # HuggingFace Inference API
    HUGGINGFACE_API_KEY: str | None = None
    HUGGINGFACE_MODEL: str | None = None  # e.g. "meta-llama/Llama-3.3-70B-Instruct"

    # ── Storage (R2 / MinIO) ──────────────────────────────────────────────────
    BUCKET_NAME: str = "liveos-assets"
    BUCKET_ACCESS_KEY_ID: str = "minioadmin"
    BUCKET_SECRET_ACCESS_KEY: str = "minioadmin"
    R2_ENDPOINT_URL: str = "http://localhost:9000"
    FILES_URL: str = "http://localhost:9000/liveos-assets"
    BUCKET_TOKEN: str | None = None

    # ── Database (Postgres) ───────────────────────────────────────────────────
    # Using 127.0.0.1 to avoid IPv6 issues; port 5433 to avoid local Postgres conflict.
    DATABASE_TRANSACTION_POOLER_URL: str | None = (
        "postgresql://user:password@127.0.0.1:5433/liveos"
    )
    DATABASE_SESSION_POOLER_URL: str | None = (
        "postgresql://user:password@127.0.0.1:5433/liveos"
    )
    DATABASE_DIRECT_CONNECTION_URL: str | None = (
        "postgresql://user:password@127.0.0.1:5433/liveos"
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "DEBUG"  # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"

    # ── Ingestion Concurrency ─────────────────────────────────────────────────
    # Maximum concurrent LLM calls inside the ingestion agent.
    # Semaphore(1) was the original Gemini rate-limit guard; for local providers
    # (Ollama / LM Studio / OpenAI) a higher value enables real parallelism.
    # Change via .env: INGESTION_AGENT_CONCURRENCY=4
    INGESTION_AGENT_CONCURRENCY: int = 2  # override to >1 for non-Gemini providers

    # ── Benchmark Mode ────────────────────────────────────────────────────────
    # When True, uses factual/objective prompts instead of personal narrative.
    # Set to True only when testing with external datasets (HotpotQA, MuSiQue).
    BENCHMARK_MODE: bool = True

    # ── Embedding Instructions ────────────────────────────────────────────────
    # When True, uses LLM to generate query-specific embedding instructions for
    # Qwen3 models. Adds ~0.1-0.2 s per query but may improve recall precision.
    USE_DYNAMIC_EMBEDDING_INSTRUCTION: bool = True


settings = Settings()
