import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tenacity import retry, stop_after_attempt, wait_fixed
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.core.config import settings


@retry(stop=stop_after_attempt(10), wait=wait_fixed(2))
def init_qdrant() -> None:
    print("⏳ Initializing Qdrant collections...")
    client = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=settings.QDRANT_API_KEY,
    )

    existing = {c.name for c in client.get_collections().collections}
    collections = [
        settings.QDRANT_COLLECTION_NODE_CORES,
        settings.QDRANT_COLLECTION_NODE_FACTS,
        settings.QDRANT_COLLECTION_NODE_QUESTIONS,
        settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS,
        settings.QDRANT_COLLECTION_NODE_ISOLATED_CONTEXTS,
    ]

    for name in collections:
        if name in existing:
            print(f"✅ Qdrant collection '{name}' already exists.")
            continue
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=settings.EMBEDDING_DIMENSIONS,
                distance=Distance.COSINE,
            ),
        )
        print(f"✅ Created Qdrant collection '{name}'.")

    print("✅ Qdrant initialization complete.")


if __name__ == "__main__":
    init_qdrant()
