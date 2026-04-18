from __future__ import annotations

from typing import Any

from elasticsearch import Elasticsearch

from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("ElasticsearchService")


class ElasticsearchService:
    def __init__(self) -> None:
        self._enabled = True
        try:
            self.client = Elasticsearch(
                f"http://{settings.ELASTICSEARCH_HOST}:{settings.ELASTICSEARCH_PORT}"
            )
        except Exception as exc:
            self._enabled = False
            self.client = None
            logger.warning(
                f"Elasticsearch client init failed, disabling ES path: {exc}"
            )

    def is_available(self) -> bool:
        if not self._enabled or not self.client:
            return False
        try:
            return self.client.ping()
        except Exception:
            return False

    def search_nodes(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if not self.is_available() or not self.client:
            return []

        index_name = settings.ELASTICSEARCH_INDEX_NAME
        try:
            response = self.client.search(
                index=index_name,
                query={
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "name^3",
                            "type^1.5",
                            "description^2",
                            "facts",
                            "potential_questions",
                            "isolated_contexts",
                            "relationship_natural_language",
                        ],
                        "type": "best_fields",
                    }
                },
                size=limit,
            )
        except Exception as exc:
            logger.debug(f"Elasticsearch search failed: {exc}")
            return []

        hits: list[dict[str, Any]] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {}) or {}
            hits.append({"score": hit.get("_score", 0.0), "payload": source})
        return hits

    # ── Write helpers ──────────────────────────────────────────────────────────

    def index_node(
        self,
        node_id: str,
        name: str,
        node_type: str,
        description: str,
        facts_text: str = "",
        questions_text: str = "",
        isolated_contexts_text: str = "",
        relationship_natural_language: str = "",
        community_level: int | None = None,
    ) -> None:
        """Index (or re-index) one node document in Elasticsearch.

        ``community_level`` is set only for community nodes (the level they ARE at).
        Regular nodes carry no community fields — membership is expressed via
        relationship natural-language sentences indexed under
        ``relationship_natural_language``.
        """
        if not self.is_available() or not self.client:
            return
        doc: dict[str, Any] = {
            "node_id": node_id,
            "name": name,
            "type": node_type,
            "description": description,
        }
        if facts_text:
            doc["facts"] = facts_text
        if questions_text:
            doc["potential_questions"] = questions_text
        if isolated_contexts_text:
            doc["isolated_contexts"] = isolated_contexts_text
        if relationship_natural_language:
            doc["relationship_natural_language"] = relationship_natural_language
        if community_level is not None:
            doc["community_level"] = community_level
        try:
            self.client.index(
                index=settings.ELASTICSEARCH_INDEX_NAME,
                id=node_id,
                document=doc,
            )
        except Exception as exc:
            logger.warning(f"Elasticsearch index_node failed for {node_id}: {exc}")

    def update_node_community(
        self,
        node_id: str,
        description: str,
        relationship_natural_language: str = "",
    ) -> None:
        """Partial update: refresh description and relationship NL for a regular node.

        Used after Leiden recompute when membership NL sentences have changed.
        Community fields are not stored on regular nodes in ES.
        """
        if not self.is_available() or not self.client:
            return
        doc: dict[str, Any] = {"description": description}
        if relationship_natural_language:
            doc["relationship_natural_language"] = relationship_natural_language
        try:
            self.client.update(
                index=settings.ELASTICSEARCH_INDEX_NAME,
                id=node_id,
                doc=doc,
            )
        except Exception as exc:
            # If the document doesn't exist yet, fall back to full index
            logger.debug(f"Elasticsearch update_node_community fell back to index for {node_id}: {exc}")

    def delete_node(self, node_id: str) -> None:
        """Remove a node document from Elasticsearch (no-op if not found)."""
        if not self.is_available() or not self.client:
            return
        try:
            self.client.delete(
                index=settings.ELASTICSEARCH_INDEX_NAME,
                id=node_id,
            )
        except Exception as exc:
            # NotFoundError (404) is expected when the doc was never indexed — ignore it
            if "404" in str(exc) or "not_found" in str(exc).lower():
                return
            logger.warning(f"Elasticsearch delete_node failed for {node_id}: {exc}")


elasticsearch_service = ElasticsearchService()
