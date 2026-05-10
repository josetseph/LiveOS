from __future__ import annotations

import uuid
from typing import Any

from app.core.config import settings
from app.core.log import get_logger
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
)

logger = get_logger("QdrantService")


class QdrantService:
    def __init__(self) -> None:
        self._enabled = True
        try:
            self.client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                api_key=settings.QDRANT_API_KEY,
            )
        except Exception as exc:
            self._enabled = False
            self.client = None
            logger.warning(f"Qdrant client init failed, disabling Qdrant path: {exc}")

    @property
    def collections(self) -> list[str]:
        # node_cores is included in vector search when nodes have a merged-context
        # vector (written by _update_node_summary). The merged vector embeds all
        # accumulated isolated contexts as a single passage, enabling multi-constraint
        # queries to match whole-node content rather than one sentence at a time.
        # Nodes without a merged vector simply don't appear in search results.
        return [
            settings.QDRANT_COLLECTION_NODE_CORES,
            settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS,
            settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,
        ]

    def is_available(self) -> bool:
        if not self._enabled or not self.client:
            return False
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def search_all_collections(
        self, query_vector: list[float], limit: int, min_score: float
    ) -> list[dict[str, Any]]:
        if not self.is_available() or not self.client:
            return []

        hits: list[dict[str, Any]] = []
        for collection in self.collections:
            try:
                result = self.client.query_points(
                    collection_name=collection,
                    query=query_vector,
                    limit=limit,
                    score_threshold=min_score,
                    with_payload=True,
                )
                for point in result.points:
                    hits.append(
                        {
                            "collection": collection,
                            "score": point.score,
                            "payload": point.payload or {},
                        }
                    )
            except Exception as exc:
                logger.debug(f"Qdrant search failed for {collection}: {exc}")
        return hits

    def search_node_cores(
        self,
        query_vector: list[float],
        limit: int,
        min_score: float,
        node_type: str | None = None,
        community_level: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_available() or not self.client:
            return []

        must = []
        if node_type is not None:
            must.append(FieldCondition(key="type", match=MatchValue(value=node_type)))
        if community_level is not None:
            must.append(
                FieldCondition(
                    key="community_level", match=MatchValue(value=community_level)
                )
            )

        query_filter = Filter(must=must) if must else None
        try:
            result = self.client.query_points(
                collection_name=settings.QDRANT_COLLECTION_NODE_CORES,
                query=query_vector,
                limit=limit,
                score_threshold=min_score,
                query_filter=query_filter,
                with_payload=True,
            )
        except Exception as exc:
            logger.debug(f"Qdrant node core search failed: {exc}")
            return []

        return [
            {"score": point.score, "payload": point.payload or {}}
            for point in result.points
        ]

    # ── Write helpers ──────────────────────────────────────────────────────────

    def upsert_node_core(
        self,
        node_id: str,
        name: str,
        node_type: str,
        description_vector: list[float],
        description: str = "",
        community_level: int | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        """Upsert one point in node_cores (one point per node).

        ``community_level`` is set only for community nodes (the level they ARE at).
        Regular nodes carry no community fields here — membership is expressed via
        relationships in node_relationships.
        """
        if not self.is_available() or not self.client:
            return
        collection = settings.QDRANT_COLLECTION_NODE_CORES
        payload: dict[str, Any] = {
            "node_id": node_id,
            "name": name,
            "type": node_type,
        }
        if description:
            payload["description"] = description
        if community_level is not None:
            payload["community_level"] = community_level
        if extra_payload:
            payload.update(extra_payload)
        try:
            self.client.upsert(
                collection_name=collection,
                points=[
                    PointStruct(
                        id=str(uuid.uuid5(uuid.NAMESPACE_OID, node_id)),
                        vector=description_vector,
                        payload=payload,
                    )
                ],
            )
        except Exception as exc:
            logger.warning(f"Qdrant upsert_node_core failed for {node_id}: {exc}")

    def upsert_node_items(
        self,
        collection_name: str,
        node_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        """Replace all points for a node in a sub-item collection.

        Each item dict must have:
          - ``content`` (str): the text to embed / store
          - ``vector`` (list[float]): pre-computed embedding
          - Any extra payload fields are forwarded as-is.

        The method first deletes all existing points with ``parent_node_id == node_id``
        then inserts fresh points so the collection always reflects current state.
        """
        if not self.is_available() or not self.client:
            return
        try:
            # Delete stale points for this node
            self.client.delete(
                collection_name=collection_name,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="parent_node_id",
                                match=MatchValue(value=node_id),
                            )
                        ]
                    )
                ),
            )
            if not items:
                return
            points = []
            for item in items:
                vector = item.get("vector")
                if not vector:
                    continue
                payload: dict[str, Any] = {"parent_node_id": node_id}
                for k, v in item.items():
                    if k != "vector":
                        payload[k] = v
                point_id = str(uuid.uuid4())
                points.append(PointStruct(id=point_id, vector=vector, payload=payload))
            if points:
                self.client.upsert(collection_name=collection_name, points=points)
        except Exception as exc:
            logger.warning(
                f"Qdrant upsert_node_items failed for {collection_name}/{node_id}: {exc}"
            )

    def append_node_item(
        self,
        collection_name: str,
        node_id: str,
        content: str,
        vector: list[float],
    ) -> None:
        """Append a single new item to a sub-item collection without touching existing points.

        Used for isolated_contexts so we never re-embed prior contexts — only the new one.
        """
        if not self.is_available() or not self.client:
            return
        try:
            point_id = str(uuid.uuid4())
            self.client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={"parent_node_id": node_id, "content": content},
                    )
                ],
            )
        except Exception as exc:
            logger.warning(
                f"Qdrant append_node_item failed for {collection_name}/{node_id}: {exc}"
            )

    def upsert_node_relationship(
        self,
        relationship_id: str,
        natural_language: str,
        nl_vector: list[float],
        source_node_id: str,
        target_node_id: str,
        is_community_rel: bool = False,
    ) -> None:
        """Upsert one point in node_relationships.

        ``is_community_rel`` marks membership relationships created during Leiden
        recomputation so they can be bulk-deleted when communities are rebuilt.
        """
        if not self.is_available() or not self.client:
            return
        collection = settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS
        payload: dict[str, Any] = {
            "natural_language": natural_language,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
        }
        if is_community_rel:
            payload["is_community_rel"] = True
        try:
            self.client.upsert(
                collection_name=collection,
                points=[
                    PointStruct(
                        id=str(uuid.uuid5(uuid.NAMESPACE_OID, relationship_id)),
                        vector=nl_vector,
                        payload=payload,
                    )
                ],
            )
        except Exception as exc:
            logger.warning(
                f"Qdrant upsert_node_relationship failed for {relationship_id}: {exc}"
            )

    def get_node_content_by_id(self, node_id: str) -> dict | None:
        """Fetch all content for a node from Qdrant.

        Returns a dict with keys: node_id, name, type, description, community_id,
        community_level, facts (list), potential_questions (list), isolated_contexts (list).
        Returns None if the node has no core entry.
        """
        if not self.is_available() or not self.client:
            return None

        point_id = str(uuid.uuid5(uuid.NAMESPACE_OID, node_id))
        try:
            cores = self.client.retrieve(
                collection_name=settings.QDRANT_COLLECTION_NODE_CORES,
                ids=[point_id],
                with_payload=True,
            )
        except Exception as exc:
            logger.debug(
                f"Qdrant get_node_content_by_id core failed for {node_id}: {exc}"
            )
            return None

        def _scroll_contents(collection: str) -> list[str]:
            try:
                scroll_filter = Filter(
                    must=[
                        FieldCondition(
                            key="parent_node_id", match=MatchValue(value=node_id)
                        )
                    ]
                )
                items: list[str] = []
                offset = None
                while True:
                    results, next_offset = self.client.scroll(
                        collection_name=collection,
                        scroll_filter=scroll_filter,
                        limit=100,
                        offset=offset,
                        with_payload=True,
                    )
                    for point in results:
                        content = (point.payload or {}).get("content")
                        if content:
                            items.append(content)
                    if next_offset is None:
                        break
                    offset = next_offset
                return items
            except Exception as exc:
                logger.debug(f"Qdrant scroll failed for {collection}/{node_id}: {exc}")
                return []

        if not cores:
            # No node_cores entry, but isolated_contexts may still exist in the
            # sub-item collection (e.g. node was written by _update_node_summary
            # which never calls upsert_node_core). Return what we can.
            isolated_only = _scroll_contents(
                settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS
            )
            if not isolated_only:
                return None
            return {
                "node_id": node_id,
                "name": "",
                "type": "",
                "description": "",
                "community_level": None,
                "isolated_contexts": isolated_only,
            }

        core_payload = cores[0].payload or {}

        return {
            "node_id": node_id,
            "name": core_payload.get("name", ""),
            "type": core_payload.get("type", ""),
            "description": core_payload.get("description", ""),
            "community_level": core_payload.get("community_level"),
            "isolated_contexts": _scroll_contents(
                settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS
            ),
        }

    def get_nodes_content_by_ids(self, node_ids: list[str]) -> dict[str, dict]:
        """Bulk-fetch content for multiple nodes from Qdrant.

        Returns a dict mapping node_id → content dict (same shape as get_node_content_by_id).
        Nodes with no core entry are omitted from the result.
        """
        if not self.is_available() or not self.client or not node_ids:
            return {}

        point_ids = [str(uuid.uuid5(uuid.NAMESPACE_OID, nid)) for nid in node_ids]
        cores_by_nodeid: dict[str, dict] = {}
        try:
            cores = self.client.retrieve(
                collection_name=settings.QDRANT_COLLECTION_NODE_CORES,
                ids=point_ids,
                with_payload=True,
            )
            for point in cores:
                payload = point.payload or {}
                nid = payload.get("node_id")
                if nid:
                    cores_by_nodeid[nid] = payload
        except Exception as exc:
            logger.debug(f"Qdrant get_nodes_content_by_ids cores failed: {exc}")

        def _bulk_scroll(collection: str) -> dict[str, list[str]]:
            try:
                scroll_filter = Filter(
                    must=[
                        FieldCondition(
                            key="parent_node_id", match=MatchAny(any=node_ids)
                        )
                    ]
                )
                result: dict[str, list[str]] = {}
                offset = None
                while True:
                    points, next_offset = self.client.scroll(
                        collection_name=collection,
                        scroll_filter=scroll_filter,
                        limit=500,
                        offset=offset,
                        with_payload=True,
                    )
                    for point in points:
                        payload = point.payload or {}
                        nid = payload.get("parent_node_id")
                        content = payload.get("content")
                        if nid and content:
                            result.setdefault(nid, []).append(content)
                    if next_offset is None:
                        break
                    offset = next_offset
                return result
            except Exception as exc:
                logger.debug(f"Qdrant bulk scroll failed for {collection}: {exc}")
                return {}

        contexts_by_id = _bulk_scroll(settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS)

        result: dict[str, dict] = {}
        for nid in node_ids:
            core = cores_by_nodeid.get(nid)
            if not core and nid not in contexts_by_id:
                continue
            result[nid] = {
                "node_id": nid,
                "name": (core or {}).get("name", ""),
                "type": (core or {}).get("type", ""),
                "description": (core or {}).get("description", ""),
                "community_level": (core or {}).get("community_level"),
                "isolated_contexts": contexts_by_id.get(nid, []),
            }
        return result

    def list_all_community_payloads(self) -> list[dict]:
        """Return a lightweight list of all community node rows from Qdrant node_cores.

        Each row has ``community_id``, ``community_level``, ``name``, and ``description``.
        Used for 3D layout computation and community description backfill.
        """
        if not self.is_available() or not self.client:
            return []
        rows: list[dict] = []
        try:
            offset = None
            while True:
                results, next_offset = self.client.scroll(
                    collection_name=settings.QDRANT_COLLECTION_NODE_CORES,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="type", match=MatchValue(value="community")
                            )
                        ]
                    ),
                    limit=500,
                    offset=offset,
                    with_payload=True,
                )
                for point in results:
                    p = point.payload or {}
                    rows.append(
                        {
                            "community_id": p.get("node_id"),
                            "community_level": p.get("community_level"),
                            "name": p.get("name"),
                            "description": p.get("description"),
                        }
                    )
                if next_offset is None:
                    break
                offset = next_offset
        except Exception as exc:
            logger.debug(f"Qdrant list_all_community_payloads failed: {exc}")
        return rows

    def delete_community_relationships(self) -> None:
        """Bulk-delete all node_relationship points flagged is_community_rel=True.

        Called at the start of every Leiden recompute so stale membership sentences
        are cleared before new ones are written.
        """
        if not self.is_available() or not self.client:
            return
        try:
            self.client.delete(
                collection_name=settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="is_community_rel",
                                match=MatchValue(value=True),
                            )
                        ]
                    )
                ),
            )
        except Exception as exc:
            logger.warning(f"Qdrant delete_community_relationships failed: {exc}")

    def find_node_id_by_name(self, name: str) -> str | None:
        """Resolve a node name to its stable node_id via the node_cores collection.

        Names are stored lowercase in Qdrant (normalized during ingestion).
        Returns the node_id string or None if not found.
        """
        if not self.is_available() or not self.client or not name:
            return None
        try:
            results, _ = self.client.scroll(
                collection_name=settings.QDRANT_COLLECTION_NODE_CORES,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="name",
                            match=MatchValue(value=name.lower().strip()),
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if results:
                return (results[0].payload or {}).get("node_id")
            return None
        except Exception as exc:
            logger.debug(f"[Qdrant] find_node_id_by_name failed for '{name}': {exc}")
            return None

    def find_node_ids_by_names(self, names: list[str]) -> dict[str, str | None]:
        """Batch-resolve node names to stable node_ids in a single Qdrant scroll.

        Returns a dict mapping each normalized name to its node_id (or None if not found).
        Uses a single OR-filter scroll instead of one query per name.
        """
        if not self.is_available() or not self.client or not names:
            return {}
        normalized = [n.lower().strip() for n in names if n and n.strip()]
        if not normalized:
            return {}
        result_map: dict[str, str | None] = {n: None for n in normalized}
        try:
            # Page through all matches so duplicates do not starve out other names
            # under a fixed limit. Stop early once all requested names are resolved.
            _scroll_filter = Filter(
                must=[
                    FieldCondition(
                        key="name",
                        match=MatchAny(any=normalized),
                    )
                ]
            )
            offset = None
            while True:
                results, next_offset = self.client.scroll(
                    collection_name=settings.QDRANT_COLLECTION_NODE_CORES,
                    scroll_filter=_scroll_filter,
                    limit=500,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in results:
                    payload = point.payload or {}
                    node_name = (payload.get("name") or "").lower().strip()
                    node_id = payload.get("node_id")
                    # Keep first non-empty mapping per name for deterministic behavior.
                    if (
                        node_name
                        and node_id
                        and node_name in result_map
                        and result_map[node_name] is None
                    ):
                        result_map[node_name] = node_id

                if all(v is not None for v in result_map.values()):
                    break
                if next_offset is None:
                    break
                offset = next_offset
        except Exception as exc:
            logger.debug(f"[Qdrant] find_node_ids_by_names failed: {exc}")
        return result_map

    def get_relationships_for_node_ids(self, node_ids: list[str]) -> list[dict]:
        """Fetch all relationship points from node_relationships where source or target is in node_ids.

        Returns list of dicts: {natural_language, source_node_id, target_node_id,
        source_node_name, target_node_name}.
        """
        if not self.is_available() or not self.client or not node_ids:
            return []
        try:
            results: list[dict] = []
            for direction_key in ("source_node_id", "target_node_id"):
                scroll_filter = Filter(
                    must=[
                        FieldCondition(
                            key=direction_key,
                            match=MatchAny(any=node_ids),
                        )
                    ]
                )
                offset = None
                while True:
                    points, next_offset = self.client.scroll(
                        collection_name=settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS,
                        scroll_filter=scroll_filter,
                        limit=500,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False,
                    )
                    for point in points:
                        payload = point.payload or {}
                        results.append(
                            {
                                "natural_language": payload.get("natural_language", ""),
                                "source_node_id": payload.get("source_node_id", ""),
                                "target_node_id": payload.get("target_node_id", ""),
                            }
                        )
                    if next_offset is None:
                        break
                    offset = next_offset
            # Deduplicate by natural_language
            seen: set[str] = set()
            unique: list[dict] = []
            for r in results:
                key = r["natural_language"]
                if key and key not in seen:
                    seen.add(key)
                    unique.append(r)
            return unique
        except Exception as exc:
            logger.debug(f"[Qdrant] get_relationships_for_node_ids failed: {exc}")
            return []

    def delete_node(self, node_id: str) -> None:
        """Delete a node core and all child items keyed by parent_node_id."""
        if not self.is_available() or not self.client:
            return

        try:
            self.client.delete(
                collection_name=settings.QDRANT_COLLECTION_NODE_CORES,
                points_selector=[str(uuid.uuid5(uuid.NAMESPACE_OID, node_id))],
            )
            for collection_name in (settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,):
                self.client.delete(
                    collection_name=collection_name,
                    points_selector=FilterSelector(
                        filter=Filter(
                            must=[
                                FieldCondition(
                                    key="parent_node_id",
                                    match=MatchValue(value=node_id),
                                )
                            ]
                        )
                    ),
                )
        except Exception as exc:
            logger.warning(f"Qdrant delete_node failed for {node_id}: {exc}")


qdrant_service = QdrantService()
