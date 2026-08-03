"""SQLAlchemy ORM models — SQLite metadata for Orb desktop.

Note bodies live in vault ``.md`` files, not in the DB.
Finance product data lives in per-KB Firefly III administrations.
"""

from app.models.chat import ChatConversation, ChatMessage
from app.models.kb import KnowledgeBase
from app.models.note import Note
from app.models.wikilink import NoteLink

__all__ = [
    "ChatConversation",
    "ChatMessage",
    "KnowledgeBase",
    "Note",
    "NoteLink",
]
