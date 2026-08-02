"""Wikilink edges between notes (notes graph)."""

import uuid
from datetime import datetime, timezone

from app.core.database import Base
from sqlalchemy import Column, DateTime, String, UniqueConstraint


class NoteLink(Base):  # pylint: disable=too-few-public-methods
    """Directed edge: source note → target note title/path via [[wikilink]]."""

    __tablename__ = "note_links"
    __table_args__ = (
        UniqueConstraint(
            "kb_id", "source_note_id", "target_title", name="uq_note_link"
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(String, nullable=False, index=True)
    source_note_id = Column(String, nullable=False, index=True)
    target_title = Column(String, nullable=False)
    target_note_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
