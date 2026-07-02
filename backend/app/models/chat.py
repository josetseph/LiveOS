"""SQLAlchemy ORM models for persisted chat conversations and messages."""

# pylint: disable=wrong-import-order
import uuid
from datetime import datetime, timezone

from app.core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship


class ChatConversation(Base):  # pylint: disable=too-few-public-methods
    """A persisted chat thread scoped to one knowledge base."""

    __tablename__ = "chat_conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, default="New Chat")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):  # pylint: disable=too-few-public-methods
    """One user or assistant turn inside a conversation."""

    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String,
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    thinking = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    conversation = relationship("ChatConversation", back_populates="messages")
