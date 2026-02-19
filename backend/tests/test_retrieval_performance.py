"""
Test script for retrieval and ranking performance.
Tests the hybrid_search pipeline without chat/synthesis.
"""

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
import json
from datetime import datetime
from pathlib import Path
from app.services.retrieval import retrieval_service


async def test_retrieval(query: str, test_number: int, markdown_lines=None):
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

    section_lines = [
        f"## Test {test_number}",
        "",
        f"**Query:** {query}",
        "",
        f"- Retrieval Time: `{duration:.2f}s`",
        f"- Total Results: `{len(results)}`",
    ]

    if not results:
        print("\n❌ No results returned!")
        section_lines.append("- No results returned.")
        section_lines.append("")
        if markdown_lines is not None:
            markdown_lines.extend(section_lines)
        return {
            "query": query,
            "duration": duration,
            "total_results": 0,
            "temporal_count": 0,
            "graph_count": 0,
            "evidence_count": 0,
            "relevance_pct": 0.0,
            "scores_descending": False,
            "query_entities": [],
        }

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

    section_lines.extend(
        [
            "",
            "### Result Breakdown",
            "",
            f"- Temporal (Recent Notes): `{temporal_count}`",
            f"- Graph Nodes: `{graph_count}`",
            f"- Evidence (Linked Notes): `{evidence_count}`",
            "",
        ]
    )

    # Show all results in detail without truncation
    print(f"\n🔍 All Results ({len(results)}):")
    print("-" * 80)

    for i, result in enumerate(results, 1):
        result_type = result.get("type", "unknown")
        score = result.get("score", 0.0)
        is_recent = result.get("is_recent", False)
        text = result.get("text", "") or ""

        # Format display
        type_label = (
            "📅 TEMPORAL"
            if is_recent and result_type == "note"
            else "🧠 GRAPH NODE" if result_type == "graph_consensus" else "🔗 EVIDENCE"
        )

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
        print("   Full Text:")
        print(text if text else "   <empty>")
        print("   Full Payload:")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

        section_lines.extend(
            [
                f"### Result {i}",
                "",
                f"- Type: `{result_type}`",
                f"- Label: `{type_label}`",
                f"- Score: `{score:.4f}`",
                f"- Is Recent: `{is_recent}`",
            ]
        )
        if metadata:
            section_lines.append(f"- Metadata: {' | '.join(metadata)}")

        section_lines.extend(
            [
                "",
                "#### Full Text",
                "",
                "```text",
                text if text else "<empty>",
                "```",
                "",
                "#### Full Payload",
                "",
                "```json",
                json.dumps(result, indent=2, ensure_ascii=False, default=str),
                "```",
                "",
            ]
        )

    # Show score distribution
    print(f"\n📊 Score Distribution:")
    scores = [r.get("score", 0) for r in results]
    if scores:
        print(f"   • Highest: {max(scores):.4f}")
        print(f"   • Lowest: {min(scores):.4f}")
        print(f"   • Average: {sum(scores)/len(scores):.4f}")
        section_lines.extend(
            [
                "### Score Distribution",
                "",
                f"- Highest: `{max(scores):.4f}`",
                f"- Lowest: `{min(scores):.4f}`",
                f"- Average: `{sum(scores)/len(scores):.4f}`",
                "",
            ]
        )

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
    section_lines.extend(
        [
            "### Relevance Check",
            "",
            f"- `{relevant_count}/10` top results contain query terms (`{relevance_pct:.0f}%`)",
            "",
        ]
    )

    # Priority order verification (NEW: Check weighted scoring works correctly)
    print(f"\n📋 Weighted Scoring Verification:")
    section_lines.extend(["### Weighted Scoring Verification", ""])

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
    for result in results:
        current_score = result.get("final_score", result.get("score", 0))
        if current_score > prev_score:
            scores_descending = False
            break
        prev_score = current_score

    if scores_descending:
        print(f"   ✓ Results correctly sorted by weighted final_score (descending)")
        section_lines.append("- Results correctly sorted by weighted final_score (descending): `True`")
    else:
        print(f"   ✗ Results NOT sorted by score - ranking issue!")
        section_lines.append("- Results correctly sorted by weighted final_score (descending): `False`")

    # Check that entity matches get boosted for entity queries
    if query_entities:
        entity_boosted_count = 0
        for i, result in enumerate(results):
            boosts = result.get("boosts", {})
            if boosts.get("entity_match", 1.0) > 1.0:
                entity_boosted_count += 1
        print(f"   • Entity-matched results: {entity_boosted_count}/{len(results)}")
        if entity_boosted_count > 0:
            print(
                f"   ✓ Entity boosting working for detected entities: {query_entities}"
            )
        section_lines.append(
            f"- Entity-matched results: `{entity_boosted_count}/{len(results)}`"
        )
        section_lines.append(f"- Detected query entities: `{query_entities}`")

    # Check keyword boost
    keyword_boosted_count = 0
    for i, result in enumerate(results):
        boosts = result.get("boosts", {})
        if boosts.get("keyword_match", 1.0) > 1.0:
            keyword_boosted_count += 1
    if keyword_boosted_count > 0:
        print(f"   • Keyword-matched results: {keyword_boosted_count}/{len(results)}")
        print(f"   ✓ Keyword boosting working")
    section_lines.append(
        f"- Keyword-matched results: `{keyword_boosted_count}/{len(results)}`"
    )

    # Check temporal boost for temporal queries
    temporal_query_detected = any(
        "temporal_query" in result.get("boosts", {})
        and result.get("boosts", {}).get("temporal_query", 1.0) > 1.0
        for result in results
    )
    if temporal_query_detected:
        print(f"   ✓ Temporal query boost applied (detected as temporal query)")
        section_lines.append("- Temporal query boost applied: `True`")
    else:
        print(f"   • No temporal query boost (semantic/entity query)")
        section_lines.append("- Temporal query boost applied: `False`")

    print(f"\n{'='*80}")
    section_lines.append("")
    section_lines.append("---")
    section_lines.append("")

    if markdown_lines is not None:
        markdown_lines.extend(section_lines)

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

    run_timestamp = datetime.now()
    report_dir = Path(__file__).resolve().parent / "benchmark" / "results"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"retrieval_performance_{run_timestamp:%Y%m%d_%H%M%S}.md"

    markdown_lines = [
        "# Retrieval & Ranking Performance Test Report",
        "",
        f"- Generated At: `{run_timestamp.isoformat(timespec='seconds')}`",
        f"- Script: `{Path(__file__).name}`",
        "",
        "---",
        "",
    ]

    print("\n" + "🔬" * 40)
    print("RETRIEVAL & RANKING PERFORMANCE TEST SUITE")
    print("🔬" * 40)

    test_queries = [
        "Were Scott Derrickson and Ed Wood of the same nationality?",
        "What government position was held by the woman who portrayed Corliss Archer in the film Kiss and Tell?",
        "What science fantasy young adult series, told in first person, has a set of companion books narrating the stories of enslaved worlds and alien species?",
        "Are the Laleli Mosque and Esma Sultan Mansion located in the same neighborhood?",
    ]

    results = []
    for i, query in enumerate(test_queries, 1):
        result = await test_retrieval(query, i, markdown_lines=markdown_lines)
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

    markdown_lines.extend(
        [
            "## Overall Summary",
            "",
            f"- Average retrieval time: `{avg_duration:.2f}s`",
            f"- Total time: `{total_duration:.2f}s`",
            f"- Average results per query: `{avg_results:.1f}`",
            f"- Average relevance: `{avg_relevance:.0f}%`",
            f"- Weighted scoring working: `{'Yes' if weighted_scoring_works else 'No'}`",
            "",
            "### Per-Query Breakdown",
            "",
        ]
    )

    for r in results:
        markdown_lines.extend(
            [
                f"- Query: {r['query']}",
                f"  - Time: `{r['duration']:.2f}s`",
                f"  - Results: `{r['total_results']}`",
                f"  - Relevance: `{r['relevance_pct']:.0f}%`",
                f"  - Distribution: `{r['temporal_count']} temporal, {r['graph_count']} graph, {r['evidence_count']} evidence`",
            ]
        )

    markdown_lines.append("")
    if avg_duration < 20.0 and avg_relevance > 60 and weighted_scoring_works:
        markdown_lines.append("**Overall Assessment:** `EXCELLENT`")
    elif avg_duration < 40.0 and avg_relevance > 40 and weighted_scoring_works:
        markdown_lines.append("**Overall Assessment:** `GOOD`")
    else:
        markdown_lines.append("**Overall Assessment:** `NEEDS IMPROVEMENT`")
    markdown_lines.append("")

    report_path.write_text("\n".join(markdown_lines), encoding="utf-8")
    print(f"\n📝 Markdown report written to: {report_path}")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
