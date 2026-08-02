"""SQLAlchemy ORM model for note metadata (body lives in vault .md files)."""

import uuid
from datetime import datetime, timezone

from app.core.database import Base
from sqlalchemy import Boolean, Column, DateTime, String, Text


class Note(Base):  # pylint: disable=too-few-public-methods
    """Note metadata; markdown body is at vault_path/rel_path."""

    __tablename__ = "notes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Deprecated: kept nullable for migration; prefer vault file via rel_path
    content = Column(Text, nullable=True, default="")
    title = Column(String, nullable=True)
    rel_path = Column(String, nullable=True)  # relative to KB vault_path
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=datetime.now(timezone.utc),
        default=datetime.now(timezone.utc),
    )
    processed = Column(Boolean, default=False)
    failed = Column(Boolean, default=False)
    processing_stage = Column(String, nullable=True)
    processing_model = Column(String, nullable=True)
    kb_id = Column(String, nullable=False, default="default", index=True)
