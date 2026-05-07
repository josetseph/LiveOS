"""Backfill script: strip entity name tokens from SEMANTIC_REL.rel_type.

LLMs at ingestion time often embed the object entity into the predicate,
e.g. "plays_corliss_archer" instead of "plays".  This script:

  1. Iterates all active SEMANTIC_REL edges in Kuzu.
  2. Applies the same `clean_rel_type()` logic used in ingestion.
  3. Updates rel_type in-place for any edge whose predicate changed.
  4. Updates the corresponding Qdrant node_relationships point's payload
     so the stored nl_sentence stays consistent (just the payload `rel_type`
     field if one exists — the natural_language sentence is left untouched
     because it was human-readable to begin with).

Run from the backend directory with the venv activated:

    python scripts/clean_relationship_predicates.py [--dry-run]
"""

import argparse
import re
import sys
from pathlib import Path

# Make the backend app importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.log import get_logger  # noqa: E402
from app.services.graph import graph_service  # noqa: E402
from app.services.qdrant_service import qdrant_service  # noqa: E402

logger = get_logger("BackfillPredicates")


# ---------------------------------------------------------------------------
# Predicate cleaner (identical logic to the one in ingestion.py)
# ---------------------------------------------------------------------------


def clean_rel_type(rel_type: str, source_name: str, target_name: str) -> str:
    """Remove entity name tokens from a relationship predicate."""
    if not rel_type:
        return rel_type

    entity_tokens: set[str] = set()
    for name in (source_name, target_name):
        for token in re.split(r"[\s_\-]+", name.lower()):
            if len(token) > 1:
                entity_tokens.add(token)

    if not entity_tokens:
        return rel_type

    parts = re.split(r"_", rel_type.lower())
    cleaned = [p for p in parts if p not in entity_tokens]
    if not cleaned:
        return "relates_to"
    return "_".join(cleaned)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing to any database.",
    )
    args = parser.parse_args()

    dry_run: bool = args.dry_run
    if dry_run:
        logger.info("DRY-RUN mode — no writes will be made.")

    # ------------------------------------------------------------------
    # 1. Fetch all active SEMANTIC_REL edges with source/target names
    # ------------------------------------------------------------------
    query = """
    MATCH (src:Node)-[r:SEMANTIC_REL]->(tgt:Node)
    WHERE r.is_active = true OR r.is_active IS NULL
    RETURN
        src.id    AS src_id,
        src.name  AS src_name,
        tgt.id    AS tgt_id,
        tgt.name  AS tgt_name,
        r.rel_type          AS rel_type,
        r.relationship_id   AS relationship_id
    """
    logger.info("Fetching all active SEMANTIC_REL edges from Kuzu …")
    rows = graph_service.execute_query(query, {})
    logger.info(f"  → {len(rows)} edges found.")

    # ------------------------------------------------------------------
    # 2. Identify edges whose predicates contain entity tokens
    # ------------------------------------------------------------------
    changes: list[dict] = []
    for row in rows:
        src_name = (row.get("src_name") or "").lower().strip()
        tgt_name = (row.get("tgt_name") or "").lower().strip()
        rel_type = (row.get("rel_type") or "").strip()
        if not rel_type or not src_name or not tgt_name:
            continue

        cleaned = clean_rel_type(rel_type, src_name, tgt_name)
        if cleaned != rel_type:
            changes.append(
                {
                    "src_id": row["src_id"],
                    "src_name": src_name,
                    "tgt_id": row["tgt_id"],
                    "tgt_name": tgt_name,
                    "old_rel_type": rel_type,
                    "new_rel_type": cleaned,
                    "relationship_id": row.get("relationship_id") or "",
                }
            )

    logger.info(f"  → {len(changes)} edges require predicate cleanup.")

    if not changes:
        logger.info("Nothing to do — all predicates are already clean.")
        return

    # ------------------------------------------------------------------
    # 3. Print / apply changes
    # ------------------------------------------------------------------
    update_query = """
    MATCH (src:Node {id: $src_id})-[r:SEMANTIC_REL]->(tgt:Node {id: $tgt_id})
    WHERE r.rel_type = $old_rel_type
      AND (r.is_active = true OR r.is_active IS NULL)
    SET r.rel_type = $new_rel_type
    """

    kuzu_updated = 0
    kuzu_failed = 0

    for c in changes:
        label = (
            f"'{c['src_name']}' --[{c['old_rel_type']}]--> '{c['tgt_name']}'"
            f" → --[{c['new_rel_type']}]-->"
        )
        logger.info(f"  {'[DRY] ' if dry_run else ''}Updating: {label}")

        if dry_run:
            continue

        try:
            graph_service.execute_query(
                update_query,
                {
                    "src_id": c["src_id"],
                    "tgt_id": c["tgt_id"],
                    "old_rel_type": c["old_rel_type"],
                    "new_rel_type": c["new_rel_type"],
                },
            )
            kuzu_updated += 1
        except Exception as exc:
            logger.error(f"  Kuzu update FAILED for {label}: {exc}")
            kuzu_failed += 1

    if not dry_run:
        logger.info(
            f"Kuzu: updated={kuzu_updated}, failed={kuzu_failed} "
            f"out of {len(changes)} targeted edges."
        )

    # ------------------------------------------------------------------
    # 4. Update Qdrant payload (rel_type field only — NL text unchanged)
    # ------------------------------------------------------------------
    # The Qdrant node_relationships points are keyed by a UUID5 derived from
    # relationship_id.  We only update the `rel_type` payload field if one
    # exists; the natural_language sentence is kept as-is because it already
    # reads naturally (e.g. "corliss archer played janet waldo").
    if not dry_run and qdrant_service.is_available():
        import uuid
        from qdrant_client.models import FieldCondition, Filter, MatchValue, MatchAny

        coll = settings.QDRANT_COLLECTION_NODE_RELATIONSHIPS
        qdrant_updated = 0
        qdrant_failed = 0

        for c in changes:
            if not c["relationship_id"]:
                continue
            point_id = str(uuid.uuid5(uuid.NAMESPACE_OID, c["relationship_id"]))
            try:
                qdrant_service.client.set_payload(
                    collection_name=coll,
                    payload={"rel_type": c["new_rel_type"]},
                    points=[point_id],
                )
                qdrant_updated += 1
            except Exception as exc:
                logger.debug(
                    f"  Qdrant payload update skipped/failed for {point_id}: {exc}"
                )
                qdrant_failed += 1

        logger.info(
            f"Qdrant: updated={qdrant_updated}, failed/skipped={qdrant_failed} "
            f"out of {len(changes)} targeted points."
        )

    logger.info("Done.")


if __name__ == "__main__":
    main()
