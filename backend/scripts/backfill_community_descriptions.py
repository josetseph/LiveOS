#!/usr/bin/env python3
"""Backfill LLM descriptions for L1 and L0 communities.

L2 communities already have real AI-generated summaries.
L1 and L0 communities only have auto-generated placeholder text.

Strategy
--------
- L1 communities: roll up from the L2 child community summaries that share members.
- L0 communities: roll up from the L1 child community summaries (just generated).

Processing order: L1 first, then L0, so L0 can use the fresh L1 descriptions.

Run from the backend directory with the venv activated:

    python scripts/backfill_community_descriptions.py [--dry-run]

Options
-------
--dry-run   Print what would be done but do not write to Qdrant/ES.
--force     Regenerate even communities that already have a real description.
"""

import argparse
import logging
import os
import sys

# ── path setup ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from app.services.embedding import embedding_service

# ── imports ──────────────────────────────────────────────────────────────────
from app.services.graph import graph_service
from app.services.llm import llm_service
from app.services.qdrant_service import qdrant_service
from app.services.typesense_service import typesense_service

# ── helpers ──────────────────────────────────────────────────────────────────


def _is_placeholder(description: str | None) -> bool:
    """Return True if this description is the auto-generated placeholder."""
    if not description:
        return True
    desc = description.strip()
    return (
        desc.startswith("Community at level")
        or desc.startswith("Community L")
        or len(desc) < 30
    )


def _parse_name_summary(raw: str) -> tuple[str | None, str | None]:
    name: str | None = None
    summary_lines: list[str] = []
    in_summary = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("NAME:") and not in_summary:
            name = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("SUMMARY:"):
            in_summary = True
            first = stripped.split(":", 1)[1].strip()
            if first:
                summary_lines.append(first)
        elif in_summary:
            summary_lines.append(stripped)
    summary = " ".join(s for s in summary_lines if s) or None
    return name, summary


def build_rollup_summary(
    child_rows: list[dict],  # [{name, summary}, ...]
    community_level: int,
) -> tuple[str | None, str | None]:
    """Ask the LLM to synthesize a parent summary from child community summaries."""
    context = "\n".join(
        f"- {row['name']}: {row['summary']}"
        for row in child_rows
        if row.get("summary") and not _is_placeholder(row.get("summary"))
    )
    if not context:
        return None, None

    prompt = (
        "You are summarizing a high-level knowledge-graph community.\n\n"
        f"Community level: {community_level} (lower level = broader and more abstract)\n\n"
        f"The following are summaries of {len(child_rows)} sub-communities "
        "that together make up this parent community:\n\n"
        f"{context}\n\n"
        "Synthesize a unified description for this parent community:\n"
        "1. A short descriptive name (3-8 words) capturing the overarching theme\n"
        "2. A thorough summary covering the overarching themes, what connects all "
        "sub-communities, major patterns, and the big-picture significance. "
        "Write as many sentences as needed.\n\n"
        "Reply in EXACTLY this format:\n"
        "NAME: <name>\n"
        "SUMMARY: <summary>"
    )
    raw = llm_service.reason(prompt) or ""
    return _parse_name_summary(raw)


def get_child_community_rows(
    community_id: str,
    this_level: int,
    child_level: int,
    child_cache: dict[str, dict] | None = None,
) -> list[dict]:
    """Return [{name, summary}] for the child-level communities whose members overlap
    with this community.  child_cache lets callers inject pre-fetched descriptions
    (e.g. all L2 data pre-cached, or freshly-generated L1 data for L0 pass).
    """
    rows = graph_service.execute_query(
        """
        MATCH (n:Indexable)-[r1:MEMBER_OF]->(c:Community {id: $community_id})
        WHERE r1.level = $this_level
        MATCH (n)-[r2:MEMBER_OF]->(child:Community)
        WHERE r2.level = $child_level
        RETURN DISTINCT child.id AS child_id, child.name AS child_name
        """,
        {
            "community_id": community_id,
            "this_level": this_level,
            "child_level": child_level,
        },
    )

    if not rows:
        return []

    child_ids = [r["child_id"] for r in rows if r.get("child_id")]
    child_name_map = {r["child_id"]: r["child_name"] for r in rows if r.get("child_id")}

    result = []
    ids_to_fetch = []

    for cid in child_ids:
        if child_cache and cid in child_cache:
            data = child_cache[cid]
            result.append(
                {
                    "name": data.get("name") or child_name_map.get(cid, cid),
                    "summary": data.get("description", ""),
                }
            )
        else:
            ids_to_fetch.append(cid)

    # Batch-fetch any IDs not in cache
    if ids_to_fetch:
        content_map = qdrant_service.get_nodes_content_by_ids(ids_to_fetch)
        for cid in ids_to_fetch:
            data = content_map.get(cid, {})
            result.append(
                {
                    "name": data.get("name") or child_name_map.get(cid, cid),
                    "summary": data.get("description", ""),
                }
            )

    return result


