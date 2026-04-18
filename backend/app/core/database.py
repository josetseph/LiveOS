from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("DatabaseService")

# Use Transaction Pooler URL (Preferred for Asyncpg/Supabase/Local Docker)
DATABASE_URL = settings.DATABASE_TRANSACTION_POOLER_URL

if not DATABASE_URL:
    logger.error("DATABASE_URL is not set in settings")
    raise ValueError("DATABASE_URL is not set in settings")

# Helper: Asyncpg requires postgresql+asyncpg:// scheme
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    logger.info(f"Converted DATABASE_URL: {DATABASE_URL} to use asyncpg driver")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool,  # No pool — each request gets its own connection, closed immediately.
    # This eliminates QueuePool exhaustion when many concurrent requests + background
    # tasks compete for connections. Appropriate for a single-process dev/benchmark server.
    connect_args={"statement_cache_size": 0},
)
logger.info("Async database engine created successfully")

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)
logger.info("Async session maker created successfully")

Base = declarative_base()
logger.info("Declarative base for ORM models created successfully")


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            logger.info("Creating new database session")
            yield session
        finally:
            logger.info("Closing database session")
            await session.close()
