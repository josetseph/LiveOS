"""
reset_database.py — Truncate the notes table (raw note content + metadata).

Preserves the schema and sequences. Does NOT touch Neo4j, Qdrant, or ES —
run reset_ingestion.py separately if you also want to clear the graph/vectors.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from sqlalchemy import text


async def _reset_database() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE TABLE notes RESTART IDENTITY CASCADE"))
        await session.commit()
    print("   ✅ Table 'notes' truncated.")


def reset_database() -> None:
    print("🗑️  Resetting PostgreSQL...")
    asyncio.run(_reset_database())
    print("✅ PostgreSQL reset complete.")


if __name__ == "__main__":
    reset_database()
