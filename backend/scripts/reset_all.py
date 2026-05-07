"""
reset_all.py — Full system reset: all stores including PostgreSQL and MinIO.

Wipes every piece of data: graph (Kuzu), vectors (Qdrant), search index
(Typesense), raw notes + feedback (PostgreSQL), and file attachments (MinIO).

Use this when you want a completely clean slate.

Usage:
    python scripts/reset_all.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reset_kuzu import reset_kuzu
from reset_minio import reset_minio
from reset_postgres import reset_postgres
from reset_qdrant import reset_qdrant
from reset_typesense import reset_typesense


def reset_all() -> None:
    print("\n🧹 FULL SYSTEM RESET — Kuzu · Qdrant · Typesense · PostgreSQL · MinIO\n")
    reset_kuzu()
    print()
    reset_qdrant()
    print()
    reset_typesense()
    print()
    reset_postgres()
    print()
    reset_minio()
    print("\n✨ Full system reset complete. All data wiped.\n")


if __name__ == "__main__":
    reset_all()
