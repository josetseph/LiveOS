from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Any


class Entity(BaseModel):
    name: str = ""
    type: str = "Thing"  # Person, Place, Tool, Organization, Anonymous
    importance: float = 0.5
    isolated_context: str = ""  # LLM-extracted context ONLY about this entity

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
        if v is None:
            if info.field_name == "importance":
                return 0.5
            if info.field_name == "type":
                return "Thing"
            return ""
        # Handle LLM returning importance as string ("High", "Medium", "Low")
        if info.field_name == "importance" and isinstance(v, str):
            importance_map = {
                "high": 0.9,
                "very high": 1.0,
                "medium": 0.5,
                "moderate": 0.5,
                "low": 0.3,
                "very low": 0.1,
            }
            return importance_map.get(v.lower().strip(), 0.5)
        return v


class Concept(BaseModel):
    name: str = ""
    definition: str = ""
    isolated_context: str = ""  # LLM-extracted context ONLY about this concept

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any) -> Any:
        return v or ""


class Task(BaseModel):
    name: str = ""  # Short label for graph node display
    description: str = ""  # Optional longer explanation
    status: str = "Todo"  # Standardized default (was "Pending")
    due_date: Optional[str] = None
    isolated_context: str = ""  # Source text context (matches Entity/Concept pattern)

    @model_validator(mode="before")
    @classmethod
    def normalize_task_keys(cls, data: Any) -> Any:
        """Handle various LLM output formats for tasks."""
        if not isinstance(data, dict):
            return data

        # If only 'description' exists (no 'name'), use description as name
        if "description" in data and "name" not in data:
            data["name"] = data["description"]

        return data

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
        if v is None:
            if info.field_name == "status":
                return "Todo"  # Use standardized default
            return None if info.field_name == "due_date" else ""
        # Normalize status variations to standard values
        if info.field_name == "status" and isinstance(v, str):
            status_map = {
                "to do": "Todo",
                "todo": "Todo",
                "pending": "Todo",
                "open": "Todo",
                "not started": "Todo",
                "in progress": "In Progress",
                "in-progress": "In Progress",
                "inprogress": "In Progress",
                "doing": "In Progress",
                "started": "In Progress",
                "wip": "In Progress",
                "done": "Complete",
                "complete": "Complete",
                "completed": "Complete",
                "finished": "Complete",
                "cancelled": "Cancelled",
                "canceled": "Cancelled",
                "dropped": "Cancelled",
            }
            return status_map.get(v.lower().strip(), v)
        return v


class PersonaTrait(BaseModel):
    trait: str = ""
    isolated_context: str = (
        ""  # Source text showing this trait (matches Entity/Concept pattern)
    )

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any) -> Any:
        return v or ""

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        """Handle LLM returning 'evidence_quote' or just string traits."""
        if not isinstance(data, dict):
            return data

        # Map evidence_quote -> isolated_context for backwards compatibility
        if "evidence_quote" in data and "isolated_context" not in data:
            data["isolated_context"] = data.pop("evidence_quote")

        return data


class ExtractedRelationship(BaseModel):
    """Relationship between two nodes extracted from content"""

    source_name: str = ""
    source_type: str = ""  # Person, Task, Entity, Concept, Event
    target_name: str = ""
    target_type: str = ""
    relationship_type: str = (
        "relates_to"  # From RelationshipType enum, defaults to relates_to
    )
    confidence: float = 0.8
    context: str = ""  # Text snippet showing this relationship

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
        if v is None:
            if info.field_name == "confidence":
                return 0.8
            if info.field_name == "relationship_type":
                return "relates_to"
            return ""
        # Handle LLM returning confidence as string ("High", "Medium", "Low")
        if info.field_name == "confidence" and isinstance(v, str):
            confidence_map = {
                "high": 0.9,
                "very high": 1.0,
                "medium": 0.7,
                "moderate": 0.7,
                "low": 0.5,
                "very low": 0.3,
            }
            return confidence_map.get(v.lower().strip(), 0.8)
        # Handle empty relationship_type string
        if (
            info.field_name == "relationship_type"
            and isinstance(v, str)
            and not v.strip()
        ):
            return "relates_to"
        return v


class ExternalReference(BaseModel):
    title: str = ""
    type: str = "Quote"  # "Song", "Quote", "Book", "Paper", "Video", "Poem"
    content: str = ""  # The actual quote/excerpt
    source: Optional[str] = None  # Author/Artist
    isolated_context: str = ""  # Source text context (matches Entity/Concept pattern)

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
    relationships: List[ExtractedRelationship] = Field(default_factory=list)
    sentiment: str = "Neutral"

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        """Normalize JSON keys from LLM output to match Pydantic field names.

        LLM may return: "Entities", "DOMAIN CATEGORIZATION", "PERSONA", etc.
        We need: "entities", "domain", "persona_traits", etc.
        """
        if not isinstance(data, dict):
            return data

        # Key mapping: LLM output -> Pydantic field name
        key_map = {
            # Domain variations
            "domain categorization": "domain",
            "domain": "domain",
            # Entity variations
            "entities": "entities",
            # Concept variations
            "concepts": "concepts",
            # Task variations
            "tasks": "tasks",
            # Persona variations
            "persona": "persona_traits",
            "persona_traits": "persona_traits",
            "traits": "persona_traits",
            # Reference variations
            "references": "references",
            "external_references": "references",
            # Relationship variations
            "relationships": "relationships",
            # Summary variations
            "summary": "summary",
            # Sentiment variations
            "sentiment": "sentiment",
            # Quote (often returned but not in schema)
            "quote": None,  # Ignore this field
        }

        normalized = {}
        for key, value in data.items():
            # Normalize key: lowercase, strip whitespace
            norm_key = key.lower().strip().replace(" ", "_")

            # Look up the mapping
            mapped_key = key_map.get(norm_key)

            if mapped_key is None:
                # Key should be ignored (like "quote")
                continue
            elif mapped_key:
                # Handle special case: PERSONA returns {"traits": [...]} instead of list
                if mapped_key == "persona_traits" and isinstance(value, dict):
                    # Extract traits list from dict
                    traits_list = value.get("traits", [])
                    # Convert string traits to PersonaTrait objects
                    normalized[mapped_key] = [
                        {"trait": t, "evidence_quote": ""} if isinstance(t, str) else t
                        for t in traits_list
                    ]
                else:
                    normalized[mapped_key] = value
            else:
                # No mapping found, use normalized key as-is
                normalized[norm_key] = value

        return normalized

    @field_validator(
        "entities",
        "concepts",
        "tasks",
        "persona_traits",
        "references",
        "relationships",
        mode="before",
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
                # relationships cannot be strings, skip
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
