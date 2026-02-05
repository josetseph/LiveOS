from sqlalchemy import Column, String, DateTime, Text, Boolean
from app.core.database import Base
from datetime import datetime, timezone
import uuid


class Note(Base):
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
    domain = Column(String, default="Personal")
    # Could add user_id later
