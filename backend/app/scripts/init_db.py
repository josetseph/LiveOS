"""Script to verify the database connection and initialise the Kuzu graph schema."""
import sys

from app.core.log import get_logger
from app.services.graph import graph_service

logger = get_logger("InitDB")


def init_db():
    """Verify the PostgreSQL connection and initialise all SQLAlchemy tables."""
    logger.info("Initializing Database...")
    if not graph_service.verify_connection():
        logger.error("Failed to connect to Kuzu graph database.")
        sys.exit(1)

    # Schema is created automatically by GraphService._init_schema() on startup.
    logger.info("Kuzu graph schema initialised.")


if __name__ == "__main__":
    init_db()
