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
    LLM_PROVIDER: str = "gemini"  # "ollama", "openai", "gemini", "anthropic"
    LLM_FALLBACK_PROVIDER: str | None = None  # Optional fallback if primary fails

    # LLM (Local - Ollama)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    MODEL_EXTRACTION: str = "gemma3:4b"
    MODEL_ARCHITECT: str = "gemma3:4b"
    MODEL_SUMMARIZATION: str = "gemma3:4b"
    MODEL_BRAIN: str = "gemma3:4b"
    MODEL_REASONING: str = "gemma3:4b"
    MODEL_EMBEDDING: str = "qwen3-embedding:0.6b"
    EMBEDDING_DIMENSIONS: int = 1024
    MODEL_VISION: str = "MedAIBase/PaddleOCR-VL:0.9b"

    # Hugging Face Models (Transformers)
    MODEL_FLORENCE_HF: str = "microsoft/Florence-2-large"
    MODEL_FLORENCE_LOCAL: str = "florence-2-large"
    MODEL_WHISPER_HF: str = "openai/whisper-large-v3-turbo"
    MODEL_WHISPER_LOCAL: str = "whisper-large-v3-turbo"
    MODEL_RERANKER_HF: str = "tomaarsen/qwen3-reranker-0.6b-seq-cls"
    MODEL_RERANKING_LOCAL: str = "qwen3-reranker-0.6b-seq-cls"

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

    # Benchmark Mode
    # When True, uses factual/objective prompts instead of personal "You" narrative
    # This is for testing with external datasets (HotpotQA, MuSiQue) where personal framing is inappropriate
    BENCHMARK_MODE: bool = True


settings = Settings()
