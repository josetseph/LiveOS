from app.services.graph import graph_service
from app.core.config import settings
from app.core.log import get_logger
import sys

logger = get_logger("InitDB")


def init_db():
    logger.info("Initializing Database...")
    if not graph_service.verify_connection():
        logger.error("Failed to connect to Neo4j. Is it running?")
        sys.exit(1)

    # 1. Constraints
    logger.info("Creating Constraints...")
    graph_service.execute_query(
        "CREATE CONSTRAINT note_id_unique IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE"
    )

    # 2. Vector Index
    logger.info("Cleaning up old Vector Index...")
    try:
        graph_service.execute_query("DROP INDEX note_vector_index IF EXISTS")
    except Exception as e:
        logger.warning(f"Could not drop index: {e}")

    logger.info(f"Creating {settings.EMBEDDING_DIMENSIONS}-dim Vector Index...")
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
        print(
            f"Vector Index 'note_vector_index' created/verified with {settings.EMBEDDING_DIMENSIONS} dims."
        )
    except Exception as e:
        print(f"Error creating vector index: {e}")


if __name__ == "__main__":
    init_db()
