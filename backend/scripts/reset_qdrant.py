"""
reset_qdrant.py — Delete all Qdrant collections and recreate them empty.

This preserves the collection schema (vector size, distance metric) while
discarding every stored point.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def reset_qdrant() -> None:
    print("🗑️  Resetting Qdrant collections...")
    client = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=settings.QDRANT_API_KEY,
    )

    collections = [
        settings.QDRANT_COLLECTION_NODE_CORES,
        settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS,
        settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,
    ]

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
    reset_qdrant()
