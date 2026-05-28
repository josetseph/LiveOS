"""
reset_ingestion.py — Reset all ingestion-related stores: Kuzu, Qdrant, Typesense.

PostgreSQL (raw notes), RustFS (file attachments), and the KB registry
(data/kb_registry.json) are left untouched so named knowledge bases are preserved.

Usage:
    python scripts/reset_ingestion.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reset_graph import reset_graph
from reset_vectors import reset_vectors
from reset_index import reset_index


def reset_ingestion() -> None:
    print("\n🧹 INGESTION RESET — Kuzu · Qdrant · Typesense\n")
    reset_graph()
    print()
    reset_vectors()
    print()
    reset_index()
    print()

    print(
        "\n✨ Ingestion reset complete. PostgreSQL, RustFS, and KB registry untouched."
    )
    print(
        "⚠️  If the backend is running in Docker, restart it to release stale Kuzu\n"
        "   file handles: docker compose restart backend\n"
    )


if __name__ == "__main__":
    reset_ingestion()
