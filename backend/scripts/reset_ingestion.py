"""
reset_ingestion.py — Reset all ingestion-related stores: Kuzu, Qdrant, Typesense.

PostgreSQL (raw notes) and RustFS (file attachments) are left untouched.
Also deletes the KB registry so all named KBs are removed.

Usage:
    python scripts/reset_ingestion.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import REPO_ROOT
from reset_graph import reset_graph
from reset_vectors import reset_vectors
from reset_index import reset_index


def reset_ingestion() -> None:
    print("\n🧹 INGESTION RESET — Kuzu · Qdrant · Typesense · KBRegistry\n")
    reset_graph()
    print()
    reset_vectors()
    print()
    reset_index()
    print()

    registry_file = REPO_ROOT / "data" / "kb_registry.json"
    if registry_file.exists():
        registry_file.unlink()
        print("🗑️  Deleted KB registry (data/kb_registry.json).")
    else:
        print("ℹ️  No KB registry file found.")

    print("\n✨ Ingestion reset complete. PostgreSQL and RustFS untouched.\n")


if __name__ == "__main__":
    reset_ingestion()
