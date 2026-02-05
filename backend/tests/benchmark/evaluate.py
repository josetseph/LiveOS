#!/usr/bin/env python3
"""
Evaluate LiveOS retrieval and answer quality against benchmark datasets.

Metrics:
- Answer Accuracy: Exact match and fuzzy match with ground truth
- Retrieval Precision: Did we retrieve the correct supporting documents?
- Multi-hop Success: Did the graph traversal find the right connections?

Usage:
    python tests/benchmark/evaluate.py --dataset hotpotqa
    python tests/benchmark/evaluate.py --dataset musique --limit 20
    python tests/benchmark/evaluate.py --dataset hotpotqa --verbose
"""

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
from tqdm import tqdm

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@dataclass
class EvaluationResult:
    """Result of evaluating a single test case."""

    test_id: str
    question: str
    expected_answer: str
    actual_answer: str

    # Answer quality
    exact_match: bool = False
    fuzzy_match: bool = False
    answer_contains_expected: bool = False

    # Retrieval quality
    retrieved_nodes: list = field(default_factory=list)
    retrieved_note_titles: list = field(default_factory=list)
    expected_notes: list = field(default_factory=list)
    retrieval_precision: float = 0.0
    retrieval_recall: float = 0.0

    # Timing
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    total_time_ms: float = 0.0

    # Error tracking
    error: Optional[str] = None


def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison."""
    # Lowercase, remove punctuation, collapse whitespace
    answer = answer.lower().strip()
    answer = re.sub(r"[^\w\s]", "", answer)
    answer = re.sub(r"\s+", " ", answer)
    return answer


def fuzzy_match(expected: str, actual: str, threshold: float = 0.8) -> bool:
    """Check if answers match with some flexibility."""
    expected_norm = normalize_answer(expected)
    actual_norm = normalize_answer(actual)

    # Exact match after normalization
    if expected_norm == actual_norm:
        return True

    # Check if expected is contained in actual
    if expected_norm in actual_norm:
        return True

    # Check word overlap (Jaccard similarity)
    expected_words = set(expected_norm.split())
    actual_words = set(actual_norm.split())

    if not expected_words or not actual_words:
        return False

    intersection = expected_words & actual_words
    union = expected_words | actual_words
    jaccard = len(intersection) / len(union)

    return jaccard >= threshold


async def query_liveos(question: str, base_url: str = "http://localhost:8000") -> dict:
    """Send a question to LiveOS chat endpoint."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"{base_url}/chat",
                json={"query": question},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}


def extract_references_from_response(response: dict) -> list[str]:
    """Extract note titles from chat response references."""
    references = response.get("references", [])
    titles = []
    for ref in references:
        title = ref.get("title", ref.get("note_title", ""))
        if title:
            titles.append(title)
    return titles


async def evaluate_single(
    test_case: dict,
    base_url: str,
    verbose: bool = False,
) -> EvaluationResult:
    """Evaluate a single test case."""
    question = test_case["question"]
    expected_answer = test_case["answer"]
    expected_notes = test_case.get("required_notes", test_case.get("notes", []))

    # Query LiveOS
    start_time = time.perf_counter()
    response = await query_liveos(question, base_url)
    total_time = (time.perf_counter() - start_time) * 1000

    result = EvaluationResult(
        test_id=test_case.get("id", "unknown"),
        question=question,
        expected_answer=expected_answer,
        actual_answer="",
        expected_notes=expected_notes,
        total_time_ms=total_time,
    )

    # Check for errors
    if "error" in response:
        result.error = response["error"]
        return result

    # Extract answer
    actual_answer = response.get("response", "")
    result.actual_answer = actual_answer

    # Answer quality metrics
    result.exact_match = normalize_answer(expected_answer) == normalize_answer(
        actual_answer
    )
    result.fuzzy_match = fuzzy_match(expected_answer, actual_answer)
    result.answer_contains_expected = normalize_answer(
        expected_answer
    ) in normalize_answer(actual_answer)

    # Retrieval quality metrics
    retrieved_titles = extract_references_from_response(response)
    result.retrieved_note_titles = retrieved_titles

    # Calculate precision/recall for retrieval
    if expected_notes and retrieved_titles:
        # Normalize for comparison
        expected_set = {normalize_answer(n) for n in expected_notes}
        retrieved_set = {normalize_answer(t) for t in retrieved_titles}

        true_positives = len(expected_set & retrieved_set)
        result.retrieval_precision = (
            true_positives / len(retrieved_set) if retrieved_set else 0
        )
        result.retrieval_recall = (
            true_positives / len(expected_set) if expected_set else 0
        )

    if verbose:
        print(f"\n{'='*60}")
        print(f"Q: {question[:100]}...")
        print(f"Expected: {expected_answer}")
        print(f"Actual: {actual_answer[:200]}...")
        print(f"Exact Match: {result.exact_match} | Fuzzy: {result.fuzzy_match}")
        print(
            f"Retrieved {len(retrieved_titles)} notes, Recall: {result.retrieval_recall:.2f}"
        )

    return result


