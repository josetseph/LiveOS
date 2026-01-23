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
            id(n) as id,
            n.name as name,
            labels(n) as labels,
            n.summary as summary,
            n.description as description,
            n.trait as trait,
            n.status as status,
            n.entity_type as entity_type,
            n.title as title,
            n.created_at as created_at
        """

        # Get all relationships
        links_query = """
        MATCH (source)-[r]->(target)
        WHERE (source:Concept OR source:Entity OR source:Task OR source:Persona OR source:Reference OR source:Note)
          AND (target:Concept OR target:Entity OR target:Task OR target:Persona OR target:Reference OR target:Note)
        RETURN 
            id(source) as source,
            id(target) as target,
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


graph_service = GraphService()
