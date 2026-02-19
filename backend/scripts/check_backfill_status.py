#!/usr/bin/env python3
"""Check the status of isolated context embeddings backfill."""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.graph import graph_service
import json


async def main():
    # Check how many nodes have isolated context embeddings
    result = graph_service.execute_query(
        """
        MATCH (n)
        WHERE n.isolated_context_embeddings_json IS NOT NULL
        RETURN count(n) as with_embeddings
    """
    )
    print(f'Nodes with isolated context embeddings: {result[0]["with_embeddings"]}')

    # Check total nodes with isolated contexts
    result = graph_service.execute_query(
        """
        MATCH (n)
        WHERE n.isolated_contexts IS NOT NULL AND size(n.isolated_contexts) > 0
        RETURN count(n) as total_with_contexts
    """
    )
    print(f'Total nodes with isolated contexts: {result[0]["total_with_contexts"]}')

    # Sample a few nodes to verify format
    result = graph_service.execute_query(
        """
        MATCH (n)
        WHERE n.isolated_context_embeddings_json IS NOT NULL
        RETURN n.name as name, n.isolated_context_count as count
        ORDER BY n.name
        LIMIT 10
    """
    )
    print(f"\nSample nodes with embeddings:")
    for record in result:
        print(f'  - {record["name"]}: {record["count"]} contexts')

    # Test parsing one node's JSON
    result = graph_service.execute_query(
        """
        MATCH (n)
        WHERE n.isolated_context_embeddings_json IS NOT NULL
        RETURN n.name as name, 
               n.isolated_context_embeddings_json as json_data,
               n.isolated_contexts as contexts
        LIMIT 1
    """
    )
    if result:
        record = result[0]
        embeddings = json.loads(record["json_data"])
        print(f'\nTesting JSON parsing for "{record["name"]}":')
        print(f'  - Contexts: {len(record["contexts"])}')
        print(f"  - Embeddings: {len(embeddings)}")
        print(f"  - First embedding shape: {len(embeddings[0])} dimensions")
        print(f'  - Match: {len(record["contexts"]) == len(embeddings)}')


if __name__ == "__main__":
    asyncio.run(main())
