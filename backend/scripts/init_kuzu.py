"""
init_kuzu.py — Initialise the embedded Kuzu graph database.

Creates the database directory if it doesn't exist and triggers schema
creation by calling GraphService.verify_connection(), which runs
_init_schema() on first open.  Safe to re-run; all DDL statements use
IF NOT EXISTS so existing data is never touched.

Usage:
    python scripts/init_kuzu.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import REPO_ROOT, settings


def init_kuzu() -> None:
    print("⏳ Initializing Kuzu graph database...")

    db_path = Path(settings.KUZU_DB_PATH).expanduser()
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    db_path = str(db_path)

    # Kuzu (0.11+) stores its database as a single file. If an empty directory
    # was left by a prior failed run, remove it so Kuzu can create the file.
    if os.path.isdir(db_path) and not os.listdir(db_path):
        os.rmdir(db_path)

    # Import after the directory fix — graph_service is a module-level singleton
    # that calls kuzu.Database() at import time.
    from app.services.graph import graph_service  # noqa: PLC0415

    if not graph_service.verify_connection():
        print(f"❌ Failed to connect to Kuzu at '{db_path}'.")
        sys.exit(1)

    print(f"✅ Kuzu graph database ready at '{db_path}'.")


if __name__ == "__main__":
    init_kuzu()
