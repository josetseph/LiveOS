from pydantic import BaseModel


class NoteResponse(BaseModel):
    id: str
    content: str
    created_at: str | None = None
    title: str | None = None
    summary: str | None = None
    processed: bool = False
    failed: bool = False

    class Config:
        from_attributes = True


class CreateNoteInput(BaseModel):
    content: str
    created_at: str | None = None
