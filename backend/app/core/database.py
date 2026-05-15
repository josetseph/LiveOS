"""Async SQLAlchemy engine and session factory for PostgreSQL."""
# pylint: disable=wrong-import-order
from app.core.config import settings
from app.core.log import get_logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

logger = get_logger("DatabaseService")

# Use Transaction Pooler URL (Preferred for Asyncpg/Supabase/Local Docker)  # pylint: disable=invalid-name
DATABASE_URL = settings.DATABASE_TRANSACTION_POOLER_URL

if not DATABASE_URL:
    logger.error("DATABASE_URL is not set in settings")
    raise ValueError("DATABASE_URL is not set in settings")

# Helper: Asyncpg requires postgresql+asyncpg:// scheme
if DATABASE_URL.startswith("postgresql://"):  # pylint: disable=invalid-name
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    logger.info(f"Converted DATABASE_URL: {DATABASE_URL} to use asyncpg driver")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=10,  # Connections kept open and reused (avoids repeated SSL handshakes).
    max_overflow=20,  # Extra burst capacity; total ceiling = 30.
    pool_timeout=30,  # Wait up to 30s for a free connection before raising TimeoutError.
    pool_pre_ping=True,  # Validate connections before use; drops stale ones silently.
    connect_args={"statement_cache_size": 0},
)
logger.info("Async database engine created successfully")
  # pylint: disable=invalid-name
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)
logger.info("Async session maker created successfully")

Base = declarative_base()
logger.info("Declarative base for ORM models created successfully")


async def get_db():
    """FastAPI dependency that yields an async SQLAlchemy database session."""
    async with AsyncSessionLocal() as session:
        try:
            logger.info("Creating new database session")
            yield session
        finally:
            logger.info("Closing database session")
            await session.close()
