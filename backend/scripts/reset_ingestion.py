"""
reset_ingestion.py — Reset all ingestion-related stores: Kuzu, Qdrant, Typesense.

PostgreSQL (raw notes) and RustFS (file attachments) are left untouched.
This is the primary reset operation when you want to re-index existing notes
from scratch without losing the source content.

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
    print("\n✨ Ingestion reset complete. PostgreSQL and RustFS untouched.\n")


if __name__ == "__main__":
    reset_ingestion()
