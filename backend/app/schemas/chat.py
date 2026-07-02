"""Pydantic schemas for chat conversations and messages."""

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """One prior turn used as model context."""

    role: str
    content: str


class ChatMessageResponse(BaseModel):
    """API response for a stored chat message."""

    id: str
    conversation_id: str
    role: str
    content: str
    thinking: str | None = None
    created_at: str | None = None

    class Config:  # pylint: disable=too-few-public-methods
        from_attributes = True


class ChatConversationResponse(BaseModel):
    """API response for a chat conversation summary."""

    id: str
    kb_id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None

    class Config:  # pylint: disable=too-few-public-methods
        from_attributes = True


class CreateConversationInput(BaseModel):
    """Optional body when explicitly creating a conversation."""

    title: str | None = None


class ChatInputBody(BaseModel):
    """Extended chat request body with conversation support."""

    query: str
    request_id: str | None = None
    conversation_id: str | None = None


class ChatAsyncStartResponse(BaseModel):
    """Immediate response from async chat start."""

    request_id: str
    conversation_id: str
    stage: str
    model: str | None = None
    done: bool = False
