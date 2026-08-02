"""Pydantic schemas for note creation and API response serialization."""
from pydantic import BaseModel


class NoteResponse(BaseModel):
    """API response schema for a note record."""
    id: str
    content: str
    created_at: str | None = None
    updated_at: str | None = None
    title: str | None = None
    summary: str | None = None
    processed: bool = False
    failed: bool = False
    processing_stage: str | None = None
    processing_model: str | None = None

    class Config:  # pylint: disable=too-few-public-methods
        """Pydantic ORM-mode configuration for NoteResponse."""
        from_attributes = True


class CreateNoteInput(BaseModel):
    """Input schema for creating a new note."""
    title: str | None = None
    content: str
    created_at: str | None = None
    # Vault-relative folder to create the note in (e.g. "Life/Daily Log")
    folder: str | None = None


class MoveNoteInput(BaseModel):
    """Move a note into a folder (or to vault root if empty)."""
    folder: str = ""


class MoveVaultFileInput(BaseModel):
    """Move any vault file (note or attachment) to a new relative path."""
    from_rel: str
    to_rel: str


class DeleteVaultFileInput(BaseModel):
    """Delete a vault attachment and strip markdown links to it."""
    rel_path: str
