#!/usr/bin/env python3
"""
Evaluate LiveOS retrieval and answer quality against benchmark datasets.

Enhanced with RAGAS metrics for comprehensive RAG evaluation:
- Answer Correctness: semantic similarity to ground truth
- Faithfulness: is the answer grounded in retrieved context?
- Answer Relevancy: is the answer relevant to the question?
- Context Precision: are relevant contexts ranked higher?
- Context Recall: are all relevant contexts retrieved?

Usage:
    # Basic evaluation (results saved automatically)
    python tests/benchmark/evaluate_ragas.py --dataset musique

    # With Ragas metrics (uses LOCAL Ollama LLM - no OpenAI needed!)
    python tests/benchmark/evaluate_ragas.py --dataset musique --use-ragas

    # Verbose output with limit
    python tests/benchmark/evaluate_ragas.py --dataset musique --use-ragas --verbose --limit 10

    # Use OpenAI instead of local LLM (if you prefer)
    OPENAI_API_KEY=your-key python tests/benchmark/evaluate_ragas.py --dataset musique --use-ragas --llm openai
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from tqdm import tqdm

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# Check for Ragas availability
RAGAS_AVAILABLE = False
try:
    from ragas import evaluate as ragas_evaluate
    from ragas.metrics.collections import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
        answer_correctness,
    )
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from datasets import Dataset

    RAGAS_AVAILABLE = True
except ImportError:
    pass

# Ollama configuration for local LLM
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")


@dataclass
class EvaluationResult:
    """Result of evaluating a single test case."""

    test_id: str
    question: str
    expected_answer: str
    actual_answer: str

    # Answer quality (basic)
    exact_match: bool = False
    fuzzy_match: bool = False
    answer_contains_expected: bool = False

    # Retrieval quality
    retrieved_contexts: list = field(default_factory=list)
    retrieved_note_titles: list = field(default_factory=list)
    expected_notes: list = field(default_factory=list)
    retrieval_precision: float = 0.0
    retrieval_recall: float = 0.0

    # RAGAS metrics (if available)
    ragas_faithfulness: Optional[float] = None
    ragas_answer_relevancy: Optional[float] = None
    ragas_context_precision: Optional[float] = None
    ragas_context_recall: Optional[float] = None
    ragas_answer_correctness: Optional[float] = None

    # Timing
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    total_time_ms: float = 0.0

    # Error tracking
    error: Optional[str] = None


def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison."""
    answer = answer.lower().strip()
    answer = re.sub(r"[^\w\s]", "", answer)
    answer = re.sub(r"\s+", " ", answer)
    return answer


def fuzzy_match(expected: str, actual: str, threshold: float = 0.8) -> bool:
    """Check if answers match with some flexibility."""
    expected_norm = normalize_answer(expected)
    actual_norm = normalize_answer(actual)

    if expected_norm == actual_norm:
        return True

    if expected_norm in actual_norm:
        return True

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
                f"{base_url}/api/v1/chat",
                json={"query": question},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}


def extract_contexts_from_response(response: dict) -> tuple[list[str], list[str]]:
    """Extract context texts and titles from chat response."""
    # API uses 'context' key, not 'references'
    context_items = response.get("context", [])
    contexts = []
    titles = []

    for item in context_items:
        # Extract from linked_notes if available
        linked_notes = item.get("linked_notes", [])
        for note in linked_notes:
            title = note.get("title", "")
            if title:
                titles.append(title)

        # Extract context text from item
        text = item.get("text", "")
        if text:
            contexts.append(text)

        # Also try original_obj description
        original_obj = item.get("original_obj", {})
        desc = original_obj.get("description", "")
        if desc and desc not in contexts:
            contexts.append(desc)

    return contexts, titles


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

    if "error" in response:
        result.error = response["error"]
        return result

    # Extract answer and contexts (API uses 'answer' key, not 'response')
    actual_answer = response.get("answer", "")
    result.actual_answer = actual_answer

    contexts, titles = extract_contexts_from_response(response)
    result.retrieved_contexts = contexts
    result.retrieved_note_titles = titles

    # Basic answer quality metrics
    result.exact_match = normalize_answer(expected_answer) == normalize_answer(
        actual_answer
    )
    result.fuzzy_match = fuzzy_match(expected_answer, actual_answer)
    result.answer_contains_expected = normalize_answer(
        expected_answer
    ) in normalize_answer(actual_answer)

    # Retrieval quality metrics
    if expected_notes and titles:
        expected_set = {normalize_answer(n) for n in expected_notes}
        retrieved_set = {normalize_answer(t) for t in titles}

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
        print(f"Retrieved {len(titles)} notes")

    return result


