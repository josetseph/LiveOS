"""
reset_vectors.py — Delete all Qdrant collections and recreate them empty.

This preserves the collection schema (vector size, distance metric) while
discarding every stored point.  Covers the default KB and all registered
per-KB collections (loaded from data/kb_registry.json).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import REPO_ROOT, settings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def _all_kb_collections() -> list[str]:
    """Return all Qdrant collection names: default 3 + per-KB collections from registry."""
    cols: list[str] = [
        settings.QDRANT_COLLECTION_NODE_CORES,
        settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS,
        settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,
    ]
    registry_file = REPO_ROOT / "data" / "kb_registry.json"
    if registry_file.exists():
        try:
            with open(registry_file) as f:
                data = json.load(f)
            for kb in data.get("knowledge_bases", []):
                for key in (
                    "qdrant_col_cores",
                    "qdrant_col_rels",
                    "qdrant_col_contexts",
                ):
                    col = kb.get(key)
                    if col and col not in cols:
                        cols.append(col)
        except Exception:
            pass
    return cols


def reset_vectors() -> None:
    print("🗑️  Resetting Qdrant collections...")
    client = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=settings.QDRANT_API_KEY,
    )

    collections = _all_kb_collections()

    existing = {c.name for c in client.get_collections().collections}

    for name in collections:
        if name in existing:
            client.delete_collection(name)
            print(f"   🗑️  Deleted collection '{name}'.")
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=settings.EMBEDDING_DIMENSIONS,
                distance=Distance.COSINE,
            ),
        )
        count = client.get_collection(name).points_count
        assert count == 0, f"Collection '{name}' has {count} points after recreation"
        print(f"   ✅ Recreated collection '{name}' (0 points).")

    print("✅ Qdrant reset complete.")


if __name__ == "__main__":
    reset_vectors()
