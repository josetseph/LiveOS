"""Persisted chat conversations and messages."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatConversation(Base):  # pylint: disable=too-few-public-methods
    """A chat thread scoped to one knowledge base."""

    __tablename__ = "chat_conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, default="New Chat")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
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
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    conversation = relationship("ChatConversation", back_populates="messages")
