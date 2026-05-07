"""Graph service backed by Kuzu (embedded graph database).

Schema
------
Node table:
    Node(id STRING PRIMARY KEY, kind STRING, name STRING, type STRING,
         pos_x DOUBLE, pos_y DOUBLE, pos_z DOUBLE)

  kind values: 'note' | 'indexable' | 'community'

Relationship tables:
    REFERENCES(FROM Node TO Node, note_id STRING, is_active BOOLEAN)
    MEMBER_OF(FROM Node TO Node, level INT64)
    CONTAINS(FROM Node TO Node)
    SEMANTIC_REL(FROM Node TO Node,
        rel_type STRING, confidence DOUBLE, strength DOUBLE,
        relevance DOUBLE, edge_weight DOUBLE, relationship_id STRING,
        ingested_at STRING, last_updated STRING, mention_count INT64,
        is_active BOOLEAN, note_id STRING, valid_from STRING, valid_to STRING,
        evolved_from STRING, evolved_to STRING, invalidated_by STRING,
        invalidation_note_id STRING, evolution_note_id STRING,
        is_similarity BOOLEAN, created_at STRING)

Cypher translation notes
------------------------
- MATCH (n:Indexable)       -> MATCH (n:Node) WHERE n.kind IN ['indexable','note']
- MATCH (n:Note)            -> MATCH (n:Node) WHERE n.kind = 'note'
- MATCH (n:Community)       -> MATCH (n:Node) WHERE n.kind = 'community'
- NOT n:Note AND NOT n:Community -> n.kind = 'indexable'
- labels(n)                 -> [n.kind]
- type(r) for semantic rels -> r.rel_type
- elementId(n)              -> n.id
- Dynamic :REL_TYPE         -> :SEMANTIC_REL with r.rel_type = $rel_type
- n =~ 'pattern'            -> regexp_matches(n, 'pattern')
"""

import re
import threading
from pathlib import Path

import kuzu
from app.core.config import REPO_ROOT, settings
from app.core.log import get_logger
from app.services.qdrant_service import qdrant_service

logger = get_logger("GraphService")


def _strip_facts_prefix(text: str) -> str:
    """Strip the legacy 'FACTS: k=v | k=v. Prose...' prefix from stored descriptions."""
    if not text or not text.startswith("FACTS:"):
        return text
    m = re.search(r"^FACTS:.*?[.]\s+(.*)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_STMTS = [
    """CREATE NODE TABLE IF NOT EXISTS Node(
        id STRING,
        kind STRING,
        name STRING,
        type STRING,
        pos_x DOUBLE,
        pos_y DOUBLE,
        pos_z DOUBLE,
        PRIMARY KEY(id)
    )""",
    """CREATE REL TABLE IF NOT EXISTS REFERENCES(
        FROM Node TO Node,
        note_id STRING,
        is_active BOOLEAN
    )""",
    """CREATE REL TABLE IF NOT EXISTS MEMBER_OF(
        FROM Node TO Node,
        level INT64
    )""",
    """CREATE REL TABLE IF NOT EXISTS CONTAINS(
        FROM Node TO Node
    )""",
    """CREATE REL TABLE IF NOT EXISTS SEMANTIC_REL(
        FROM Node TO Node,
        rel_type STRING,
        confidence DOUBLE,
        strength DOUBLE,
        relevance DOUBLE,
        edge_weight DOUBLE,
        relationship_id STRING,
        ingested_at STRING,
        last_updated STRING,
        mention_count INT64,
        is_active BOOLEAN,
        note_id STRING,
        valid_from STRING,
        valid_to STRING,
        evolved_from STRING,
        evolved_to STRING,
        invalidated_by STRING,
        invalidation_note_id STRING,
        evolution_note_id STRING,
        is_similarity BOOLEAN,
        created_at STRING
    )""",
]


