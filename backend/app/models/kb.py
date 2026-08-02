"""Knowledge base registry rows (replaces kb_registry.json)."""

import uuid
from datetime import datetime, timezone

from app.core.database import Base
from sqlalchemy import Column, DateTime, String, Text


class KnowledgeBase(Base):  # pylint: disable=too-few-public-methods
    """One vault / knowledge base."""

    __tablename__ = "knowledge_bases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    vault_path = Column(Text, nullable=False)
    kuzu_path = Column(Text, nullable=False)
    qdrant_col_cores = Column(String, nullable=False)
    qdrant_col_rels = Column(String, nullable=False)
    qdrant_col_contexts = Column(String, nullable=False)
    typesense_collection = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
