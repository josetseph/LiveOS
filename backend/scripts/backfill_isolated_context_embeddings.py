"""
Backfill script to generate embeddings for isolated contexts in already-ingested entities/concepts.

This enables true isolated-context-based retrieval where search uses embeddings
from raw contexts rather than LLM-generated summaries.

Usage:
    python scripts/backfill_isolated_context_embeddings.py [--batch-size 50] [--dry-run]
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.graph import graph_service
from app.services.embedding import embedding_service
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def get_nodes_with_isolated_contexts():
    """
    Fetch all Entity and Concept nodes that have isolated_contexts but no isolated_context_embeddings_json.
    """
    query = """
    MATCH (n)
    WHERE (n:Entity OR n:Concept)
      AND n.isolated_contexts IS NOT NULL
      AND size(n.isolated_contexts) > 0
      AND n.isolated_context_embeddings_json IS NULL
    RETURN 
        n.name as name,
        labels(n)[0] as label,
        n.isolated_contexts as isolated_contexts,
        size(n.isolated_contexts) as num_contexts
    ORDER BY num_contexts DESC
    """

    return graph_service.execute_query(query)


async def generate_embeddings_for_node(node: dict) -> dict:
    """
    Generate embeddings for all isolated contexts of a node.
    Each context gets its own embedding for individual matching.

    Args:
        node: Dict with 'name', 'label', 'isolated_contexts'

    Returns:
        Dict with 'name', 'label', 'embeddings' (list of embeddings)
    """
    name = node["name"]
    label = node["label"]
    contexts = node["isolated_contexts"]

    if not contexts:
        logger.warning(f"  [Skip] {label}:{name} has no isolated contexts")
        return None

    # Generate embedding for each isolated context
    embeddings = []
    for i, context in enumerate(contexts):
        try:
            # Use entity/concept name as prefix for better semantic matching
            text_to_embed = f"{name}: {context}"
            embedding = embedding_service.embed_query(text_to_embed)
            embeddings.append(embedding)
        except Exception as e:
            logger.error(
                f"  [Error] Failed to embed context {i} for {label}:{name}: {e}"
            )
            return None

    return {
        "name": name,
        "label": label,
        "embeddings": embeddings,
        "num_contexts": len(contexts),
    }


async def update_node_embeddings(node_data: dict, dry_run: bool = False):
    """
    Update node with isolated_context_embeddings property.
    Store as JSON string since Neo4j doesn't support nested arrays.

    Args:
        node_data: Dict with 'name', 'label', 'embeddings'
        dry_run: If True, log what would be updated but don't execute
    """
    import json

    name = node_data["name"]
    label = node_data["label"]
    embeddings = node_data["embeddings"]

    if dry_run:
        logger.info(
            f"  [DRY RUN] Would update {label}:{name} with {len(embeddings)} embeddings"
        )
        return

    # Convert embeddings to JSON string (Neo4j doesn't support nested arrays)
    embeddings_json = json.dumps(embeddings)

    query = f"""
    MATCH (n:{label} {{name: $name}})
    SET n.isolated_context_embeddings_json = $embeddings_json,
        n.isolated_context_count = $count
    RETURN n.name as name
    """

    try:
        result = graph_service.execute_query(
            query,
            {
                "name": name,
                "embeddings_json": embeddings_json,
                "count": len(embeddings),
            },
        )
        if result:
            logger.info(
                f"  [✓] Updated {label}:{name} with {len(embeddings)} individual context embeddings (JSON)"
            )
        else:
            logger.warning(f"  [!] Node not found: {label}:{name}")
    except Exception as e:
        logger.error(f"  [✗] Failed to update {label}:{name}: {e}")


async def backfill_all(batch_size: int = 50, dry_run: bool = False):
    """
    Backfill embeddings for all nodes with isolated contexts.

    Args:
        batch_size: Number of nodes to process in parallel
        dry_run: If True, don't actually update the database
    """
    logger.info("=" * 80)
    logger.info("BACKFILL: Isolated Context Embeddings")
    logger.info("=" * 80)

    # Fetch all nodes that need embeddings
    logger.info("\n[1] Fetching nodes with isolated_contexts...")
    nodes = await get_nodes_with_isolated_contexts()

    if not nodes:
        logger.info("✓ No nodes need backfilling. All done!")
        return

    logger.info(f"✓ Found {len(nodes)} nodes to process")

    # Calculate total contexts
    total_contexts = sum(n["num_contexts"] for n in nodes)
    logger.info(f"  Total isolated contexts: {total_contexts}")

    # Group by label
    by_label = {}
    for node in nodes:
        label = node["label"]
        by_label[label] = by_label.get(label, 0) + 1

    for label, count in by_label.items():
        logger.info(f"  {label}: {count} nodes")

    if dry_run:
        logger.info("\n⚠️  DRY RUN MODE - No database changes will be made")

    # Process nodes in batches
    logger.info(f"\n[2] Processing nodes (batch_size={batch_size})...")

    success_count = 0
    error_count = 0

    with tqdm(total=len(nodes), desc="Backfilling embeddings") as pbar:
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i : i + batch_size]

            # Generate embeddings for batch (sequential to avoid rate limits)
            for node in batch:
                try:
                    node_data = await generate_embeddings_for_node(node)
                    if node_data:
                        await update_node_embeddings(node_data, dry_run=dry_run)
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(
                        f"  [Error] Failed to process {node['label']}:{node['name']}: {e}"
                    )
                    error_count += 1

                pbar.update(1)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("BACKFILL COMPLETE")
    logger.info("=" * 80)
    logger.info(f"✓ Successfully processed: {success_count} nodes")
    if error_count > 0:
        logger.info(f"✗ Errors: {error_count} nodes")
    logger.info(
        f"Total embeddings generated: {success_count * batch_size // len(nodes) if nodes else 0}"
    )

    if dry_run:
        logger.info("\n⚠️  This was a DRY RUN. Run without --dry-run to apply changes.")


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill embeddings for isolated contexts"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of nodes to process in parallel (default: 50)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be updated without making changes",
    )

    args = parser.parse_args()

    await backfill_all(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
