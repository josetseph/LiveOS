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

    # LLM Provider Selection
    LLM_PROVIDER: str = (
        "ollama"  # "ollama", "lm_studio", "openai", "gemini", "anthropic"
    )
    LLM_FALLBACK_PROVIDER: str | None = None  # Optional fallback if primary fails

    # LLM (Local - Ollama)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma3:4b"
    OLLAMA_KEEP_ALIVE: str = "-1"  # -1 = keep loaded indefinitely

    # Legacy task-specific aliases (kept for backward compatibility)
    MODEL_EXTRACTION: str = OLLAMA_MODEL
    MODEL_ARCHITECT: str = OLLAMA_MODEL
    MODEL_SUMMARIZATION: str = OLLAMA_MODEL
    MODEL_BRAIN: str = OLLAMA_MODEL
    MODEL_REASONING: str = OLLAMA_MODEL
    # Embeddings can use a different backend than chat/reasoning:
    # "ollama", "lm_studio", "mlx", or "auto" (follows LLM_PROVIDER)
    # "mlx": runs the model locally via mlx-lm (Apple Silicon, no server required)
    EMBEDDING_PROVIDER: str = "ollama"
    MODEL_EMBEDDING: str = "qwen3-embedding:8b"
    EMBEDDING_DIMENSIONS: int = 4096
    # MLX local embedding model — subfolder name under MODELS_PATH
    # Used only when EMBEDDING_PROVIDER="mlx"
    MLX_EMBEDDING_MODEL: str = "Qwen3-Embedding-8B-4bit-DWQ"

    # LLM (Local - LM Studio, OpenAI-compatible API)
    LM_STUDIO_BASE_URL: str = "http://127.0.0.1:1234"
    LM_STUDIO_API_KEY: str = "lm-studio"
    LM_STUDIO_MODEL: str = "google/gemma-3-4b"
    LM_STUDIO_KEEP_ALIVE: str = "-1"  # Use max/indefinite keep-alive when supported
    LM_STUDIO_MODEL_EMBEDDING: str = "text-embedding-qwen3-embedding-8b"
    # "auto" tries json_schema, then json_object, then text. You can also set:
    # "json_schema", "json_object", or "text"
    # Default is "text" — LM Studio no longer accepts "json_object" (returns 400).
    LM_STUDIO_RESPONSE_FORMAT: str = "text"

    # Hugging Face Models (Transformers)
    MODEL_FLORENCE_HF: str = "microsoft/Florence-2-large"
    MODEL_FLORENCE_LOCAL: str = "florence-2-large"
    MODEL_WHISPER_HF: str = "openai/whisper-large-v3-turbo"
    MODEL_WHISPER_LOCAL: str = "whisper-large-v3-turbo"

    # Model Storage Path
    MODELS_PATH: str = "models"  # Relative to backend root

    # LLM (Cloud Providers)
    # OpenAI
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str | None = (
        None  # Supports structured outputs. e.g., "gpt-4o-2024-08-06"
    )
    OPENAI_MODEL_REASONING: str | None = (
        None  # For complex reasoning tasks. e.g., "o1-mini"
    )

    # Google Gemini
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str | None = None  # Supports JSON schema. eg., "gemini-3-pro"

    # Anthropic Claude
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str | None = None  # e.g., "claude-3"

    # Storage (R2 / MinIO)
    BUCKET_NAME: str = "liveos-assets"
    BUCKET_ACCESS_KEY_ID: str = "minioadmin"
    BUCKET_SECRET_ACCESS_KEY: str = "minioadmin"
    R2_ENDPOINT_URL: str = "http://localhost:9000"
    FILES_URL: str = "http://localhost:9000/liveos-assets"  # Direct link for now
    BUCKET_TOKEN: str | None = None

    # Database (Postgres)
    # Default to local docker if not set
    # Using 127.0.0.1 to avoid IPv6 resolution issues on Mac
    # Using Port 5433 to avoid conflict with local system Postgres
    DATABASE_TRANSACTION_POOLER_URL: str | None = (
        "postgresql://user:password@127.0.0.1:5433/liveos"
    )
    DATABASE_SESSION_POOLER_URL: str | None = (
        "postgresql://user:password@127.0.0.1:5433/liveos"
    )
    DATABASE_DIRECT_CONNECTION_URL: str | None = (
        "postgresql://user:password@127.0.0.1:5433/liveos"
    )

    # Logging
    LOG_LEVEL: str = "DEBUG"  # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"

    # Benchmark Mode
    # When True, uses factual/objective prompts instead of personal "You" narrative
    # This is for testing with external datasets (HotpotQA, MuSiQue) where personal framing is inappropriate
    BENCHMARK_MODE: bool = True

    # Embedding Configuration
    # Dynamic Instruction Generation: When True, uses LLM to generate query-specific
    # embedding instructions for Qwen3 models. Adds ~0.1-0.2s per query but may improve precision.
    # When False, uses static PKM-specific instruction.
    USE_DYNAMIC_EMBEDDING_INSTRUCTION: bool = True


settings = Settings()
