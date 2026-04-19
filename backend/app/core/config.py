from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    PROJECT_NAME: str = "LiveOS Brain"
    API_V1_STR: str = "/api/v1"

    # Neo4j
    NEO4J_URI: str = "bolt://127.0.0.1:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # ── LLM Provider ──────────────────────────────────────────────────────────
    # "ollama", "lm_studio", "openai", "gemini", "anthropic"
    LLM_PROVIDER: str = "ollama"
    LLM_FALLBACK_PROVIDER: str | None = None  # Optional fallback if primary fails

    # Local / OpenAI-compatible LLM (Ollama, LM Studio, or any v1 endpoint)
    # These are used when LLM_PROVIDER is "ollama" or "lm_studio".
    LLM_BASE_URL: str = (
        "http://192.168.10.182:11434"  # LM Studio default: http://127.0.0.1:1234
    )
    LLM_API_KEY: str = "ollama"  # LM Studio default: "lm-studio"
    LLM_MODEL: str = "gemma3:4b"  # LM Studio example: "google/gemma-3-4b"
    LLM_KEEP_ALIVE: str = "-1"  # Keep model loaded indefinitely
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
    VECTOR_SIMILARITY_THRESHOLD: float = 0.5
    COMMUNITY_RECOMPUTE_BATCH_SIZE: int = 100
    RERANKER_ENABLED: bool = False
    MAX_POTENTIAL_QUESTIONS: int = 10
    FALLBACK_MODE: str = "none"  # "none" | "web" | "self"
    TAVILY_API_KEY: str | None = None

    # ── Qdrant ───────────────────────────────────────────────────────────────
    QDRANT_HOST: str = "127.0.0.1"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION_NODE_CORES: str = "node_cores"
    QDRANT_COLLECTION_NODE_FACTS: str = "node_facts"
    QDRANT_COLLECTION_NODE_QUESTIONS: str = "node_questions"
    QDRANT_COLLECTION_NODE_RELATIONSHIPS: str = "node_relationships"
    QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS: str = "node_isolated_contexts"

    # ── Elasticsearch ────────────────────────────────────────────────────────
    ELASTICSEARCH_HOST: str = "127.0.0.1"
    ELASTICSEARCH_PORT: int = 9200
    ELASTICSEARCH_INDEX_NAME: str = "liveos_nodes"

    # ── Vision / Audio Models ─────────────────────────────────────────────────
    MODEL_FLORENCE_HF: str = "microsoft/Florence-2-large"
    MODEL_FLORENCE_LOCAL: str = "florence-2-large"
    MODEL_WHISPER_HF: str = "openai/whisper-large-v3-turbo"
    MODEL_WHISPER_LOCAL: str = "whisper-large-v3-turbo"
    MODEL_RERANKER_LOCAL: str = "jina-reranker-v2-base-multilingual"

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

    # ── Benchmark Mode ────────────────────────────────────────────────────────
    # When True, uses factual/objective prompts instead of personal narrative.
    # Set to True only when testing with external datasets (HotpotQA, MuSiQue).
    BENCHMARK_MODE: bool = True

    # ── Embedding Instructions ────────────────────────────────────────────────
    # When True, uses LLM to generate query-specific embedding instructions for
    # Qwen3 models. Adds ~0.1-0.2 s per query but may improve recall precision.
    USE_DYNAMIC_EMBEDDING_INSTRUCTION: bool = True


settings = Settings()
