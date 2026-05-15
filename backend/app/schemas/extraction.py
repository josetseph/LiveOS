"""Pydantic schemas for LLM-extracted knowledge graph nodes, relationships, and notes."""

# pylint: disable=import-outside-toplevel
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Node(BaseModel):
    """Single uniform node type — LLM sets `type` freely (e.g. 'person', 'song', 'event')."""

    name: str = ""
    type: str = "thing"
    type_reasoning: str = ""
    isolated_context: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        """Normalise common LLM key-name drift (e.g. 'trait' → 'name') before field validation."""
        if not isinstance(data, dict):
            return data
        # trait → name (persona drift)
        if "trait" in data and "name" not in data:
            data["name"] = data["trait"]
        # title → name (reference drift)
        if "title" in data and "name" not in data:
            data["name"] = data["title"]
        # evidence_quote / context → isolated_context
        if "evidence_quote" in data and "isolated_context" not in data:
            data["isolated_context"] = data.pop("evidence_quote")
        if "context" in data and "isolated_context" not in data:
            data["isolated_context"] = data["context"]
        return data

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

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, data: Any) -> Any:
        """Normalise common LLM key-name drift in extracted relationship objects."""
        if not isinstance(data, dict):
            return data
        # New prompt format uses entity1/entity2/description/direction
        if "entity1" in data and "source_name" not in data:
            data["source_name"] = data["entity1"]
        if "entity2" in data and "target_name" not in data:
            data["target_name"] = data["entity2"]
        if "description" in data:
            desc = str(data["description"])
            if "natural_language" not in data:
                data["natural_language"] = desc
            if "relationship_type" not in data:
                import re as _re

                rt = _re.sub(r"[^a-z0-9 ]", "", desc.lower()).strip()
                data["relationship_type"] = "_".join(rt.split()) or "relates_to"
        return data

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
        # Handle LLM returning scores as strings ("high", "medium", "low")
        score_fields = ("confidence", "strength", "relevance")
        if info.field_name in score_fields and isinstance(v, str):
            score_map = {
                "very high": 9.0,
                "high": 8.0,
                "medium": 6.0,
                "moderate": 6.0,
                "low": 4.0,
                "very low": 2.0,
            }
            mapped = score_map.get(v.lower().strip())
            if mapped is not None:
                return mapped
            _score_default = 7.0 if info.field_name == "confidence" else 5.0
            try:
                v = float(v)  # fall through to float normalization below
            except ValueError:
                return _score_default
        # If LLM returns 0–1 float (or a coerced float string), normalise to 1–10
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
    """Root extraction result containing all nodes and relationships found in a note."""

    nodes: List[Node] = Field(default_factory=list)
    relationships: List[ExtractedRelationship] = Field(default_factory=list)
    sentiment: str = "Neutral"
    title: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        cls, data: Any
    ) -> Any:
        """Normalise LLM JSON keys → Pydantic field names.

        Also coerces legacy multi-list responses (entities/concepts/tasks/…) into
        the unified `nodes` list so old-format responses still parse cleanly.
        """
        if not isinstance(data, dict):
            # LLM returned a bare list of node dicts, e.g. gemma4 format:
            # [{"name": "X", "relationships": [...]}, ...]
            # Hoist any relationships embedded inside each node dict.
            if isinstance(data, list):
                # Handle "list of two lists" format: [[nodes...], [rels...]]
                # Some models (e.g. Ollama/gemma3) wrap the response as a
                # top-level array where index 0 = node dicts, index 1 = rel dicts.
                if data and isinstance(data[0], list):
                    nodes_raw = [item for item in data[0] if isinstance(item, dict)]
                    rels_raw = (
                        [item for item in data[1] if isinstance(item, dict)]
                        if len(data) > 1 and isinstance(data[1], list)
                        else []
                    )
                    return {"nodes": nodes_raw, "relationships": rels_raw}

                hoisted_rels: list = []
                clean_nodes: list = []
                for item in data:
                    if isinstance(item, dict):
                        embedded = item.pop("relationships", None)
                        if isinstance(embedded, list):
                            hoisted_rels.extend(embedded)
                        clean_nodes.append(item)
                    elif isinstance(item, str) and item.strip():
                        clean_nodes.append({"name": item.strip()})
                    else:
                        clean_nodes.append(item)
                return {"nodes": clean_nodes, "relationships": hoisted_rels}
            return data

        # Unwrap {"extraction": {...}} wrapper
        wrapped = data.get("extraction")
        if isinstance(wrapped, dict):
            data = wrapped

        # Unwrap {"data": {...}} or {"result": {...}} wrapper
        for outer_key in ("data", "result"):
            outer = data.get(outer_key)
            if isinstance(outer, dict) and (
                "nodes" in outer or "relationships" in outer or "entities" in outer
            ):
                data = outer
                break

        # Normalise all keys to lowercase_underscore
        norm: dict = {}
        for key, value in data.items():
            k = key.lower().strip().replace(" ", "_")
            norm[k] = value

        result: dict = {}

        # Relationship key aliases: relationships / edges / links / connections / graph_edges
        for rel_key in (
            "relationships",
            "edges",
            "links",
            "connections",
            "graph_edges",
            "edge_list",
        ):
            if rel_key in norm and "relationships" not in result:
                result["relationships"] = norm[rel_key]
                break

        # Node key aliases: nodes / node_list / graph_nodes / elements
        for node_key in ("nodes", "node_list", "graph_nodes", "elements"):
            if node_key in norm and "nodes" not in result:
                result["nodes"] = norm[node_key]
                break

        # sentiment pass through directly
        result["sentiment"] = norm.get("sentiment", "Neutral")

        # Coerce legacy multi-list format → nodes
        legacy_nodes: list = list(result.get("nodes") or [])
        for legacy_key in (
            "entities",
            "concepts",
            "tasks",
            "persona_traits",
            "persona",
            "traits",
            "references",
            "external_references",
        ):
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
        _consumed = {
            "entities",
            "concepts",
            "tasks",
            "persona_traits",
            "persona",
            "traits",
            "references",
            "external_references",
            "summary",
            "quote",
            "edges",
            "links",
            "connections",
            "graph_edges",
            "edge_list",
            "node_list",
            "graph_nodes",
            "elements",
            "data",
            "result",
        }
        for k, v in norm.items():
            if k not in result and k not in _consumed:
                result[k] = v

        return result

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
