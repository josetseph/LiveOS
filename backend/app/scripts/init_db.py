from app.services.graph import graph_service
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
    graph_service.execute_query(
        "CREATE CONSTRAINT indexable_id_unique IF NOT EXISTS FOR (n:Indexable) REQUIRE n.id IS UNIQUE"
    )
    graph_service.execute_query(
        "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (n:Community) REQUIRE n.id IS UNIQUE"
    )
    logger.info("Neo4j initialised for structural-only graph storage.")


if __name__ == "__main__":
    init_db()
