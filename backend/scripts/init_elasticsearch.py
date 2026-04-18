import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from elasticsearch import (
    Elasticsearch,
    ConnectionError as ESConnectionError,
    TransportError,
)

from app.core.config import settings


@retry(
    stop=stop_after_attempt(10),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(
        (ESConnectionError, TransportError, ConnectionRefusedError, OSError)
    ),
)
def init_elasticsearch() -> None:
    print("⏳ Initializing Elasticsearch index...")
    es = Elasticsearch(
        f"http://{settings.ELASTICSEARCH_HOST}:{settings.ELASTICSEARCH_PORT}"
    )
    index_name = settings.ELASTICSEARCH_INDEX_NAME

    if es.indices.exists(index=index_name):
        print(f"✅ Elasticsearch index '{index_name}' already exists.")
        return

    mappings = {
        "properties": {
            "node_id": {"type": "keyword"},
            "community_id": {"type": "keyword"},
            "community_level": {"type": "integer"},
            "name": {"type": "text"},
            "description": {"type": "text"},
            "facts": {"type": "text"},
            "potential_questions": {"type": "text"},
            "isolated_contexts": {"type": "text"},
            "relationship_natural_language": {"type": "text"},
        }
    }
    es.indices.create(index=index_name, mappings=mappings)
    print(f"✅ Elasticsearch index '{index_name}' created.")


if __name__ == "__main__":
    init_elasticsearch()
