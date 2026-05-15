"""
init_index.py — Ensure the Typesense collection exists and is ready.

TypesenseService._ensure_collection() handles creation automatically on first
use; this script just forces an eager initialisation so the CI/startup init
step can verify connectivity before the API starts accepting traffic.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.typesense_service import typesense_service
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


@retry(
    stop=stop_after_attempt(10),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(ConnectionError),
)
def init_index() -> None:
    print("⏳ Initializing Typesense collection...")
    if not typesense_service.is_available():
        raise ConnectionError("Typesense not reachable — retrying...")
    typesense_service._ensure_collection()
    print(f"✅ Typesense collection '{typesense_service.collection}' ready.")


if __name__ == "__main__":
    init_index()
