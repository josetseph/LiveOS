"""SQLAlchemy ORM model for note records."""

# pylint: disable=wrong-import-order
import uuid
from datetime import datetime, timezone

from app.core.database import Base
from sqlalchemy import Boolean, Column, DateTime, String, Text


class Note(Base):  # pylint: disable=too-few-public-methods
    """Persisted note record with content, title, and processing-state flags."""

    __tablename__ = "notes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    content = Column(Text, nullable=False)
    title = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    # Allow DB to handle updated_at triggers if configured, or app level
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=datetime.now(timezone.utc),
        default=datetime.now(timezone.utc),
    )
    processed = Column(Boolean, default=False)
    failed = Column(Boolean, default=False)
    kb_id = Column(String, nullable=False, default="default", index=True)
    # Could add user_id later
