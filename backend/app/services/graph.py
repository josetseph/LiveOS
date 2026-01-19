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
        self, vector: list[float], top_k: int = 5, min_score: float = 0.7
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


graph_service = GraphService()
