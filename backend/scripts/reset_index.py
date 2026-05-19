"""
reset_index.py — Drop and recreate the Typesense liveos_nodes collection.

Clears all indexed documents then recreates the collection with the correct
schema for the current architecture.  Covers the default KB and all registered
per-KB collections (loaded from data/kb_registry.json).

Usage:
    python scripts/reset_typesense.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import REPO_ROOT
from app.services.typesense_service import typesense_service


def _all_kb_typesense_collections() -> list[str]:
    """Return all Typesense collection names: default + per-KB from registry."""
    cols: list[str] = [typesense_service.collection]
    registry_file = REPO_ROOT / "data" / "kb_registry.json"
    if registry_file.exists():
        try:
            with open(registry_file) as f:
                data = json.load(f)
            for kb in data.get("knowledge_bases", []):
                col = kb.get("typesense_collection")
                if col and col not in cols:
                    cols.append(col)
        except Exception:
            pass
    return cols


def reset_index() -> None:
    print("🗑️  Resetting Typesense collection(s)...")
    client = typesense_service.client

    for collection in _all_kb_typesense_collections():
        try:
            client.collections[collection].delete()
            print(f"   🗑️  Deleted collection '{collection}'.")
        except Exception:
            pass  # Collection may not exist yet

    # Recreate the default collection (per-KB collections are created on demand).
    typesense_service._ensure_collection()
    print(f"   ✅ Recreated collection '{typesense_service.collection}' (0 documents).")
    print("✅ Typesense reset complete.")


if __name__ == "__main__":
    reset_index()
