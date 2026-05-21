"""Application configuration loaded from environment variables via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_KUZU_DB_PATH = str(REPO_ROOT / "data" / "kuzu" / "kuzu_graph")


class Settings(BaseSettings):
    """Pydantic settings that load all configuration from environment variables and .env files."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    PROJECT_NAME: str = "LiveOS"
    API_V1_STR: str = "/api/v1"

    # ── Kuzu (embedded graph database) ──────────────────────────────────────
    KUZU_DB_PATH: str = DEFAULT_KUZU_DB_PATH

    # ── LLM Provider ──────────────────────────────────────────────────────────
    # "local"  — any OpenAI-compatible server (LM Studio, Ollama, vLLM, etc.)
    #            set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL below
    # "ollama" / "lm_studio" — legacy aliases (still work; prefer "local")
    # "openai", "gemini", "anthropic", "huggingface" — cloud providers
    LLM_PROVIDER: str = "local"
    LLM_FALLBACK_PROVIDER: str | None = None  # Optional fallback if primary fails

    # ── Local / OpenAI-compatible server ─────────────────────────────────────
    # Used when LLM_PROVIDER is "local", "ollama", or "lm_studio".
    LLM_BASE_URL: str = (
        "http://127.0.0.1:1234"  # LM Studio default; Ollama: http://127.0.0.1:11434
    )
    LLM_API_KEY: str = "lm-studio"  # Ollama: "ollama"
    LLM_MODEL: str = "google/gemma-4-e4b"  # model name as shown in your server
    LLM_KEEP_ALIVE: str = "10m"  # Keep model loaded after last request
    # Response format for local JSON extraction ("text", "json_object", "auto").
    # LM Studio no longer accepts "json_object" (returns 400) — use "text".
    LLM_RESPONSE_FORMAT: str = "text"

    # ── Universal model overrides (provider-agnostic) ─────────────────────────
    # Set these instead of provider-specific keys (GEMINI_MODEL, LLM_MODEL, etc.).
    # Works regardless of which provider is active.
    #   CHAT_MODEL=gemini-2.5-pro       → used for chat/retrieval
    #   INGESTION_MODEL=gemma-4-e4b     → used for extraction/entity reasoning
    # If blank, falls back to the provider-specific key (GEMINI_MODEL, LLM_MODEL, etc.)
    CHAT_MODEL: str | None = None
    INGESTION_MODEL: str | None = None

    # ── Ingestion overrides (extraction / entity reasoning) ───────────────────
    # Leave blank to share the main LLM settings above.
    # Set any of these to route ingestion to a different provider or server.
    INGESTION_PROVIDER: str | None = (
        None  # e.g. "gemini", "local" — defaults to LLM_PROVIDER
    )
    INGESTION_BASE_URL: str | None = (
        None  # defaults to LLM_BASE_URL (local providers only)
    )
    INGESTION_API_KEY: str | None = None  # defaults to LLM_API_KEY
    # Provider-specific model fallbacks (used when INGESTION_MODEL is not set)
    INGESTION_LLM_MODEL: str | None = "google/gemma-4-e4b"  # for local/ollama providers
    INGESTION_GEMINI_MODEL: str | None = None  # for Gemini provider

    # ── Embeddings ────────────────────────────────────────────────────────────
    # "local" / "ollama" / "lm_studio" — any OpenAI-compatible /v1/embeddings server
    # "auto" — follows LLM_PROVIDER
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
    RERANKER_SCORE_THRESHOLD: float = (
        0.05  # Drop candidates below this score after top_k slice
    )
    GRAPH_EXPAND_TOP_NEIGHBORS: int = (
        10  # Keep top N neighbors per expansion pass after individual ranking
    )
    GRAPH_EXPAND_SCORE_THRESHOLD: float = (
        0  # Drop expansion neighbors below this score after top-N slice
    )
    MAX_POTENTIAL_QUESTIONS: int = 10
    MAX_LOOP_ITERATIONS: int = 10
    # When True: strict benchmark prompting (exact fact extraction, terse output).
    # When False: verbose, natural-language answers for general KB use.
    BENCHMARK_MODE: bool = False
    FALLBACK_MODE: str = "none"  # "none" | "web" | "self"
    TAVILY_API_KEY: str | None = None

    # ── Qdrant ───────────────────────────────────────────────────────────────
    QDRANT_HOST: str = (
        "qdrant"  # Docker service name; override to 127.0.0.1 for local dev
    )
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION_NODE_CORES: str = "node_cores"
    QDRANT_COLLECTION_NODE_RELATIONSHIPS: str = "node_relationships"
    QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS: str = "node_isolated_contexts"

    # ── Typesense ─────────────────────────────────────────────────────────────
    TYPESENSE_HOST: str = (
        "typesense"  # Docker service name; override to 127.0.0.1 for local dev
    )
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

    # Google Gemini
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str | None = None  # e.g. "gemini-2.5-pro"

    # Anthropic Claude
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str | None = None  # e.g. "claude-3-5-sonnet-20241022"

    # HuggingFace Inference API
    HUGGINGFACE_API_KEY: str | None = None
    HUGGINGFACE_MODEL: str | None = None  # e.g. "meta-llama/Llama-3.3-70B-Instruct"

    # ── Storage (R2 / RustFS) ─────────────────────────────────────────────────
    BUCKET_NAME: str = "liveos-assets"
    BUCKET_ACCESS_KEY_ID: str = "rustfsadmin"
    BUCKET_SECRET_ACCESS_KEY: str = "rustfsadmin"
    R2_ENDPOINT_URL: str = (
        "http://rustfs:9000"  # Docker service name; override to http://localhost:9000 for local dev
    )
    FILES_URL: str = "http://rustfs:9000/liveos-assets"
    BUCKET_TOKEN: str | None = None

    # ── Database (Postgres) ───────────────────────────────────────────────────
    # Defaults use the Docker service name. Override in .env for local dev.
    DATABASE_TRANSACTION_POOLER_URL: str | None = (
        "postgresql://user:password@postgres:5432/liveos"
    )
    DATABASE_SESSION_POOLER_URL: str | None = (
        "postgresql://user:password@postgres:5432/liveos"
    )
    DATABASE_DIRECT_CONNECTION_URL: str | None = (
        "postgresql://user:password@postgres:5432/liveos"
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "DEBUG"  # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"

    # ── Ingestion Concurrency ─────────────────────────────────────────────────
    # Maximum concurrent LLM calls inside the ingestion agent.
    # Semaphore(1) was the original Gemini rate-limit guard; for local providers
    # (Ollama / LM Studio / OpenAI) a higher value enables real parallelism.
    # Change via .env: INGESTION_AGENT_CONCURRENCY=4
    INGESTION_AGENT_CONCURRENCY: int = 2  # override to >1 for non-Gemini providers

    # ── Embedding Instructions ────────────────────────────────────────────────
    # When True, uses LLM to generate query-specific embedding instructions for
    # Qwen3 models. Adds ~0.1-0.2 s per query but may improve recall precision.
    USE_DYNAMIC_EMBEDDING_INSTRUCTION: bool = True


settings = Settings()
