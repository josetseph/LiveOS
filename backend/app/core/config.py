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

    # LLM (Local)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    MODEL_EXTRACTION: str = "gemma3:12b"
    MODEL_ARCHITECT: str = "gemma3:12b"
    MODEL_SUMMARIZATION: str = "gemma3:12b"
    MODEL_BRAIN: str = "gemma3:12b"
    MODEL_REASONING: str = "gemma3:12b"
    MODEL_EMBEDDING: str = "qwen3-embedding:0.6b"
    EMBEDDING_DIMENSIONS: int = 1024
    MODEL_VISION: str = "deepseek-ocr:latest"

    # Hugging Face Models (Transformers)
    MODEL_FLORENCE_HF: str = "microsoft/Florence-2-large"
    MODEL_FLORENCE_LOCAL: str = "florence-2-large"
    MODEL_WHISPER_HF: str = "openai/whisper-large-v3"
    MODEL_WHISPER_LOCAL: str = "whisper-large-v3"
    MODEL_RERANKER_HF: str = "michaelfeil/mxbai-rerank-large-v2-seq"
    MODEL_RERANKING_LOCAL: str = "mxbai-rerank-large-v2-seq"

    # Model Storage Path
    MODELS_PATH: str = "models"  # Relative to backend root

    # LLM (Cloud)
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str | None = None

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


settings = Settings()
