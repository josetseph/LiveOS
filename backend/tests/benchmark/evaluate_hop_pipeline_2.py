"""
Hop-Pipeline v2 — full HotPotQA evaluation with:

  1. Pure vector search (no graph expansion, no entity matching)
     — embeds each sub-question, returns every node whose cosine similarity
       to the query is ≥ min_score (default 0.5).  All candidates are passed
       to a per-candidate LLM YES/NO filter.

  2. Early stopping
     — after every step (except the last), a quick LLM check asks whether
       the original question can already be answered from the evidence
       collected so far.  If yes, synthesis runs immediately.

  3. Improved synthesis prompt (fixes A / B / C failure categories)
     A — YES/NO: output the word YES/NO, never the value itself
     B — multi-hop: final answer comes from the LAST sub-question
     C — comparison: return the WINNER's name, not the metric

Usage:
    python tests/benchmark/evaluate_hop_pipeline_2.py
    python tests/benchmark/evaluate_hop_pipeline_2.py --limit 20
    python tests/benchmark/evaluate_hop_pipeline_2.py --min-score 0.55
    python tests/benchmark/evaluate_hop_pipeline_2.py --echo
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

# ── path setup ───────────────────────────────────────────────────────────────
BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parents[1]))

# ── shared helpers (LLM callers, back-ref rewriter, substitution) ─────────────
from tests.benchmark.test_hop_pipeline import (  # noqa: E402
    _ask_llm_yes_no,
    _ask_llm_text,
    _substitute_placeholders,
    _rewrite_back_references,
)

# ── metrics from evaluate.py ─────────────────────────────────────────────────
from tests.benchmark.evaluate import (  # noqa: E402
    fuzzy_match,
    normalize_answer,
    compute_answer_f1,
    extract_answer_from_response,
)

from app.services.llm import llm_service  # noqa: E402
from app.services.graph import graph_service  # noqa: E402
from app.services.embedding import embedding_service  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  Pure vector search — no expansion, no entity matching
# ─────────────────────────────────────────────────────────────────────────────

def _node_text(node: dict) -> str:
    """Build a single readable text string from a raw graph node."""
    name = node.get("name", "")
    summary = node.get("summary", "") or ""
    description = node.get("description", "") or ""
    body = (summary or description).strip()
    if name and body:
        return f"{name}: {body}"
    return body or name


def _vector_search_all(query: str, min_score: float = 0.5) -> list[dict]:
    """
    Embed query → call graph vector index with a very high top_k cap.
    Returns every node whose cosine similarity ≥ min_score.
    No entity matching, no neighbour expansion, no re-scoring.
    """
    vector = embedding_service.embed_query(query)
    nodes = graph_service.search_knowledge_graph(
        vector, top_k=500, min_score=min_score
    )
    return nodes


# ─────────────────────────────────────────────────────────────────────────────
#  Short-answer extractor
# ─────────────────────────────────────────────────────────────────────────────

def _extract_name_only(question: str, verified_nodes: list[dict]) -> str:
    """Return a short (≤6-word) entity name / value that answers the question."""
    context = "\n\n".join(_node_text(n) for n in verified_nodes[:3])
    prompt = (
        f"Answer the question below with ONLY the name or value — "
        f"no sentence, no explanation.\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"ANSWER (1–6 words):"
    )
    return _ask_llm_text(prompt, max_tokens=20).split("\n")[0].strip()


# ─────────────────────────────────────────────────────────────────────────────
#  Early stopping
# ─────────────────────────────────────────────────────────────────────────────

def _check_early_stop(question: str, step_records: list[dict]) -> tuple[bool, str]:
    """
    Ask LLM whether the original question can already be answered from the
    evidence collected so far.

    Returns (can_answer: bool, answer: str).
    """
    direct_answers = [r["short_answer"] for r in step_records if r["short_answer"]]
    if not direct_answers:
        return False, ""

    evidence_lines = []
    for r in step_records:
        evidence_lines.append(f"Sub-question: {r['sub_question']}")
        if r["short_answer"]:
            evidence_lines.append(f"DIRECT ANSWER: {r['short_answer']}")
        evidence_lines.append("")

    prompt = (
        f"ORIGINAL QUESTION: {question}\n\n"
        f"EVIDENCE GATHERED SO FAR:\n" + "\n".join(evidence_lines) + "\n"
        f"Can the original question be FULLY and CORRECTLY answered "
        f"from this evidence alone?\n\n"
        f"If YES, reply exactly:  YES: <your answer>\n"
        f"If NO, reply exactly:   NO"
    )
    resp = _ask_llm_text(prompt, max_tokens=60).strip()
    upper = resp.upper()
    if upper.startswith("YES"):
        # Extract the answer part after "YES:"
        answer = resp[resp.find(":")+1:].strip() if ":" in resp else ""
        return True, answer
    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
#  Synthesis (v2 prompt — fixes A, B, C)
# ─────────────────────────────────────────────────────────────────────────────

def _synthesize(question: str, step_records: list[dict]) -> str:
    evidence_lines = []
    for i, rec in enumerate(step_records, 1):
        evidence_lines.append(f"Sub-question {i}: {rec['sub_question']}")
        if rec["short_answer"]:
            evidence_lines.append(f"  DIRECT ANSWER: {rec['short_answer']}")
        if rec["verified_texts"]:
            for j, t in enumerate(rec["verified_texts"][:3], 1):
                evidence_lines.append(f"  Supporting passage {j}: {t[:300]}")
        else:
            evidence_lines.append("  (no verified evidence found)")
        evidence_lines.append("")

    evidence_block = "\n".join(evidence_lines)

    prompt = f"""You have to answer this question:
{question}

