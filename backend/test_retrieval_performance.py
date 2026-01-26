"""
Test script for retrieval and ranking performance.
Tests the hybrid_search pipeline without chat/synthesis.
"""

import sys

sys.path.insert(0, "/Users/joey/Projects/LiveOS/backend")

import asyncio
from datetime import datetime
from app.services.retrieval import retrieval_service


async def test_retrieval(query: str, test_number: int):
    """Test retrieval for a single query and display detailed results."""

    print("\n" + "=" * 80)
    print(f"TEST {test_number}: '{query}'")
    print("=" * 80)

    # Run retrieval
    start_time = datetime.now()
    results = await retrieval_service.hybrid_search(query, top_k=25)
    duration = (datetime.now() - start_time).total_seconds()

    print(f"\n⏱️  Retrieval Time: {duration:.2f}s")
    print(f"📊 Total Results: {len(results)}")

    if not results:
        print("\n❌ No results returned!")
        return

    # Analyze result distribution
    temporal_count = sum(
        1 for r in results if r.get("is_recent", False) and r.get("type") == "note"
    )
    graph_count = sum(1 for r in results if r.get("type") == "graph_consensus")
    evidence_count = sum(
        1 for r in results if not r.get("is_recent", False) and r.get("type") == "note"
    )

    print(f"\n📈 Result Breakdown:")
    print(f"   • Temporal (Recent Notes): {temporal_count}")
    print(f"   • Graph Nodes: {graph_count}")
    print(f"   • Evidence (Linked Notes): {evidence_count}")

    # Show top results in detail
    print(f"\n🔍 Top 10 Results:")
    print("-" * 80)

    for i, result in enumerate(results[:10], 1):
        result_type = result.get("type", "unknown")
        score = result.get("score", 0.0)
        is_recent = result.get("is_recent", False)
        text = result.get("text", "")

        # Format display
        type_label = (
            "📅 TEMPORAL"
            if is_recent and result_type == "note"
            else "🧠 GRAPH NODE" if result_type == "graph_consensus" else "🔗 EVIDENCE"
        )

        # Truncate text for display
        display_text = text[:150].replace("\n", " ").strip()
        if len(text) > 150:
            display_text += "..."

        # Additional metadata
        metadata = []
        if result_type == "note":
            title = result.get("title", "Untitled")
            created_at = result.get("created_at", "")
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                    metadata.append(f"Date: {date_str}")
                except:
                    pass
            metadata.append(f"Title: {title}")
        elif result_type == "graph_consensus":
            original = result.get("original_obj", {})
            labels = original.get("labels", ["Unknown"])
            name = original.get("name", "Unknown")
            metadata.append(f"Node: {labels[0]} - {name}")

        print(f"\n{i}. [{type_label}] Score: {score:.4f}")
        if metadata:
            print(f"   {' | '.join(metadata)}")
        print(f"   {display_text}")

    # Show score distribution
    print(f"\n📊 Score Distribution:")
    scores = [r.get("score", 0) for r in results]
    if scores:
        print(f"   • Highest: {max(scores):.4f}")
        print(f"   • Lowest: {min(scores):.4f}")
        print(f"   • Average: {sum(scores)/len(scores):.4f}")

    # Check if results are relevant (basic heuristic)
    print(f"\n🎯 Relevance Check:")
    query_terms = set(query.lower().split())
    relevant_count = 0

    for result in results[:10]:
        text_lower = result.get("text", "").lower()
        # Check if any query term appears in result
        if any(term in text_lower for term in query_terms if len(term) > 3):
            relevant_count += 1

    relevance_pct = (relevant_count / min(10, len(results))) * 100 if results else 0
    print(
        f"   {relevant_count}/10 top results contain query terms ({relevance_pct:.0f}%)"
    )

    # Priority order verification (NEW: Check weighted scoring works correctly)
    print(f"\n📋 Weighted Scoring Verification:")

    # Extract query entities for checking
    import re

    query_entities = []
    words = query.split()
    for word in words:
        clean_word = re.sub(r"[^a-zA-Z0-9]", "", word)
        if (
            clean_word
            and clean_word[0].isupper()
            and clean_word.lower() not in {"what", "how", "where", "when", "is", "are"}
        ):
            query_entities.append(clean_word)

    # Check that results are sorted by final_score descending
    scores_descending = True
    prev_score = float("inf")
    for result in results[:20]:
        current_score = result.get("final_score", result.get("score", 0))
        if current_score > prev_score:
            scores_descending = False
            break
        prev_score = current_score

    if scores_descending:
        print(f"   ✓ Results correctly sorted by weighted final_score (descending)")
    else:
        print(f"   ✗ Results NOT sorted by score - ranking issue!")

    # Check that entity matches get boosted for entity queries
    if query_entities:
        entity_boosted_count = 0
        for i, result in enumerate(results[:10]):
            boosts = result.get("boosts", {})
            if boosts.get("entity_match", 1.0) > 1.0:
                entity_boosted_count += 1
        print(f"   • Entity-matched results in top 10: {entity_boosted_count}/10")
        if entity_boosted_count > 0:
            print(
                f"   ✓ Entity boosting working for detected entities: {query_entities}"
            )

    # Check keyword boost
    keyword_boosted_count = 0
    for i, result in enumerate(results[:10]):
        boosts = result.get("boosts", {})
        if boosts.get("keyword_match", 1.0) > 1.0:
            keyword_boosted_count += 1
    if keyword_boosted_count > 0:
        print(f"   • Keyword-matched results in top 10: {keyword_boosted_count}/10")
        print(f"   ✓ Keyword boosting working")

    # Check temporal boost for temporal queries
    temporal_query_detected = any(
        "temporal_query" in result.get("boosts", {})
        and result.get("boosts", {}).get("temporal_query", 1.0) > 1.0
        for result in results[:10]
    )
    if temporal_query_detected:
        print(f"   ✓ Temporal query boost applied (detected as temporal query)")
    else:
        print(f"   • No temporal query boost (semantic/entity query)")

    print(f"\n{'='*80}")

    return {
        "query": query,
        "duration": duration,
        "total_results": len(results),
        "temporal_count": temporal_count,
        "graph_count": graph_count,
        "evidence_count": evidence_count,
        "relevance_pct": relevance_pct,
        "scores_descending": scores_descending,
        "query_entities": query_entities,
    }