async def run_evaluation(
    manifest_path: Path,
    limit: Optional[int] = None,
    base_url: str = "http://localhost:8000",
    verbose: bool = False,
) -> list[EvaluationResult]:
    """Run evaluation on all test cases in manifest."""

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    test_cases = manifest["test_cases"]
    if limit:
        test_cases = test_cases[:limit]

    print(f"\n🧪 Evaluating {len(test_cases)} test cases from {manifest['dataset']}")
    print(f"   Endpoint: {base_url}")

    results = []
    for test_case in tqdm(test_cases, desc="Evaluating"):
        result = await evaluate_single(test_case, base_url, verbose)
        results.append(result)

        # Small delay to avoid overwhelming the system
        await asyncio.sleep(0.5)

    return results


def calculate_metrics(results: list[EvaluationResult]) -> dict:
    """Calculate aggregate metrics from evaluation results."""
    total = len(results)
    if total == 0:
        return {}

    # Filter out errors
    valid_results = [r for r in results if r.error is None]
    valid_count = len(valid_results)
    error_count = total - valid_count

    if valid_count == 0:
        return {"error": "All queries failed", "error_count": error_count}

    # Answer quality
    exact_matches = sum(1 for r in valid_results if r.exact_match)
    fuzzy_matches = sum(1 for r in valid_results if r.fuzzy_match)
    contains_matches = sum(1 for r in valid_results if r.answer_contains_expected)

    # Retrieval quality
    avg_precision = sum(r.retrieval_precision for r in valid_results) / valid_count
    avg_recall = sum(r.retrieval_recall for r in valid_results) / valid_count

    # Timing
    avg_time = sum(r.total_time_ms for r in valid_results) / valid_count

    return {
        "total_tests": total,
        "valid_tests": valid_count,
        "error_count": error_count,
        "answer_exact_match": exact_matches / valid_count,
        "answer_fuzzy_match": fuzzy_matches / valid_count,
        "answer_contains_expected": contains_matches / valid_count,
        "retrieval_precision": avg_precision,
        "retrieval_recall": avg_recall,
        "retrieval_f1": (
            (2 * avg_precision * avg_recall / (avg_precision + avg_recall))
            if (avg_precision + avg_recall) > 0
            else 0
        ),
        "avg_response_time_ms": avg_time,
    }


def print_report(metrics: dict, results: list[EvaluationResult]):
    """Print evaluation report."""
    print("\n" + "=" * 70)
    print("📊 EVALUATION REPORT")
    print("=" * 70)

    print(f"\n📈 SUMMARY")
    print(f"   Total Tests: {metrics.get('total_tests', 0)}")
    print(f"   Valid Tests: {metrics.get('valid_tests', 0)}")
    print(f"   Errors: {metrics.get('error_count', 0)}")

    print(f"\n🎯 ANSWER QUALITY")
    print(f"   Exact Match:     {metrics.get('answer_exact_match', 0):.1%}")
    print(f"   Fuzzy Match:     {metrics.get('answer_fuzzy_match', 0):.1%}")
    print(f"   Contains Answer: {metrics.get('answer_contains_expected', 0):.1%}")

    print(f"\n🔍 RETRIEVAL QUALITY")
    print(f"   Precision: {metrics.get('retrieval_precision', 0):.1%}")
    print(f"   Recall:    {metrics.get('retrieval_recall', 0):.1%}")
    print(f"   F1 Score:  {metrics.get('retrieval_f1', 0):.1%}")

    print(f"\n⏱️  PERFORMANCE")
    print(f"   Avg Response Time: {metrics.get('avg_response_time_ms', 0):.0f}ms")

    # Show some failures for debugging
    failures = [r for r in results if not r.fuzzy_match and r.error is None]
    if failures:
        print(f"\n❌ SAMPLE FAILURES ({len(failures)} total):")
        for r in failures[:3]:
            print(f"\n   Q: {r.question[:80]}...")
            print(f"   Expected: {r.expected_answer}")
            print(f"   Got: {r.actual_answer[:100]}...")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate LiveOS against benchmark datasets"
    )
    parser.add_argument(
        "--dataset",
        choices=["hotpotqa", "musique"],
        required=True,
        help="Dataset to evaluate",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of test cases"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="LiveOS API base URL",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output for each test",
    )
    parser.add_argument("--output", "-o", type=str, help="Save results to JSON file")

    args = parser.parse_args()

    # Find manifest
    base_dir = Path(__file__).parent
    manifest_path = base_dir / f"{args.dataset}_manifest.json"

    if not manifest_path.exists():
        print(f"❌ Manifest not found: {manifest_path}")
        print(f"   Run prepare_{args.dataset}.py first to create the dataset")
        return

    # Run evaluation
    results = asyncio.run(
        run_evaluation(
            manifest_path,
            limit=args.limit,
            base_url=args.base_url,
            verbose=args.verbose,
        )
    )

    # Calculate and print metrics
    metrics = calculate_metrics(results)
    print_report(metrics, results)

    # Save results if requested
    if args.output:
        output_path = Path(args.output)
        output_data = {
            "metrics": metrics,
            "results": [
                {
                    "test_id": r.test_id,
                    "question": r.question,
                    "expected_answer": r.expected_answer,
                    "actual_answer": r.actual_answer,
                    "exact_match": r.exact_match,
                    "fuzzy_match": r.fuzzy_match,
                    "retrieval_precision": r.retrieval_precision,
                    "retrieval_recall": r.retrieval_recall,
                    "total_time_ms": r.total_time_ms,
                    "error": r.error,
                }
                for r in results
            ],
        }
        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n💾 Results saved to {output_path}")


if __name__ == "__main__":
    main()
