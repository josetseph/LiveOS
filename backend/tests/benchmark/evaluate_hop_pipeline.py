"""
Full HotPotQA evaluation using the careful multi-hop retrieval pipeline.

Runs every question in the manifest through the same per-candidate YES/NO filter
pipeline used in test_hop_pipeline.py, then writes the full per-question trace
to a log file and a JSON results file, while showing a progress bar in the terminal.

Usage:
    python tests/benchmark/evaluate_hop_pipeline.py
    python tests/benchmark/evaluate_hop_pipeline.py --limit 20
    python tests/benchmark/evaluate_hop_pipeline.py --dataset hotpotqa --limit 20
"""

import argparse
import asyncio
import json
import re
import sys
import os
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

# ── path setup ───────────────────────────────────────────────────────────────
BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parents[1]))

# ── reuse helpers from the existing hop-pipeline test ─────────────────────────
from tests.benchmark.test_hop_pipeline import (  # noqa: E402
    _ask_llm_yes_no,
    _ask_llm_text,
    _extract_name_only,
    _substitute_placeholders,
    _rewrite_back_references,
    _candidate_text,
    TOP_K,
)

# ── reuse metrics from evaluate.py ───────────────────────────────────────────
from tests.benchmark.evaluate import (  # noqa: E402
    fuzzy_match,
    normalize_answer,
    compute_answer_f1,
    extract_answer_from_response,
)

from app.services.retrieval import retrieval_service  # noqa: E402
from app.services.llm import llm_service  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  Logger — writes every line to a file; optionally echoes to stdout too
# ─────────────────────────────────────────────────────────────────────────────


class Logger:
    def __init__(self, path: Path, echo: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "w", encoding="utf-8", buffering=1)
        self._echo = echo

    def log(self, msg: str = ""):
        self._fh.write(msg + "\n")
        if self._echo:
            tqdm.write(msg)

    def close(self):
        self._fh.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline (same logic as test_hop_pipeline.py, but writes to Logger)
# ─────────────────────────────────────────────────────────────────────────────


