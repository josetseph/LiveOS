"""Typesense keyword search service for fast BM25 node retrieval."""

from __future__ import annotations

from typing import Any

import typesense
from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("TypesenseService")

_COLLECTION_SCHEMA = {
    "name": "liveos_nodes",
    "fields": [
        {"name": "node_id", "type": "string"},
        {"name": "name", "type": "string"},
        {"name": "type", "type": "string", "optional": True},
        {"name": "isolated_contexts", "type": "string", "optional": True},
        {"name": "relationship_natural_language", "type": "string", "optional": True},
        {"name": "community_level", "type": "int32", "optional": True},
    ],
}


class TypesenseService:
    """Typesense client managing the liveos_nodes collection for BM25 keyword search."""

    def __init__(self, collection_name: str | None = None) -> None:
        self._enabled = True
        self.collection = collection_name or settings.TYPESENSE_COLLECTION_NAME
        try:
            self.client = typesense.Client(
                {
                    "api_key": settings.TYPESENSE_API_KEY,
                    "nodes": [
                        {
                            "host": settings.TYPESENSE_HOST,
                            "port": str(settings.TYPESENSE_PORT),
                            "protocol": "http",
                        }
                    ],
                    "connection_timeout_seconds": 3,
                    "retry_interval_seconds": 0.1,
                    "num_retries": 3,
                }
            )
            self._ensure_collection()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._enabled = False
            self.client = None
            logger.warning(
                f"Typesense client init failed, disabling search path: {exc}"
            )

    def _ensure_collection(self) -> None:
        """Create the collection if it does not already exist."""
        collection_name = self.collection
        try:
            self.client.collections[collection_name].retrieve()
        except Exception:  # pylint: disable=broad-exception-caught
            try:
                schema = dict(_COLLECTION_SCHEMA)
                schema["name"] = collection_name
                self.client.collections.create(schema)
                logger.info(f"[Typesense] Created collection '{collection_name}'")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(f"[Typesense] Collection creation failed: {exc}")

    def is_available(self) -> bool:
        """Return True if Typesense is reachable and the service is enabled."""
        if not self._enabled or not self.client:
            return False
        try:
            self.client.collections[self.collection].retrieve()
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    def search_nodes(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Run a BM25 keyword search across name, type, context, and relationship fields."""
        if not self.is_available():
            return []

        try:
            response = self.client.collections[self.collection].documents.search(
                {
                    "q": query,
                    "query_by": (
                        "name,type,isolated_contexts," "relationship_natural_language"
                    ),
                    "query_by_weights": "3,2,1,1",
                    "per_page": limit,
                }
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug(f"Typesense search failed: {exc}")
            return []

        hits: list[dict[str, Any]] = []
        total = len(response.get("hits", []))
        for idx, hit in enumerate(response.get("hits", [])):
            document = hit.get("document", {}) or {}
            # Use descending rank as relative score (first hit = highest)
            score = float(total - idx)
            hits.append({"score": score, "payload": document})
        return hits

    # ── Write helpers ──────────────────────────────────────────────────────────

    def index_node(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        node_id: str,
        name: str,
        node_type: str,
        isolated_contexts_text: str = "",
        relationship_natural_language: str = "",
        community_level: int | None = None,
    ) -> None:  # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Index (or re-index) one node document in Typesense."""
        if not self.is_available():
            return
        doc: dict[str, Any] = {
            "id": node_id,  # Typesense document ID
            "node_id": node_id,
            "name": name,
            "type": node_type,
        }
        if isolated_contexts_text:
            doc["isolated_contexts"] = isolated_contexts_text
        if relationship_natural_language:
            doc["relationship_natural_language"] = relationship_natural_language
        if community_level is not None:
            doc["community_level"] = community_level
        try:
            self.client.collections[self.collection].documents.upsert(doc)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"Typesense index_node failed for {node_id}: {exc}")

    def update_node_community(
        self,
        node_id: str,
        relationship_natural_language: str = "",
        name: str = "",
    ) -> None:
        """Refresh relationship NL for a regular node.

        When ``name`` is supplied the document is upserted (emplace), which
        repairs nodes that were previously indexed without a ``name`` field.
        Without ``name`` a partial PATCH update is attempted; 400/404 are
        logged at DEBUG level and treated as non-fatal.
        """
        if not self.is_available():
            return
        doc: dict[str, Any] = {
            "id": node_id,
            "node_id": node_id,
        }
        if relationship_natural_language:
            doc["relationship_natural_language"] = relationship_natural_language
        try:
            if name:
                # Full upsert — includes both required fields (node_id + name) so the
                # document is valid even when it doesn't already exist in the index.
                doc["name"] = name
                doc["node_id"] = node_id
                self.client.collections[self.collection].documents.upsert(doc)
            else:
                # Partial PATCH — only works when the doc already has all required fields.
                self.client.collections[self.collection].documents[node_id].update(doc)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _msg = str(exc).lower()
            # Match genuine HTTP 404 only — not field-level "not found in the document"
            # errors which are actually 400s from a missing required schema field.
            if "object not found" in _msg or (
                "404" in _msg and "not found in the document" not in _msg
            ):
                logger.debug(
                    f"Typesense update_node_community skipped (doc not in index) {node_id}: {exc}"
                )
                return
            logger.debug(f"Typesense update_node_community failed for {node_id}: {exc}")

    def delete_node(self, node_id: str) -> None:
        """Remove a node document from Typesense (no-op if not found)."""
        if not self.is_available():
            return
        try:
            self.client.collections[self.collection].documents[node_id].delete()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if "404" in str(exc) or "not found" in str(exc).lower():
                return
            logger.warning(f"Typesense delete_node failed for {node_id}: {exc}")


typesense_service = TypesenseService()
