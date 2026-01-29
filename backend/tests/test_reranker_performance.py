"""
Test script to compare Ollama reranker vs HuggingFace reranker
"""

import asyncio
import sys
import time

sys.path.append("/Users/joey/Projects/LiveOS/backend")

from app.services.retrieval import retrieval_service


async def test_retrieval():
    """Test retrieval with timing"""

    test_queries = [
        "What are my thoughts on livecops?",
        "Tell me about Votex365 and what has happened recently",
        "What tasks am I working on?",
        "Recent notes about development",
    ]

    print("=" * 80)
    print("RETRIEVAL PERFORMANCE TEST")
    print("=" * 80)

    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*80}")
        print(f"TEST {i}: {query}")
        print(f"{'='*80}\n")

        start_time = time.perf_counter()
        results = await retrieval_service.hybrid_search(query, top_k=10)
        total_time = time.perf_counter() - start_time

        print(f"\n✅ Query completed in {total_time:.2f}s")
        print(f"📊 Retrieved {len(results)} results")

        if results:
            print(f"\nTop 3 Results:")
            for j, result in enumerate(results[:3], 1):
                score = result.get("final_score", 0)
                text = result.get("text", "")[:100]
                print(f"  {j}. [Score: {score:.4f}] {text}...")

        print("\n" + "-" * 80)

        # Wait a bit between queries
        await asyncio.sleep(1)

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_retrieval())