async def run_pipeline(entry: dict, L: Logger) -> dict:
    question = entry["question"]
    expected = entry["answer"]

    L.log()
    L.log("=" * 70)
    L.log(f"QUESTION : {question}")
    L.log(f"EXPECTED : {expected}")
    L.log("=" * 70)

    # Step 1 — decompose
    info_needs = await llm_service.identify_information_needs(question)
    info_needs = _rewrite_back_references(info_needs)

    L.log(f"\n[Step 1] Sub-questions identified ({len(info_needs)}):")
    for i, n in enumerate(info_needs, 1):
        L.log(f"  {i}. {n}")

    # Step 2 — retrieve → filter per sub-question
    step_records = []
    prev_short_answers: list[str] = []

    for step_idx, raw_need in enumerate(info_needs, 1):
        need = _substitute_placeholders(raw_need, prev_short_answers)

        if need != raw_need:
            L.log(f"\n[Step 2.{step_idx}] Sub-question (filled): {need}")
        else:
            L.log(f"\n[Step 2.{step_idx}] Sub-question: {need}")

        docs = await retrieval_service.hybrid_search(need, top_k=TOP_K)
        L.log(f"  Retrieved {len(docs)} candidates.")

        verified = []
        for doc in docs:
            text = _candidate_text(doc)
            if not text:
                continue
            node_name = doc.get("original_obj", {}).get("name", "?")
            check_prompt = (
                f"GOAL: We are trying to answer: {question}\n\n"
                f"SUB-QUESTION: To do that, we need to know: {need}\n\n"
                f"PASSAGE:\n{text}\n\n"
                f"Does this passage specifically answer the sub-question? Reply YES or NO only."
            )
            is_answer = _ask_llm_yes_no(check_prompt)
            status = "✓ YES" if is_answer else "  no "
            L.log(f"    {status}  [{node_name}] {text[:90].replace(chr(10), ' ')}...")
            if is_answer:
                verified.append(doc)

        L.log(f"  → {len(verified)} verified answer(s) for sub-question {step_idx}.")

        short_answer = ""
        if verified:
            short_answer = _extract_name_only(
                need, verified, original_question=question
            )
            L.log(f"  → Short answer extracted: '{short_answer}'")
        prev_short_answers.append(short_answer)

        step_records.append(
            {
                "sub_question": need,
                "candidates": len(docs),
                "verified_docs": verified,
                "verified_texts": [_candidate_text(d) for d in verified],
                "short_answer": short_answer,
            }
        )

    # Step 3 — synthesis
    L.log(f"\n[Step 3] Final synthesis...")

    # Build Q&A block
    qa_lines = []
    for i, rec in enumerate(step_records, 1):
        qa_lines.append(f"Q{i}: {rec['sub_question']}")
        if rec["short_answer"]:
            qa_lines.append(f"A{i}: {rec['short_answer']}")
        else:
            qa_lines.append(f"A{i}: (no answer found)")
        if rec["verified_texts"]:
            for t in rec["verified_texts"][:2]:
                qa_lines.append(f"  Evidence: {t[:250]}")
        qa_lines.append("")

    qa_block = "\n".join(qa_lines)

    synthesis_prompt = f"""You are answering a question using the sub-question answers below.

{qa_block}Final question: {question}

RULE 1 (YES/NO): If the question asks whether two things share the same property, compare the answers above. ALL same → output the single word YES. ANY differ → output the single word NO. Never output the compared value.
RULE 2 (COMPARISON): If the question asks which had more/fewer/greater/less, compare the values, then output the WINNER'S NAME — not the metric.
RULE 3 (MULTI-HOP): The final answer is whatever the sub-question directly resolves to for the answer type requested. Bridge entities found along the way are NOT the final answer.

Be short and direct — return only the value, no explanation.

Answer:"""

    final_answer = _ask_llm_text(synthesis_prompt, max_tokens=150)
    L.log(f"\n  FINAL ANSWER : {final_answer}")
    L.log(f"  EXPECTED     : {expected}")

    # Metrics
    extracted = extract_answer_from_response(final_answer)
    is_fuzzy = fuzzy_match(expected, final_answer)
    is_exact = normalize_answer(expected) == normalize_answer(extracted)
    f1 = compute_answer_f1(extracted, expected)

    L.log(f"  FUZZY PASS   : {is_fuzzy}")
    L.log(f"  EXACT MATCH  : {is_exact}")
    L.log(f"  F1           : {f1:.2f}")

    return {
        "id": entry.get("id", ""),
        "question": question,
        "expected": expected,
        "final_answer": final_answer,
        "fuzzy_match": is_fuzzy,
        "exact_match": is_exact,
        "f1": f1,
        "steps": [
            {
                "sub_question": r["sub_question"],
                "candidates": r["candidates"],
                "verified_count": len(r["verified_docs"]),
                "short_answer": r["short_answer"],
            }
            for r in step_records
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(
        description="Evaluate all HotPotQA questions with the hop pipeline"
    )
    parser.add_argument(
        "--dataset", default="hotpotqa", choices=["hotpotqa", "musique"]
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap number of questions"
    )
    parser.add_argument(
        "--echo", action="store_true", help="Also print trace to terminal"
    )
    args = parser.parse_args()

    manifest_path = BENCH_DIR / f"{args.dataset}_manifest.json"
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    test_cases = manifest["test_cases"]
    if args.limit:
        test_cases = test_cases[: args.limit]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    limit_tag = f"_n{args.limit}" if args.limit else ""
    results_dir = BENCH_DIR / "results"
    log_path = results_dir / f"hop_pipeline_{args.dataset}{limit_tag}_{timestamp}.txt"
    json_path = results_dir / f"hop_pipeline_{args.dataset}{limit_tag}_{timestamp}.json"

    L = Logger(log_path, echo=args.echo)
    L.log(f"Hop-Pipeline Evaluation — {args.dataset.upper()}")
    L.log(f"Started : {datetime.now().isoformat()}")
    L.log(f"Questions: {len(test_cases)}")
    L.log("=" * 70)

    results = []
    pbar = tqdm(test_cases, desc="Evaluating", unit="q")
    for entry in pbar:
        result = await run_pipeline(entry, L)
        results.append(result)

        # live stats in progress bar
        n = len(results)
        fuzzy_so_far = sum(1 for r in results if r["fuzzy_match"])
        pbar.set_postfix(fuzzy=f"{fuzzy_so_far}/{n}")

    L.log()
    L.log("=" * 70)
    L.log("SUMMARY")
    L.log("=" * 70)

    total = len(results)
    fuzzy_n = sum(1 for r in results if r["fuzzy_match"])
    exact_n = sum(1 for r in results if r["exact_match"])
    avg_f1 = sum(r["f1"] for r in results) / total if total else 0

    L.log(f"Total     : {total}")
    L.log(f"Fuzzy     : {fuzzy_n}/{total}  ({fuzzy_n/total:.1%})")
    L.log(f"Exact     : {exact_n}/{total}  ({exact_n/total:.1%})")
    L.log(f"Avg F1    : {avg_f1:.3f}")

    failures = [r for r in results if not r["fuzzy_match"]]
    L.log(f"\nFailures  : {len(failures)}")
    for r in failures:
        L.log(f"  ✗  {r['question'][:65]}...")
        L.log(f"       Expected : {r['expected']}")
        L.log(f"       Got      : {r['final_answer'][:80]}")
        L.log()

    L.close()

    # JSON results
    results_dir.mkdir(exist_ok=True)
    summary = {
        "timestamp": datetime.now().isoformat(),
        "dataset": args.dataset,
        "num_tests": total,
        "metrics": {
            "fuzzy_match": fuzzy_n / total,
            "exact_match": exact_n / total,
            "avg_f1": avg_f1,
            "fuzzy_count": fuzzy_n,
            "exact_count": exact_n,
        },
        "results": results,
    }
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Terminal summary
    print(f"\n{'='*60}")
    print(f"RESULTS  ({args.dataset.upper()}, {total} questions)")
    print(f"{'='*60}")
    print(f"  Fuzzy Match : {fuzzy_n}/{total}  ({fuzzy_n/total:.1%})")
    print(f"  Exact Match : {exact_n}/{total}  ({exact_n/total:.1%})")
    print(f"  Avg F1      : {avg_f1:.3f}")
    print(f"\n  Log  → {log_path}")
    print(f"  JSON → {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
