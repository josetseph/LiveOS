"""
Central Logging Module for LiveOS

Handles configuration and retrieval of loggers.
Routes logs to specific files based on component name.
Respects global LOG_LEVEL from settings.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.core.config import settings

# Create logs directory
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Log formatters
file_formatter = logging.Formatter(
    fmt="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

console_formatter = logging.Formatter(fmt="%(levelname)s: %(message)s")

# Mapping of logger names to filenames
COMPONENT_LOG_FILES = {
    "IngestionPipeline": "ingestion.log",
    "RetrievalService": "retrieval.log",
    "GraphService": "graph.log",
    "LLMService": "llm.log",
    "AliasScript": "alias_detection.log",
    "AliasDetector": "alias_detection.log",
    "uvicorn.access": "api.log",
    "uvicorn.error": "api.log",
    "MultimediaService": "multimedia.log",
    "ChatWorkflow": "chat.log",
    "BucketStorage": "storage.log",
    "DatabaseService": "database.log",
    "ResetIndex": "system.log",
    "InitDB": "system.log",
    "Neo4jVerification": "tests.log",
    "RelationshipTest": "tests.log",
    "SummaryVerification": "tests.log",
}


def get_file_handler(filename: str, level: int) -> RotatingFileHandler:
    """Create a rotating file handler."""
    handler = RotatingFileHandler(
        LOGS_DIR / filename,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(file_formatter)
    return handler


def get_console_handler(level: int) -> logging.StreamHandler:
    """Create console handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(console_formatter)
    return handler


def setup_logging():
    """
    Initialize the logging configuration.
    Should be called once at application startup.
    """
    # Determine global log level
    log_level_str = settings.LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # Console output (always attached to root)
    root_logger.addHandler(get_console_handler(log_level))

    # Error file handler (catches ERROR+ from everywhere)
    error_handler = get_file_handler("errors.log", logging.ERROR)
    root_logger.addHandler(error_handler)

    # Configure component-specific loggers
    for logger_name, filename in COMPONENT_LOG_FILES.items():
        logger = logging.getLogger(logger_name)
        # Ensure component logger captures at least the global level
        logger.setLevel(log_level)

        # Avoid adding multiple handlers if called multiple times (though setup usually runs once)
        if not any(
            isinstance(h, RotatingFileHandler) and Path(h.baseFilename).name == filename
            for h in logger.handlers
        ):
            logger.addHandler(get_file_handler(filename, log_level))

        # Prevent propagation to root to avoid duplicate console/error logs
        # IF we want component logs strictly in their files + console.
        # But if we propagate, they go to root -> console AND root -> errors.log.
        # Usually, we WANT them in console.
        # If we stop propagation, we must add console handler to EACH component logger.
        # EASIER: Let them propagate, but the file handler is specific.
        # WAIT: The previous config had `propagate = False`.
        # If propagate is False, we need to add console handler here too if we want console output.
        logger.propagate = False
        logger.addHandler(get_console_handler(log_level))  # Add console to component
        logger.addHandler(
            error_handler
        )  # Ensure errors also go to errors.log via this logger

    # Third-party noise reduction
    calm_loggers = ["httpx", "httpcore", "neo4j", "asyncio", "urllib3", "multipart"]
    for name in calm_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.info(f"Logging initialized at level {log_level_str} | Logs dir: {LOGS_DIR}")
    print(f"✅ Logging initialized at level {log_level_str}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.
    Use defined component names to ensure routing to correct log files.
    """
    return logging.getLogger(name)
