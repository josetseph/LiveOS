"""
reset_ingestion.py — Reset all ingestion-related stores: Kuzu, Qdrant, Typesense.

PostgreSQL (raw notes) and MinIO (file attachments) are left untouched.
This is the primary reset operation when you want to re-index existing notes
from scratch without losing the source content.

Usage:
    python scripts/reset_ingestion.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reset_kuzu import reset_kuzu
from reset_qdrant import reset_qdrant
from reset_typesense import reset_typesense


def reset_ingestion() -> None:
    print("\n🧹 INGESTION RESET — Kuzu · Qdrant · Typesense\n")
    reset_kuzu()
    print()
    reset_qdrant()
    print()
    reset_typesense()
    print("\n✨ Ingestion reset complete. PostgreSQL and MinIO untouched.\n")


if __name__ == "__main__":
    reset_ingestion()
