"""
Hop-Pipeline v5 — same as v4 but with all token limits removed.

Changes from v4:
  - All LLM calls use max_tokens=2048 (no effective limit)
  - Local overrides of _extract_name_only and _rewrite_back_references
    to raise their hardcoded limits from 20/60 to 2048
  - Allows gemma3 to write full reasoning before FINAL: without truncation

Usage:
    python tests/benchmark/evaluate_hop_pipeline_v5.py
    python tests/benchmark/evaluate_hop_pipeline_v5.py --limit 20 --echo
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

# ── reuse helpers from the hop-pipeline test ─────────────────────────────────
from tests.benchmark.test_hop_pipeline import (  # noqa: E402
    _ask_llm_yes_no,
    _ask_llm_text,
    _substitute_placeholders,
    _candidate_text,
    TOP_K,
    _BACK_REF_RE,
)

# ── metrics from evaluate.py ─────────────────────────────────────────────────
from tests.benchmark.evaluate import (  # noqa: E402
    fuzzy_match,
    normalize_answer,
    compute_answer_f1,
    extract_answer_from_response,
)

from app.services.retrieval import retrieval_service  # noqa: E402
from app.services.llm import llm_service  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  Logger  (identical to v4)
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
#  Helpers  (token-limit-free overrides)
# ─────────────────────────────────────────────────────────────────────────────

_NO_LIMIT = 2048


def _clean_text(doc: dict) -> str:
    """Return clean node summary text, stripping retrieval metadata prefixes."""
    obj = doc.get("original_obj", {})
    raw = (obj.get("summary") or doc.get("text", "")).strip()
    return re.sub(r"^\[.*?\](?:\s*\([^)]*\))?\s*:\s*", "", raw).strip()


def _is_fuzzy_pass(expected: str, final_answer: str, f1: float) -> bool:
    return fuzzy_match(expected, final_answer) or f1 >= 0.4


def _extract_name_only(
    question: str, verified_docs: list[dict], original_question: str = ""
) -> str:
    """Short-answer extractor — no token limit."""
    context = "\n\n".join(_candidate_text(d) for d in verified_docs[:3])
    granularity_hint = ""
    if original_question:
        granularity_hint = (
            f'\nIMPORTANT: The final question is: "{original_question}"\n'
            "Extract only the part of the answer that is relevant to that "
            "question's granularity (e.g. if the final question compares "
            "neighborhoods, return the neighborhood name only — not the full address)."
        )
    prompt = (
        f"Answer the question below with ONLY the name or value — "
        f"no sentence, no explanation.{granularity_hint}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"ANSWER (1–6 words):"
    )
    return _ask_llm_text(prompt, max_tokens=_NO_LIMIT).split("\n")[0].strip()


def _rewrite_back_references(sub_questions: list[str]) -> list[str]:
    """Replace vague back-references with [placeholder] — no token limit."""
    rewritten = []
    for i, q in enumerate(sub_questions):
        if i == 0 or not _BACK_REF_RE.search(q):
            rewritten.append(q)
            continue
        prompt = (
            f"Rewrite this question by replacing vague back-references "
            f"('that series', 'those books', 'those companion books', 'the film', "
            f"'the author', 'that person', 'this work', etc.) "
            f"with a [placeholder] token in square brackets.\n"
            f"If there is no vague back-reference, return the question unchanged.\n\n"
            f"QUESTION: {q}\n\n"
            f"REWRITTEN (one line only):"
        )
        result = _ask_llm_text(prompt, max_tokens=_NO_LIMIT).split("\n")[0].strip()
        rewritten.append(result if result else q)
    return rewritten


def _identify_answer_type(question: str) -> str:
    prompt = (
        f"What type of answer does this question require? "
        f"Reply with one short phrase only — nothing else.\n"
        f"Examples: 'a year', 'a person\\'s name', 'a song or album title', "
        f"'yes or no', 'a number or count', 'a place name', "
        f"'a job title or role', 'an award or distinction', 'a company name'.\n\n"
        f"Question: {question}\n\nAnswer type:"
    )
    return _ask_llm_text(prompt, max_tokens=_NO_LIMIT).strip()


# ─────────────────────────────────────────────────────────────────────────────
#  Synthesis prompt  (identical to v4)
# ─────────────────────────────────────────────────────────────────────────────

SYNTHESIS_RULES = """\
Use the specific details in the evidence above to answer precisely.
RULE 1 (YES/NO): If the question asks whether two things share the same property, \
extract the specific value for each from the evidence (e.g. the exact neighborhood, \
not just the city), then compare. ALL same → YES. ANY differ → NO. \
Never output the compared value.
RULE 2 (COMPARISON): If the question asks which had more/fewer/greater/less/older/younger, \
compare the values, then output the WINNER'S NAME — not the metric. \
For age: born in an EARLIER year = OLDER (e.g. born 1965 is older than born 1970).
RULE 3 (MULTI-HOP): The final answer comes from the last relevant sub-question. \
Bridge entities found along the way are NOT the final answer.
RULE 4 (ANSWER TYPE): Match the exact type of thing the question asks for — \
never substitute a related entity:
  - "What song/award/title/distinction..." → output the song/award/title, NOT the person associated with it
  - "How many / what population..." → output the number, NOT the entity being counted
  - "What city/neighbourhood..." → output the city/location, NOT a building or institution inside it
  - "What position/role/office..." → output the title, NOT the person who held it
