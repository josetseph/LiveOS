import uuid
from datetime import datetime, timezone

from app.core.database import Base
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    relevance = Column(Integer, nullable=False)
    quality = Column(Integer, nullable=False)
    comments = Column(Text, nullable=True)
    node_ids_used = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
