"""
reset_kuzu.py — Delete the embedded Kuzu graph database directory.

Removes the entire kuzu_graph data directory so the next startup of
GraphService will reinitialise a clean schema from scratch.

Usage:
    python scripts/reset_kuzu.py
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import REPO_ROOT, settings


def reset_kuzu() -> None:
    print("🗑️  Resetting Kuzu graph database...")
    configured_db_path = Path(settings.KUZU_DB_PATH).expanduser()
    if not configured_db_path.is_absolute():
        configured_db_path = REPO_ROOT / configured_db_path

    legacy_db_path = REPO_ROOT / "data" / "kuzu_graph"

    # Clear both current and legacy locations so startup migration cannot
    # repopulate a just-reset graph from leftover legacy files.
    candidate_paths = [configured_db_path, legacy_db_path]
    seen: set[str] = set()
    deleted_any = False

    def _delete_path(path: Path) -> bool:
        if not path.exists():
            return False
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True

    for db_path in candidate_paths:
        key = str(db_path.resolve())
        if key in seen:
            continue
        seen.add(key)

        deleted_db = _delete_path(db_path)
        wal_path = Path(f"{db_path}.wal")
        deleted_wal = _delete_path(wal_path)

        if deleted_db:
            print(f"   🗑️  Deleted Kuzu database at '{db_path}'.")
            deleted_any = True
        if deleted_wal:
            print(f"   🗑️  Deleted Kuzu WAL at '{wal_path}'.")
            deleted_any = True

    if not deleted_any:
        print("   ℹ️  No Kuzu database files found in configured or legacy paths.")

    print("✅ Kuzu reset complete. Schema will be recreated on next startup.")


if __name__ == "__main__":
    reset_kuzu()
