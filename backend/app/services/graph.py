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
        OPTIONAL MATCH (n)-[r1:MENTIONS]->(e:Entity) WHERE r1.status = 'active'
        OPTIONAL MATCH (n)-[r2:CONTRIBUTES_TO]->(c:Concept) WHERE r2.status = 'active'
        OPTIONAL MATCH (n)-[r3:PRODUCES_TASK]->(t:Task) WHERE r3.status = 'active'
        OPTIONAL MATCH (p:Persona)-[r4:REVEALED_BY]->(n) WHERE r4.status = 'active'
        RETURN n.id as note_id, 
               collect(distinct {name: e.name, type: e.type}) as entities,
               collect(distinct {name: c.name, summary: c.summary}) as concepts,
               collect(distinct {description: t.description, status: t.status}) as tasks,
               collect(distinct {trait: p.trait, quote: r4.quote}) as persona_traits
        """
        return self.execute_query(query, {"note_ids": note_ids})

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
             WHERE r.status = "active"
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
            WHERE r.status = 'active' AND any(label IN labels(n) WHERE label IN $all_labels)
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
        MATCH (n:Indexable {name: node_name})
        MATCH (note:Note)-[r]-(n)
        WHERE r.status = 'active' 
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
        # Get all knowledge nodes
        nodes_query = """
        MATCH (n)
        WHERE n:Concept OR n:Entity OR n:Task OR n:Persona OR n:Reference OR n:Note
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

        # Get all relationships
        links_query = """
        MATCH (source)-[r]->(target)
        WHERE (source:Concept OR source:Entity OR source:Task OR source:Persona OR source:Reference OR source:Note)
          AND (target:Concept OR target:Entity OR target:Task OR target:Persona OR target:Reference OR target:Note)
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
                    in ["Concept", "Entity", "Task", "Persona", "Reference", "Note"]
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
    ) -> dict:
        """
        Create or update a relationship between two nodes with evolution support

        Args:
            source_name: Name of the source node
            source_label: Label of the source node (Person, Task, Entity, Concept, Event)
            target_name: Name of the target node
            target_label: Label of the target node
            relationship_type: Type of relationship (from RelationshipType enum)
            confidence: Confidence score (0.0-1.0)
            context: Sample text showing the relationship
            note_id: ID of the note where this relationship was mentioned

        Returns:
            Dict with relationship info and whether it was created/updated/evolved
        """
        from datetime import datetime
        from app.schemas.relationships import can_evolve, is_bidirectional

        current_time = datetime.utcnow().isoformat()

        # Check if relationship already exists
        check_query = """
        MATCH (source:$source_label {name: $source_name})
        MATCH (target:$target_label {name: $target_name})
        OPTIONAL MATCH (source)-[r]->(target)
        RETURN r, type(r) as current_type
        """

        existing = self.execute_query(
            check_query.replace("$source_label", source_label).replace(
                "$target_label", target_label
            ),
            {"source_name": source_name, "target_name": target_name},
        )

        action = "created"
        previous_type = None

        if existing and existing[0].get("r"):
            # Relationship exists
            current_type = existing[0]["current_type"]

            if current_type == relationship_type:
                # Same type, just update properties
                action = "updated"
                update_query = f"""
                MATCH (source:{source_label} {{name: $source_name}})
                MATCH (target:{target_label} {{name: $target_name}})
                MATCH (source)-[r:{relationship_type}]->(target)
                SET r.last_updated = $current_time,
                    r.mention_count = coalesce(r.mention_count, 0) + 1,
                    r.confidence = CASE 
                        WHEN $confidence > coalesce(r.confidence, 0) THEN $confidence
                        ELSE r.confidence
                    END,
                    r.context = $context
                RETURN r
                """
            elif can_evolve(current_type, relationship_type):
                # Relationship can evolve
                action = "evolved"
                previous_type = current_type

                # Delete old relationship and create new one with history
                update_query = f"""
                MATCH (source:{source_label} {{name: $source_name}})
                MATCH (target:{target_label} {{name: $target_name}})
                MATCH (source)-[old]->(target)
                DELETE old
                CREATE (source)-[r:{relationship_type}]->(target)
                SET r.confidence = $confidence,
                    r.first_seen = $current_time,
                    r.last_updated = $current_time,
                    r.relationship_changed = $current_time,
                    r.previous_type = $previous_type,
                    r.mention_count = 1,
                    r.context = $context,
                    r.is_active = true,
                    r.note_id = $note_id
                RETURN r
                """
            else:
                # Can't evolve, keep existing
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
            # Create new relationship
            update_query = f"""
            MERGE (source:{source_label} {{name: $source_name}})
            MERGE (target:{target_label} {{name: $target_name}})
            CREATE (source)-[r:{relationship_type}]->(target)
            SET r.confidence = $confidence,
                r.first_seen = $current_time,
                r.last_updated = $current_time,
                r.mention_count = 1,
                r.context = $context,
                r.is_active = true,
                r.note_id = $note_id
            RETURN r
            """

        self.execute_query(
            update_query,
            {
                "source_name": source_name,
                "target_name": target_name,
                "confidence": confidence,
                "context": context,
                "current_time": current_time,
                "previous_type": previous_type,
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
                current_time,
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
        current_time: str,
    ):
        """Helper to create inverse relationship for bidirectional types"""
        query = f"""
        MERGE (source:{source_label} {{name: $source_name}})
        MERGE (target:{target_label} {{name: $target_name}})
        MERGE (source)-[r:{relationship_type}]->(target)
        SET r.confidence = $confidence,
            r.first_seen = coalesce(r.first_seen, $current_time),
            r.last_updated = $current_time,
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
                "current_time": current_time,
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
            [rel in rels | rel.confidence] as confidence_path
        ORDER BY depth, related.name
        """

        return self.execute_query(
            query,
            {
                "node_name": node_name,
                "min_confidence": min_confidence,
            },
        )


graph_service = GraphService()
