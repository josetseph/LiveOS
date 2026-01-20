"""
Logging Configuration for LiveOS Backend

Sets up file-based logging with rotation for different components:
- ingestion.log: Ingestion pipeline operations
- retrieval.log: Search and retrieval operations
- graph.log: Neo4j graph operations
- llm.log: LLM service calls
- api.log: FastAPI request logs
- errors.log: All ERROR and CRITICAL level logs

Console output is limited to WARNING and above.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Create logs directory
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Log format
DETAILED_FORMAT = logging.Formatter(
    fmt="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

SIMPLE_FORMAT = logging.Formatter(fmt="%(levelname)s: %(message)s")


def get_file_handler(filename: str, level=logging.DEBUG) -> RotatingFileHandler:
    """Create a rotating file handler (max 10MB, keep 5 backups)"""
    handler = RotatingFileHandler(
        LOGS_DIR / filename,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(DETAILED_FORMAT)
    return handler


def get_console_handler(level=logging.WARNING) -> logging.StreamHandler:
    """Create console handler for warnings and errors only"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(SIMPLE_FORMAT)
    return handler


def setup_logging():
    """Configure logging for all components"""

    # Root logger - catches everything
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any existing handlers
    root_logger.handlers.clear()

    # Add console handler (WARNING+)
    root_logger.addHandler(get_console_handler(logging.WARNING))

    # Component-specific loggers
    loggers = {
        "IngestionPipeline": "ingestion.log",
        "RetrievalService": "retrieval.log",
        "GraphService": "graph.log",
        "LLMService": "llm.log",
        "uvicorn.access": "api.log",
        "uvicorn.error": "api.log",
        "ResetIndexTask": "system.log",
        "MultimediaService": "multimedia.log",
        "ChatWorkflow": "chat.log",
        "BucketStorage": "storage.log",
        "DatabaseService": "database.log",
    }

    for logger_name, log_file in loggers.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(get_file_handler(log_file))
        logger.propagate = False  # Don't duplicate to root

    # Errors log - all ERROR+ from all components
    error_handler = get_file_handler("errors.log", level=logging.ERROR)
    root_logger.addHandler(error_handler)

    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Startup message
    startup_msg = f"Logging initialized | Logs directory: {LOGS_DIR}"
    logging.info(startup_msg)
    print(f"✅ {startup_msg}")


def get_component_logger(component_name: str) -> logging.Logger:
    """Get a logger for a specific component"""
    return logging.getLogger(component_name)
