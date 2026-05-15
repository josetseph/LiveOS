"""Pydantic schemas for note creation and API response serialization."""
from pydantic import BaseModel


class NoteResponse(BaseModel):
    """API response schema for a note record."""
    id: str
    content: str
    created_at: str | None = None
    title: str | None = None
    summary: str | None = None
    processed: bool = False
    failed: bool = False

    class Config:  # pylint: disable=too-few-public-methods
        """Pydantic ORM-mode configuration for NoteResponse."""
        from_attributes = True


class CreateNoteInput(BaseModel):
    """Input schema for creating a new note."""
    content: str
    created_at: str | None = None
