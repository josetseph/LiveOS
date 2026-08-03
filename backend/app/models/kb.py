"""Knowledge base registry rows (SQLite metadata; also maintained via kb_registry)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import synonym

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeBase(Base):  # pylint: disable=too-few-public-methods
    """One vault / knowledge base — indexes + Firefly admin scope."""

    __tablename__ = "knowledge_bases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    vault_path = Column(Text, nullable=False)
    kuzu_path = Column(Text, nullable=False)
    qdrant_col_cores = Column(String, nullable=False)
    qdrant_col_rels = Column(String, nullable=False)
    qdrant_col_contexts = Column(String, nullable=False)
    # Meilisearch index name (column kept as typesense_collection for existing DBs)
    typesense_collection = Column(String, nullable=False)
    meili_index = synonym("typesense_collection")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    # Per-KB Firefly III administration (user_group_id) — never leak across vaults
    firefly_group_id = Column(Integer, nullable=True)
    firefly_group_title = Column(Text, nullable=True)
