"""
reset_elasticsearch.py — Delete and recreate the liveos_nodes ES index.

Drops the index (clearing all documents) then recreates it with the correct
field mappings for the current architecture.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elasticsearch import Elasticsearch

from app.core.config import settings


def reset_elasticsearch() -> None:
    print("🗑️  Resetting Elasticsearch index...")
    es = Elasticsearch(
        f"http://{settings.ELASTICSEARCH_HOST}:{settings.ELASTICSEARCH_PORT}"
    )
    index_name = settings.ELASTICSEARCH_INDEX_NAME

    if es.indices.exists(index=index_name):
        es.indices.delete(index=index_name)
        print(f"   🗑️  Deleted index '{index_name}'.")

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

    doc_count = es.count(index=index_name)["count"]
    assert doc_count == 0, f"Index '{index_name}' has {doc_count} docs after recreation"
    print(f"   ✅ Recreated index '{index_name}' (0 documents).")
    print("✅ Elasticsearch reset complete.")


if __name__ == "__main__":
    reset_elasticsearch()
