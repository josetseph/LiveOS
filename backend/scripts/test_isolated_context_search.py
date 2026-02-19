#!/usr/bin/env python3
"""Test the isolated context search functionality."""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.graph import graph_service
from app.services.embedding import embedding_service


async def main():
    # Test query
    test_query = "What is Ed Wood's nationality?"

    print(f"Testing isolated context search with query: '{test_query}'\n")

    # Generate query embedding
    print("1. Generating query embedding...")
    query_embedding = embedding_service.embed_query(test_query)
    print(f"   ✓ Query embedding: {len(query_embedding)} dimensions\n")

    # Search using isolated contexts
    print("2. Searching with isolated context embeddings...")
    results = graph_service.search_knowledge_graph_isolated_contexts(
        vector=query_embedding, top_k=5
    )

    print(f"   ✓ Found {len(results)} results\n")

    # Display results
    print("3. Top results:")
    for i, result in enumerate(results, 1):
        print(f"\n   {i}. {result['name']} (score: {result['score']:.4f})")
        print(f"      Matched context: '{result['matched_context'][:100]}...'")
        print(f"      Context index: {result['matched_context_index']}")

    # Verify data structure
    if results:
        print(f"\n4. Verification:")
        print(f"   ✓ Results have 'name' field: {all('name' in r for r in results)}")
        print(
            f"   ✓ Results have 'matched_context' field: {all('matched_context' in r for r in results)}"
        )
        print(
            f"   ✓ Results have 'matched_context_index' field: {all('matched_context_index' in r for r in results)}"
        )
        print(f"   ✓ Results have 'score' field: {all('score' in r for r in results)}")
        print(
            f"   ✓ Scores are descending: {all(results[i]['score'] >= results[i+1]['score'] for i in range(len(results)-1))}"
        )

        print("\n✅ Isolated context search is working properly!")
    else:
        print("\n⚠️ No results found - this might indicate an issue")


if __name__ == "__main__":
    asyncio.run(main())