RULE 5 (SPECIFICITY): Use the most specific value the evidence supports. \
If the evidence says "formed in Fujioka, Gunma", answer with "Fujioka, Gunma" — not "Japan". \
If the evidence gives a specific street/neighbourhood, do not broaden to city or country.
RULE 6 (PAST vs CURRENT): If the question asks about a past or former state \
(e.g. "formerly known as", "from 1988 to 1996", "at the time"), answer with \
the historical value from that period — not the current name or current value."""


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline
# ─────────────────────────────────────────────────────────────────────────────


async def run_pipeline(entry: dict, L: Logger) -> dict:
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

    # ── Step 2: retrieve → filter per sub-question ───────────────────────────
    step_records = []
    prev_short_answers: list[str] = []

    for step_idx, raw_need in enumerate(info_needs, 1):
        need = _substitute_placeholders(raw_need, prev_short_answers)

        if need != raw_need:
            L.log(f"\n[Step 2.{step_idx}] Sub-question (filled): {need}")
        else:
            L.log(f"\n[Step 2.{step_idx}] Sub-question: {need}")

        docs = await retrieval_service.hybrid_search(need, top_k=TOP_K)

        verified = []
        for doc in docs:
            text = _candidate_text(doc)
            if not text:
                continue
            check_prompt = (
                f"GOAL: We are trying to answer: {question}\n\n"
                f"SUB-QUESTION: To do that, we need to know: {need}\n\n"
                f"PASSAGE:\n{text}\n\n"
                f"Does this passage contain explicit text that answers the sub-question? "
                f"Judge ONLY by what is written in the passage — do NOT use outside knowledge. "
                f"Reply YES or NO only."
            )
            if _ask_llm_yes_no(check_prompt):
                verified.append(doc)

        L.log(f"  Potential answers:")
        if verified:
            for doc in verified:
                node_name = doc.get("original_obj", {}).get("name", "?")
                L.log(f"    {node_name}: {_clean_text(doc)}")
        else:
            L.log(f"    (none)")

        short_answer = ""
        if verified:
            short_answer = _extract_name_only(
                need, verified, original_question=question
            )
        prev_short_answers.append(short_answer)

        step_records.append(
            {
                "sub_question": need,
                "candidates": len(docs),
                "verified_docs": verified,
                "short_answer": short_answer,
            }
        )

    # ── Step 3: synthesis ────────────────────────────────────────────────────
    answer_type = _identify_answer_type(question)
    L.log(f"\n[Step 3] Final synthesis... (answer type: {answer_type})")

    synthesis_parts = []
    for i, rec in enumerate(step_records, 1):
        synthesis_parts.append(f"Sub-question {i}: {rec['sub_question']}")
        if rec["verified_docs"]:
            for doc in rec["verified_docs"]:
                node_name = doc.get("original_obj", {}).get("name", "?")
                synthesis_parts.append(f"  - {node_name}: {_clean_text(doc)}")
        else:
            synthesis_parts.append("  (no answers found)")
        synthesis_parts.append("")

    synthesis_block = "\n".join(synthesis_parts)

    synthesis_prompt = (
        f"You are answering a multi-hop question using retrieved evidence below.\n\n"
        f"{synthesis_block}"
        f"Final question: {question}\n\n"
        f"ANSWER TYPE CONSTRAINT: This question requires {answer_type}. "
        f"Your FINAL: answer MUST be {answer_type} — do not substitute a related "
        f"entity, person, or broader concept instead.\n\n"
        f"{SYNTHESIS_RULES}\n\n"
        f"First write 1-2 sentences of reasoning that end with a clear statement "
        f"of your answer, then on a new line write:\n"
        f"FINAL: <your answer (must match the conclusion in your reasoning)>"
    )

    raw_response = _ask_llm_text(synthesis_prompt, max_tokens=_NO_LIMIT)

    reasoning = raw_response.strip()
    final_answer = raw_response.strip()
    if "FINAL:" in raw_response:
        parts = raw_response.split("FINAL:", 1)
        reasoning = parts[0].strip()
        final_answer = parts[1].strip().split("\n")[0].strip()

    L.log(f"\n  REASONING    : {reasoning}")
    L.log(f"  FINAL ANSWER : {final_answer}")
    L.log(f"  EXPECTED     : {expected}")

    extracted = extract_answer_from_response(final_answer)
    f1 = compute_answer_f1(extracted, expected)
    is_fuzzy = _is_fuzzy_pass(expected, final_answer, f1)
    is_exact = normalize_answer(expected) == normalize_answer(extracted)

    L.log(f"  FUZZY PASS   : {is_fuzzy}")
    L.log(f"  EXACT MATCH  : {is_exact}")
    L.log(f"  F1           : {f1:.2f}")

    return {
        "id": entry.get("id", ""),
        "question": question,
        "expected": expected,
        "final_answer": final_answer,
        "reasoning": reasoning,
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
        description="Hop-Pipeline v5: no token limits on any LLM call"
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
    log_path = results_dir / f"hop_v5_{args.dataset}{limit_tag}_{timestamp}.txt"
    json_path = results_dir / f"hop_v5_{args.dataset}{limit_tag}_{timestamp}.json"

    L = Logger(log_path, echo=args.echo)
    L.log(f"Hop-Pipeline v5 — {args.dataset.upper()}")
    L.log(f"Started   : {datetime.now().isoformat()}")
    L.log(f"Questions : {len(test_cases)}")
    L.log("=" * 70)

    results = []
    pbar = tqdm(test_cases, desc="Evaluating", unit="q")
    for entry in pbar:
        result = await run_pipeline(entry, L)
        results.append(result)
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
