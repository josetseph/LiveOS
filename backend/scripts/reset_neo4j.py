"""
reset_neo4j.py — Wipe all Neo4j data and recreate constraints.

Deletes every node and relationship, then re-applies the constraints
required by the current architecture (Indexable + Community).
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.graph import graph_service


def reset_neo4j() -> None:
    print("🗑️  Wiping Neo4j (all nodes + relationships)...")
    if not graph_service.verify_connection():
        raise RuntimeError("Cannot connect to Neo4j")

    graph_service.execute_query("MATCH (n) DETACH DELETE n")
    count = graph_service.execute_query("MATCH (n) RETURN count(n) AS c")[0]["c"]
    assert count == 0, f"Neo4j still has {count} nodes after wipe"
    print("   ✅ All nodes and relationships deleted.")

    # Drop legacy indexes/constraints that may exist from prior architecture
    for stmt in [
        "DROP CONSTRAINT note_id_unique IF EXISTS",
        "DROP CONSTRAINT entity_name_unique IF EXISTS",
        "DROP CONSTRAINT concept_name_unique IF EXISTS",
        "DROP INDEX note_vector_index IF EXISTS",
        "DROP INDEX distilled_knowledge_index IF EXISTS",
    ]:
        graph_service.execute_query(stmt)

    # Re-apply current architecture constraints
    graph_service.execute_query(
        "CREATE CONSTRAINT indexable_id_unique IF NOT EXISTS "
        "FOR (n:Indexable) REQUIRE n.id IS UNIQUE"
    )
    graph_service.execute_query(
        "CREATE CONSTRAINT community_id_unique IF NOT EXISTS "
        "FOR (n:Community) REQUIRE n.id IS UNIQUE"
    )
    print("   ✅ Neo4j constraints re-applied.")
    print("✅ Neo4j reset complete.")


if __name__ == "__main__":
    reset_neo4j()