class GraphService:
    def __init__(self):
        db_path = Path(settings.KUZU_DB_PATH).expanduser()
        if not db_path.is_absolute():
            db_path = REPO_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_db_path(db_path)

        self.db = kuzu.Database(str(db_path))
        self.conn = kuzu.Connection(self.db)
        self._lock = threading.RLock()
        self._init_schema()

    def _migrate_legacy_db_path(self, db_path: Path) -> None:
        """Move legacy Kuzu files from data root into the dedicated kuzu folder."""
        legacy_db_path = REPO_ROOT / "data" / "kuzu_graph"
        if db_path == legacy_db_path or db_path.exists():
            return

        legacy_wal_path = Path(f"{legacy_db_path}.wal")
        target_wal_path = Path(f"{db_path}.wal")
        if not legacy_db_path.exists() and not legacy_wal_path.exists():
            return

        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            if legacy_db_path.exists() and not db_path.exists():
                legacy_db_path.rename(db_path)
            if legacy_wal_path.exists() and not target_wal_path.exists():
                legacy_wal_path.rename(target_wal_path)
            logger.info(f"[Graph] Migrated Kuzu data to '{db_path}'.")
        except Exception as exc:
            logger.warning(f"[Graph] Legacy Kuzu migration skipped: {exc}")

    def _init_schema(self) -> None:
        """Create all tables if they do not exist."""
        for stmt in _SCHEMA_STMTS:
            try:
                with self._lock:
                    self.conn.execute(stmt)
            except Exception as exc:
                if "already exist" not in str(exc).lower():
                    logger.warning(f"[Graph] Schema init: {exc}")

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def resolve_node_id(self, name: str) -> str | None:
        """Resolve a node name to its stable node_id via Qdrant node_cores."""
        return qdrant_service.find_node_id_by_name(name)

    def verify_connection(self) -> bool:
        try:
            self.execute_query("MATCH (n:Node) RETURN count(n) AS c LIMIT 1")
            return True
        except Exception as exc:
            logger.error(f"[Graph] Connection check failed: {exc}")
            return False

    def execute_query(self, query: str, params: dict = None):
        if params is None:
            params = {}
        with self._lock:
            try:
                result = self.conn.execute(query, params)
                columns = result.get_column_names()
                rows = []
                while result.has_next():
                    row_values = result.get_next()
                    rows.append(dict(zip(columns, row_values)))
                return rows
            except Exception as exc:
                logger.error(f"[Graph] Query Failed: {exc}")
                logger.error(f"  Query: {query}")
                logger.error(f"  Params: {params}")
                raise

    # ---- Node lookup --------------------------------------------------------

    def find_nodes_by_name(self, names: list[str], fuzzy: bool = True) -> list[dict]:
        if not names:
            return []
        names_lower = [n.lower() for n in names]

        if fuzzy:
            query = """
                        UNWIND $names AS q
            MATCH (n:Node)
            WHERE n.kind IN ['indexable', 'note']
                            AND toLower(n.name) CONTAINS q
            RETURN DISTINCT
                n.id AS node_id,
                n.name AS name,
                [n.kind] AS labels,
                n.type AS entity_type,
                                q AS matched_query
            LIMIT 50
            """
        else:
            query = """
            MATCH (n:Node)
            WHERE n.kind IN ['indexable', 'note']
              AND toLower(n.name) IN $names
            RETURN DISTINCT
                n.id AS node_id,
                n.name AS name,
                [n.kind] AS labels,
                n.type AS entity_type,
                toLower(n.name) AS matched_query
            LIMIT 50
            """
        return self.execute_query(query, {"names": names_lower})

    def find_name_variants(self, base_name: str, limit: int = 5) -> list[dict]:
        base_lower = base_name.lower().strip()
        _SUFFIX_PAT = ".* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$"
        query = """
        MATCH (n:Node)
        WHERE n.kind IN ['indexable', 'note']
          AND (toLower(n.name) STARTS WITH ($base_name + ' ')
           OR (toLower(n.name) CONTAINS $base_name AND size(n.name) > size($base_name) + 2))
          AND NOT (
            (toLower(n.name) CONTAINS ' sr' AND toLower($base_name) CONTAINS ' jr')
            OR (toLower(n.name) CONTAINS ' jr' AND toLower($base_name) CONTAINS ' sr')
            OR (regexp_matches(toLower(n.name), $suffix_pat)
                AND NOT regexp_matches(toLower($base_name), $suffix_pat))
            OR (regexp_matches(toLower($base_name), $suffix_pat)
                AND NOT regexp_matches(toLower(n.name), $suffix_pat))
          )
        RETURN DISTINCT
            n.id AS node_id,
            n.name AS name,
            [n.kind] AS labels,
            n.type AS entity_type
        LIMIT $limit
        """
        return self.execute_query(
            query,
            {"base_name": base_lower, "limit": limit, "suffix_pat": _SUFFIX_PAT},
        )

    def find_similar_entities(
        self,
        entity_name: str,
        entity_type: str = "Person",
        limit: int = 10,
        node_label: str = "Indexable",
    ) -> list[dict]:
        import re as _re

        name_lower = entity_name.lower().strip()
        name_parts = name_lower.split()
        _SUFFIX_RE = _re.compile(r"^(sr\.?|jr\.?|senior|junior|[ivxlc]{1,6})$", _re.I)
        _SUFFIX_PAT = ".* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$"

        if entity_type.lower() == "person" and len(name_parts) >= 2:
            first_name = name_parts[0]
            last_name = name_parts[-1]
            if _SUFFIX_RE.match(last_name):
                last_name = name_parts[-2] if len(name_parts) > 2 else name_parts[0]

            query = """
            MATCH (e:Node)
            WHERE e.kind IN ['indexable', 'note']
              AND toLower(e.type) = 'person'
              AND toLower(e.name) <> $name
              AND size(string_split(trim(e.name), ' ')) >= 2
              AND (
                toLower($name) STARTS WITH (toLower(e.name) + ' ')
                OR toLower(e.name) STARTS WITH (toLower($name) + ' ')
                OR (toLower(e.name) STARTS WITH ($first_name + ' ')
                    AND toLower(e.name) ENDS WITH (' ' + $last_name))
              )
              AND NOT (
                (toLower(e.name) CONTAINS ' sr' AND toLower($name) CONTAINS ' jr')
                OR (toLower(e.name) CONTAINS ' jr' AND toLower($name) CONTAINS ' sr')
                OR (regexp_matches(toLower(e.name), $suffix_pat)
                    AND NOT regexp_matches(toLower($name), $suffix_pat))
                OR (regexp_matches(toLower($name), $suffix_pat)
                    AND NOT regexp_matches(toLower(e.name), $suffix_pat))
              )
            RETURN e.id AS node_id, e.name AS name, e.type AS entity_type
            LIMIT $limit
            """
            return self.execute_query(
                query,
                {
                    "name": name_lower,
                    "first_name": first_name,
                    "last_name": last_name,
                    "limit": limit,
                    "suffix_pat": _SUFFIX_PAT,
                },
            )
        else:
            type_filter = (
                "AND toLower(e.type) = toLower($entity_type)"
                if entity_type and entity_type.lower() not in ("unknown", "")
                else ""
            )
            _YEAR_PAT = ".*(^| )[0-9]{4}( |$).*"
            query = f"""
            MATCH (e:Node)
            WHERE e.kind IN ['indexable', 'note']
              AND toLower(e.name) <> $name
              {type_filter}
              AND (
                toLower($name) CONTAINS toLower(e.name)
                OR toLower(e.name) CONTAINS toLower($name)
              )
              AND size(string_split(trim(e.name), ' ')) >= 2
              AND size(string_split(trim($name), ' ')) >= 2
              AND abs(size(e.name) - size($name)) >= 2
              AND NOT regexp_matches($name, $year_pat)
              AND NOT regexp_matches(toLower(e.name), $year_pat)
            RETURN e.id AS node_id, e.name AS name, e.type AS entity_type
            LIMIT $limit
            """
            return self.execute_query(
                query,
                {
                    "name": name_lower,
                    "entity_type": entity_type,
                    "limit": limit,
                    "year_pat": _YEAR_PAT,
                },
            )

    def get_similar_entities(
        self, entity_name: str, node_label: str = "Indexable"
    ) -> list[dict]:
        name_lower = entity_name.lower().strip()
        node_id = self.resolve_node_id(name_lower)
        if not node_id:
            return []
        query = """
        MATCH (e:Node {id: $node_id})-[r:SEMANTIC_REL]-(similar:Node)
        WHERE r.is_similarity = true
        RETURN DISTINCT similar.id AS node_id, r.rel_type AS rel_type
        """
        return self.execute_query(query, {"node_id": node_id})

    def find_paths_between_nodes(
        self,
        node_names: list[str],
        max_depth: int = 3,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        if len(node_names) < 2:
            return []
        node_ids = [
            nid
            for n in node_names
            if (nid := qdrant_service.find_node_id_by_name(n.lower().strip()))
        ]
        if len(node_ids) < 2:
            return []

        # NOTE: Do NOT add `all(rel IN relationships(path) WHERE ...)` inside a
        # variable-length MATCH — it triggers a KU_UNREACHABLE parser assertion in
        # this Kuzu build.  Confidence and is_active filtering is done in Python
        # below after the query returns.
        query = f"""
        UNWIND $node_ids AS source_id
        UNWIND $node_ids AS target_id
        WITH source_id, target_id
        WHERE source_id < target_id
        MATCH (source:Node {{id: source_id}}), (target:Node {{id: target_id}})
        MATCH path = (source)-[:SEMANTIC_REL|REFERENCES*1..{max_depth}]-(target)
        WITH path, source_id, target_id, length(path) AS pathLength,
             relationships(path) AS rels
        RETURN DISTINCT
            source_id,
            target_id,
            [node IN nodes(path) | node.id] AS path_node_ids,
            [rel IN rels |
                CASE WHEN label(rel) = 'SEMANTIC_REL' THEN rel.rel_type
                     ELSE label(rel) END
            ] AS relationship_types,
            [rel IN rels | coalesce(rel.confidence, 0.8)] AS confidence_path,
            [rel IN rels | coalesce(rel.is_active, true)] AS is_active_path,
            pathLength AS depth
        ORDER BY pathLength
        LIMIT 20
        """
        rows = self.execute_query(query, {"node_ids": node_ids})
        # Post-filter: keep only paths where every hop meets confidence and is_active.
        return [
            r
            for r in rows
            if all(c >= min_confidence for c in (r.get("confidence_path") or []))
            and all(a for a in (r.get("is_active_path") or [True]))
        ]

    def get_indexable_nodes_for_communities(self) -> list[dict]:
        query = """
        MATCH (n:Node)
        WHERE n.kind = 'indexable' AND n.id IS NOT NULL
        RETURN
            n.id AS node_id,
            n.name AS name,
            n.type AS type
        """
        return self.execute_query(query, {})

    def get_weighted_relationships_for_communities(self) -> list[dict]:
        query = """
        MATCH (a:Node)-[r:SEMANTIC_REL]->(b:Node)
        WHERE a.kind = 'indexable' AND b.kind = 'indexable'
          AND a.id IS NOT NULL AND b.id IS NOT NULL
          AND a.id < b.id
          AND (r.is_active = true OR r.is_active IS NULL)
        RETURN DISTINCT
            a.id AS source_node_id,
            b.id AS target_node_id,
            CASE
                WHEN r.edge_weight IS NOT NULL THEN r.edge_weight
                WHEN r.confidence IS NOT NULL THEN r.confidence * 10.0
                ELSE 1.0
            END AS weight
        """
        return self.execute_query(query, {})

    def clear_all_communities(self) -> list[str]:
        existing = self.execute_query(
            "MATCH (c:Node) WHERE c.kind = 'community' RETURN c.id AS community_id",
            {},
        )
        community_ids = [
            row["community_id"] for row in existing if row.get("community_id")
        ]
        self.execute_query("MATCH ()-[r:MEMBER_OF]->() DELETE r", {})
        self.execute_query(
            "MATCH (c:Node) WHERE c.kind = 'community' DETACH DELETE c", {}
        )
        qdrant_service.delete_community_relationships()
        return community_ids

    def set_node_community_membership(
        self, node_ids: list[str], community_id: str, community_level: int
    ) -> None:
        if not node_ids:
            return
        for node_id in node_ids:
            self.execute_query(
                """
                MATCH (c:Node {id: $community_id})
                MATCH (n:Node {id: $node_id})
                MERGE (n)-[r:MEMBER_OF]->(c)
                SET r.level = $community_level
                """,
                {
                    "node_id": node_id,
                    "community_id": community_id,
                    "community_level": community_level,
                },
            )

    def create_leiden_community(
        self,
        community_id: str,
        community_level: int,
        name: str,
        summary: str,
        member_node_ids: list[str],
    ) -> dict:
        from app.services.embedding import embedding_service as _emb

        self.execute_query(
            """
            MERGE (c:Node {id: $community_id})
            ON CREATE SET c.kind = 'community', c.type = 'community', c.name = $name
            ON MATCH SET c.name = $name
            """,
            {"community_id": community_id, "name": name},
        )

        for member_id in member_node_ids:
            try:
                self.execute_query(
                    """
                    MATCH (c:Node {id: $community_id})
                    MATCH (n:Node {id: $member_id})
                    MERGE (c)-[:CONTAINS]->(n)
                    """,
                    {"community_id": community_id, "member_id": member_id},
                )
            except Exception as exc:
                logger.debug(
                    f"[Graph] CONTAINS edge {community_id}->{member_id} skipped: {exc}"
                )

        try:
            summary_text = summary or name or community_id
            summary_vector = _emb.embed_documents([summary_text])[0]
            qdrant_service.upsert_node_core(
                node_id=community_id,
                name=name,
                node_type="community",
                description=summary_text,
                description_vector=summary_vector,
                community_level=community_level,
            )
        except Exception as exc:
            logger.warning(
                f"[Graph] create_leiden_community Qdrant write failed: {exc}"
            )

        return {"community_id": community_id}

    def get_node_storage_payload(self, node_id: str) -> dict | None:
        rows = self.execute_query(
            "MATCH (n:Node {id: $node_id}) RETURN n.id AS node_id, [n.kind] AS labels",
            {"node_id": node_id},
        )
        if not rows:
            return None
        row = dict(rows[0])

        try:
            content = qdrant_service.get_node_content_by_id(node_id)
        except Exception as exc:
            logger.warning(
                f"[Graph] get_node_storage_payload Qdrant fetch failed for {node_id}: {exc}"
            )
            content = None

        try:
            rels = qdrant_service.get_relationships_for_node_ids([node_id])
            relationship_natural_language = [
                r["natural_language"] for r in rels if r.get("natural_language")
            ]
        except Exception as exc:
            logger.warning(
                f"[Graph] get_node_storage_payload NL fetch failed for {node_id}: {exc}"
            )
            relationship_natural_language = []

        row["name"] = (content or {}).get("name", "")
        row["description"] = _strip_facts_prefix((content or {}).get("description", ""))
        row["facts"] = (content or {}).get("facts", [])
        row["potential_questions"] = (content or {}).get("potential_questions", [])
        row["isolated_contexts"] = (content or {}).get("isolated_contexts", [])
        row["community_level"] = (content or {}).get("community_level")
        row["relationship_natural_language"] = relationship_natural_language
        return row

    def get_node_source_notes(
        self, node_names: list[str], node_labels: list[str]
    ) -> list[dict]:
        if not node_names:
            return []
        node_ids = [
            nid
            for n in node_names
            if (nid := qdrant_service.find_node_id_by_name(n.lower().strip()))
        ]
        if not node_ids:
            return []
        query = """
        UNWIND $node_ids AS node_id
        MATCH (n:Node {id: node_id})<-[r:REFERENCES]-(note:Node)
        WHERE note.kind = 'note' AND r.is_active = true
        RETURN n.id AS node_id, note.id AS note_id, 'REFERENCES' AS relationship_type
        """
        return self.execute_query(query, {"node_ids": node_ids})

    def get_linked_evidence(
        self, node_names: list[str], limit_per_node: int = 3
    ) -> list[dict]:
        if not node_names:
            return []
        normalized_names = [n.lower().strip() for n in node_names if n and n.strip()]
        if not normalized_names:
            return []

        name_to_id = qdrant_service.find_node_ids_by_names(normalized_names)
        id_to_name = {nid: name for name, nid in name_to_id.items() if nid and name}
        if not id_to_name:
            return []

        return self.get_linked_evidence_by_node_ids(
            list(id_to_name.keys()),
            limit_per_node=limit_per_node,
            node_id_to_name=id_to_name,
        )

    def get_linked_evidence_by_node_ids(
        self,
        node_ids: list[str],
        limit_per_node: int = 3,
        node_id_to_name: dict[str, str] | None = None,
    ) -> list[dict]:
        """Fetch linked note evidence for known node IDs.

        This avoids brittle name-to-id resolution when candidate names are aliases,
        enriched variants, or missing from sub-collection payloads.
        """
        if not node_ids:
            return []

        unique_node_ids = list(dict.fromkeys(nid for nid in node_ids if nid))
        if not unique_node_ids:
            return []

        query = """
        UNWIND $node_ids AS node_id
        MATCH (n:Node {id: node_id})<-[r:REFERENCES]-(note:Node)
        WHERE note.kind = 'note' AND r.is_active = true
        WITH node_id, collect(DISTINCT {id: note.id, title: note.name}) AS evidence
        RETURN node_id, evidence
        """
        rows = self.execute_query(query, {"node_ids": unique_node_ids})
        id_to_name = {
            nid: (name or "").lower().strip()
            for nid, name in (node_id_to_name or {}).items()
            if nid
        }
        for row in rows:
            row["evidence"] = (row.get("evidence") or [])[:limit_per_node]
            row["node_name"] = id_to_name.get(row.get("node_id", ""), "")
        return rows

    def get_full_graph(self) -> dict:
        nodes_query = """
        MATCH (n:Node)
        WHERE n.kind IN ['indexable', 'note']
        RETURN n.id AS node_id, [n.kind] AS labels
        """
        links_query = """
        MATCH (source:Node)-[r:SEMANTIC_REL|REFERENCES]->(target:Node)
        WHERE (r.is_active = true OR r.is_active IS NULL)
          AND source.kind IN ['indexable', 'note']
          AND target.kind IN ['indexable', 'note']
        RETURN
            source.id AS source,
            target.id AS target,
            CASE WHEN label(r) = 'SEMANTIC_REL' THEN r.rel_type
                 ELSE label(r) END AS type,
            r.edge_weight AS edge_weight
        """
        nodes_data = self.execute_query(nodes_query)
        links_data = self.execute_query(links_query)

        node_ids = [row["node_id"] for row in nodes_data if row.get("node_id")]
        content_map = (
            qdrant_service.get_nodes_content_by_ids(node_ids) if node_ids else {}
        )

        nodes = []
        for row in nodes_data:
            nid = row.get("node_id")
            c = content_map.get(nid, {})
            nodes.append(
                {
                    "id": nid,
                    "name": c.get("name") or nid or "Unknown",
                    "group": c.get("type") or "unknown",
                    "description": _strip_facts_prefix(c.get("description", "")),
                    "entity_type": c.get("type") or "unknown",
                    "labels": row.get("labels", []),
                }
            )
        links = [
            {
                "source": link["source"],
                "target": link["target"],
                "type": link["type"],
                "edge_weight": link.get("edge_weight"),
            }
            for link in links_data
            if link.get("source") and link.get("target")
        ]
        return {"nodes": nodes, "links": links}

    # ---- Relationship management -------------------------------------------

    def create_or_update_relationship(
        self,
        source_name: str,
        source_label: str,
        target_name: str,
        target_label: str,
        relationship_type: str,
        confidence: float = 1.0,
        strength: float = 5.0,
        relevance: float = 5.0,
        natural_language: str = "",
        relationship_id: str = None,
        context: str = "",
        note_id: str = None,
        source_id: str = "",
        target_id: str = "",
    ) -> dict:
        import uuid as _uuid
        from datetime import datetime

        from app.schemas.relationships import (
            can_evolve,
            get_contradicting_types,
            is_bidirectional,
        )

        if not relationship_type or not relationship_type.strip():
            raise ValueError(
                f"relationship_type cannot be empty for {source_name} -> {target_name}"
            )

        relationship_type = re.sub(r"[^A-Za-z0-9_]", "_", relationship_type.strip())

        if not relationship_id:
            relationship_id = str(_uuid.uuid4())

        edge_weight = round(
            (strength * 0.5) + (confidence * 0.3) + (relevance * 0.2), 4
        )

        if not source_id and source_name:
            source_id = self.resolve_node_id(source_name.lower().strip()) or ""
        if not target_id and target_name:
            target_id = self.resolve_node_id(target_name.lower().strip()) or ""

        if not source_id or not target_id:
            logger.warning(
                f"[Graph] Skipping relationship {source_name}->{target_name}: "
                f"unresolvable IDs (src={source_id!r} tgt={target_id!r})"
            )
            return {
                "action": "failed",
                "reason": "unresolvable IDs",
                "source": source_name,
                "target": target_name,
                "relationship_type": relationship_type,
                "confidence": confidence,
                "strength": strength,
                "relevance": relevance,
                "edge_weight": edge_weight,
                "natural_language": natural_language,
                "relationship_id": relationship_id,
                "previous_type": None,
            }

        ingestion_time = datetime.utcnow().isoformat()

        contradicting_types = get_contradicting_types(relationship_type)
        for contra_type in contradicting_types:
            result = self.execute_query(
                """
                MATCH (source:Node {id: $source_id})-[r:SEMANTIC_REL]->(target:Node {id: $target_id})
                WHERE r.rel_type = $contra_type AND r.is_active = true
                SET r.is_active = false,
                    r.valid_to = $ingestion_time,
                    r.invalidated_by = $relationship_type,
                    r.invalidation_note_id = $note_id
                RETURN r.rel_type AS invalidated_type
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "contra_type": contra_type,
                    "ingestion_time": ingestion_time,
                    "relationship_type": relationship_type,
                    "note_id": note_id,
                },
            )
            for r in result or []:
                if r.get("invalidated_type"):
                    logger.info(
                        f"[Bi-Temporal] Invalidated: ({source_name})"
                        f"-[{r['invalidated_type']}]->({target_name})"
                    )

        existing = self.execute_query(
            """
            MATCH (source:Node {id: $source_id})-[r:SEMANTIC_REL]->(target:Node {id: $target_id})
            WHERE r.rel_type = $rel_type
              AND (r.is_active = true OR r.is_active IS NULL)
            RETURN r.rel_type AS current_type, r.confidence AS current_confidence
            LIMIT 1
            """,
            {
                "source_id": source_id,
                "target_id": target_id,
                "rel_type": relationship_type,
            },
        )

        existing_other = self.execute_query(
            """
            MATCH (source:Node {id: $source_id})-[r:SEMANTIC_REL]->(target:Node {id: $target_id})
            WHERE r.rel_type <> $rel_type
              AND (r.is_active = true OR r.is_active IS NULL)
            RETURN r.rel_type AS current_type
            LIMIT 1
            """,
            {
                "source_id": source_id,
                "target_id": target_id,
                "rel_type": relationship_type,
            },
        )

        action = "created"
        previous_type = None

        if existing:
            action = "reinforced"
            self.execute_query(
                """
                MATCH (source:Node {id: $source_id})-[r:SEMANTIC_REL]->(target:Node {id: $target_id})
                WHERE r.rel_type = $rel_type
                  AND (r.is_active = true OR r.is_active IS NULL)
                SET r.last_updated = $ingestion_time,
                    r.mention_count = coalesce(r.mention_count, 0) + 1,
                    r.confidence = CASE
                        WHEN $confidence > coalesce(r.confidence, 0.0) THEN $confidence
                        ELSE r.confidence
                    END,
                    r.is_active = true,
                    r.relationship_id = CASE
                        WHEN r.relationship_id IS NULL THEN $relationship_id
                        ELSE r.relationship_id
                    END,
                    r.strength = CASE WHEN r.strength IS NULL THEN $strength ELSE r.strength END,
                    r.relevance = CASE WHEN r.relevance IS NULL THEN $relevance ELSE r.relevance END,
                    r.edge_weight = CASE WHEN r.edge_weight IS NULL THEN $edge_weight ELSE r.edge_weight END
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "rel_type": relationship_type,
                    "confidence": confidence,
                    "ingestion_time": ingestion_time,
                    "relationship_id": relationship_id,
                    "strength": strength,
                    "relevance": relevance,
                    "edge_weight": edge_weight,
                },
            )
        elif existing_other:
            current_type = existing_other[0]["current_type"]
            if can_evolve(current_type, relationship_type):
                action = "evolved"
                previous_type = current_type
                self.execute_query(
                    """
                    MATCH (source:Node {id: $source_id})-[r:SEMANTIC_REL]->(target:Node {id: $target_id})
                    WHERE r.rel_type = $current_type
                      AND (r.is_active = true OR r.is_active IS NULL)
                    SET r.is_active = false,
                        r.valid_to = $ingestion_time,
                        r.evolved_to = $new_type,
                        r.evolution_note_id = $note_id
                    """,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "current_type": current_type,
                        "ingestion_time": ingestion_time,
                        "new_type": relationship_type,
                        "note_id": note_id,
                    },
                )
                self.execute_query(
                    """
                    MATCH (source:Node {id: $source_id})
                    MATCH (target:Node {id: $target_id})
                    CREATE (source)-[r:SEMANTIC_REL]->(target)
                    SET r.rel_type = $rel_type,
                        r.confidence = $confidence,
                        r.strength = $strength,
                        r.relevance = $relevance,
                        r.edge_weight = $edge_weight,
                        r.relationship_id = $relationship_id,
                        r.ingested_at = $ingestion_time,
                        r.last_updated = $ingestion_time,
                        r.evolved_from = $previous_type,
                        r.mention_count = 1,
                        r.is_active = true,
                        r.note_id = $note_id
                    """,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "rel_type": relationship_type,
                        "confidence": confidence,
                        "strength": strength,
                        "relevance": relevance,
                        "edge_weight": edge_weight,
                        "relationship_id": relationship_id,
                        "ingestion_time": ingestion_time,
                        "previous_type": previous_type,
                        "note_id": note_id,
                    },
                )
                logger.info(
                    f"[Bi-Temporal] Evolved: ({source_name})"
                    f"-[{previous_type}\u2192{relationship_type}]->({target_name})"
                )
            else:
                # current_type cannot evolve to relationship_type.
                # If current_type has no evolution rules defined at all, the two
                # relationships are semantically independent (e.g. IS_MARRIED_SPOUSE
                # and IS_PERSONA) — create the new one as a parallel edge instead
                # of rejecting.  Only reject when evolution was explicitly defined
                # but this specific target type is excluded.
                from app.schemas.relationships import EVOLUTION_RULES as _EVO_RULES

                if current_type not in _EVO_RULES:
                    logger.debug(
                        f"[Bi-Temporal] '{current_type}' has no evolution rules — "
                        f"creating '{relationship_type}' as parallel edge "
                        f"({source_name} → {target_name})"
                    )
                    action = "created_parallel"
                    self.execute_query(
                        """
                        MATCH (source:Node {id: $source_id})
                        MATCH (target:Node {id: $target_id})
                        CREATE (source)-[r:SEMANTIC_REL]->(target)
                        SET r.rel_type = $rel_type,
                            r.confidence = $confidence,
                            r.strength = $strength,
                            r.relevance = $relevance,
                            r.edge_weight = $edge_weight,
                            r.relationship_id = $relationship_id,
                            r.ingested_at = $ingestion_time,
                            r.last_updated = $ingestion_time,
                            r.mention_count = 1,
                            r.is_active = true,
                            r.note_id = $note_id
                        """,
                        {
                            "source_id": source_id,
                            "target_id": target_id,
                            "rel_type": relationship_type,
                            "confidence": confidence,
                            "strength": strength,
                            "relevance": relevance,
                            "edge_weight": edge_weight,
                            "relationship_id": relationship_id,
                            "ingestion_time": ingestion_time,
                            "note_id": note_id,
                        },
                    )
                else:
                    logger.warning(
                        f"Cannot evolve relationship {current_type} to {relationship_type}"
                    )
                    return {
                        "action": "rejected",
                        "reason": f"Cannot evolve {current_type} to {relationship_type}",
                        "source": source_name,
                        "target": target_name,
                        "relationship_type": relationship_type,
                        "confidence": confidence,
                        "strength": strength,
                        "relevance": relevance,
                        "edge_weight": edge_weight,
                        "natural_language": natural_language,
                        "relationship_id": relationship_id,
                        "previous_type": None,
                    }
        else:
            self.execute_query(
                "MERGE (n:Node {id: $id}) ON CREATE SET n.kind = 'indexable'",
                {"id": source_id},
            )
            self.execute_query(
                "MERGE (n:Node {id: $id}) ON CREATE SET n.kind = 'indexable'",
                {"id": target_id},
            )
            self.execute_query(
                """
                MATCH (source:Node {id: $source_id})
                MATCH (target:Node {id: $target_id})
                CREATE (source)-[r:SEMANTIC_REL]->(target)
                SET r.rel_type = $rel_type,
                    r.confidence = $confidence,
                    r.strength = $strength,
                    r.relevance = $relevance,
                    r.edge_weight = $edge_weight,
                    r.relationship_id = $relationship_id,
                    r.ingested_at = $ingestion_time,
                    r.last_updated = $ingestion_time,
                    r.mention_count = 1,
                    r.is_active = true,
                    r.note_id = $note_id
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "rel_type": relationship_type,
                    "confidence": confidence,
                    "strength": strength,
                    "relevance": relevance,
                    "edge_weight": edge_weight,
                    "relationship_id": relationship_id,
                    "ingestion_time": ingestion_time,
                    "note_id": note_id,
                },
            )

        if is_bidirectional(relationship_type):
            self._create_inverse_relationship(
                source_id=target_id,
                target_id=source_id,
                relationship_type=relationship_type,
                confidence=confidence,
                note_id=note_id,
                ingestion_time=ingestion_time,
            )

        logger.info(
            f"[Graph] Relationship {action}: "
            f"({source_name})-[{relationship_type}]->({target_name})"
        )

        return {
            "action": action,
            "source": source_name,
            "target": target_name,
            "relationship_type": relationship_type,
            "confidence": confidence,
            "strength": strength,
            "relevance": relevance,
            "edge_weight": edge_weight,
            "natural_language": natural_language,
            "relationship_id": relationship_id,
            "previous_type": previous_type,
        }

    def _create_inverse_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        confidence: float,
        note_id: str,
        ingestion_time: str,
    ) -> None:
        self.execute_query(
            "MERGE (n:Node {id: $id}) ON CREATE SET n.kind = 'indexable'",
            {"id": source_id},
        )
        self.execute_query(
            "MERGE (n:Node {id: $id}) ON CREATE SET n.kind = 'indexable'",
            {"id": target_id},
        )
        existing = self.execute_query(
            """
            MATCH (s:Node {id: $source_id})-[r:SEMANTIC_REL]->(t:Node {id: $target_id})
            WHERE r.rel_type = $rel_type
            RETURN r.mention_count AS mc LIMIT 1
            """,
            {
                "source_id": source_id,
                "target_id": target_id,
                "rel_type": relationship_type,
            },
        )
        if existing:
            self.execute_query(
                """
                MATCH (s:Node {id: $source_id})-[r:SEMANTIC_REL]->(t:Node {id: $target_id})
                WHERE r.rel_type = $rel_type
                SET r.last_updated = $ingestion_time,
                    r.mention_count = coalesce(r.mention_count, 0) + 1,
                    r.is_active = true,
                    r.note_id = $note_id
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "rel_type": relationship_type,
                    "ingestion_time": ingestion_time,
                    "note_id": note_id,
                },
            )
        else:
            self.execute_query(
                """
                MATCH (source:Node {id: $source_id})
                MATCH (target:Node {id: $target_id})
                CREATE (source)-[r:SEMANTIC_REL]->(target)
                SET r.rel_type = $rel_type,
                    r.confidence = $confidence,
                    r.ingested_at = $ingestion_time,
                    r.last_updated = $ingestion_time,
                    r.mention_count = 1,
                    r.is_active = true,
                    r.note_id = $note_id
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "rel_type": relationship_type,
                    "confidence": confidence,
                    "ingestion_time": ingestion_time,
                    "note_id": note_id,
                },
            )

    def create_similarity_relationship(
        self,
        name1: str,
        name2: str,
        confidence: float = 0.9,
        note_id: str = None,
        rel_type: str = "IS_SIMILAR",
        node_label: str = "Indexable",
    ) -> dict:
        import re as _re
        from datetime import datetime

        name1_lower = name1.lower().strip()
        name2_lower = name2.lower().strip()
        created_at = datetime.utcnow().isoformat()
        rel_type = _re.sub(r"[^A-Za-z0-9_]", "_", rel_type.strip()) or "ALIAS_OF"

        result = self.execute_query(
            """
            MATCH (e1:Node)-[r:SEMANTIC_REL]-(e2:Node)
            WHERE e1.name = $name1 AND e2.name = $name2 AND r.is_similarity = true
            RETURN count(r) > 0 AS exists
            """,
            {"name1": name1_lower, "name2": name2_lower},
        )
        if result and result[0].get("exists"):
            return {"action": "exists", "name1": name1_lower, "name2": name2_lower}

        id1 = self.resolve_node_id(name1_lower)
        id2 = self.resolve_node_id(name2_lower)
        if not id1 or not id2:
            return {"action": "failed", "name1": name1_lower, "name2": name2_lower}

        for src, tgt in [(id1, id2), (id2, id1)]:
            self.execute_query(
                """
                MATCH (source:Node {id: $source_id})
                MATCH (target:Node {id: $target_id})
                CREATE (source)-[r:SEMANTIC_REL]->(target)
                SET r.rel_type = $rel_type,
                    r.confidence = $confidence,
                    r.created_at = $created_at,
                    r.note_id = $note_id,
                    r.is_active = true,
                    r.is_similarity = true
                """,
                {
                    "source_id": src,
                    "target_id": tgt,
                    "rel_type": rel_type,
                    "confidence": confidence,
                    "created_at": created_at,
                    "note_id": note_id,
                },
            )

        logger.info(
            f"[Similarity] Created {rel_type}: {name1_lower} <-> {name2_lower} "
            f"(confidence={confidence:.2f})"
        )
        return {"action": "created", "name1": name1_lower, "name2": name2_lower}

    def get_related_nodes(
        self,
        node_name: str,
        node_label: str = None,
        max_depth: int = 2,
        relationship_types: list[str] = None,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        node_id = self.resolve_node_id(node_name.lower().strip())
        if not node_id:
            return []

        # Fast path for the common retrieval case (1-hop expansion).
        # This avoids variable-length path/list comprehension constructs that can
        # trigger parser assertions in some Kuzu builds.
        if max_depth == 1:
            # Run two directed queries so we can track edge direction correctly.
            # An undirected match loses directionality, causing the expansion prompt
            # to display incoming edges backwards (e.g. "corliss archer plays shirley
            # temple" instead of "shirley temple plays corliss archer").
            outgoing_query = """
            MATCH (start:Node {id: $node_id})-[r:SEMANTIC_REL|REFERENCES]->(related:Node)
            WHERE (r.is_active = true OR r.is_active IS NULL)
              AND coalesce(r.confidence, 1.0) >= $min_confidence
            RETURN DISTINCT
                related.id AS node_id,
                related.name AS name,
                related.kind AS label,
                1 AS depth,
                [CASE WHEN label(r) = 'SEMANTIC_REL' THEN r.rel_type ELSE label(r) END] AS relationship_path,
                [coalesce(r.confidence, 1.0)] AS confidence_path,
                [NULL] AS context_path,
                [NULL] AS natural_language_path
            ORDER BY name
            """
            incoming_query = """
            MATCH (start:Node {id: $node_id})<-[r:SEMANTIC_REL|REFERENCES]-(related:Node)
            WHERE (r.is_active = true OR r.is_active IS NULL)
              AND coalesce(r.confidence, 1.0) >= $min_confidence
            RETURN DISTINCT
                related.id AS node_id,
                related.name AS name,
                related.kind AS label,
                1 AS depth,
                [CASE WHEN label(r) = 'SEMANTIC_REL' THEN r.rel_type ELSE label(r) END] AS relationship_path,
                [coalesce(r.confidence, 1.0)] AS confidence_path,
                [NULL] AS context_path,
                [NULL] AS natural_language_path
            ORDER BY name
            """
            params = {"node_id": node_id, "min_confidence": min_confidence}
            outgoing = self.execute_query(outgoing_query, params)
            for row in outgoing:
                row["edge_direction"] = "outgoing"
            incoming = self.execute_query(incoming_query, params)
            # Deduplicate: if a neighbor appears in both directions, keep outgoing.
            seen_ids: set[str] = {r["node_id"] for r in outgoing if r.get("node_id")}
            for row in incoming:
                row["edge_direction"] = "incoming"
                if row.get("node_id") not in seen_ids:
                    outgoing.append(row)
                    seen_ids.add(row["node_id"])
            return sorted(outgoing, key=lambda r: r.get("name") or "")

        # NOTE: Do NOT add `all(rel IN relationships(path) WHERE ...)` inside a
        # variable-length MATCH — it triggers a KU_UNREACHABLE parser assertion in
        # this Kuzu build.  Confidence and is_active filtering is done in Python
        # below after the query returns.
        query = f"""
        MATCH path = (start:Node {{id: $node_id}})-[:SEMANTIC_REL|REFERENCES*1..{max_depth}]-(related:Node)
        WITH related, relationships(path) AS rels, length(path) AS depth
        RETURN DISTINCT
            related.id AS node_id,
            related.name AS name,
            related.kind AS label,
            depth,
            [rel IN rels |
                CASE WHEN label(rel) = 'SEMANTIC_REL' THEN rel.rel_type
                     ELSE label(rel) END
            ] AS relationship_path,
            [rel IN rels | coalesce(rel.confidence, 0.0)] AS confidence_path,
            [rel IN rels | coalesce(rel.is_active, true)] AS is_active_path,
            [rel IN rels | NULL] AS context_path,
            [rel IN rels | NULL] AS natural_language_path
        ORDER BY depth
        LIMIT 200
        """
        rows = self.execute_query(query, {"node_id": node_id})
        # Post-filter: keep only paths where every hop meets confidence and is_active.
        return [
            r
            for r in rows
            if all(c >= min_confidence for c in (r.get("confidence_path") or []))
            and all(a for a in (r.get("is_active_path") or [True]))
        ]

    def get_relationships_between_nodes(self, names: list[str]) -> list[dict]:
        if not names or len(names) < 2:
            return []
        ids = [
            nid
            for n in names
            if (nid := qdrant_service.find_node_id_by_name(n.lower().strip()))
        ]
        if len(ids) < 2:
            return []
        query = """
        MATCH (a:Node)-[r:SEMANTIC_REL]->(b:Node)
        WHERE a.id IN $ids AND b.id IN $ids
          AND (r.is_active = true OR r.is_active IS NULL)
        RETURN a.id AS source, r.rel_type AS rel_type, b.id AS target,
               r.edge_weight AS weight
        ORDER BY r.confidence DESC
        """
        return self.execute_query(query, {"ids": ids}) or []

    # ---- Communities --------------------------------------------------------

    def search_communities(
        self, vector: list[float], top_k: int = 5, min_score: float = 0.55
    ) -> list[dict]:
        """Find semantically relevant communities via Qdrant (no graph query needed)."""
        hits = qdrant_service.search_node_cores(
            query_vector=vector,
            limit=top_k,
            min_score=min_score,
            node_type="community",
        )
        results = []
        for hit in hits:
            payload = hit.get("payload", {})
            results.append(
                {
                    "name": payload.get("name"),
                    "domain": "Semantic",
                    "summary": _strip_facts_prefix(payload.get("description", "")),
                    "themes": payload.get("themes", []),
                    "last_updated": payload.get("updated_at"),
                    "member_count": payload.get("member_count", 0),
                    "community_id": payload.get("node_id"),
                    "community_level": payload.get("community_level"),
                    "score": hit.get("score", 0.0),
                }
            )
        return results

    def get_community_linked_notes(
        self, community_names: list[str], limit_per_community: int = 3
    ) -> list[dict]:
        if not community_names:
            return []
        query = """
        UNWIND $community_names AS comm_name
        MATCH (c:Node) WHERE c.kind = 'community' AND c.name = comm_name
        MATCH (c)-[:CONTAINS]->(member:Node)
        WHERE member.kind IN ['indexable', 'note']
        MATCH (note:Node)-[r:REFERENCES]->(member)
        WHERE note.kind = 'note' AND r.is_active = true
        WITH comm_name, note.id AS note_id, note.name AS note_name
        WITH comm_name, collect(DISTINCT {id: note_id, title: note_name}) AS all_notes
        RETURN comm_name AS community_name, all_notes AS notes
        """
        rows = self.execute_query(query, {"community_names": community_names})
        for row in rows:
            row["notes"] = (row.get("notes") or [])[:limit_per_community]
        return rows

    # ---- 3D spatial layout --------------------------------------------------

    def get_all_node_ids_and_edges(
        self,
    ) -> tuple[list[str], list[tuple[str, str]]]:
        node_rows = self.execute_query(
            """
            MATCH (n:Node)
            WHERE n.kind IN ['indexable', 'note', 'community']
              AND n.id IS NOT NULL
            RETURN n.id AS node_id
            """,
            {},
        )
        node_ids = [r["node_id"] for r in node_rows if r.get("node_id")]

        edge_rows = self.execute_query(
            """
            MATCH (a:Node)-[r:SEMANTIC_REL]->(b:Node)
            WHERE (r.is_active = true OR r.is_active IS NULL)
              AND a.id IS NOT NULL AND b.id IS NOT NULL
            RETURN DISTINCT a.id AS src, b.id AS tgt
            UNION
            MATCH (n:Node)-[:MEMBER_OF]->(c:Node)
            WHERE n.id IS NOT NULL AND c.id IS NOT NULL
            RETURN DISTINCT n.id AS src, c.id AS tgt
            LIMIT 5000
            """,
            {},
        )
        edges = [
            (r["src"], r["tgt"]) for r in edge_rows if r.get("src") and r.get("tgt")
        ]
        return node_ids, edges

    def get_full_3d_graph(self) -> dict:
        indexable_rows = self.execute_query(
            """
            MATCH (n:Node)
            WHERE n.kind IN ['indexable', 'note']
              AND n.id IS NOT NULL AND n.name IS NOT NULL
            RETURN n.id AS node_id, n.name AS name, n.type AS node_type
            """,
            {},
        )
        community_rows = self.execute_query(
            """
            MATCH (c:Node)
            WHERE c.kind = 'community'
              AND c.id IS NOT NULL AND c.name IS NOT NULL
            RETURN c.id AS node_id, c.name AS name, NULL AS community_level
            """,
            {},
        )
        membership_rows = self.execute_query(
            """
            MATCH (n:Node)-[r:MEMBER_OF]->(c:Node)
            WHERE n.id IS NOT NULL AND c.id IS NOT NULL
            RETURN n.id AS node_id, c.id AS community_id, r.level AS level
            ORDER BY r.level DESC
            """,
            {},
        )

        node_community_map: dict[str, str] = {}
        node_level_map: dict[str, dict[int, str]] = {}
        community_level_map: dict[str, int] = {}
        for row in membership_rows:
            nid = row.get("node_id")
            cid = row.get("community_id")
            lvl = row.get("level")
            if nid and cid:
                if nid not in node_community_map:
                    node_community_map[nid] = cid
                if lvl is not None:
                    lvl_int = int(lvl)
                    node_level_map.setdefault(nid, {})[lvl_int] = cid
                    # Derive community level from the membership edge level —
                    # community_level is not stored on the community node itself.
                    community_level_map[cid] = lvl_int

        from app.utils.graph_layout import compute_solar_positions

        all_node_ids = [r["node_id"] for r in indexable_rows if r.get("node_id")]
        communities_meta = [
            {
                "community_id": r["node_id"],
                "community_level": community_level_map.get(r["node_id"], 0),
                "name": r.get("name", ""),
            }
            for r in community_rows
            if r.get("node_id")
        ]
        positions = compute_solar_positions(
            communities=communities_meta,
            node_level_map=node_level_map,
            all_node_ids=all_node_ids,
        )

        nodes = []
        for row in indexable_rows:
            nid = row.get("node_id")
            name = (row.get("name") or "").strip()
            if not nid or not name:
                continue
            x, y, z = positions.get(nid, (0.0, 0.0, 0.0))
            nodes.append(
                {
                    "node_id": nid,
                    "name": name,
                    "node_type": row.get("node_type") or "unknown",
                    "description": "",
                    "community_id": node_community_map.get(nid),
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                }
            )
        for row in community_rows:
            nid = row.get("node_id")
            name = (row.get("name") or "").strip()
            if not nid or not name:
                continue
            x, y, z = positions.get(nid, (0.0, 0.0, 0.0))
            nodes.append(
                {
                    "node_id": nid,
                    "name": name,
                    "node_type": "community",
                    "description": "",
                    "community_id": None,
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                }
            )

        edge_rows = self.execute_query(
            """
            MATCH (a:Node)-[r:SEMANTIC_REL]->(b:Node)
            WHERE (r.is_active = true OR r.is_active IS NULL)
              AND a.id IS NOT NULL AND b.id IS NOT NULL
              AND a.kind IN ['indexable', 'note']
              AND b.kind IN ['indexable', 'note']
            RETURN DISTINCT a.id AS source, b.id AS target, r.rel_type AS rel_type
            LIMIT 4000
            """,
            {},
        )
        # Build MEMBER_OF edges from membership_rows (already fetched without a
        # limit for the layout calculation) so no edges are dropped by a cap.
        seen_member = set()
        member_edge_rows = []
        for row in membership_rows:
            nid = row.get("node_id")
            cid = row.get("community_id")
            if nid and cid:
                key = (nid, cid)
                if key not in seen_member:
                    seen_member.add(key)
                    member_edge_rows.append(
                        {"source": nid, "target": cid, "rel_type": "MEMBER_OF"}
                    )
        edges = [
            {
                "source": r["source"],
                "target": r["target"],
                "type": r.get("rel_type", ""),
            }
            for r in (list(edge_rows) + member_edge_rows)
            if r.get("source") and r.get("target")
        ]
        return {"nodes": nodes, "edges": edges}

    def store_node_positions(
        self, positions: dict[str, tuple[float, float, float]]
    ) -> None:
        if not positions:
            return
        for nid, xyz in positions.items():
            try:
                self.execute_query(
                    """
                    MATCH (n:Node {id: $node_id})
                    SET n.pos_x = $x, n.pos_y = $y, n.pos_z = $z
                    """,
                    {
                        "node_id": nid,
                        "x": float(xyz[0]),
                        "y": float(xyz[1]),
                        "z": float(xyz[2]),
                    },
                )
            except Exception as exc:
                logger.debug(f"[Graph] store_node_positions skipped {nid}: {exc}")

    def get_3d_overview(self) -> dict:
        from app.utils.graph_layout import compute_positions

        rows = self.execute_query(
            """
            MATCH (c:Node)
            WHERE c.kind = 'community' AND c.id IS NOT NULL
            RETURN c.id AS community_id, NULL AS community_level
            """,
            {},
        )
        membership_rows = self.execute_query(
            """
            MATCH (n:Node)-[r:MEMBER_OF]->(c:Node)
            WHERE n.id IS NOT NULL AND c.id IS NOT NULL
            RETURN n.id AS node_id, c.id AS community_id, r.level AS level
            ORDER BY r.level DESC
            """,
            {},
        )

        community_members: dict[str, list[str]] = {}
        for mr in membership_rows:
            nid = mr.get("node_id")
            cid = mr.get("community_id")
            if nid and cid and (mr.get("level") or 0) == 2:
                community_members.setdefault(cid, []).append(nid)

        community_ids = [r["community_id"] for r in rows if r.get("community_id")]
        content_map = (
            qdrant_service.get_nodes_content_by_ids(community_ids)
            if community_ids
            else {}
        )

        communities_meta = [
            {
                "community_id": r["community_id"],
                "community_level": r.get("community_level") or 2,
                "name": content_map.get(r["community_id"], {}).get("name", ""),
            }
            for r in rows
            if r.get("community_id")
        ]
        positions = compute_positions(
            communities=communities_meta,
            memberships=community_members,
        )

        communities = []
        for r in rows:
            cid = r.get("community_id")
            c = content_map.get(cid, {})
            x, y, z = positions.get(cid, (0.0, 0.0, 0.0))
            communities.append(
                {
                    "community_id": cid,
                    "name": c.get("name") or "Unnamed Cluster",
                    "summary": _strip_facts_prefix(c.get("description") or ""),
                    "community_level": c.get("community_level") or 2,
                    "member_count": c.get("member_count") or 0,
                    "themes": c.get("themes") or [],
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                }
            )

        orphan_rows = self.execute_query(
            """
            MATCH (n:Node)
            WHERE n.kind IN ['indexable', 'note']
              AND n.id IS NOT NULL AND n.name IS NOT NULL
              AND NOT EXISTS { MATCH (n)-[:MEMBER_OF]->(:Node) }
            RETURN n.id AS node_id, n.name AS name, n.type AS node_type
            """,
            {},
        )
        orphan_ids = [r["node_id"] for r in orphan_rows if r.get("node_id")]
        orphan_content = (
            qdrant_service.get_nodes_content_by_ids(orphan_ids) if orphan_ids else {}
        )

        from app.utils.graph_layout import (
            ORPHAN_RADIUS,
            _deterministic_jitter,
            _fibonacci_sphere,
        )

        orphan_pts = _fibonacci_sphere(len(orphan_ids), ORPHAN_RADIUS)
        orphan_nodes = []
        for idx, row in enumerate(orphan_rows):
            nid = row.get("node_id")
            if not nid:
                continue
            c = orphan_content.get(nid, {})
            ox, oy, oz = orphan_pts[idx] if idx < len(orphan_pts) else (0.0, 0.0, 0.0)
            jx, jy, jz = _deterministic_jitter(nid, 3.0)
            orphan_nodes.append(
                {
                    "node_id": nid,
                    "name": c.get("name") or row.get("name") or "Unnamed",
                    "node_type": c.get("type") or row.get("node_type") or "unknown",
                    "description": _strip_facts_prefix(c.get("description", "")),
                    "facts": c.get("facts", []),
                    "x": float(ox + jx),
                    "y": float(oy + jy),
                    "z": float(oz + jz),
                }
            )

        orphan_edge_rows = self.execute_query(
            """
            MATCH (a:Node)-[r:SEMANTIC_REL]->(b:Node)
            WHERE a.kind IN ['indexable', 'note']
              AND b.kind IN ['indexable', 'note']
              AND NOT EXISTS { MATCH (:Node)-[:CONTAINS]->(a) }
              AND NOT EXISTS { MATCH (:Node)-[:CONTAINS]->(b) }
              AND (r.is_active = true OR r.is_active IS NULL)
              AND a.id IS NOT NULL AND b.id IS NOT NULL
            RETURN DISTINCT a.id AS source, b.id AS target, r.rel_type AS rel_type
            LIMIT 1000
            """,
            {},
        )
        orphan_edges = [
            {
                "source": r["source"],
                "target": r["target"],
                "type": r.get("rel_type", ""),
            }
            for r in orphan_edge_rows
            if r.get("source") and r.get("target")
        ]

        return {
            "communities": communities,
            "orphan_nodes": orphan_nodes,
            "orphan_edges": orphan_edges,
        }

    def get_community_members(self, community_id: str) -> dict:
        node_rows = self.execute_query(
            """
            MATCH (c:Node {id: $cid})-[:CONTAINS]->(n:Node)
            WHERE n.id IS NOT NULL
            RETURN n.id AS node_id
            """,
            {"cid": community_id},
        )
        edge_rows = self.execute_query(
            """
            MATCH (c:Node {id: $cid})-[:CONTAINS]->(a:Node)
            MATCH (c)-[:CONTAINS]->(b:Node)
            MATCH (a)-[r:SEMANTIC_REL]->(b)
            WHERE a.id IS NOT NULL AND b.id IS NOT NULL
              AND (r.is_active = true OR r.is_active IS NULL)
            RETURN DISTINCT
                a.id AS source,
                b.id AS target,
                r.rel_type AS rel_type,
                r.edge_weight AS edge_weight
            LIMIT 500
            """,
            {"cid": community_id},
        )

        import math as _math

        from app.utils.graph_layout import (
            CLUSTER_RADIUS_BASE,
            _deterministic_jitter,
            _fibonacci_sphere,
        )

        node_ids = [row["node_id"] for row in node_rows if row.get("node_id")]
        content_map = (
            qdrant_service.get_nodes_content_by_ids(node_ids) if node_ids else {}
        )

        cluster_radius = CLUSTER_RADIUS_BASE * _math.sqrt(max(len(node_ids), 1))
        cluster_radius = min(cluster_radius, CLUSTER_RADIUS_BASE * 8)
        pts = _fibonacci_sphere(len(node_ids), cluster_radius)

        nodes = []
        for idx, row in enumerate(node_rows):
            nid = row.get("node_id")
            if not nid:
                continue
            c = content_map.get(nid, {})
            px, py, pz = pts[idx] if idx < len(pts) else (0.0, 0.0, 0.0)
            jx, jy, jz = _deterministic_jitter(nid, 3.0)
            nodes.append(
                {
                    "node_id": nid,
                    "name": c.get("name") or "Unnamed",
                    "node_type": c.get("type") or "unknown",
                    "description": _strip_facts_prefix(c.get("description", "")),
                    "facts": c.get("facts", []),
                    "community_id": c.get("community_id"),
                    "x": float(px + jx),
                    "y": float(py + jy),
                    "z": float(pz + jz),
                }
            )
        edges = [
            {
                "source": row["source"],
                "target": row["target"],
                "type": row.get("rel_type", ""),
                "edge_weight": row.get("edge_weight"),
            }
            for row in edge_rows
            if row.get("source") and row.get("target")
        ]
        return {"nodes": nodes, "edges": edges}

    def get_node_detail(self, node_id: str) -> dict | None:
        rows = self.execute_query(
            """
            MATCH (n:Node {id: $nid})
            WHERE n.kind IN ['indexable', 'note']
            OPTIONAL MATCH (n)-[:MEMBER_OF]->(c:Node)
            RETURN n.id AS node_id, n.name AS name, n.type AS node_type,
                   c.id AS community_id, n.kind AS kind
            LIMIT 1
            """,
            {"nid": node_id},
        )
        if not rows:
            rows = self.execute_query(
                """
                MATCH (c:Node {id: $nid})
                WHERE c.kind = 'community'
                RETURN c.id AS node_id, c.name AS name,
                       'community' AS node_type, NULL AS community_id,
                       'community' AS kind
                LIMIT 1
                """,
                {"nid": node_id},
            )
        if not rows:
            return None

        row = rows[0]
        nid = row.get("node_id")
        if not nid:
            return None

        content_map = qdrant_service.get_nodes_content_by_ids([nid])
        c = content_map.get(nid, {})

        return {
            "node_id": nid,
            "name": c.get("name") or row.get("name") or "",
            "node_type": row.get("node_type") or "unknown",
            "description": _strip_facts_prefix(c.get("description") or ""),
            "isolated_contexts": c.get("isolated_contexts") or [],
            "facts": c.get("facts") or [],
            "domain": c.get("domain"),
            "status": c.get("status"),
            "community_id": row.get("community_id"),
            "summary": _strip_facts_prefix(c.get("description") or ""),
            "themes": c.get("themes") or [],
            "member_count": c.get("member_count") or 0,
        }


graph_service = GraphService()