def update_community(
    community_id: str,
    community_level: int,
    current_name: str,
    new_name: str | None,
    new_summary: str,
    dry_run: bool,
) -> None:
    """Write the updated description back to Qdrant and Typesense."""
    name = new_name or current_name or f"Community L{community_level}"

    if dry_run:
        logger.info(
            f"  [DRY RUN] Would update {community_id}: name='{name}' "
            f"summary={new_summary[:80]}..."
        )
        return

    try:
        description_vector = embedding_service.embed_documents([new_summary])[0]
        qdrant_service.upsert_node_core(
            node_id=community_id,
            name=name,
            node_type="community",
            description=new_summary,
            description_vector=description_vector,
            community_level=community_level,
        )
        typesense_service.index_node(
            node_id=community_id,
            name=name,
            node_type="community",
            community_level=community_level,
        )
        logger.info(f"  ✓ Updated {community_id[:40]}… → '{name[:50]}'")
    except Exception as exc:
        logger.error(f"  ✗ Failed to update {community_id}: {exc}")


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="No writes — preview only"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even communities that already have a real description",
    )
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("Community description backfill — L1 → L0")
    logger.info(f"  dry_run={args.dry_run}  force={args.force}")
    logger.info("=" * 70)

    # Fetch all community rows from Qdrant
    logger.info("Fetching all community payloads from Qdrant …")
    all_communities = qdrant_service.list_all_community_payloads()
    logger.info(f"Found {len(all_communities)} community records in Qdrant")

    by_level: dict[int, list[dict]] = {}
    for c in all_communities:
        lvl = c.get("community_level")
        if lvl is not None:
            by_level.setdefault(lvl, []).append(c)

    for lvl, rows in sorted(by_level.items()):
        logger.info(f"  L{lvl}: {len(rows)} communities")

    # Pre-cache all L2 descriptions so child lookups don't need extra Qdrant calls
    l2_cache: dict[str, dict] = {
        c["community_id"]: {
            "name": c.get("name", ""),
            "description": c.get("description", ""),
        }
        for c in by_level.get(2, [])
        if c.get("community_id")
    }
    logger.info(f"Pre-cached {len(l2_cache)} L2 community descriptions")

    # --- PASS 1: L1 communities -------------------------------------------------
    l1_rows = by_level.get(1, [])
    l1_to_update = [
        c for c in l1_rows if args.force or _is_placeholder(c.get("description"))
    ]
    logger.info(
        f"\nL1: {len(l1_to_update)} / {len(l1_rows)} communities need new descriptions"
    )

    # freshly_generated maps community_id → {name, description} so L0 can use them
    freshly_generated: dict[str, dict] = {}

    for idx, community in enumerate(l1_to_update, 1):
        community_id = community.get("community_id") or community.get("node_id")
        if not community_id:
            continue

        current_name = community.get("name") or f"Community L1-{idx}"

        child_rows = get_child_community_rows(
            community_id=community_id,
            this_level=1,
            child_level=2,
            child_cache=l2_cache,
        )
        real_child_rows = [
            r for r in child_rows if not _is_placeholder(r.get("summary"))
        ]
        logger.info(
            f"  Found {len(child_rows)} L2 children, "
            f"{len(real_child_rows)} have real descriptions"
        )

        if not real_child_rows:
            logger.warning(f"  Skipping — no L2 children with real descriptions")
            continue

        new_name, new_summary = build_rollup_summary(real_child_rows, community_level=1)
        if not new_summary:
            logger.warning(f"  LLM returned empty summary — skipping")
            continue

        update_community(
            community_id=community_id,
            community_level=1,
            current_name=current_name,
            new_name=new_name,
            new_summary=new_summary,
            dry_run=args.dry_run,
        )

        # Cache for L0 pass
        freshly_generated[community_id] = {
            "name": new_name or current_name,
            "description": new_summary,
        }

    # --- PASS 2: L0 communities -------------------------------------------------
    l0_rows = by_level.get(0, [])
    l0_to_update = [
        c for c in l0_rows if args.force or _is_placeholder(c.get("description"))
    ]
    logger.info(
        f"\nL0: {len(l0_to_update)} / {len(l0_rows)} communities need new descriptions"
    )

    for idx, community in enumerate(l0_to_update, 1):
        community_id = community.get("community_id") or community.get("node_id")
        if not community_id:
            continue

        current_name = community.get("name") or f"Community L0-{idx}"
        logger.info(
            f"[L0 {idx}/{len(l0_to_update)}] {current_name} ({community_id[:30]}…)"
        )

        child_rows = get_child_community_rows(
            community_id=community_id,
            this_level=0,
            child_level=1,
            child_cache=freshly_generated,
        )
        real_child_rows = [
            r for r in child_rows if not _is_placeholder(r.get("summary"))
        ]
        logger.info(
            f"  Found {len(child_rows)} L1 children, "
            f"{len(real_child_rows)} have real descriptions"
        )

        if not real_child_rows:
            logger.warning(f"  Skipping — no L1 children with real descriptions")
            continue

        new_name, new_summary = build_rollup_summary(real_child_rows, community_level=0)
        if not new_summary:
            logger.warning(f"  LLM returned empty summary — skipping")
            continue

        update_community(
            community_id=community_id,
            community_level=0,
            current_name=current_name,
            new_name=new_name,
            new_summary=new_summary,
            dry_run=args.dry_run,
        )

    # ── summary ─────────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 70)
    logger.info(
        f"Done.  Processed {len(l1_to_update)} L1 + {len(l0_to_update)} L0 communities."
    )
    if args.dry_run:
        logger.info("DRY RUN — no data was written.")


if __name__ == "__main__":
    main()
