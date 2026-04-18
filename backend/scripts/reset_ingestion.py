"""
reset_ingestion.py — Reset all ingestion-related stores: Neo4j, Qdrant, Elasticsearch.

PostgreSQL (raw notes) and MinIO (file attachments) are left untouched.
This is the primary reset operation when you want to re-index existing notes
from scratch without losing the source content.

Usage:
    python scripts/reset_ingestion.py
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reset_neo4j import reset_neo4j
from reset_qdrant import reset_qdrant
from reset_elasticsearch import reset_elasticsearch


def reset_ingestion() -> None:
    print("\n🧹 INGESTION RESET — Neo4j · Qdrant · Elasticsearch\n")
    reset_neo4j()
    print()
    reset_qdrant()
    print()
    reset_elasticsearch()
    print("\n✨ Ingestion reset complete. PostgreSQL and MinIO untouched.\n")


if __name__ == "__main__":
    reset_ingestion()
