from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

# Use Transaction Pooler URL (Preferred for Asyncpg/Supabase/Local Docker)
DATABASE_URL = settings.DATABASE_TRANSACTION_POOLER_URL

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in settings")

# Helper: Asyncpg requires postgresql+asyncpg:// scheme
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=False, 
    future=True,
    pool_pre_ping=True,
    poolclass=NullPool, # Use NullPool for Transaction Poolers to avoid conflicts
    connect_args={
        "statement_cache_size": 0
    }
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
