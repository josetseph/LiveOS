"""Pydantic schemas for LLM-extracted knowledge graph nodes, relationships, and notes."""

# pylint: disable=import-outside-toplevel
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


class Node(BaseModel):
    """Single uniform node type — LLM sets `type` freely (e.g. 'person', 'song', 'event')."""

    name: str = ""
    type: str = "thing"
    type_reasoning: str = ""
    isolated_context: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
        """Coerce None or empty strings to safe defaults for each field."""
        if v is None:
            if info.field_name == "type":
                return "thing"
            return ""
        return v


class ExtractedRelationship(BaseModel):
    """Relationship between two nodes extracted from content."""

    source_name: str = ""
    target_name: str = ""
    relationship_type: str = "relates_to"
    reasoning: str = ""
    # All three scores on the 1–10 scale (plan-aligned).
    # edge_weight = (strength × 0.5) + (confidence × 0.3) + (relevance × 0.2)
    strength: float = 5.0
    confidence: float = 7.0
    relevance: float = 5.0
    natural_language: str = ""
    context: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
        """Coerce None, strings, and out-of-range floats to valid field values."""
        if v is None:
            _none_defaults = {
                "confidence": 7.0,
                "strength": 5.0,
                "relevance": 5.0,
                "relationship_type": "relates_to",
            }
            return _none_defaults.get(info.field_name, "")
        # Empty relationship_type → default
        if (
            info.field_name == "relationship_type"
            and isinstance(v, str)
            and not v.strip()
        ):
            return "relates_to"
        return v


class Extraction(BaseModel):
    """Root extraction result containing all nodes and relationships found in a note."""

    nodes: List[Node] = Field(default_factory=list)
    relationships: List[ExtractedRelationship] = Field(default_factory=list)
    sentiment: str = "Neutral"
    title: Optional[str] = None

    @field_validator("nodes", "relationships", mode="before")
    @classmethod
    def ensure_list(cls, v, info):
        """Coerce None or scalar values to an empty list for nodes/relationships fields."""
        if v is None or not isinstance(v, list):
            return []
        if info.field_name == "nodes":
            # Coerce plain strings → minimal node dicts so Node validation doesn't crash
            return [
                (
                    {"name": item.strip()}
                    if isinstance(item, str) and item.strip()
                    else item
                )
                for item in v
            ]
        return v

    @field_validator("sentiment", mode="before")
    @classmethod
    def handle_sentiment_none(cls, v: Any) -> Any:
        """Replace None or empty sentiment with the default value 'Neutral'."""
        return v if v else "Neutral"


class NoteInput(BaseModel):
    """Input schema for creating or re-ingesting a note."""

    content: str
    created_at: Optional[str] = None
    title: Optional[str] = None  # If provided, use instead of auto-generating
    skip_ingestion: bool = False  # If True, save to DB but don't process in brain