async def run_all_tests():
    """Run all test queries and summarize results."""

    print("\n" + "🔬" * 40)
    print("RETRIEVAL & RANKING PERFORMANCE TEST SUITE")
    print("🔬" * 40)

    test_queries = [
        "How is my job going at livecops?",
        "What is the current state of my work with Votex365?",
        "What are my recent notes about?",
        "What are my recent thoughts?",
    ]

    results = []
    for i, query in enumerate(test_queries, 1):
        result = await test_retrieval(query, i)
        results.append(result)

        # Brief pause between tests
        await asyncio.sleep(0.5)

    # Overall Summary
    print("\n\n" + "=" * 80)
    print("📊 OVERALL SUMMARY")
    print("=" * 80)

    total_duration = sum(r["duration"] for r in results)
    avg_duration = total_duration / len(results)
    avg_results = sum(r["total_results"] for r in results) / len(results)
    avg_relevance = sum(r["relevance_pct"] for r in results) / len(results)
    weighted_scoring_works = all(r.get("scores_descending", False) for r in results)

    print(f"\n⏱️  Performance:")
    print(f"   • Average retrieval time: {avg_duration:.2f}s")
    print(f"   • Total time: {total_duration:.2f}s")

    print(f"\n📈 Results Quality:")
    print(f"   • Average results per query: {avg_results:.1f}")
    print(f"   • Average relevance: {avg_relevance:.0f}%")
    print(
        f"   • Weighted scoring working: {'✅ Yes' if weighted_scoring_works else '❌ No'}"
    )

    print(f"\n📋 Per-Query Breakdown:")
    for r in results:
        print(f"\n   '{r['query']}'")
        print(
            f"      Time: {r['duration']:.2f}s | Results: {r['total_results']} | Relevance: {r['relevance_pct']:.0f}%"
        )
        print(
            f"      Distribution: {r['temporal_count']} temporal, {r['graph_count']} graph, {r['evidence_count']} evidence"
        )

    # Final assessment
    print(f"\n{'='*80}")

    if avg_duration < 20.0 and avg_relevance > 60 and weighted_scoring_works:
        print("✅ OVERALL ASSESSMENT: EXCELLENT")
        print(
            "   Fast retrieval, good relevance, and weighted scoring working correctly."
        )
    elif avg_duration < 40.0 and avg_relevance > 40 and weighted_scoring_works:
        print("⚠️  OVERALL ASSESSMENT: GOOD")
        print("   Weighted scoring works but speed/relevance could improve.")
    else:
        print("❌ OVERALL ASSESSMENT: NEEDS IMPROVEMENT")
        print("   Consider further optimization of speed or relevance tuning.")

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
