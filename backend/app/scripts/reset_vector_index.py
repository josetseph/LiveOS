"""
Reset Vector Index Script

Drops and recreates the Neo4j vector index with current EMBEDDING_DIMENSIONS from config.
This is the consolidated version - replaces both reset_index.py and reset_index_mrl.py
"""

from app.services.graph import graph_service
from app.core.config import settings
from app.core.logging_config import get_component_logger

logger = get_component_logger("ResetIndex")


def reset_index():
    """Drop and recreate vector index with current dimensions from config"""
    logger.info("Dropping existing vector index...")
    try:
        graph_service.execute_query("DROP INDEX note_vector_index IF EXISTS")
        logger.info("Index dropped successfully.")
    except Exception as e:
        logger.error(f"Error dropping index: {e}")

    logger.info(
        f"Creating Vector Index ({settings.EMBEDDING_DIMENSIONS} dimensions)..."
    )
    try:
        query_index = f"""
        CREATE VECTOR INDEX note_vector_index IF NOT EXISTS
        FOR (n:Note)
        ON (n.embedding)
        OPTIONS {{indexConfig: {{
         `vector.dimensions`: {settings.EMBEDDING_DIMENSIONS},
         `vector.similarity_function`: 'cosine'
        }}}}
        """
        graph_service.execute_query(query_index)
        logger.info(
            f"✅ Vector Index 'note_vector_index' created with {settings.EMBEDDING_DIMENSIONS} dims."
        )
    except Exception as e:
        logger.error(f"Error creating vector index: {e}")


if __name__ == "__main__":
    reset_index()
