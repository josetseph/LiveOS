"""
reset_all.py — Full system reset: all stores including PostgreSQL and RustFS.

Wipes every piece of data: graph (Kuzu), vectors (Qdrant), search index
(Typesense), raw notes (PostgreSQL), and file attachments (RustFS).
Also deletes the KB registry file so all named KBs are removed.

Use this when you want a completely clean slate.

Usage:
    python scripts/reset_all.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import REPO_ROOT
from reset_graph import reset_graph
from reset_storage import reset_storage
from reset_database import reset_database
from reset_vectors import reset_vectors
from reset_index import reset_index


def reset_all() -> None:
    print(
        "\n🧹 FULL SYSTEM RESET — Kuzu · Qdrant · Typesense · PostgreSQL · RustFS · KBRegistry\n"
    )
    reset_graph()
    print()
    reset_vectors()
    print()
    reset_index()
    print()
    reset_database()
    print()
    reset_storage()
    print()

    registry_file = REPO_ROOT / "data" / "kb_registry.json"
    if registry_file.exists():
        registry_file.unlink()
        print("🗑️  Deleted KB registry (data/kb_registry.json).")
    else:
        print("ℹ️  No KB registry file found.")

    print("\n✨ Full system reset complete. All data wiped.\n")


if __name__ == "__main__":
    reset_all()