def get_ragas_llm_and_embeddings(llm_provider: str = "ollama"):
    """
    Get LLM and embeddings for Ragas evaluation.

    Args:
        llm_provider: 'ollama' for local LLM (default), 'openai' for OpenAI
    """
    if llm_provider == "openai":
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        llm = ChatOpenAI(model="gpt-4o-mini")
        embeddings = OpenAIEmbeddings()
    else:
        # Use local Ollama
        from langchain_ollama import ChatOllama, OllamaEmbeddings

        llm = ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
        embeddings = OllamaEmbeddings(
            model=OLLAMA_EMBED_MODEL,
            base_url=OLLAMA_BASE_URL,
        )

    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(embeddings)


def run_ragas_evaluation(
    results: list[EvaluationResult], llm_provider: str = "ollama", verbose: bool = False
) -> list[EvaluationResult]:
    """Run Ragas evaluation on all results using local or cloud LLM."""
    if not RAGAS_AVAILABLE:
        print("⚠️  Ragas not available. Install with: pip install ragas")
        return results

    print(f"\n🔬 Running Ragas evaluation with {llm_provider.upper()} LLM...")

    # Prepare data for Ragas
    valid_results = [r for r in results if r.error is None and r.retrieved_contexts]

    if not valid_results:
        print("   No valid results to evaluate")
        return results

    # Get LLM and embeddings
    try:
        ragas_llm, ragas_embeddings = get_ragas_llm_and_embeddings(llm_provider)
        print(
            f"   Using model: {OLLAMA_MODEL if llm_provider == 'ollama' else 'gpt-4o-mini'}"
        )
    except Exception as e:
        print(f"   ❌ Failed to initialize LLM: {e}")
        return results

    # Create Ragas dataset
    ragas_data = {
        "question": [r.question for r in valid_results],
        "answer": [r.actual_answer for r in valid_results],
        "contexts": [r.retrieved_contexts for r in valid_results],
        "ground_truth": [r.expected_answer for r in valid_results],
    }

    dataset = Dataset.from_dict(ragas_data)

    try:
        # Run Ragas evaluation with our LLM
        ragas_result = ragas_evaluate(
            dataset,
            metrics=[
                faithfulness,
                answer_relevancy,
                context_precision,
                context_recall,
                answer_correctness,
            ],
            llm=ragas_llm,
            embeddings=ragas_embeddings,
        )

        # Map results back
        ragas_df = ragas_result.to_pandas()
        for i, result in enumerate(valid_results):
            if i < len(ragas_df):
                row = ragas_df.iloc[i]
                result.ragas_faithfulness = row.get("faithfulness")
                result.ragas_answer_relevancy = row.get("answer_relevancy")
                result.ragas_context_precision = row.get("context_precision")
                result.ragas_context_recall = row.get("context_recall")
                result.ragas_answer_correctness = row.get("answer_correctness")

        print("   ✓ Ragas evaluation complete")

    except Exception as e:
        print(f"   ❌ Ragas evaluation failed: {e}")
        if verbose:
            import traceback

            traceback.print_exc()

    return results


async def run_evaluation(
    manifest_path: Path,
    limit: Optional[int] = None,
    base_url: str = "http://localhost:8000",
    verbose: bool = False,
    use_ragas: bool = False,
    llm_provider: str = "ollama",
) -> list[EvaluationResult]:
    """Run evaluation on all test cases."""

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
        await asyncio.sleep(0.5)

    # Run Ragas if requested
    if use_ragas:
        results = run_ragas_evaluation(
            results, llm_provider=llm_provider, verbose=verbose
        )

    return results


