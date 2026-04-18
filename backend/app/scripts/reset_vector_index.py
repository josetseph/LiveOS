"""Legacy no-op kept for compatibility.

Neo4j vector indexes are no longer used. Qdrant is the vector store.
"""

from app.services.graph import graph_service
from app.core.log import get_logger

logger = get_logger("ResetIndex")


def reset_index():
    """Drop any leftover Neo4j vector index from the old architecture."""
    logger.info("Dropping legacy Neo4j vector index if it exists...")
    try:
        graph_service.execute_query("DROP INDEX note_vector_index IF EXISTS")
        graph_service.execute_query("DROP INDEX distilled_knowledge_index IF EXISTS")
        logger.info("Legacy Neo4j vector indexes removed successfully.")
    except Exception as e:
        logger.error(f"Error dropping legacy indexes: {e}")


if __name__ == "__main__":
    reset_index()
