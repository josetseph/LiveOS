"""
reset_index.py — Drop and recreate the Typesense liveos_nodes collection.

Clears all indexed documents then recreates the collection with the correct
schema for the current architecture.

Usage:
    python scripts/reset_typesense.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.typesense_service import typesense_service


def reset_index() -> None:
    print("🗑️  Resetting Typesense collection...")
    client = typesense_service.client
    collection = typesense_service.collection

    try:
        client.collections[collection].delete()
        print(f"   🗑️  Deleted collection '{collection}'.")
    except Exception:
        pass  # Collection may not exist yet

    typesense_service._ensure_collection()
    print(f"   ✅ Recreated collection '{collection}' (0 documents).")
    print("✅ Typesense reset complete.")


if __name__ == "__main__":
    reset_index()