def calculate_metrics(
    results: list[EvaluationResult], include_ragas: bool = False
) -> dict:
    """Calculate aggregate metrics from evaluation results."""
    total = len(results)
    if total == 0:
        return {}

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

    metrics = {
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

    # Ragas metrics
    if include_ragas:
        ragas_results = [r for r in valid_results if r.ragas_faithfulness is not None]
        if ragas_results:
            ragas_count = len(ragas_results)
            metrics["ragas"] = {
                "faithfulness": sum(r.ragas_faithfulness or 0 for r in ragas_results)
                / ragas_count,
                "answer_relevancy": sum(
                    r.ragas_answer_relevancy or 0 for r in ragas_results
                )
                / ragas_count,
                "context_precision": sum(
                    r.ragas_context_precision or 0 for r in ragas_results
                )
                / ragas_count,
                "context_recall": sum(
                    r.ragas_context_recall or 0 for r in ragas_results
                )
                / ragas_count,
                "answer_correctness": sum(
                    r.ragas_answer_correctness or 0 for r in ragas_results
                )
                / ragas_count,
            }

    return metrics


def print_report(metrics: dict, results: list[EvaluationResult]):
    """Print evaluation report."""
    print("\n" + "=" * 70)
    print("📊 EVALUATION REPORT")
    print(f"   Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print(f"\n📈 SUMMARY")
    print(f"   Total Tests: {metrics.get('total_tests', 0)}")
    print(f"   Valid Tests: {metrics.get('valid_tests', 0)}")
    print(f"   Errors: {metrics.get('error_count', 0)}")

    print(f"\n🎯 ANSWER QUALITY (Basic)")
    print(f"   Exact Match:     {metrics.get('answer_exact_match', 0):.1%}")
    print(f"   Fuzzy Match:     {metrics.get('answer_fuzzy_match', 0):.1%}")
    print(f"   Contains Answer: {metrics.get('answer_contains_expected', 0):.1%}")

    print(f"\n🔍 RETRIEVAL QUALITY")
    print(f"   Precision: {metrics.get('retrieval_precision', 0):.1%}")
    print(f"   Recall:    {metrics.get('retrieval_recall', 0):.1%}")
    print(f"   F1 Score:  {metrics.get('retrieval_f1', 0):.1%}")

    # Ragas metrics
    if "ragas" in metrics:
        ragas = metrics["ragas"]
        print(f"\n🔬 RAGAS METRICS (Semantic Evaluation)")
        print(f"   Faithfulness:       {ragas.get('faithfulness', 0):.1%}")
        print(f"   Answer Relevancy:   {ragas.get('answer_relevancy', 0):.1%}")
        print(f"   Answer Correctness: {ragas.get('answer_correctness', 0):.1%}")
        print(f"   Context Precision:  {ragas.get('context_precision', 0):.1%}")
        print(f"   Context Recall:     {ragas.get('context_recall', 0):.1%}")

    print(f"\n⏱️  PERFORMANCE")
    print(f"   Avg Response Time: {metrics.get('avg_response_time_ms', 0):.0f}ms")

    # Show sample failures
    failures = [r for r in results if not r.fuzzy_match and r.error is None]
    if failures:
        print(f"\n❌ SAMPLE FAILURES ({len(failures)} total):")
        for r in failures[:3]:
            print(f"\n   Q: {r.question[:80]}...")
            print(f"   Expected: {r.expected_answer}")
            print(f"   Got: {r.actual_answer[:100]}...")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Evaluate LiveOS with Ragas metrics")
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
    parser.add_argument(
        "--use-ragas",
        action="store_true",
        help="Run Ragas evaluation (uses local Ollama by default)",
    )
    parser.add_argument(
        "--llm",
        type=str,
        choices=["ollama", "openai"],
        default="ollama",
        help="LLM provider for Ragas: 'ollama' (default, local) or 'openai'",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Custom output path (default: auto-generated in tests/benchmark/results/)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to file",
    )

    args = parser.parse_args()

    # Check Ragas availability
    if args.use_ragas and not RAGAS_AVAILABLE:
        print("❌ Ragas not installed. Install with:")
        print("   pip install ragas datasets")
        return

    # Find manifest
    base_dir = Path(__file__).parent
    manifest_path = base_dir / f"{args.dataset}_manifest.json"

    if not manifest_path.exists():
        print(f"❌ Manifest not found: {manifest_path}")
        print(f"   Run prepare_{args.dataset}_local.py first to create the dataset")
        return

    # Run evaluation
    results = asyncio.run(
        run_evaluation(
            manifest_path,
            limit=args.limit,
            base_url=args.base_url,
            verbose=args.verbose,
            use_ragas=args.use_ragas,
            llm_provider=args.llm,
        )
    )

    # Calculate and print metrics
    metrics = calculate_metrics(results, include_ragas=args.use_ragas)
    print_report(metrics, results)

    # Save results by default (unless --no-save)
    if not args.no_save:
        # Create results directory
        results_dir = base_dir / "results"
        results_dir.mkdir(exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ragas_suffix = "_ragas" if args.use_ragas else ""
        limit_suffix = f"_n{args.limit}" if args.limit else ""

        if args.output:
            output_path = Path(args.output)
        else:
            output_path = (
                results_dir
                / f"{args.dataset}{ragas_suffix}{limit_suffix}_{timestamp}.json"
            )

        output_data = {
            "timestamp": datetime.now().isoformat(),
            "dataset": args.dataset,
            "num_tests": len(results),
            "use_ragas": args.use_ragas,
            "llm_provider": args.llm if args.use_ragas else None,
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
                    "ragas_faithfulness": r.ragas_faithfulness,
                    "ragas_answer_relevancy": r.ragas_answer_relevancy,
                    "ragas_answer_correctness": r.ragas_answer_correctness,
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
