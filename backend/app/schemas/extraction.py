from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Any


class Entity(BaseModel):
    name: str = ""
    type: str = "Thing"
    importance: float = 0.5

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
        if v is None:
            if info.field_name == "importance":
                return 0.5
            if info.field_name == "type":
                return "Thing"
            return ""
        return v


class Concept(BaseModel):
    name: str = ""
    definition: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any) -> Any:
        return v or ""


class Task(BaseModel):
    description: str = ""
    status: str = "Pending"
    due_date: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
        if v is None:
            if info.field_name == "status":
                return "Pending"
            return None if info.field_name == "due_date" else ""
        return v


class PersonaTrait(BaseModel):
    trait: str = ""
    evidence_quote: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any) -> Any:
        return v or ""


class ExternalReference(BaseModel):
    title: str = ""
    type: str = "Quote"  # "Song", "Quote", "Book", "Paper", "Video", "Poem"
    content: str = ""
    source: Optional[str] = None  # Author/Artist

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any) -> Any:
        return v or "" if v is not None else ""


class Extraction(BaseModel):
    summary: str = ""
    domain: str = (
        "Personal"  # "Personal", "Academic", "Professional", "Creative", "Dreams"
    )
    entities: List[Entity] = Field(default_factory=list)
    concepts: List[Concept] = Field(default_factory=list)
    tasks: List[Task] = Field(default_factory=list)
    persona_traits: List[PersonaTrait] = Field(default_factory=list)
    references: List[ExternalReference] = Field(default_factory=list)
    sentiment: str = "Neutral"

    @field_validator(
        "entities", "concepts", "tasks", "persona_traits", "references", mode="before"
    )
    @classmethod
    def ensure_list_of_objects(cls, v, info):
        if v is None:
            return []
        if not isinstance(v, list):
            return []

        new_list = []
        for item in v:
            if isinstance(item, str):
                if info.field_name == "entities":
                    new_list.append({"name": item, "type": "Thing"})
                elif info.field_name == "concepts":
                    new_list.append({"name": item})
                elif info.field_name == "tasks":
                    new_list.append({"description": item})
                elif info.field_name == "persona_traits":
                    new_list.append({"trait": item})
            else:
                new_list.append(item)
        return new_list

    @field_validator("*", mode="before")
    @classmethod
    def handle_none_top(cls, v: Any, info) -> Any:
        if v is None:
            if info.field_name == "sentiment":
                return "Neutral"
            return ""
        return v


class NoteInput(BaseModel):
    content: str
    created_at: Optional[str] = None
    skip_ingestion: bool = False  # If True, save to DB but don't process in brain
