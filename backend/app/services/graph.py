import re
from neo4j import GraphDatabase
from app.core.config import settings
from app.core.log import get_logger
from app.services.qdrant_service import qdrant_service

logger = get_logger("GraphService")


def _strip_facts_prefix(text: str) -> str:
    """Strip the legacy 'FACTS: k=v | k=v. Prose...' prefix from stored descriptions.

    The old ingestion prompt instructed the LLM to prepend a structured FACTS
    line before the prose summary. We now store facts separately, so we strip
    that prefix when serving descriptions to callers.
    """
    if not text or not text.startswith("FACTS:"):
        return text
    m = re.search(r"^FACTS:.*?[.]\s+(.*)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


class GraphService:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )

    def close(self):
        self.driver.close()

    def resolve_node_id(self, name: str) -> str | None:
        """Resolve a node name to its stable node_id via Qdrant node_cores."""
        return qdrant_service.find_node_id_by_name(name)

    def verify_connection(self) -> bool:
        try:
            self.driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error(f"Neo4j Connection Failed: {e}")
            return False

    def execute_query(self, query: str, params: dict = None):
        if params is None:
            params = {}
        with self.driver.session() as session:
            try:
                result = session.run(query, params)
                data = [record.data() for record in result]

                # Log summary if writing (consume headers to check counters)
                summary = result.consume()
                if summary.counters.contains_updates:
                    logger.info(f"[Graph] Updates: {summary.counters}")

                return data
            except Exception as e:
                logger.error(f"[Graph] Query Failed: {e}")
                logger.error(f"  Query: {query}")
                logger.error(f"  Params: {params}")
                raise e

    def get_note_context(self, note_ids: list[str]) -> list[dict]:
        """
        Fetches linked knowledge nodes for a list of note IDs.
        Used for Hybrid Retrieval context enrichment.
        """
        query = """
        UNWIND $note_ids as note_id
        MATCH (n:Indexable {id: note_id, type: 'note'})
        OPTIONAL MATCH (n)-[r:REFERENCES]->(linked:Indexable)
        WHERE r.is_active = true AND linked.type <> 'note'
        RETURN n.id as note_id,
               collect(distinct {node_id: linked.id, name: linked.name, type: linked.type}) as linked_nodes
        """
        return self.execute_query(query, {"note_ids": note_ids})

    def find_nodes_by_name(self, names: list[str], fuzzy: bool = True) -> list[dict]:
        """
        Find graph nodes by name (case-insensitive).
        Used for looking up query entities in the knowledge graph.

        Args:
            names: List of entity names to search for
            fuzzy: If True, uses CONTAINS for partial matching; if False, exact match

        Returns:
            List of matching nodes with name, labels, summary, description, and entity_type
        """
        if not names:
            return []

        # Normalize names to lowercase for case-insensitive matching
        names_lower = [n.lower() for n in names]

        if fuzzy:
            # Partial matching with CONTAINS
            query = """
            MATCH (n:Indexable)
            WHERE any(name_param IN $names WHERE toLower(n.name) CONTAINS name_param)
            RETURN DISTINCT
                n.id as node_id,
                n.name as name,
                labels(n) as labels,
                n.status as status,
                n.type as entity_type,
                [name_param IN $names WHERE toLower(n.name) CONTAINS name_param][0] as matched_query
            LIMIT 50
            """
        else:
            # Exact matching
            query = """
            MATCH (n:Indexable)
            WHERE toLower(n.name) IN $names
            RETURN DISTINCT
                n.id as node_id,
                n.name as name,
                labels(n) as labels,
                n.status as status,
                n.type as entity_type,
                toLower(n.name) as matched_query
            LIMIT 50
            """

        return self.execute_query(query, {"names": names_lower})

    def find_name_variants(self, base_name: str, limit: int = 5) -> list[dict]:
        """
        Find name variants for an entity using pattern matching:
        1. Names that start with the base name (e.g., "Robert Smith" → "Robert Smith Jr.")
        2. Names that contain the base name

        Args:
            base_name: The base name to search variants for
            limit: Maximum variants to return

        Returns:
            List of nodes with variant names
        """
        base_lower = base_name.lower().strip()

        # Pattern-based name variant search
        query = """
        // Find pattern-based name variants
        // EXCLUDE Sr./Jr./Roman numeral mismatches - these are different people!
        MATCH (n:Indexable)
        WHERE (toLower(n.name) STARTS WITH $base_name + ' '
           OR (toLower(n.name) CONTAINS $base_name AND size(n.name) > size($base_name) + 2))
          // CRITICAL: Exclude generational suffixes that indicate different people
          AND NOT (
            // One has Sr. and the other has Jr.
            (toLower(n.name) CONTAINS ' sr' AND toLower($base_name) CONTAINS ' jr')
            OR (toLower(n.name) CONTAINS ' jr' AND toLower($base_name) CONTAINS ' sr')
            // One has generational suffix and the other doesn't
            OR (toLower(n.name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$' 
                AND NOT toLower($base_name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$')
            OR (toLower($base_name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$'
                AND NOT toLower(n.name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$')
          )
        RETURN DISTINCT n.id as node_id,
               n.name as name,
               labels(n) as labels,
               n.type as entity_type
        LIMIT $limit
        """

        return self.execute_query(query, {"base_name": base_lower, "limit": limit})

    def find_similar_entities(
        self,
        entity_name: str,
        entity_type: str = "Person",
        limit: int = 10,
        node_label: str = "Indexable",
    ) -> list[dict]:
        """
        Find existing entities that might be similar to the given entity.

        Checks for:
        1. Names that contain the new name (e.g., "Margaret Johnson-Williams" for "Margaret Johnson")
        2. Names that the new name contains (e.g., "Robert Smith" for "Robert Smith III")
        3. Names with same first/last name (for Person entities)

        EXCLUDES:
        - Sr./Jr. mismatches (these are always different people)
        - Roman numeral suffixes that differ (I, II, III, IV, V)

        Args:
            entity_name: Name of the new entity being ingested
            entity_type: Type of entity (Person, Place, Organization, etc.)
            limit: Maximum similar entities to return

        Returns:
            List of similar entity candidates with name, summary, and type
        """
        name_lower = entity_name.lower().strip()
        name_parts = name_lower.split()

        # Regex for generational/honorific suffixes that are never a meaningful last name.
        import re as _re

        _SUFFIX_RE = _re.compile(r"^(sr\.?|jr\.?|senior|junior|[ivxlc]{1,6})$", _re.I)

        # For Person entities with multi-word names, check for related names
        if entity_type.lower() == "person" and len(name_parts) >= 2:
            first_name = name_parts[0]
            last_name = name_parts[-1]
            # If the trailing token is a generational suffix, use the preceding word as last name
            if _SUFFIX_RE.match(last_name):
                last_name = name_parts[-2] if len(name_parts) > 2 else name_parts[0]

            query = """
            MATCH (e:Indexable)
            WHERE toLower(e.type) = 'person'
              AND toLower(e.name) <> $name
              AND size(split(trim(e.name), ' ')) >= 2
              AND (
                // New name contains existing name (shorter → longer)
                toLower($name) STARTS WITH toLower(e.name) + ' '
                // Existing name contains new name (longer → shorter) 
                OR toLower(e.name) STARTS WITH toLower($name) + ' '
                // Same first AND last name (different middle parts)
                OR (toLower(e.name) STARTS WITH $first_name + ' '
                    AND toLower(e.name) ENDS WITH ' ' + $last_name)
              )
              // EXCLUDE Sr./Jr. mismatches - these are ALWAYS different people
              AND NOT (
                // One has Sr. and the other has Jr.
                (toLower(e.name) CONTAINS ' sr' AND toLower($name) CONTAINS ' jr')
                OR (toLower(e.name) CONTAINS ' jr' AND toLower($name) CONTAINS ' sr')
                // One has generational suffix and the other doesn't
                OR (toLower(e.name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$' 
                    AND NOT toLower($name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$')
                OR (toLower($name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$'
                    AND NOT toLower(e.name) =~ '.* (sr\\.?|jr\\.?|senior|junior|i|ii|iii|iv|v|vi)$')
              )
            RETURN 
                e.id as node_id,
                e.name as name,
                e.type as entity_type
            LIMIT $limit
            """
            return self.execute_query(
                query,
                {
                    "name": name_lower,
                    "first_name": first_name,
                    "last_name": last_name,
                    "limit": limit,
                },
            )
        else:
            # Generic similarity — optionally filter by type when entity_type is meaningful
            type_filter = (
                "AND toLower(e.type) = toLower($entity_type)"
                if entity_type and entity_type.lower() not in ("unknown", "")
                else ""
            )
            query = f"""
            MATCH (e:Indexable)
            WHERE toLower(e.name) <> $name
              {type_filter}
              AND (
                toLower($name) CONTAINS toLower(e.name)
                OR toLower(e.name) CONTAINS toLower($name)
              )
              AND size(split(trim(e.name), ' ')) >= 2
              AND size(split(trim($name), ' ')) >= 2
              AND abs(size(e.name) - size($name)) >= 2
              // Skip entirely if either name contains a 4-digit year
              AND NOT $name =~ '.*(^| )[0-9]{{4}}( |$).*'
              AND NOT toLower(e.name) =~ '.*(^| )[0-9]{{4}}( |$).*'
            RETURN
                e.id as node_id,
                e.name as name,
                e.type as entity_type
            LIMIT $limit
            """
            return self.execute_query(
                query, {"name": name_lower, "entity_type": entity_type, "limit": limit}
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
        """
        Create a bidirectional similarity relationship between two entities.

        rel_type controls the Neo4j relationship type stored, e.g.:
            IS_SHORTENED_TITLE, IS_CANONICAL_NAME_VARIANT, IS_FORMER_TITLE,
            IS_ALTERNATIVE_TITLE, IS_BROADER_CATEGORICAL_VARIANT, etc.

        A pair can only have ONE outbound similarity relationship in each direction,
        regardless of rel_type, so this is safe to call idempotently.
        """
        import re as _re
        from datetime import datetime

        name1_lower = name1.lower().strip()
        name2_lower = name2.lower().strip()
        created_at = datetime.utcnow().isoformat()

        # Sanitise relationship type (must be valid Neo4j identifier)
        rel_type = _re.sub(r"[^A-Za-z0-9_]", "_", rel_type.strip()) or "ALIAS_OF"

        # Check if any similarity relationship already exists (in either direction)
        check_query = f"""
        MATCH (e1:Indexable {{name: $name1}})-[r]-(e2:Indexable {{name: $name2}})
        WHERE r.is_similarity = true
        RETURN count(r) > 0 as exists
        """
        result = self.execute_query(
            check_query, {"name1": name1_lower, "name2": name2_lower}
        )

        if result and result[0].get("exists"):
            return {"action": "exists", "name1": name1_lower, "name2": name2_lower}

        # Create bidirectional typed similarity relationship
        create_query = f"""
        MATCH (e1:Indexable {{name: $name1}})
        MATCH (e2:Indexable {{name: $name2}})
        MERGE (e1)-[r1:{rel_type}]->(e2)
        SET r1.confidence = $confidence,
            r1.created_at = $created_at,
            r1.note_id = $note_id,
            r1.is_active = true,
            r1.is_similarity = true
        MERGE (e2)-[r2:{rel_type}]->(e1)
        SET r2.confidence = $confidence,
            r2.created_at = $created_at,
            r2.note_id = $note_id,
            r2.is_active = true,
            r2.is_similarity = true
        RETURN e1.name as name1, e2.name as name2
        """
        result = self.execute_query(
            create_query,
            {
                "name1": name1_lower,
                "name2": name2_lower,
                "confidence": confidence,
                "created_at": created_at,
                "note_id": note_id,
            },
        )

        if result:
            logger.info(
                f"[Similarity] Created {rel_type}: {name1_lower} <-> {name2_lower} "
                f"(confidence={confidence:.2f})"
            )
            return {"action": "created", "name1": name1_lower, "name2": name2_lower}

        return {"action": "failed", "name1": name1_lower, "name2": name2_lower}

    def merge_nodes(self, canonical_name: str, dup_name: str) -> dict:
        """
        Merge dup_name into canonical_name.
        Resolves node IDs via Qdrant; all Neo4j operations use IDs.
        """
        canonical = canonical_name.lower().strip()
        dup = dup_name.lower().strip()
        if canonical == dup:
            return {"action": "skip", "reason": "same name"}

        # Resolve IDs from Qdrant (source of truth for node identities)
        dup_node_id = qdrant_service.find_node_id_by_name(dup)
        canonical_node_id = qdrant_service.find_node_id_by_name(canonical)

        if not dup_node_id or not canonical_node_id:
            logger.warning(
                f"[Merge] Cannot merge '{dup}' → '{canonical}': "
                f"dup_id={dup_node_id}, canonical_id={canonical_node_id}"
            )
            return {"action": "skip", "reason": "unresolvable IDs"}

        # Transfer isolated_contexts from dup to canonical in Qdrant
        if dup_node_id and canonical_node_id:
            try:
                from app.services.embedding import embedding_service as _emb
                dup_content = qdrant_service.get_node_content_by_id(dup_node_id)
                dup_contexts = (dup_content or {}).get("isolated_contexts", [])
                if dup_contexts:
                    canonical_content = qdrant_service.get_node_content_by_id(canonical_node_id)
                    existing_ctxs = (canonical_content or {}).get("isolated_contexts", [])
                    all_ctxs = existing_ctxs + dup_contexts
                    merged_items = []
                    for ctx in all_ctxs:
                        if ctx and ctx.strip():
                            vec = _emb.embed_documents([ctx])[0]
                            merged_items.append({"content": ctx, "vector": vec})
                    canonical_name = (canonical_content or {}).get("name", canonical)
                    canonical_type = (canonical_content or {}).get("type", "")
                    for item in merged_items:
                        item["name"] = canonical_name
                        item["type"] = canonical_type
                    qdrant_service.upsert_node_items(
                        collection_name=settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,
                        node_id=canonical_node_id,
                        items=merged_items,
                    )
            except Exception as _e:
                logger.warning(f"[Merge] Failed to transfer isolated_contexts in Qdrant: {_e}")

        # Transfer REFERENCES from notes
        self.execute_query(
            """
            MATCH (source)-[r:REFERENCES]->(dup:Indexable {id: $dup_id})
            MATCH (canonical:Indexable {id: $canonical_id})
            WHERE NOT (source)-[:REFERENCES]->(canonical)
            MERGE (source)-[new_r:REFERENCES]->(canonical)
            SET new_r.note_id = r.note_id,
                new_r.is_active = true
            """,
            {"canonical_id": canonical_node_id, "dup_id": dup_node_id},
        )

        # Collect outgoing semantic relationships from dup
        out_rels = self.execute_query(
            """
            MATCH (dup:Indexable {id: $dup_id})-[r]->(other:Indexable)
            WHERE type(r) <> 'REFERENCES' AND other.id <> $canonical_id
            RETURN type(r) AS rel_type, other.id AS target_id,
                   r.confidence AS confidence, r.strength AS strength,
                   r.relevance AS relevance
            """,
            {"dup_id": dup_node_id, "canonical_id": canonical_node_id},
        )

        # Collect incoming semantic relationships to dup
        in_rels = self.execute_query(
            """
            MATCH (source:Indexable)-[r]->(dup:Indexable {id: $dup_id})
            WHERE type(r) <> 'REFERENCES' AND source.id <> $canonical_id
            RETURN type(r) AS rel_type, source.id AS source_id,
                   r.confidence AS confidence, r.strength AS strength,
                   r.relevance AS relevance
            """,
            {"dup_id": dup_node_id, "canonical_id": canonical_node_id},
        )

        # Delete dup relationships and dup node
        self.execute_query("MATCH (dup:Indexable {id: $id})-[r]-() DELETE r", {"id": dup_node_id})
        self.execute_query("MATCH (dup:Indexable {id: $id}) DELETE dup", {"id": dup_node_id})

        # Recreate transferred relationships from/to canonical
        for rel in out_rels:
            tgt_id = rel.get("target_id")
            if not tgt_id:
                continue
            try:
                self.create_or_update_relationship(
                    source_name=canonical, source_label="Indexable",
                    target_name="", target_label="Indexable",
                    relationship_type=rel["rel_type"],
                    confidence=rel.get("confidence") or 7.0,
                    strength=rel.get("strength") or 5.0,
                    relevance=rel.get("relevance") or 5.0,
                    source_id=canonical_node_id,
                    target_id=tgt_id,
                )
            except Exception as e:
                logger.warning(f"[Merge] Failed to transfer outgoing rel: {e}")

        for rel in in_rels:
            src_id = rel.get("source_id")
            if not src_id:
                continue
            try:
                self.create_or_update_relationship(
                    source_name="", source_label="Indexable",
                    target_name=canonical, target_label="Indexable",
                    relationship_type=rel["rel_type"],
                    confidence=rel.get("confidence") or 7.0,
                    strength=rel.get("strength") or 5.0,
                    relevance=rel.get("relevance") or 5.0,
                    source_id=src_id,
                    target_id=canonical_node_id,
                )
            except Exception as e:
                logger.warning(f"[Merge] Failed to transfer incoming rel: {e}")

        # Remove dup from Qdrant now that its data has been transferred
        if dup_node_id:
            try:
                qdrant_service.delete_node(dup_node_id)
            except Exception as _e:
                logger.warning(f"[Merge] Failed to delete dup Qdrant node {dup_node_id}: {_e}")

        logger.info(f"[Merge] Merged '{dup}' → '{canonical}' (dup_id={dup_node_id})")
        return {"action": "merged", "canonical": canonical, "dup": dup, "dup_node_id": dup_node_id}

    def get_similar_entities(
        self, entity_name: str, node_label: str = "Indexable"
    ) -> list[dict]:
        """
        Get all nodes similar to the given node via the `is_similarity = true` property.
        Resolves name to ID via Qdrant before querying Neo4j.
        """
        name_lower = entity_name.lower().strip()
        node_id = self.resolve_node_id(name_lower)
        if not node_id:
            return []

        query = """
        MATCH (e:Indexable {id: $node_id})-[r]-(similar:Indexable)
        WHERE r.is_similarity = true
        RETURN DISTINCT
            similar.id as node_id,
            type(r) as rel_type
        """
        return self.execute_query(query, {"node_id": node_id})

    def find_paths_between_nodes(
        self,
        node_names: list[str],
        max_depth: int = 3,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """Find paths connecting multiple nodes in the graph.

        Resolves names to IDs via Qdrant; all Neo4j traversal uses IDs.
        """
        if len(node_names) < 2:
            return []

        node_ids = [
            nid for n in node_names
            if (nid := qdrant_service.find_node_id_by_name(n.lower().strip()))
        ]
        if len(node_ids) < 2:
            return []

        query = f"""
        UNWIND $node_ids as source_id
        UNWIND $node_ids as target_id
        WITH source_id, target_id
        WHERE source_id < target_id
        MATCH (source:Indexable {{id: source_id}}), (target:Indexable {{id: target_id}})
        MATCH path = shortestPath((source)-[*1..{max_depth}]-(target))
        WHERE all(rel in relationships(path) WHERE
            coalesce(rel.confidence, 0.8) >= $min_confidence
            AND (rel.is_active = true OR rel.is_active IS NULL)
        )
        WITH path, source_id, target_id, length(path) as pathLength
        RETURN DISTINCT
            source_id,
            target_id,
            [node in nodes(path) | node.id] as path_node_ids,
            [rel in relationships(path) | type(rel)] as relationship_types,
            pathLength as depth
        ORDER BY pathLength
        LIMIT 20
        """
        return self.execute_query(
            query, {"node_ids": node_ids, "min_confidence": min_confidence}
        )

    def get_recent_notes(self, limit: int = 10, domain: str = None) -> list[dict]:
        """
        Fetches the most recently ingested note node IDs from Neo4j.
        Content (title, domain, created_at) comes from Qdrant node_cores.
        """
        query = """
        MATCH (n:Note)
        RETURN n.id as id
        ORDER BY elementId(n) DESC
        LIMIT $limit
        """
        rows = self.execute_query(query, {"limit": limit})
        if not rows:
            return []
        # Enrich from Qdrant
        ids = [r["id"] for r in rows if r.get("id")]
        if not ids:
            return []
        content_map = qdrant_service.get_nodes_content_by_ids(ids)
        result = []
        for nid in ids:
            c = content_map.get(nid, {})
            if domain and c.get("domain") and c.get("domain") != domain:
                continue
            result.append({
                "id": nid,
                "title": c.get("name", ""),
                "summary": _strip_facts_prefix(c.get("description", "")),
                "domain": c.get("domain"),
                "created_at": c.get("created_at"),
            })
        return result

    def get_indexable_nodes_for_communities(self) -> list[dict]:
        """Return all knowledge nodes (non-note, non-community) with stable IDs.

        Only node_id is returned — content (name, type, description, facts) is
        enriched from Qdrant by the Leiden caller.
        """
        query = """
        MATCH (n:Indexable)
        WHERE NOT n:Note AND NOT n:Community AND n.id IS NOT NULL
        RETURN n.id AS node_id
        """
        return self.execute_query(query, {})

    def get_weighted_relationships_for_communities(self) -> list[dict]:
        """Return weighted edges between knowledge nodes for Leiden clustering."""
        query = """
        MATCH (a:Indexable)-[r]-(b:Indexable)
        WHERE NOT a:Note AND NOT b:Note
          AND NOT a:Community AND NOT b:Community
          AND a.id IS NOT NULL AND b.id IS NOT NULL
          AND elementId(a) < elementId(b)
          AND (r.is_active = true OR r.is_active IS NULL)
        RETURN DISTINCT
            a.id AS source_node_id,
            b.id AS target_node_id,
            coalesce(r.edge_weight, CASE WHEN r.confidence IS NOT NULL THEN r.confidence * 10 ELSE 1.0 END) AS weight
        """
        return self.execute_query(query, {})

    def clear_all_communities(self) -> list[str]:
        """Delete all existing community nodes, MEMBER_OF relationships, and community
        membership NL sentences from Qdrant.
        """
        existing = self.execute_query(
            "MATCH (c:Community) RETURN coalesce(c.community_id, c.id) AS community_id",
            {},
        )
        community_ids = [
            row["community_id"] for row in existing if row.get("community_id")
        ]
        # Drop MEMBER_OF relationships (community membership is graph-structural)
        self.execute_query("MATCH ()-[r:MEMBER_OF]->() DELETE r", {})
        self.execute_query("MATCH (c:Community) DETACH DELETE c", {})
        # Drop all community membership NL sentences from Qdrant
        qdrant_service.delete_community_relationships()
        return community_ids

    def set_node_community_membership(
        self, node_ids: list[str], community_id: str, community_level: int
    ) -> None:
        """Record community membership as a MEMBER_OF relationship in Neo4j.

        The community node is expected to already exist (created by create_leiden_community).
        Community-level metadata (name, summary, etc.) lives in Qdrant only.
        """
        if not node_ids:
            return
        query = """
        MATCH (c:Community {id: $community_id})
        UNWIND $node_ids AS node_id
        MATCH (n:Indexable {id: node_id})
        MERGE (n)-[r:MEMBER_OF]->(c)
        SET r.level = $community_level
        """
        self.execute_query(
            query,
            {
                "node_ids": node_ids,
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
        """Create a community node in Neo4j (id only) and write content to Qdrant.

        Neo4j: bare (:Community {id}) node + CONTAINS edges to member nodes.
        Qdrant (node_cores): name, description (summary), community_level only.
        Membership NL sentences are written separately to node_relationships.
        """
        from app.services.embedding import embedding_service as _emb

        # 1. Neo4j: community node with its stable ID, display name, + CONTAINS edges
        query = """
        MERGE (c:Community {id: $community_id})
        SET c.name = $name
        WITH c
        UNWIND $member_node_ids AS member_node_id
        MATCH (n:Indexable {id: member_node_id})
        MERGE (c)-[:CONTAINS]->(n)
        RETURN c.id AS community_id
        """
        rows = self.execute_query(
            query,
            {
                "community_id": community_id,
                "name": name,
                "member_node_ids": member_node_ids,
            },
        )

        # 2. Qdrant: community node — name, description, community_level only
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
        except Exception as _e:
            logger.warning(f"[Graph] create_leiden_community Qdrant write failed: {_e}")

        return rows[0] if rows else {"community_id": community_id}

    def get_node_storage_payload(self, node_id: str) -> dict | None:
        """Return fields needed to refresh Qdrant/Elasticsearch for a node.

        All content (description, facts, questions, isolated_contexts, relationship NL)
        comes from Qdrant. Neo4j provides only the structural confirmation the node exists.
        """
        # Confirm node exists in Neo4j
        rows = self.execute_query(
            "MATCH (n:Indexable {id: $node_id}) RETURN n.id AS node_id, labels(n) AS labels",
            {"node_id": node_id},
        )
        if not rows:
            return None
        row = dict(rows[0])

        # Fetch content fields from Qdrant
        try:
            content = qdrant_service.get_node_content_by_id(node_id)
        except Exception as _e:
            logger.warning(f"[Graph] get_node_storage_payload Qdrant fetch failed for {node_id}: {_e}")
            content = None

        # Fetch relationship NL sentences from Qdrant node_relationships
        try:
            rels = qdrant_service.get_relationships_for_node_ids([node_id])
            relationship_natural_language = [r["natural_language"] for r in rels if r.get("natural_language")]
        except Exception as _e:
            logger.warning(f"[Graph] get_node_storage_payload NL fetch failed for {node_id}: {_e}")
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
        """Trace back from knowledge nodes to the notes that created them.

        Resolves names to IDs via Qdrant, then traverses REFERENCES edges in Neo4j.
        """
        if not node_names:
            return []
        # Resolve names to IDs
        node_ids = [
            nid for n in node_names
            if (nid := qdrant_service.find_node_id_by_name(n.lower().strip()))
        ]
        if not node_ids:
            return []
        query = """
        UNWIND $node_ids as node_id
        MATCH (n:Indexable {id: node_id})<-[r:REFERENCES]-(note:Note)
        WHERE r.is_active = true
        RETURN n.id as node_id,
               note.id as note_id,
               'REFERENCES' as relationship_type
        """
        return self.execute_query(query, {"node_ids": node_ids})

    def get_linked_evidence(
        self, node_names: list[str], limit_per_node: int = 3
    ) -> list[dict]:
        """Fetch the N most recently created notes linked to specific graph nodes.

        Resolves names to IDs via Qdrant, then looks up REFERENCES edges in Neo4j.
        Each returned row contains ``node_id``, ``node_name``, and ``evidence``
        (list of ``{id: note_id}`` dicts). The ``node_name`` field allows callers
        to map results back to the original name without a second lookup.
        """
        if not node_names:
            return []
        id_to_name: dict[str, str] = {}
        node_ids: list[str] = []
        for n in node_names:
            name_lower = n.lower().strip()
            nid = qdrant_service.find_node_id_by_name(name_lower)
            if nid:
                node_ids.append(nid)
                id_to_name[nid] = name_lower
        if not node_ids:
            return []
        query = """
        UNWIND $node_ids as node_id
        MATCH (n:Indexable {id: node_id})<-[r:REFERENCES]-(note:Note)
        WHERE r.is_active = true
        WITH node_id,
             collect(distinct {id: note.id})[0..$limit] as evidence
        RETURN node_id, evidence
        """
        rows = self.execute_query(
            query, {"node_ids": node_ids, "limit": limit_per_node}
        )
        for row in rows:
            row["node_name"] = id_to_name.get(row.get("node_id", ""), "")
        return rows

    def get_full_graph(self) -> dict:
        """Fetch all nodes and relationships for graph visualization.

        Returns only IDs from Neo4j; names/types enriched from Qdrant.
        """
        nodes_query = "MATCH (n:Indexable) RETURN n.id as node_id, labels(n) as labels"
        links_query = """
        MATCH (source:Indexable)-[r]->(target:Indexable)
        WHERE r.is_active = true OR r.is_active IS NULL
        RETURN
            source.id as source,
            target.id as target,
            type(r) as type,
            r.edge_weight as edge_weight
        """
        nodes_data = self.execute_query(nodes_query)
        links_data = self.execute_query(links_query)

        node_ids = [row["node_id"] for row in nodes_data if row.get("node_id")]
        content_map = qdrant_service.get_nodes_content_by_ids(node_ids) if node_ids else {}

        nodes = []
        for row in nodes_data:
            nid = row.get("node_id")
            c = content_map.get(nid, {})
            nodes.append({
                "id": nid,
                "name": c.get("name") or nid or "Unknown",
                "group": c.get("type") or "unknown",
                "description": _strip_facts_prefix(c.get("description", "")),
                "entity_type": c.get("type") or "unknown",
                "labels": row.get("labels", []),
            })
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

    # ============ RELATIONSHIP MANAGEMENT ============

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
        """
        Create or update a relationship between two nodes with BI-TEMPORAL support.
        Uses node IDs (not names) for all Neo4j operations — names are for logging only.
        If source_id/target_id are not provided they are resolved from Qdrant.

        Edge weight formula: (strength × 0.5) + (confidence × 0.3) + (relevance × 0.2)
        natural_language is NOT written to Neo4j — it lives in Qdrant node_relationships.
        """
        import uuid as _uuid
        from datetime import datetime
        from app.schemas.relationships import (
            can_evolve,
            is_bidirectional,
            get_contradicting_types,
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

        # Resolve IDs from Qdrant if callers didn't supply them
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

        # Step 1: Invalidate CONTRADICTING relationships
        contradicting_types = get_contradicting_types(relationship_type)
        invalidated_relationships = []
        for contra_type in contradicting_types:
            invalidate_query = f"""
            MATCH (source:{source_label} {{id: $source_id}})
            MATCH (target:{target_label} {{id: $target_id}})
            MATCH (source)-[r:{contra_type}]->(target)
            WHERE r.is_active = true
            SET r.is_active = false,
                r.valid_to = $ingestion_time,
                r.invalidated_by = $relationship_type,
                r.invalidation_note_id = $note_id
            RETURN type(r) as invalidated_type
            """
            result = self.execute_query(
                invalidate_query,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "ingestion_time": ingestion_time,
                    "relationship_type": relationship_type,
                    "note_id": note_id,
                },
            )
            for r in (result or []):
                if r.get("invalidated_type"):
                    invalidated_relationships.append(r["invalidated_type"])
                    logger.info(
                        f"[Bi-Temporal] Invalidated: ({source_name})-[{r['invalidated_type']}]->({target_name})"
                    )

        # Step 2: Check if relationship already exists
        check_query = f"""
        MATCH (source:{source_label} {{id: $source_id}})
        MATCH (target:{target_label} {{id: $target_id}})
        OPTIONAL MATCH (source)-[r:{relationship_type}]->(target)
        WHERE r.is_active = true OR r.is_active IS NULL
        RETURN r, type(r) as current_type
        """
        existing = self.execute_query(
            check_query,
            {"source_id": source_id, "target_id": target_id},
        )

        action = "created"
        previous_type = None

        if existing and existing[0].get("r"):
            current_type = existing[0]["current_type"]

            if current_type == relationship_type:
                action = "reinforced"
                update_query = f"""
                MATCH (source:{source_label} {{id: $source_id}})
                MATCH (target:{target_label} {{id: $target_id}})
                MATCH (source)-[r:{relationship_type}]->(target)
                WHERE r.is_active = true OR r.is_active IS NULL
                SET r.last_updated = $ingestion_time,
                    r.mention_count = coalesce(r.mention_count, 0) + 1,
                    r.confidence = CASE
                        WHEN $confidence > coalesce(r.confidence, 0) THEN $confidence
                        ELSE r.confidence
                    END,
                    r.is_active = true,
                    r.relationship_id = CASE WHEN r.relationship_id IS NULL THEN $relationship_id ELSE r.relationship_id END,
                    r.strength = CASE WHEN r.strength IS NULL THEN $strength ELSE r.strength END,
                    r.relevance = CASE WHEN r.relevance IS NULL THEN $relevance ELSE r.relevance END,
                    r.edge_weight = CASE WHEN r.edge_weight IS NULL THEN $edge_weight ELSE r.edge_weight END
                RETURN r
                """
                self.execute_query(
                    update_query,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "confidence": confidence,
                        "ingestion_time": ingestion_time,
                        "relationship_id": relationship_id,
                        "strength": strength,
                        "relevance": relevance,
                        "edge_weight": edge_weight,
                    },
                )
            elif can_evolve(current_type, relationship_type):
                action = "evolved"
                previous_type = current_type

                invalidate_old = f"""
                MATCH (source:{source_label} {{id: $source_id}})
                MATCH (target:{target_label} {{id: $target_id}})
                MATCH (source)-[old:{current_type}]->(target)
                WHERE old.is_active = true OR old.is_active IS NULL
                SET old.is_active = false,
                    old.valid_to = $ingestion_time,
                    old.evolved_to = $new_type,
                    old.evolution_note_id = $note_id
                """
                self.execute_query(
                    invalidate_old,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "ingestion_time": ingestion_time,
                        "new_type": relationship_type,
                        "note_id": note_id,
                    },
                )

                create_query = f"""
                MATCH (source:{source_label} {{id: $source_id}})
                MATCH (target:{target_label} {{id: $target_id}})
                CREATE (source)-[r:{relationship_type}]->(target)
                SET r.confidence = $confidence,
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
                RETURN r
                """
                self.execute_query(
                    create_query,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
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
                    f"[Bi-Temporal] Evolved: ({source_name})-[{previous_type}\u2192{relationship_type}]->({target_name})"
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
            # Create NEW relationship
            create_query = f"""
            MERGE (source:{source_label} {{id: $source_id}})
            MERGE (target:{target_label} {{id: $target_id}})
            CREATE (source)-[r:{relationship_type}]->(target)
            SET r.confidence = $confidence,
                r.strength = $strength,
                r.relevance = $relevance,
                r.edge_weight = $edge_weight,
                r.relationship_id = $relationship_id,
                r.ingested_at = $ingestion_time,
                r.last_updated = $ingestion_time,
                r.mention_count = 1,
                r.is_active = true,
                r.note_id = $note_id
            RETURN r
            """
            self.execute_query(
                create_query,
                {
                    "source_id": source_id,
                    "target_id": target_id,
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
                source_label=target_label,
                target_label=source_label,
                relationship_type=relationship_type,
                confidence=confidence,
                note_id=note_id,
                ingestion_time=ingestion_time,
            )

        logger.info(
            f"[Graph] Relationship {action}: ({source_name})-[{relationship_type}]->({target_name})"
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
        source_label: str,
        target_label: str,
        relationship_type: str,
        confidence: float,
        note_id: str,
        ingestion_time: str,
    ):
        """Helper to create inverse relationship for bidirectional types. Uses IDs only."""
        query = f"""
        MERGE (source:{source_label} {{id: $source_id}})
        MERGE (target:{target_label} {{id: $target_id}})
        MERGE (source)-[r:{relationship_type}]->(target)
        SET r.confidence = $confidence,
            r.ingested_at = coalesce(r.ingested_at, $ingestion_time),
            r.last_updated = $ingestion_time,
            r.mention_count = coalesce(r.mention_count, 0) + 1,
            r.is_active = true,
            r.note_id = $note_id
        RETURN r
        """
        self.execute_query(
            query,
            {
                "source_id": source_id,
                "target_id": target_id,
                "confidence": confidence,
                "ingestion_time": ingestion_time,
                "note_id": note_id,
            },
        )

    def get_node_relationships(
        self,
        node_name: str,
        node_label: str = None,
        relationship_types: list[str] = None,
        direction: str = "both",
        min_confidence: float = 0.0,
    ) -> list[dict]:
        """Get all relationships for a node. Resolves name to ID via Qdrant.

        Returns IDs only — callers can enrich names from Qdrant if needed.
        """
        node_id = self.resolve_node_id(node_name.lower().strip())
        if not node_id:
            return []

        label_filter = f":{node_label}" if node_label else ""

        if direction == "outgoing":
            match_pattern = f"(node{label_filter} {{id: $node_id}})-[r]->(other)"
        elif direction == "incoming":
            match_pattern = f"(other)-[r]->(node{label_filter} {{id: $node_id}})"
        else:
            match_pattern = f"(node{label_filter} {{id: $node_id}})-[r]-(other)"

        type_filter = ""
        if relationship_types:
            type_filter = "AND type(r) IN $relationship_types"

        query = f"""
        MATCH {match_pattern}
        WHERE r.is_active = true
          AND coalesce(r.confidence, 0) >= $min_confidence
          {type_filter}
        RETURN
            node.id as node_id,
            other.id as other_node_id,
            type(r) as relationship_type,
            r.confidence as confidence,
            r.last_updated as last_updated,
            r.mention_count as mention_count,
            r.edge_weight as edge_weight
        """

        params: dict = {"node_id": node_id, "min_confidence": min_confidence}
        if relationship_types:
            params["relationship_types"] = relationship_types
        return self.execute_query(query, params)

    def get_related_nodes(
        self,
        node_name: str,
        node_label: str = None,
        max_depth: int = 2,
        relationship_types: list[str] = None,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """
        Get nodes related to a given node up to max_depth hops away.
        Resolves name to node_id via Qdrant; queries Neo4j by ID.
        """
        node_id = self.resolve_node_id(node_name.lower().strip())
        if not node_id:
            return []

        type_filter = ""
        if relationship_types:
            type_filter = f":{('|').join(relationship_types)}"

        query = f"""
        MATCH path = (start:Indexable {{id: $node_id}})-[r{type_filter}*1..{max_depth}]-(related)
        WHERE all(rel in relationships(path) WHERE
            rel.is_active = true AND
            coalesce(rel.confidence, 0) >= $min_confidence
        )
        WITH related, relationships(path) as rels, length(path) as depth
        RETURN DISTINCT
            related.id as node_id,
            related.name as name,
            labels(related)[0] as label,
            depth,
            [rel in rels | type(rel)] as relationship_path,
            [rel in rels | rel.confidence] as confidence_path,
            [rel in rels | rel.context] as context_path,
            [rel in rels | rel.natural_language] as natural_language_path
        ORDER BY depth
        """

        return self.execute_query(
            query,
            {
                "node_id": node_id,
                "min_confidence": min_confidence,
            },
        )

    def get_relationships_between_nodes(self, names: list[str]) -> list[dict]:
        """
        Return all active relationships where BOTH endpoints are in `names`.
        Resolves names to IDs via Qdrant, then queries Neo4j by ID.
        """
        if not names or len(names) < 2:
            return []
        # Resolve names to IDs
        ids = [nid for n in names if (nid := qdrant_service.find_node_id_by_name(n.lower().strip()))]
        if len(ids) < 2:
            return []
        query = """
        MATCH (a)-[r]->(b)
        WHERE a.id IN $ids AND b.id IN $ids
          AND (r.is_active = true OR r.is_active IS NULL)
        RETURN a.id AS source, type(r) AS rel_type, b.id AS target,
               r.edge_weight AS weight
        ORDER BY r.confidence DESC
        """
        return self.execute_query(query, {"ids": ids}) or []

    # ============ BI-TEMPORAL QUERY METHODS ============

    def get_relationships_at_time(
        self,
        node_name: str,
        target_date: str,
        node_label: str = None,
        relationship_types: list[str] = None,
    ) -> list[dict]:
        """
        Get relationships that were ACTIVE at a specific point in time.

        Use for queries like: "Who were my friends in January 2024?"

        Args:
            node_name: Name of the node
            target_date: ISO format date string (e.g., "2024-01-15T00:00:00")
            node_label: Optional label filter
            relationship_types: Optional list of relationship types to filter

        Returns:
            List of relationships that were valid at the target date
        """
        label_filter = f":{node_label}" if node_label else ""
        type_filter = ""
        if relationship_types:
            types_str = "|".join(relationship_types)
            type_filter = f":{types_str}"

        query = f"""
        MATCH (node{label_filter} {{name: $node_name}})-[r{type_filter}]-(other)
        WHERE r.valid_from <= $target_date
          AND (r.valid_to IS NULL OR r.valid_to > $target_date)
        RETURN 
            node.name as source_name,
            labels(node)[0] as source_label,
            other.name as target_name,
            labels(other)[0] as target_label,
            type(r) as relationship_type,
            r.valid_from as valid_from,
            r.valid_to as valid_to,
            r.is_active as is_active,
            r.confidence as confidence,
            r.context as context
        ORDER BY r.valid_from DESC
        """

        return self.execute_query(
            query, {"node_name": node_name, "target_date": target_date}
        )

    def get_relationship_history(
        self,
        source_name: str,
        target_name: str,
        source_label: str = None,
        target_label: str = None,
    ) -> list[dict]:
        """
        Get the FULL history of relationships between two nodes.

        Use for queries like: "How has my relationship with John changed?"

        Args:
            source_name: Name of the source node
            target_name: Name of the target node
            source_label: Optional label for source
            target_label: Optional label for target

        Returns:
            List of all relationships (current and historical) between the nodes,
            ordered chronologically
        """
        source_filter = f":{source_label}" if source_label else ""
        target_filter = f":{target_label}" if target_label else ""

        source_id = qdrant_service.find_node_id_by_name(source_name.lower().strip())
        target_id = qdrant_service.find_node_id_by_name(target_name.lower().strip())
        if not source_id or not target_id:
            return []

        query = f"""
        MATCH (source{source_filter} {{id: $source_id}})-[r]-(target{target_filter} {{id: $target_id}})
        RETURN
            type(r) as relationship_type,
            r.valid_from as valid_from,
            r.valid_to as valid_to,
            r.is_active as is_active,
            r.evolved_from as evolved_from,
            r.evolved_to as evolved_to,
            r.invalidated_by as invalidated_by,
            r.confidence as confidence,
            r.note_id as note_id
        ORDER BY coalesce(r.valid_from, r.ingested_at, '1970-01-01') ASC
        """

        return self.execute_query(
            query, {"source_id": source_id, "target_id": target_id}
        )

    def get_recent_changes(
        self,
        since_date: str,
        change_types: list[str] = None,
    ) -> list[dict]:
        """
        Get all relationship changes since a specific date.

        Use for queries like: "What changed since last week?"

        Args:
            since_date: ISO format date string
            change_types: Optional filter for change types:
                          ["created", "evolved", "invalidated"]

        Returns:
            List of relationship changes with metadata
        """
        query = """
        MATCH (source)-[r]-(target)
        WHERE r.valid_from >= $since_date
           OR r.valid_to >= $since_date
        WITH source, r, target,
             CASE 
                 WHEN r.valid_from >= $since_date AND r.evolved_from IS NOT NULL THEN 'evolved'
                 WHEN r.valid_from >= $since_date THEN 'created'
                 WHEN r.valid_to >= $since_date THEN 'invalidated'
                 ELSE 'unknown'
             END as change_type
        RETURN 
            source.name as source_name,
            labels(source)[0] as source_label,
            target.name as target_name,
            labels(target)[0] as target_label,
            type(r) as relationship_type,
            change_type,
            r.valid_from as valid_from,
            r.valid_to as valid_to,
            r.evolved_from as evolved_from,
            r.invalidated_by as invalidated_by,
            r.note_id as note_id
        ORDER BY coalesce(r.valid_from, r.valid_to) DESC
        """

        results = self.execute_query(query, {"since_date": since_date})

        # Filter by change_types if specified
        if change_types:
            results = [r for r in results if r.get("change_type") in change_types]

        return results

    def get_entity_timeline(
        self,
        entity_name: str,
        entity_label: str = None,
    ) -> list[dict]:
        """
        Get the complete timeline of an entity's relationships.

        Use for understanding how an entity's connections evolved over time.

        Args:
            entity_name: Name of the entity
            entity_label: Optional label filter

        Returns:
            Chronological list of all relationship events for this entity
        """
        label_filter = f":{entity_label}" if entity_label else ""

        query = f"""
        MATCH (entity{label_filter} {{name: $entity_name}})-[r]-(other)
        WITH entity, r, other,
             CASE 
                 WHEN r.evolved_from IS NOT NULL THEN 'evolved'
                 WHEN r.valid_to IS NOT NULL THEN 'ended'
                 ELSE 'started'
             END as event_type
        RETURN 
            other.name as related_entity,
            labels(other)[0] as related_type,
            type(r) as relationship_type,
            event_type,
            r.valid_from as started,
            r.valid_to as ended,
            r.evolved_from as previous_relationship,
            r.evolved_to as next_relationship,
            r.is_active as is_current,
            r.context as context
        ORDER BY coalesce(r.valid_from, '1970-01-01') ASC
        """

        return self.execute_query(query, {"entity_name": entity_name})

    # ============ COMMUNITY/CLUSTER METHODS ============
    # Communities group related nodes and provide high-level summaries
    # for broad queries like "What have I been learning lately?"

    def create_or_update_community(
        self,
        name: str,
        domain: str,
        member_names: list[str],
        summary: str = None,
        themes: list[str] = None,
    ) -> dict:
        """
        Create or update a Community node that groups related entities.

        Communities are domain-based clusters (Professional, Academic, Personal, Creative)
        that contain related entities and concepts. They provide high-level summaries
        for broad queries.

        Args:
            name: Community name (e.g., "Professional Development", "Physics Learning")
            domain: Domain type (Professional, Academic, Personal, Creative, Dreams)
            member_names: List of node names that belong to this community
            summary: High-level summary of the community's content
            themes: Key themes/topics in this community

        Returns:
            Dict with community info
        """
        from datetime import datetime

        current_time = datetime.utcnow().isoformat()

        # Create or update community node
        query = """
        MERGE (c:Community {name: $name})
        SET c.domain = $domain,
            c.summary = CASE 
                WHEN $summary IS NOT NULL THEN $summary 
                ELSE c.summary 
            END,
            c.themes = CASE 
                WHEN $themes IS NOT NULL THEN $themes 
                ELSE c.themes 
            END,
            c.updated_at = $current_time,
            c.member_count = size($member_names)
        WITH c
        UNWIND $member_names as member_name
        MATCH (n:Indexable {name: member_name})
        MERGE (c)-[:CONTAINS]->(n)
        RETURN c.name as name, c.summary as summary, c.member_count as member_count
        """

        results = self.execute_query(
            query,
            {
                "name": name,
                "domain": domain,
                "summary": summary,
                "themes": themes or [],
                "member_names": member_names,
                "current_time": current_time,
            },
        )

        if results:
            logger.info(
                f"[Community] Updated '{name}' with {len(member_names)} members"
            )
            return results[0]
        return {"name": name, "status": "created"}

    def get_community_summary(self, community_name: str) -> dict | None:
        """
        Get the summary for a Community/Cluster node.

        Args:
            community_name: Name of the community

        Returns:
            Dict with community summary, member count, and key themes, or None
        """
        query = """
        MATCH (c:Community {name: $community_name})
        OPTIONAL MATCH (c)-[:CONTAINS]->(member:Indexable)
        WITH c, collect(distinct {
            name: member.name, 
            label: labels(member)[0], 
            summary: member.summary
        }) as members
        RETURN 
            c.name as name,
            c.domain as domain,
            c.summary as summary,
            c.themes as themes,
            c.updated_at as last_updated,
            size(members) as member_count,
            members[0..10] as top_members
        """
        results = self.execute_query(query, {"community_name": community_name})
        return results[0] if results else None

    def get_communities_by_domain(self, domain: str) -> list[dict]:
        """
        Get all communities in a specific domain.

        Args:
            domain: Domain type (Professional, Academic, Personal, Creative, Dreams)

        Returns:
            List of communities with summaries
        """
        query = """
        MATCH (c:Community {domain: $domain})
        OPTIONAL MATCH (c)-[:CONTAINS]->(member)
        RETURN 
            c.name as name,
            c.summary as summary,
            c.themes as themes,
            c.updated_at as last_updated,
            count(member) as member_count
        ORDER BY count(member) DESC
        """
        return self.execute_query(query, {"domain": domain})

    def get_communities_for_query(self, query_entities: list[str]) -> list[dict]:
        """
        Find communities that contain nodes matching query entities.

        For queries like "What have I been learning lately?", finds
        communities containing the mentioned entities.

        Args:
            query_entities: List of entity names extracted from query

        Returns:
            List of relevant communities with summaries
        """
        if not query_entities:
            return []

        query = """
        UNWIND $entity_names as entity_name
        MATCH (c:Community)-[:CONTAINS]->(n:Indexable)
        WHERE toLower(n.name) CONTAINS toLower(entity_name)
        WITH c, count(distinct n) as matched_members
        OPTIONAL MATCH (c)-[:CONTAINS]->(all_member)
        WITH c, matched_members, count(all_member) as total_members
        RETURN DISTINCT
            c.name as name,
            c.domain as domain,
            c.summary as summary,
            c.themes as themes,
            matched_members,
            total_members as member_count,
            toFloat(matched_members) / toFloat(total_members) as relevance
        ORDER BY relevance DESC, matched_members DESC
        LIMIT 5
        """
        return self.execute_query(query, {"entity_names": query_entities})

    def get_all_communities(self) -> list[dict]:
        """
        Get all communities for broad queries.

        Returns:
            List of all communities with summaries and member counts
        """
        query = """
        MATCH (c:Community)
        OPTIONAL MATCH (c)-[:CONTAINS]->(member)
        RETURN 
            c.name as name,
            c.domain as domain,
            c.summary as summary,
            c.themes as themes,
            c.updated_at as last_updated,
            count(member) as member_count
        ORDER BY c.domain, member_count DESC
        """
        return self.execute_query(query, {})

    def search_communities(
        self, vector: list[float], top_k: int = 5, min_score: float = 0.55
    ) -> list[dict]:
        """
        Find communities whose summaries are semantically relevant to a query vector.
        Community vectors now live in Qdrant node_cores, filtered by type=community.

        Returns communities ordered by relevance score, highest first.
        """
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

    def assign_node_to_community(self, node_name: str, community_name: str) -> bool:
        """Add a node to a community. Resolves names to IDs via Qdrant."""
        node_id = qdrant_service.find_node_id_by_name(node_name.lower().strip())
        community_id = qdrant_service.find_node_id_by_name(community_name.lower().strip())
        if not node_id or not community_id:
            return False
        query = """
        MATCH (c:Community {id: $community_id})
        MATCH (n:Indexable {id: $node_id})
        MERGE (c)-[:CONTAINS]->(n)
        RETURN c.id as community_id
        """
        results = self.execute_query(
            query, {"community_id": community_id, "node_id": node_id}
        )
        return len(results) > 0

    def update_community_summary(
        self,
        community_name: str,
        summary: str,
        themes: list[str] = None,
        embedding: list[float] = None,
    ):
        """
        Update a community's summary (typically called after new nodes are added).

        Args:
            community_name: Name of the community
            summary: New high-level summary
            themes: Updated list of key themes
            embedding: Vector embedding of the summary for semantic search
        """
        from datetime import datetime

        query = """
        MATCH (c:Community {name: $community_name})
        SET c.summary = $summary,
            c.themes = $themes,
            c.updated_at = $current_time,
            c:Indexable,
            c.name = $community_name
        WITH c
        // Set embedding if provided
        CALL apoc.do.when(
            $embedding IS NOT NULL,
            'SET c.embedding = embedding RETURN c',
            'RETURN c',
            {c: c, embedding: $embedding}
        ) YIELD value
        RETURN c.name as name
        """
        self.execute_query(
            query,
            {
                "community_name": community_name,
                "summary": summary,
                "themes": themes or [],
                "current_time": datetime.utcnow().isoformat(),
                "embedding": embedding,
            },
        )

    def get_community_linked_notes(
        self, community_names: list[str], limit_per_community: int = 3
    ) -> list[dict]:
        """
        Get notes linked to nodes that belong to the specified communities.

        For reference traceability - shows which notes support a community's summary.

        Args:
            community_names: Names of communities to find linked notes for
            limit_per_community: Max notes per community

        Returns:
            List of dicts with community_name and notes list
        """
        if not community_names:
            return []

        query = """
        UNWIND $community_names as comm_name
        MATCH (c:Community {name: comm_name})-[:CONTAINS]->(member:Indexable)
        MATCH (note:Indexable {type: 'note'})-[r:REFERENCES]->(member)
        WHERE r.is_active = true
        WITH comm_name, note, member
        ORDER BY note.created_at DESC
        WITH comm_name, collect(DISTINCT {
            id: elementId(note),
            title: note.name
        })[0..$limit] as notes
        RETURN comm_name as community_name, notes
        """
        return self.execute_query(
            query,
            {
                "community_names": community_names,
                "limit": limit_per_community,
            },
        )


    # ── 3D spatial layout ────────────────────────────────────────────────────

    def get_all_node_ids_and_edges(
        self,
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Return (all_node_ids, edge_pairs) for spring layout computation.

        Includes :Indexable nodes + :Community nodes.
        Edges include active relationships between Indexable nodes and
        MEMBER_OF edges from Indexable → Community.
        """
        node_query = """
        CALL () {
            MATCH (n:Indexable) RETURN n.id AS node_id
            UNION ALL
            MATCH (c:Community) RETURN c.id AS node_id
        }
        RETURN node_id
        """
        node_rows = self.execute_query(node_query, {})
        node_ids = [r["node_id"] for r in node_rows if r.get("node_id")]

        edge_query = """
        CALL () {
            MATCH (a:Indexable)-[r]->(b:Indexable)
            WHERE (r.is_active = true OR r.is_active IS NULL)
              AND a.id IS NOT NULL AND b.id IS NOT NULL
              AND type(r) <> 'MEMBER_OF'
              AND NOT type(r) STARTS WITH '__'
            RETURN a.id AS src, b.id AS tgt
            UNION ALL
            MATCH (n:Indexable)-[:MEMBER_OF]->(c:Community)
            WHERE n.id IS NOT NULL AND c.id IS NOT NULL
            RETURN n.id AS src, c.id AS tgt
        }
        RETURN DISTINCT src, tgt
        LIMIT 5000
        """
        edge_rows = self.execute_query(edge_query, {})
        edges = [
            (r["src"], r["tgt"])
            for r in edge_rows
            if r.get("src") and r.get("tgt")
        ]
        return node_ids, edges

    def get_full_3d_graph(self) -> dict:
        """Return all nodes and all edges for the flat 3D graph renderer.

        Positions are computed at request time using the solar-system hierarchical
        layout: L0 stars → L1 planets → L2 moons → individual nodes.
        """
        # ── Indexable nodes ───────────────────────────────────────────────────
        indexable_rows = self.execute_query(
            """
            MATCH (n:Indexable)
            WHERE n.id IS NOT NULL AND n.name IS NOT NULL
            RETURN n.id AS node_id, n.name AS name, n.type AS node_type
            """,
            {},
        )

        # ── Community nodes ───────────────────────────────────────────────────
        community_rows = self.execute_query(
            """
            MATCH (c:Community)
            WHERE c.id IS NOT NULL AND c.name IS NOT NULL
            RETURN c.id AS node_id, c.name AS name,
                   c.level AS community_level
            """,
            {},
        )

        # ── Memberships: which Indexable belongs to which Community ───────────
        membership_rows = self.execute_query(
            """
            MATCH (n:Indexable)-[r:MEMBER_OF]->(c:Community)
            WHERE n.id IS NOT NULL AND c.id IS NOT NULL
            RETURN n.id AS node_id, c.id AS community_id, r.level AS level
            ORDER BY r.level DESC
            """,
            {},
        )

        # node_id → primary (highest-level) community
        node_community_map: dict[str, str] = {}
        # node_id → {level: community_id} — used for solar layout
        node_level_map: dict[str, dict[int, str]] = {}
        for row in membership_rows:
            nid = row.get("node_id")
            cid = row.get("community_id")
            lvl = row.get("level")
            if nid and cid:
                if nid not in node_community_map:
                    node_community_map[nid] = cid
                if lvl is not None:
                    node_level_map.setdefault(nid, {})[int(lvl)] = cid

        # ── Compute positions ─────────────────────────────────────────────────
        from app.utils.graph_layout import compute_solar_positions

        all_node_ids = [r["node_id"] for r in indexable_rows if r.get("node_id")]
        communities_meta = [
            {
                "community_id": r["node_id"],
                "community_level": r.get("community_level") or 0,
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

        # ── Build node list ───────────────────────────────────────────────────
        nodes = []
        for row in indexable_rows:
            nid = row.get("node_id")
            name = (row.get("name") or "").strip()
            if not nid or not name:
                continue
            x, y, z = positions.get(nid, (0.0, 0.0, 0.0))
            nodes.append({
                "node_id": nid,
                "name": name,
                "node_type": row.get("node_type") or "unknown",
                "description": "",
                "community_id": node_community_map.get(nid),
                "x": float(x),
                "y": float(y),
                "z": float(z),
            })

        for row in community_rows:
            nid = row.get("node_id")
            name = (row.get("name") or "").strip()
            if not nid or not name:
                continue
            x, y, z = positions.get(nid, (0.0, 0.0, 0.0))
            nodes.append({
                "node_id": nid,
                "name": name,
                "node_type": "community",
                "description": "",
                "community_id": None,
                "x": float(x),
                "y": float(y),
                "z": float(z),
            })

        # ── Edges ─────────────────────────────────────────────────────────────
        edge_rows = self.execute_query(
            """
            MATCH (a:Indexable)-[r]->(b:Indexable)
            WHERE (r.is_active = true OR r.is_active IS NULL)
              AND a.id IS NOT NULL AND b.id IS NOT NULL
              AND NOT type(r) STARTS WITH '__'
              AND type(r) <> 'MEMBER_OF'
            RETURN DISTINCT a.id AS source, b.id AS target, type(r) AS rel_type
            LIMIT 4000
            """,
            {},
        )
        member_edge_rows = self.execute_query(
            """
            MATCH (n:Indexable)-[:MEMBER_OF]->(c:Community)
            WHERE n.id IS NOT NULL AND c.id IS NOT NULL
            RETURN DISTINCT n.id AS source, c.id AS target, 'MEMBER_OF' AS rel_type
            LIMIT 2000
            """,
            {},
        )
        edges = [
            {"source": r["source"], "target": r["target"], "type": r.get("rel_type", "")}
            for r in (list(edge_rows) + list(member_edge_rows))
            if r.get("source") and r.get("target")
        ]

        return {"nodes": nodes, "edges": edges}

    def get_unpositioned_node_ids(self) -> list[str]:
        """Return IDs of :Indexable nodes that have no 3D position yet (pos_x IS NULL)."""
        rows = self.execute_query(
            "MATCH (n:Indexable) WHERE n.pos_x IS NULL RETURN n.id AS node_id",
            {},
        )
        return [row["node_id"] for row in rows if row.get("node_id")]

    def store_node_positions(self, positions: dict[str, tuple[float, float, float]]) -> None:
        """Write pre-computed (x, y, z) onto Indexable + Community nodes in Neo4j."""
        if not positions:
            return
        batch = [
            {"node_id": nid, "x": float(xyz[0]), "y": float(xyz[1]), "z": float(xyz[2])}
            for nid, xyz in positions.items()
        ]
        # Works for both :Indexable (non-community) nodes and :Community nodes.
        self.execute_query(
            """
            UNWIND $batch AS item
            OPTIONAL MATCH (n:Indexable {id: item.node_id})
            WITH n, item WHERE n IS NOT NULL
            SET n.pos_x = item.x, n.pos_y = item.y, n.pos_z = item.z
            """,
            {"batch": batch},
        )
        self.execute_query(
            """
            UNWIND $batch AS item
            OPTIONAL MATCH (c:Community {id: item.node_id})
            WITH c, item WHERE c IS NOT NULL
            SET c.pos_x = item.x, c.pos_y = item.y, c.pos_z = item.z
            """,
            {"batch": batch},
        )

    def get_3d_overview(self) -> dict:
        """Return community nodes, orphan nodes, and orphan edges for the LOD overview.

        IDs come from Neo4j; names/summaries/levels enriched from Qdrant.
        Positions computed at request time — no pos_x stored in Neo4j.
        """
        from app.utils.graph_layout import compute_positions

        community_query = """
        MATCH (c:Community)
        WHERE c.id IS NOT NULL
        RETURN c.id AS community_id, c.level AS community_level
        """
        membership_query = """
        MATCH (n:Indexable)-[r:MEMBER_OF]->(c:Community)
        WHERE n.id IS NOT NULL AND c.id IS NOT NULL
        RETURN n.id AS node_id, c.id AS community_id, r.level AS level
        ORDER BY r.level DESC
        """
        rows = self.execute_query(community_query, {})
        membership_rows = self.execute_query(membership_query, {})

        community_members: dict[str, list[str]] = {}
        for mr in membership_rows:
            nid = mr.get("node_id")
            cid = mr.get("community_id")
            if nid and cid and (mr.get("level") or 0) == 2:
                community_members.setdefault(cid, []).append(nid)

        community_ids = [r["community_id"] for r in rows if r.get("community_id")]
        content_map = qdrant_service.get_nodes_content_by_ids(community_ids) if community_ids else {}

        communities_meta = [
            {
                "community_id": r["community_id"],
                "community_level": r.get("community_level") or 2,
                "name": content_map.get(r["community_id"], {}).get("name", ""),
            }
            for r in rows if r.get("community_id")
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
            communities.append({
                "community_id": cid,
                "name": c.get("name") or "Unnamed Cluster",
                "summary": _strip_facts_prefix(c.get("description") or ""),
                "community_level": c.get("community_level") or 2,
                "member_count": c.get("member_count") or 0,
                "themes": c.get("themes") or [],
                "x": float(x),
                "y": float(y),
                "z": float(z),
            })

        # Orphan nodes: Indexable nodes not in any community
        orphan_node_query = """
        MATCH (n:Indexable)
        WHERE NOT (n)-[:MEMBER_OF]->(:Community)
          AND n.id IS NOT NULL AND n.name IS NOT NULL
        RETURN n.id AS node_id, n.name AS name, n.type AS node_type
        """
        orphan_rows = self.execute_query(orphan_node_query, {})
        orphan_ids = [r["node_id"] for r in orphan_rows if r.get("node_id")]
        orphan_content = qdrant_service.get_nodes_content_by_ids(orphan_ids) if orphan_ids else {}

        from app.utils.graph_layout import _fibonacci_sphere, _deterministic_jitter, ORPHAN_RADIUS
        orphan_pts = _fibonacci_sphere(len(orphan_ids), ORPHAN_RADIUS)
        orphan_nodes = []
        for idx, row in enumerate(orphan_rows):
            nid = row.get("node_id")
            if not nid:
                continue
            c = orphan_content.get(nid, {})
            ox, oy, oz = orphan_pts[idx] if idx < len(orphan_pts) else (0.0, 0.0, 0.0)
            jx, jy, jz = _deterministic_jitter(nid, 3.0)
            orphan_nodes.append({
                "node_id": nid,
                "name": c.get("name") or row.get("name") or "Unnamed",
                "node_type": c.get("type") or row.get("node_type") or "unknown",
                "description": _strip_facts_prefix(c.get("description", "")),
                "facts": c.get("facts", []),
                "x": float(ox + jx),
                "y": float(oy + jy),
                "z": float(oz + jz),
            })

        # Edges between orphan nodes (for drawing connections before Leiden runs)
        orphan_edge_query = """
        MATCH (a:Indexable)-[r]->(b:Indexable)
        WHERE NOT ()-[:CONTAINS]->(a)
          AND NOT ()-[:CONTAINS]->(b)
          AND (r.is_active = true OR r.is_active IS NULL)
          AND a.id IS NOT NULL AND b.id IS NOT NULL
        RETURN DISTINCT a.id AS source, b.id AS target, type(r) AS rel_type
        LIMIT 1000
        """
        orphan_edge_rows = self.execute_query(orphan_edge_query, {})
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
        """Return member nodes and intra-community edges for one community.

        Used by the frontend when the camera flies into a cluster.
        Positions computed at request time using a fibonacci cluster sphere.
        """
        nodes_query = """
        MATCH (c:Community {id: $cid})-[:CONTAINS]->(n:Indexable)
        WHERE n.id IS NOT NULL
        RETURN n.id AS node_id
        """
        edges_query = """
        MATCH (c:Community {id: $cid})-[:CONTAINS]->(a:Indexable)
        MATCH (c)-[:CONTAINS]->(b:Indexable)
        MATCH (a)-[r]->(b)
        WHERE a.id IS NOT NULL AND b.id IS NOT NULL
          AND (r.is_active = true OR r.is_active IS NULL)
        RETURN DISTINCT
            a.id         AS source,
            b.id         AS target,
            type(r)      AS rel_type,
            r.edge_weight AS edge_weight
        LIMIT 500
        """
        from app.utils.graph_layout import _fibonacci_sphere, _deterministic_jitter, CLUSTER_RADIUS_BASE
        import math as _math

        node_rows = self.execute_query(nodes_query, {"cid": community_id})
        edge_rows = self.execute_query(edges_query, {"cid": community_id})

        # Enrich node content from Qdrant
        node_ids = [row["node_id"] for row in node_rows if row.get("node_id")]
        content_map = qdrant_service.get_nodes_content_by_ids(node_ids) if node_ids else {}

        # Compute positions: fibonacci sphere centred at origin, scaled to member count
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
            nodes.append({
                "node_id": nid,
                "name": c.get("name") or "Unnamed",
                "node_type": c.get("type") or "unknown",
                "description": _strip_facts_prefix(c.get("description", "")),
                "facts": c.get("facts", []),
                "community_id": c.get("community_id"),
                "x": float(px + jx),
                "y": float(py + jy),
                "z": float(pz + jz),
            })
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
        """Return full detail for a single Indexable or Community node.

        Tries :Indexable first, then :Community, so community nodes clicked in
        the 3D graph also surface their description and themes from Qdrant.
        """
        # ── Indexable node ────────────────────────────────────────────────────
        neo4j_rows = self.execute_query(
            """
            MATCH (n:Indexable {id: $nid})
            OPTIONAL MATCH (n)-[:MEMBER_OF]->(c:Community)
            RETURN n.id AS node_id, n.name AS name, n.type AS node_type,
                   collect(DISTINCT c.id)[0] AS community_id, 'indexable' AS kind
            """,
            {"nid": node_id},
        )

        # ── Community node (fallback) ─────────────────────────────────────────
        if not neo4j_rows:
            neo4j_rows = self.execute_query(
                """
                MATCH (c:Community {id: $nid})
                RETURN c.id AS node_id, c.name AS name,
                       'community' AS node_type, NULL AS community_id,
                       'community' AS kind
                """,
                {"nid": node_id},
            )

        if not neo4j_rows:
            return None

        row = neo4j_rows[0]
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
            "facts": c.get("facts") or [],
            "domain": c.get("domain"),
            "status": c.get("status"),
            "community_id": row.get("community_id"),
            # Community-specific extras (harmless on non-community nodes)
            "summary": _strip_facts_prefix(c.get("description") or ""),
            "themes": c.get("themes") or [],
            "member_count": c.get("member_count") or 0,
        }


graph_service = GraphService()
