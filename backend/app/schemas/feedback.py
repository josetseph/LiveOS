from datetime import datetime

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    query: str
    response: str
    relevance: int = Field(ge=1, le=5)
    quality: int = Field(ge=1, le=5)
    comments: str | None = None
    node_ids_used: list[str] | None = None


class FeedbackResponse(BaseModel):
    id: str
    query: str
    response: str
    relevance: int
    quality: int
    comments: str | None = None
    node_ids_used: list[str] | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True
