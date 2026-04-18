"""
reset_all.py — Full system reset: all stores including PostgreSQL and MinIO.

Wipes every piece of data: graph (Neo4j), vectors (Qdrant), search index
(Elasticsearch), raw notes + feedback (PostgreSQL), and file attachments (MinIO).

Use this when you want a completely clean slate.

Usage:
    python scripts/reset_all.py
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reset_neo4j import reset_neo4j
from reset_qdrant import reset_qdrant
from reset_elasticsearch import reset_elasticsearch
from reset_postgres import reset_postgres
from reset_minio import reset_minio


def reset_all() -> None:
    print("\n🧹 FULL SYSTEM RESET — Neo4j · Qdrant · Elasticsearch · PostgreSQL · MinIO\n")
    reset_neo4j()
    print()
    reset_qdrant()
    print()
    reset_elasticsearch()
    print()
    reset_postgres()
    print()
    reset_minio()
    print("\n✨ Full system reset complete. All data wiped.\n")


if __name__ == "__main__":
    reset_all()
