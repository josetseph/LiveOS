"""
Standalone script: run a full Leiden community detection pass over all ingested data.

Usage (from backend/ with venv active):
    python scripts/run_community_detection.py
"""

import os
import sys

# Make sure the backend package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ENV", "development")

# Initialize logging before importing any app modules so file handlers are attached.
from app.core.log import setup_logging  # noqa: E402

setup_logging()

from app.workflows.ingestion import ingestion_workflow  # noqa: E402

if __name__ == "__main__":
    print("Starting full Leiden community detection run...")
    created = ingestion_workflow.rebuild_leiden_communities()
    print(f"Done. {created} community nodes created/rebuilt.")