The sub-questions below were answered in order. Each has a DIRECT ANSWER and supporting passages.

--- EVIDENCE ---
{evidence_block}
--- END EVIDENCE ---

RULES (read ALL before answering):

1. YES/NO QUESTIONS  ("Were X and Y both...?", "Are X and Y both...?", "Is X a...?")
   - Compare the DIRECT ANSWER values for each entity.
   - ALL the same → output the single word YES
   - ANY differ   → output the single word NO
   - NEVER output the value itself ("American", "yes, both American", etc.)

2. COMPARISON QUESTIONS  ("Who is older?", "Which has more members?", "Which is bigger?")
   - Extract the relevant metric (birth year, count, size) for each option from the evidence.
   - Compare them, then output only the NAME of the winner.
   - NEVER output the metric itself.

3. MULTI-HOP QUESTIONS  (all others)
   - The original question asks for a SPECIFIC type of thing (city, title, year, person, …).
   - Identify which sub-question directly asks for that thing.
   - Return the DIRECT ANSWER from THAT sub-question only.
   - Intermediate entities found in earlier steps are NOT the final answer.
   - Example: Q="What city is [director] based in?" → answer comes from the sub-question
     about the city, NOT from the sub-question that found the director's name.

4. Be short — one value, no explanation.

FINAL ANSWER:"""

    return _ask_llm_text(prompt, max_tokens=150)


# ─────────────────────────────────────────────────────────────────────────────
#  Logger
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
#  Core pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def run_pipeline(entry: dict, L: Logger, min_score: float = 0.5) -> dict:
    question = entry["question"]
    expected = entry["answer"]

    L.log()
    L.log("=" * 70)
    L.log(f"QUESTION : {question}")
    L.log(f"EXPECTED : {expected}")
    L.log("=" * 70)

    # ── Step 1: decompose ────────────────────────────────────────────────────
    info_needs = await llm_service.identify_information_needs(question)
    info_needs = _rewrite_back_references(info_needs)

    L.log(f"\n[Step 1] Sub-questions identified ({len(info_needs)}):")
    for i, n in enumerate(info_needs, 1):
        L.log(f"  {i}. {n}")

    # ── Step 2: iterate sub-questions ────────────────────────────────────────
    step_records: list[dict] = []
    prev_short_answers: list[str] = []
    early_stopped = False
    early_answer = ""

    for step_idx, raw_need in enumerate(info_needs, 1):
        need = _substitute_placeholders(raw_need, prev_short_answers)

        if need != raw_need:
            L.log(f"\n[Step 2.{step_idx}] Sub-question (filled): {need}")
        else:
            L.log(f"\n[Step 2.{step_idx}] Sub-question: {need}")

        # 2a — pure vector search
        nodes = _vector_search_all(need, min_score=min_score)
        L.log(f"  Retrieved {len(nodes)} candidates (min_score={min_score}).")

        # 2b — per-candidate LLM filter
        verified: list[dict] = []
        for node in nodes:
            text = _node_text(node)
            if not text:
                continue
            node_name = node.get("name", "?")
            score = node.get("score", 0.0)
            check_prompt = (
                f"GOAL: We are trying to answer: {question}\n\n"
                f"SUB-QUESTION: To do that, we need to know: {need}\n\n"
                f"PASSAGE:\n{text}\n\n"
                f"Does this passage specifically answer the sub-question? Reply YES or NO only."
            )
            is_answer = _ask_llm_yes_no(check_prompt)
            status = "✓ YES" if is_answer else "  no "
            L.log(
                f"    {status}  [{node_name}] (sim={score:.2f}) "
                f"{text[:80].replace(chr(10), ' ')}..."
            )
            if is_answer:
                verified.append(node)

        L.log(f"  → {len(verified)} verified answer(s) for sub-question {step_idx}.")

        # 2c — extract short answer for placeholder relay
        short_answer = ""
        if verified:
            short_answer = _extract_name_only(need, verified)
            L.log(f"  → Short answer extracted: '{short_answer}'")
        prev_short_answers.append(short_answer)

        step_records.append({
            "sub_question": need,
            "candidates": len(nodes),
            "verified_nodes": verified,
            "verified_texts": [_node_text(n) for n in verified],
            "short_answer": short_answer,
        })

        # 2d — early stopping: can we already answer the original question?
        is_last_step = (step_idx == len(info_needs))
        if not is_last_step:
            can_stop, candidate_answer = _check_early_stop(question, step_records)
            if can_stop and candidate_answer:
                L.log(f"\n  [Early stop] Question answerable after step {step_idx}.")
                L.log(f"  [Early stop] Answer: '{candidate_answer}'")
                early_stopped = True
                early_answer = candidate_answer
                break

    # ── Step 3: synthesis ────────────────────────────────────────────────────
    L.log(f"\n[Step 3] Final synthesis...")

    if early_stopped and early_answer:
        final_answer = early_answer
        L.log(f"  (used early-stop answer)")
    else:
        final_answer = _synthesize(question, step_records)

    L.log(f"\n  FINAL ANSWER : {final_answer}")
    L.log(f"  EXPECTED     : {expected}")

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
        "early_stopped": early_stopped,
        "steps": [
            {
                "sub_question": r["sub_question"],
                "candidates": r["candidates"],
                "verified_count": len(r["verified_nodes"]),
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
        description="Hop-Pipeline v2: pure vector search + early stopping"
    )
    parser.add_argument("--dataset", default="hotpotqa", choices=["hotpotqa", "musique"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-score", type=float, default=0.5,
                        help="Minimum cosine similarity for vector search (default 0.5)")
    parser.add_argument("--echo", action="store_true",
                        help="Also echo trace to terminal")
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
    score_tag = f"_s{int(args.min_score*100)}"
    results_dir = BENCH_DIR / "results"

    log_path  = results_dir / f"hop2_{args.dataset}{limit_tag}{score_tag}_{timestamp}.txt"
    json_path = results_dir / f"hop2_{args.dataset}{limit_tag}{score_tag}_{timestamp}.json"

    L = Logger(log_path, echo=args.echo)
    L.log(f"Hop-Pipeline v2 — {args.dataset.upper()}")
    L.log(f"Started   : {datetime.now().isoformat()}")
    L.log(f"Questions : {len(test_cases)}")
    L.log(f"Min score : {args.min_score}")
    L.log("=" * 70)

    results = []
    pbar = tqdm(test_cases, desc="Evaluating", unit="q")
    for entry in pbar:
        result = await run_pipeline(entry, L, min_score=args.min_score)
        results.append(result)
        n = len(results)
        fuzzy_n = sum(1 for r in results if r["fuzzy_match"])
        stops   = sum(1 for r in results if r["early_stopped"])
        pbar.set_postfix(fuzzy=f"{fuzzy_n}/{n}", stops=stops)

    L.log()
    L.log("=" * 70)
    L.log("SUMMARY")
    L.log("=" * 70)

    total   = len(results)
    fuzzy_n = sum(1 for r in results if r["fuzzy_match"])
    exact_n = sum(1 for r in results if r["exact_match"])
    stops   = sum(1 for r in results if r["early_stopped"])
    avg_f1  = sum(r["f1"] for r in results) / total if total else 0

    L.log(f"Total         : {total}")
    L.log(f"Fuzzy         : {fuzzy_n}/{total}  ({fuzzy_n/total:.1%})")
    L.log(f"Exact         : {exact_n}/{total}  ({exact_n/total:.1%})")
    L.log(f"Avg F1        : {avg_f1:.3f}")
    L.log(f"Early stopped : {stops}/{total}")

    failures = [r for r in results if not r["fuzzy_match"]]
    L.log(f"\nFailures  : {len(failures)}")
    for r in failures:
        L.log(f"  ✗  {r['question'][:65]}...")
        L.log(f"       Expected : {r['expected']}")
        L.log(f"       Got      : {r['final_answer'][:80]}")
        L.log()

    L.close()

    # JSON output
    results_dir.mkdir(exist_ok=True)
    with open(json_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "dataset": args.dataset,
            "min_score": args.min_score,
            "num_tests": total,
            "metrics": {
                "fuzzy_match": fuzzy_n / total,
                "exact_match": exact_n / total,
                "avg_f1": avg_f1,
                "early_stopped": stops,
            },
            "results": results,
        }, f, indent=2)

    print(f"\n{'='*60}")
    print(f"RESULTS  ({args.dataset.upper()}, {total} questions, min_score={args.min_score})")
    print(f"{'='*60}")
    print(f"  Fuzzy Match   : {fuzzy_n}/{total}  ({fuzzy_n/total:.1%})")
    print(f"  Exact Match   : {exact_n}/{total}  ({exact_n/total:.1%})")
    print(f"  Avg F1        : {avg_f1:.3f}")
    print(f"  Early stopped : {stops}/{total}")
    print(f"\n  Log  → {log_path}")
    print(f"  JSON → {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
