from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Any


class Node(BaseModel):
    """Single uniform node type — LLM sets `type` freely (e.g. 'person', 'song', 'event')."""

    name: str = ""
    type: str = "thing"
    description: str = ""
    isolated_context: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # trait → name (persona drift)
        if "trait" in data and "name" not in data:
            data["name"] = data["trait"]
        # title → name (reference drift)
        if "title" in data and "name" not in data:
            data["name"] = data["title"]
        # definition → description
        if "definition" in data and "description" not in data:
            data["description"] = data["definition"]
        # evidence_quote / context → isolated_context
        if "evidence_quote" in data and "isolated_context" not in data:
            data["isolated_context"] = data.pop("evidence_quote")
        if "context" in data and "isolated_context" not in data:
            data["isolated_context"] = data["context"]
        return data

    @field_validator("*", mode="before")
    @classmethod
    def handle_none(cls, v: Any, info) -> Any:
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
        if v is None:
            if info.field_name == "confidence":
                return 7.0
            if info.field_name in ("strength", "relevance"):
                return 5.0
            if info.field_name == "relationship_type":
                return "relates_to"
            return ""
        # Handle LLM returning scores as strings ("high", "medium", "low")
        score_fields = ("confidence", "strength", "relevance")
        if info.field_name in score_fields and isinstance(v, str):
            score_map = {
                "very high": 9.0, "high": 8.0, "medium": 6.0,
                "moderate": 6.0, "low": 4.0, "very low": 2.0,
            }
            mapped = score_map.get(v.lower().strip())
            if mapped is not None:
                return mapped
            try:
                return float(v)
            except ValueError:
                return 7.0 if info.field_name == "confidence" else 5.0
        # If LLM returns 0–1 float, normalise to 1–10
        if info.field_name in score_fields and isinstance(v, (int, float)):
            val = float(v)
            if 0.0 <= val <= 1.0:
                val = round(val * 10.0, 1)
            return max(1.0, min(10.0, val))
        # Empty relationship_type → default
        if (
            info.field_name == "relationship_type"
            and isinstance(v, str)
            and not v.strip()
        ):
            return "relates_to"
        return v


class Extraction(BaseModel):
    domain: str = "Personal"
    nodes: List[Node] = Field(default_factory=list)
    relationships: List[ExtractedRelationship] = Field(default_factory=list)
    sentiment: str = "Neutral"

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        """Normalise LLM JSON keys → Pydantic field names.

        Also coerces legacy multi-list responses (entities/concepts/tasks/…) into
        the unified `nodes` list so old-format responses still parse cleanly.
        """
        if not isinstance(data, dict):
            return data

        # Unwrap {"extraction": {...}} wrapper
        wrapped = data.get("extraction")
        if isinstance(wrapped, dict):
            data = wrapped

        # Normalise all keys to lowercase_underscore
        norm: dict = {}
        for key, value in data.items():
            k = key.lower().strip().replace(" ", "_")
            norm[k] = value

        result: dict = {}

        # domain / sentiment / relationships pass through directly
        for field in ("domain", "domain_categorization", "sentiment", "relationships", "nodes"):
            if field in norm:
                v = norm[field]
                real_key = "domain" if field == "domain_categorization" else field
                result[real_key] = v

        # Coerce legacy multi-list format → nodes
        legacy_nodes: list = list(result.get("nodes") or [])
        for legacy_key in ("entities", "concepts", "tasks", "persona_traits",
                           "persona", "traits", "references", "external_references"):
            items = norm.get(legacy_key)
            if not items or not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, str):
                    legacy_nodes.append({"name": item, "type": legacy_key.rstrip("s")})
                elif isinstance(item, dict):
                    # Normalise trait/title → name
                    if "trait" in item and "name" not in item:
                        item = dict(item, name=item["trait"])
                    elif "title" in item and "name" not in item:
                        item = dict(item, name=item["title"])
                    legacy_nodes.append(item)
        if legacy_nodes:
            result["nodes"] = legacy_nodes

        # Pass through any remaining unknown keys
        for k, v in norm.items():
            if k not in result and k not in (
                "entities", "concepts", "tasks", "persona_traits",
                "persona", "traits", "references", "external_references",
                "domain_categorization", "summary", "quote",
            ):
                result[k] = v

        return result

    @field_validator("nodes", "relationships", mode="before")
    @classmethod
    def ensure_list(cls, v, info):
        if v is None or not isinstance(v, list):
            return []
        return v

    @field_validator("sentiment", mode="before")
    @classmethod
    def handle_sentiment_none(cls, v: Any) -> Any:
        return v if v else "Neutral"


class NoteInput(BaseModel):
    content: str
    created_at: Optional[str] = None
    title: Optional[str] = None  # If provided, use instead of auto-generating
    skip_ingestion: bool = False  # If True, save to DB but don't process in brain
