import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tenacity import retry, stop_after_attempt, wait_fixed

from app.services.graph import graph_service


@retry(stop=stop_after_attempt(10), wait=wait_fixed(2))
def init_neo4j() -> None:
    print("⏳ Waiting for Neo4j & Initializing...")

    if not graph_service.verify_connection():
        raise Exception("Cannot connect to Neo4j")

    print("✅ Neo4j is Ready.")

    # Cleanup legacy constraints/indexes from prior architecture
    print("🗑️  Cleaning up legacy Neo4j schema artifacts...")
    graph_service.execute_query("DROP CONSTRAINT note_id_unique IF EXISTS")
    graph_service.execute_query("DROP CONSTRAINT entity_name_unique IF EXISTS")
    graph_service.execute_query("DROP CONSTRAINT concept_name_unique IF EXISTS")
    graph_service.execute_query("DROP INDEX note_vector_index IF EXISTS")
    graph_service.execute_query("DROP INDEX distilled_knowledge_index IF EXISTS")

    # Constraints for structure-only graph (Qdrant/ES hold all vectors & content)
    print("🔄 Creating Neo4j constraints for structure-only graph...")
    graph_service.execute_query(
        "CREATE CONSTRAINT indexable_id_unique IF NOT EXISTS FOR (n:Indexable) REQUIRE n.id IS UNIQUE"
    )
    graph_service.execute_query(
        "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (n:Community) REQUIRE n.id IS UNIQUE"
    )
    print("✅ Neo4j constraints created.")


if __name__ == "__main__":
    init_neo4j()
