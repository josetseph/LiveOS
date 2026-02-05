from neo4j import GraphDatabase
from app.core.config import settings
from app.core.logging_config import get_component_logger

logger = get_component_logger("GraphService")


class GraphService:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )

    def close(self):
        self.driver.close()

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

    def query_vector(
        self, vector: list[float], top_k: int = 5, min_score: float = 0.7
    ) -> list[dict]:
        """
        Performs a vector search on the Note index.
        Assumes an index 'note_vector_index' exists.
        """
        query = """
        CALL db.index.vector.queryNodes('note_vector_index', $top_k, $vector)
        YIELD node, score
        WHERE score >= $min_score
        RETURN node.content as content, node.id as id, score
        """
        return self.execute_query(
            query, {"vector": vector, "top_k": top_k, "min_score": min_score}
        )

    def query_vector_with_domain(
        self, vector: list[float], top_k: int = 5, min_score: float = 0.5
    ) -> list[dict]:
        """
        Performs a vector search on the Note index, including domain field.
        Used for domain-aware retrieval.
        """
        query = """
        CALL db.index.vector.queryNodes('note_vector_index', $top_k, $vector)
        YIELD node, score
        WHERE score >= $min_score
        RETURN node.content as content, node.id as id, node.domain as domain, score
        """
        return self.execute_query(
            query, {"vector": vector, "top_k": top_k, "min_score": min_score}
        )

    def get_note_context(self, note_ids: list[str]) -> list[dict]:
        """
        Fetches linked concepts, entities, and tasks for a list of note IDs.
        Used for Hybrid Retrieval context enrichment.
        """
        query = """
        UNWIND $note_ids as note_id
        MATCH (n:Note {id: note_id})
        OPTIONAL MATCH (n)-[r1:MENTIONS]->(e:Entity) WHERE r1.is_active = true
        OPTIONAL MATCH (n)-[r2:CONTRIBUTES_TO]->(c:Concept) WHERE r2.is_active = true
        OPTIONAL MATCH (n)-[r3:PRODUCES_TASK]->(t:Task) WHERE r3.is_active = true
        OPTIONAL MATCH (p:Persona)-[r4:REVEALED_BY]->(n) WHERE p.is_active = true
        RETURN n.id as note_id, 
               collect(distinct {name: e.name, type: e.type}) as entities,
               collect(distinct {name: c.name, summary: c.summary}) as concepts,
               collect(distinct {description: t.description, status: t.status}) as tasks,
               collect(distinct {trait: p.trait, quote: r4.quote}) as persona_traits
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
            List of matching nodes with name, labels, summary, and description
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
                n.name as name,
                labels(n) as labels,
                n.summary as summary,
                n.description as description,
                n.trait as trait,
                n.status as status,
                [name_param IN $names WHERE toLower(n.name) CONTAINS name_param][0] as matched_query
            LIMIT 50
            """
        else:
            # Exact matching
            query = """
            MATCH (n:Indexable)
            WHERE toLower(n.name) IN $names
            RETURN DISTINCT
                n.name as name,
                labels(n) as labels,
                n.summary as summary,
                n.description as description,
                n.trait as trait,
                n.status as status,
                toLower(n.name) as matched_query
            LIMIT 50
            """

        return self.execute_query(query, {"names": names_lower})

    def find_paths_between_nodes(
        self,
        node_names: list[str],
        max_depth: int = 3,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """
        Find paths connecting multiple nodes in the graph.
        Used for multi-hop reasoning between query entities.

        Args:
            node_names: List of node names to find connections between
            max_depth: Maximum path length (1-4 recommended)
            min_confidence: Minimum relationship confidence

        Returns:
            List of paths with nodes and relationships along the path
        """
        if len(node_names) < 2:
            return []

        # Find all pairwise shortest paths between the specified nodes
        query = f"""
        UNWIND $node_names as source_name
        UNWIND $node_names as target_name
        WITH source_name, target_name
        WHERE source_name < target_name  // Avoid duplicate pairs
        MATCH (source:Indexable), (target:Indexable)
        WHERE toLower(source.name) CONTAINS toLower(source_name)
          AND toLower(target.name) CONTAINS toLower(target_name)
        MATCH path = shortestPath((source)-[*1..{max_depth}]-(target))
        WHERE all(rel in relationships(path) WHERE 
            coalesce(rel.confidence, 0.8) >= $min_confidence
            AND (rel.is_active = true OR rel.is_active IS NULL)
        )
        WITH path, source, target, length(path) as pathLength
        RETURN DISTINCT
            source.name as source_name,
            labels(source)[0] as source_label,
            target.name as target_name,
            labels(target)[0] as target_label,
            [node in nodes(path) | node.name] as path_nodes,
            [node in nodes(path) | labels(node)[0]] as path_labels,
            [node in nodes(path) | coalesce(node.summary, node.description, '')] as path_summaries,
            [rel in relationships(path) | type(rel)] as relationship_types,
            pathLength as depth
        ORDER BY pathLength
        LIMIT 20
        """

        return self.execute_query(
            query,
            {
                "node_names": node_names,
                "min_confidence": min_confidence,
            },
        )

    def get_recent_notes(self, limit: int = 10, domain: str = None) -> list[dict]:
        """
        Fetches the most recent notes by created_at timestamp.
        Optionally filter by domain.
        """
        domain_filter = "WHERE n.domain = $domain" if domain else ""
        query = f"""
        MATCH (n:Note)
        {domain_filter}
        RETURN n.id as id, n.title as title, n.summary as summary, 
               n.created_at as created_at, n.domain as domain
        ORDER BY n.created_at DESC
        LIMIT $limit
        """
        params = {"limit": limit}
        if domain:
            params["domain"] = domain
        return self.execute_query(query, params)

    def search_knowledge_graph(
        self, vector: list[float], top_k: int = 25, min_score: float = 0.6
    ) -> list[dict]:
        """
        Search across all distilled knowledge nodes (Concept, Entity, Task, Persona, Reference)
        using the unified :Indexable vector index.

        Returns structured data with name, summary/description, node types, and relevance score.
        """
        query = """
        CALL db.index.vector.queryNodes('distilled_knowledge_index', $top_k, $vector)
        YIELD node, score
        WHERE score >= $min_score
        RETURN 
            node.name as name,
            node.summary as summary,
            node.description as description,
            node.trait as trait,
            node.status as status,
            node.type as entity_type,
            labels(node) as labels,
            score
        ORDER BY score DESC
        """
        return self.execute_query(
            query, {"vector": vector, "top_k": top_k, "min_score": min_score}
        )

    def get_node_source_notes(
        self, node_names: list[str], node_labels: list[str]
    ) -> list[dict]:
        """
        Trace back from knowledge nodes (Concept, Entity, Task, Persona) to the Notes that created them.
        Returns note IDs with metadata for the grounding phase.

        Args:
            node_names: List of node names to find source notes for
            node_labels: Corresponding node labels (e.g., ['Concept', 'Entity'])

        Returns:
            List of dicts with node_name, note_id, note_title, relationship_type
        """
        query = """
        UNWIND range(0, size($node_names) - 1) as idx
        WITH $node_names[idx] as node_name, $node_labels[idx] as node_label
        CALL apoc.cypher.run(
            'MATCH (n:' + node_label + ' {name: $name})<-[r]-(note:Note) 
             WHERE r.is_active = true
             RETURN n.name as node_name, note.id as note_id, note.title as note_title, type(r) as rel_type',
            {name: node_name}
        ) YIELD value
        RETURN value.node_name as node_name, 
               value.note_id as note_id, 
               value.note_title as note_title,
               value.rel_type as relationship_type
        """
        try:
            return self.execute_query(
                query, {"node_names": node_names, "node_labels": node_labels}
            )
        except Exception as e:
            # Fallback if APOC is not available - use simpler query
            logger.warning(f"APOC query failed, using fallback: {e}")
            fallback_query = """
            UNWIND $node_names as node_name
            MATCH (n {name: node_name})<-[r]-(note:Note)
            WHERE r.is_active = true AND any(label IN labels(n) WHERE label IN $all_labels)
            RETURN n.name as node_name,
                   note.id as note_id,
                   note.title as note_title,
                   type(r) as relationship_type
            """
            # Get unique labels from node_labels
            all_labels = list(set(node_labels))
            return self.execute_query(
                fallback_query, {"node_names": node_names, "all_labels": all_labels}
            )

    def get_linked_evidence(
        self, node_names: list[str], limit_per_node: int = 3
    ) -> list[dict]:
        """
        Fetches the N most recent notes linked to specific graph nodes.

        This method provides semantic traceability by retrieving evidence notes
        that are directly connected to discovered graph topics, prioritizing
        recent context to show the user's latest thoughts on each topic.

        Args:
            node_names: List of graph node names to find linked notes for
            limit_per_node: Maximum number of recent notes to return per node (default: 3)

        Returns:
            List of dicts with node_name and evidence (list of note objects with id, content, title, created_at)
        """
        query = """
        UNWIND $node_names as node_name
        MATCH (n:Indexable)
        WHERE toLower(n.name) = toLower(node_name)
        MATCH (note:Note)-[r]->(n)
        WHERE r.is_active = true 
          AND type(r) IN ['MENTIONS', 'CONTRIBUTES_TO', 'PRODUCES_TASK', 'REVEALED_BY']
        WITH n, note 
        ORDER BY note.created_at DESC
        WITH n.name as node_name, 
             collect(distinct {
                 id: note.id, 
                 content: note.content, 
                 title: note.title, 
                 created_at: note.created_at
             })[0..$limit] as evidence
        RETURN node_name, evidence
        """
        return self.execute_query(
            query, {"node_names": node_names, "limit": limit_per_node}
        )

    def get_full_graph(self) -> dict:
        """
        Fetch all nodes and relationships for graph visualization.
        Returns data in 3d-force-graph format: {nodes: [...], links: [...]}
        """
        # Get all knowledge nodes including Communities
        nodes_query = """
        MATCH (n)
        WHERE n:Concept OR n:Entity OR n:Task OR n:Persona OR n:Reference OR n:Note OR n:Community
        RETURN 
            elementId(n) as id,
            n.name as name,
            labels(n) as labels,
            n.summary as summary,
            n.description as description,
            n.trait as trait,
            n.status as status,
            n.type as entity_type,
            n.title as title,
            n.created_at as created_at
        """

        # Get all relationships including MEMBER_OF
        links_query = """
        MATCH (source)-[r]->(target)
        WHERE (source:Concept OR source:Entity OR source:Task OR source:Persona OR source:Reference OR source:Note OR source:Community)
          AND (target:Concept OR target:Entity OR target:Task OR target:Persona OR target:Reference OR target:Note OR target:Community)
        RETURN 
            elementId(source) as source,
            elementId(target) as target,
            type(r) as type,
            r.status as status,
            r.created_at as created_at
        """

        nodes_data = self.execute_query(nodes_query)
        links_data = self.execute_query(links_query)

        # Transform nodes
        nodes = []
        for node in nodes_data:
            node_type = (
                [
                    label
                    for label in node["labels"]
                    if label
                    in [
                        "Concept",
                        "Entity",
                        "Task",
                        "Persona",
                        "Reference",
                        "Note",
                        "Community",
                    ]
                ][0]
                if node["labels"]
                else "Unknown"
            )

            # Determine node display name
            display_name = node.get("name") or node.get("title") or f"Node {node['id']}"

            nodes.append(
                {
                    "id": node["id"],
                    "name": display_name,
                    "group": node_type,
                    "summary": node.get("summary"),
                    "description": node.get("description"),
                    "trait": node.get("trait"),
                    "status": node.get("status"),
                    "entity_type": node.get("entity_type"),
                    "created_at": node.get("created_at"),
                }
            )

        # Transform links (filter out inactive relationships)
        links = []
        for link in links_data:
            if link.get("status") != "inactive":  # Skip inactive relationships
                links.append(
                    {
                        "source": link["source"],
                        "target": link["target"],
                        "type": link["type"],
                        "created_at": link.get("created_at"),
                    }
                )

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
        context: str = "",
        note_id: str = None,
        event_time: str = None,
    ) -> dict:
        """
        Create or update a relationship between two nodes with BI-TEMPORAL support.

        Bi-Temporal Logic:
        - valid_from: When this fact became true (event time - from the note's date)
        - valid_to: When this fact stopped being true (null = still valid)
        - ingested_at: When this was recorded in the system (always now())
        - is_active: Quick filter for current relationships

        Args:
            source_name: Name of the source node
            source_label: Label of the source node (Person, Task, Entity, Concept, Event)
            target_name: Name of the target node
            target_label: Label of the target node
            relationship_type: Type of relationship (from RelationshipType enum)
            confidence: Confidence score (0.0-1.0)
            context: Sample text showing the relationship
            note_id: ID of the note where this relationship was mentioned
            event_time: When this fact became true (note's created_at). If None, uses now().

        Returns:
            Dict with relationship info and whether it was created/updated/evolved/invalidated
        """
        from datetime import datetime
        from app.schemas.relationships import (
            can_evolve,
            is_bidirectional,
            get_contradicting_types,
        )

        # Validate relationship_type is not empty
        if not relationship_type or not relationship_type.strip():
            raise ValueError(
                f"relationship_type cannot be empty for {source_name} -> {target_name}"
            )

        # Bi-temporal: separate event time from ingestion time
        ingestion_time = (
            datetime.utcnow().isoformat()
        )  # When we recorded this (always now)
        valid_from_time = (
            event_time or ingestion_time
        )  # When the fact became true (note's date or now)

        # Step 1: Invalidate any CONTRADICTING relationships
        contradicting_types = get_contradicting_types(relationship_type)
        invalidated_relationships = []

        for contra_type in contradicting_types:
            invalidate_query = f"""
            MATCH (source:{source_label} {{name: $source_name}})
            MATCH (target:{target_label} {{name: $target_name}})
            MATCH (source)-[r:{contra_type}]->(target)
            WHERE r.is_active = true
            SET r.is_active = false,
                r.valid_to = $valid_from_time,
                r.invalidated_by = $relationship_type,
                r.invalidation_note_id = $note_id
            RETURN type(r) as invalidated_type
            """
            result = self.execute_query(
                invalidate_query,
                {
                    "source_name": source_name,
                    "target_name": target_name,
                    "valid_from_time": valid_from_time,
                    "relationship_type": relationship_type,
                    "note_id": note_id,
                },
            )
            if result:
                for r in result:
                    if r.get("invalidated_type"):
                        invalidated_relationships.append(r["invalidated_type"])
                        logger.info(
                            f"[Bi-Temporal] Invalidated contradicting relationship: "
                            f"({source_name})-[{r['invalidated_type']}]->({target_name})"
                        )

        # Step 2: Check if this exact relationship already exists (active)
        check_query = f"""
        MATCH (source:{source_label} {{name: $source_name}})
        MATCH (target:{target_label} {{name: $target_name}})
        OPTIONAL MATCH (source)-[r]->(target)
        WHERE r.is_active = true OR r.is_active IS NULL
        RETURN r, type(r) as current_type
        """

        existing = self.execute_query(
            check_query,
            {"source_name": source_name, "target_name": target_name},
        )

        action = "created"
        previous_type = None

        if existing and existing[0].get("r"):
            # Relationship exists
            current_type = existing[0]["current_type"]

            if current_type == relationship_type:
                # Same type - reinforce it (increase mention count, update confidence)
                action = "reinforced"
                update_query = f"""
                MATCH (source:{source_label} {{name: $source_name}})
                MATCH (target:{target_label} {{name: $target_name}})
                MATCH (source)-[r:{relationship_type}]->(target)
                WHERE r.is_active = true OR r.is_active IS NULL
                SET r.last_updated = $ingestion_time,
                    r.mention_count = coalesce(r.mention_count, 0) + 1,
                    r.confidence = CASE 
                        WHEN $confidence > coalesce(r.confidence, 0) THEN $confidence
                        ELSE r.confidence
                    END,
                    r.context = $context,
                    r.is_active = true
                RETURN r
                """
                self.execute_query(
                    update_query,
                    {
                        "source_name": source_name,
                        "target_name": target_name,
                        "confidence": confidence,
                        "context": context,
                        "ingestion_time": ingestion_time,
                    },
                )
            elif can_evolve(current_type, relationship_type):
                # Relationship EVOLUTION - soft invalidate old, create new
                action = "evolved"
                previous_type = current_type

                # Soft invalidate old relationship (preserve history)
                invalidate_old = f"""
                MATCH (source:{source_label} {{name: $source_name}})
                MATCH (target:{target_label} {{name: $target_name}})
                MATCH (source)-[old:{current_type}]->(target)
                WHERE old.is_active = true OR old.is_active IS NULL
                SET old.is_active = false,
                    old.valid_to = $valid_from_time,
                    old.evolved_to = $new_type,
                    old.evolution_note_id = $note_id
                """
                self.execute_query(
                    invalidate_old,
                    {
                        "source_name": source_name,
                        "target_name": target_name,
                        "valid_from_time": valid_from_time,
                        "new_type": relationship_type,
                        "note_id": note_id,
                    },
                )

                # Create new evolved relationship
                create_query = f"""
                MATCH (source:{source_label} {{name: $source_name}})
                MATCH (target:{target_label} {{name: $target_name}})
                CREATE (source)-[r:{relationship_type}]->(target)
                SET r.confidence = $confidence,
                    r.valid_from = $valid_from_time,
                    r.ingested_at = $ingestion_time,
                    r.last_updated = $ingestion_time,
                    r.evolved_from = $previous_type,
                    r.mention_count = 1,
                    r.context = $context,
                    r.is_active = true,
                    r.note_id = $note_id
                RETURN r
                """
                self.execute_query(
                    create_query,
                    {
                        "source_name": source_name,
                        "target_name": target_name,
                        "confidence": confidence,
                        "context": context,
                        "valid_from_time": valid_from_time,
                        "ingestion_time": ingestion_time,
                        "previous_type": previous_type,
                        "note_id": note_id,
                    },
                )

                logger.info(
                    f"[Bi-Temporal] Evolved: ({source_name})-[{previous_type}→{relationship_type}]->({target_name})"
                )
            else:
                # Can't evolve - keep existing
                logger.warning(
                    f"Cannot evolve relationship {current_type} to {relationship_type}"
                )
                return {
                    "action": "rejected",
                    "reason": f"Cannot evolve {current_type} to {relationship_type}",
                    "source": source_name,
                    "target": target_name,
                }
        else:
            # Create NEW relationship with bi-temporal fields
            create_query = f"""
            MERGE (source:{source_label} {{name: $source_name}})
            MERGE (target:{target_label} {{name: $target_name}})
            CREATE (source)-[r:{relationship_type}]->(target)
            SET r.confidence = $confidence,
                r.valid_from = $valid_from_time,
                r.ingested_at = $ingestion_time,
                r.last_updated = $ingestion_time,
                r.mention_count = 1,
                r.context = $context,
                r.is_active = true,
                r.note_id = $note_id
            RETURN r
            """
            self.execute_query(
                create_query,
                {
                    "source_name": source_name,
                    "target_name": target_name,
                    "confidence": confidence,
                    "context": context,
                    "valid_from_time": valid_from_time,
                    "ingestion_time": ingestion_time,
                    "note_id": note_id,
                },
            )

        # Handle bidirectional relationships
        if is_bidirectional(relationship_type):
            # Create inverse relationship automatically
            self._create_inverse_relationship(
                target_name,
                target_label,
                source_name,
                source_label,
                relationship_type,
                confidence,
                context,
                note_id,
                valid_from_time,
                ingestion_time,
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
            "previous_type": previous_type,
        }

    def _create_inverse_relationship(
        self,
        source_name: str,
        source_label: str,
        target_name: str,
        target_label: str,
        relationship_type: str,
        confidence: float,
        context: str,
        note_id: str,
        valid_from_time: str,
        ingestion_time: str,
    ):
        """Helper to create inverse relationship for bidirectional types"""
        query = f"""
        MERGE (source:{source_label} {{name: $source_name}})
        MERGE (target:{target_label} {{name: $target_name}})
        MERGE (source)-[r:{relationship_type}]->(target)
        SET r.confidence = $confidence,
            r.valid_from = coalesce(r.valid_from, $valid_from_time),
            r.ingested_at = coalesce(r.ingested_at, $ingestion_time),
            r.last_updated = $ingestion_time,
            r.mention_count = coalesce(r.mention_count, 0) + 1,
            r.context = $context,
            r.is_active = true,
            r.note_id = $note_id
        RETURN r
        """

        self.execute_query(
            query,
            {
                "source_name": source_name,
                "target_name": target_name,
                "confidence": confidence,
                "context": context,
                "valid_from_time": valid_from_time,
                "ingestion_time": ingestion_time,
                "note_id": note_id,
            },
        )

    def get_node_relationships(
        self,
        node_name: str,
        node_label: str = None,
        relationship_types: list[str] = None,
        direction: str = "both",  # "outgoing", "incoming", "both"
        min_confidence: float = 0.0,
    ) -> list[dict]:
        """
        Get all relationships for a node

        Args:
            node_name: Name of the node
            node_label: Optional label filter (Person, Task, etc.)
            relationship_types: Optional list of relationship types to filter
            direction: "outgoing", "incoming", or "both"
            min_confidence: Minimum confidence threshold

        Returns:
            List of relationship dicts with source, target, type, properties
        """
        label_filter = f":{node_label}" if node_label else ""

        if direction == "outgoing":
            match_pattern = f"(node{label_filter} {{name: $node_name}})-[r]->(target)"
        elif direction == "incoming":
            match_pattern = f"(source)-[r]->(node{label_filter} {{name: $node_name}})"
        else:  # both
            match_pattern = f"(node{label_filter} {{name: $node_name}})-[r]-(other)"

        type_filter = ""
        if relationship_types:
            type_filter = "AND type(r) IN $relationship_types"

        query = f"""
        MATCH {match_pattern}
        WHERE r.is_active = true 
          AND coalesce(r.confidence, 0) >= $min_confidence
          {type_filter}
        RETURN 
            CASE 
                WHEN startNode(r) = node THEN node.name 
                ELSE startNode(r).name 
            END as source_name,
            labels(startNode(r))[0] as source_label,
            CASE 
                WHEN endNode(r) = node THEN node.name 
                ELSE endNode(r).name 
            END as target_name,
            labels(endNode(r))[0] as target_label,
            type(r) as relationship_type,
            r.confidence as confidence,
            r.first_seen as first_seen,
            r.last_updated as last_updated,
            r.mention_count as mention_count,
            r.context as context
        """

        params = {
            "node_name": node_name,
            "min_confidence": min_confidence,
        }
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
        Get nodes related to a given node up to max_depth hops away

        Args:
            node_name: Name of the starting node
            node_label: Optional label of the starting node
            max_depth: Maximum graph traversal depth (1-3 recommended)
            relationship_types: Optional filter for relationship types
            min_confidence: Minimum confidence threshold

        Returns:
            List of related nodes with their relationship paths
        """
        label_filter = f":{node_label}" if node_label else ""
        type_filter = ""
        if relationship_types:
            type_filter = f":{('|').join(relationship_types)}"

        query = f"""
        MATCH path = (start{label_filter} {{name: $node_name}})-[r{type_filter}*1..{max_depth}]-(related)
        WHERE all(rel in relationships(path) WHERE 
            rel.is_active = true AND 
            coalesce(rel.confidence, 0) >= $min_confidence
        )
        WITH related, relationships(path) as rels, length(path) as depth
        RETURN DISTINCT
            related.name as name,
            labels(related)[0] as label,
            related.summary as summary,
            related.description as description,
            depth,
            [rel in rels | type(rel)] as relationship_path,
            [rel in rels | rel.confidence] as confidence_path,
            [rel in rels | rel.context] as context_path
        ORDER BY depth, related.name
        """

        return self.execute_query(
            query,
            {
                "node_name": node_name,
                "min_confidence": min_confidence,
            },
        )

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

        query = f"""
        MATCH (source{source_filter} {{name: $source_name}})-[r]-(target{target_filter} {{name: $target_name}})
        RETURN 
            type(r) as relationship_type,
            r.valid_from as valid_from,
            r.valid_to as valid_to,
            r.is_active as is_active,
            r.evolved_from as evolved_from,
            r.evolved_to as evolved_to,
            r.invalidated_by as invalidated_by,
            r.confidence as confidence,
            r.context as context,
            r.note_id as note_id
        ORDER BY coalesce(r.valid_from, r.ingested_at, '1970-01-01') ASC
        """

        return self.execute_query(
            query, {"source_name": source_name, "target_name": target_name}
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
        ORDER BY c.domain, count(member) DESC
        """
        return self.execute_query(query, {})

    def assign_node_to_community(self, node_name: str, community_name: str) -> bool:
        """
        Add a node to a community.

        Args:
            node_name: Name of the node to add
            community_name: Name of the community

        Returns:
            True if successful
        """
        query = """
        MATCH (c:Community {name: $community_name})
        MATCH (n:Indexable {name: $node_name})
        MERGE (c)-[:CONTAINS]->(n)
        RETURN c.name as community
        """
        results = self.execute_query(
            query, {"community_name": community_name, "node_name": node_name}
        )
        return len(results) > 0

    def update_community_summary(
        self, community_name: str, summary: str, themes: list[str] = None
    ):
        """
        Update a community's summary (typically called after new nodes are added).

        Args:
            community_name: Name of the community
            summary: New high-level summary
            themes: Updated list of key themes
        """
        from datetime import datetime

        query = """
        MATCH (c:Community {name: $community_name})
        SET c.summary = $summary,
            c.themes = $themes,
            c.updated_at = $current_time
        RETURN c.name as name
        """
        self.execute_query(
            query,
            {
                "community_name": community_name,
                "summary": summary,
                "themes": themes or [],
                "current_time": datetime.utcnow().isoformat(),
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
        MATCH (note:Note)-[r]-(member)
        WHERE r.is_active = true
        WITH comm_name, note, member
        ORDER BY note.created_at DESC
        WITH comm_name, collect(DISTINCT {
            id: toString(id(note)),
            title: note.title
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


graph_service = GraphService()
