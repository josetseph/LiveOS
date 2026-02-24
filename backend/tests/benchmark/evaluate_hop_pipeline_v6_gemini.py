"""
Hop-Pipeline v6 (Gemini) — Google Gemini-backed evaluator.

Mirrors evaluate_hop_pipeline_v4.py exactly in logic and output format, but
replaces all local Ollama/gemma3 calls with Google Gemini API calls.
Questions are processed sequentially, exactly like the gemma3 v4 evaluator.

Usage:
    python tests/benchmark/evaluate_hop_pipeline_v6_gemini.py
    python tests/benchmark/evaluate_hop_pipeline_v6_gemini.py --limit 20 --echo
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

# ── path setup ───────────────────────────────────────────────────────────────
BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parents[1]))

# ── load .env manually (avoids requiring python-dotenv) ──────────────────────
_ENV_PATH = BENCH_DIR.parents[1] / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not set in .env or environment.")
    sys.exit(1)

# ── google-genai ─────────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    print("ERROR: google-genai package not installed.  Run:  pip install google-genai")
    sys.exit(1)

# Synchronous client — matches llm.py exactly.
# 30-minute HTTP timeout (1 800 000 ms) so long prompts never time out.
_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=genai_types.HttpOptions(timeout=1800000),
)


# ── reuse non-LLM helpers from v4 and evaluate.py ────────────────────────────
from tests.benchmark.evaluate_hop_pipeline_v4 import (  # noqa: E402
    _clean_text,
    _is_fuzzy_pass,
    SYNTHESIS_RULES,
    Logger,
)
from tests.benchmark.evaluate import (  # noqa: E402
    fuzzy_match,
    normalize_answer,
    compute_answer_f1,
    extract_answer_from_response,
)
from tests.benchmark.test_hop_pipeline import (  # noqa: E402
    _substitute_placeholders,
    _candidate_text,
    TOP_K,
)
from app.services.retrieval import retrieval_service  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  Async Gemini helpers
# ─────────────────────────────────────────────────────────────────────────────


def _gemini_text_sync(
    prompt: str,
    temperature: float = 0.0,
) -> str:
    """Synchronous Gemini call using streaming — matches the official API example.

    Uses the sync client.models.generate_content_stream exactly as shown in
    the Google docs. No thinking, no tools, no search.
    Retries with capped backoff: 2s, 4s, 6s, … up to 30s.
    """
    contents = [
        genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=prompt)],
        )
    ]
    cfg_kwargs: dict = {"temperature": temperature}
    cfg = genai_types.GenerateContentConfig(**cfg_kwargs)

    attempt = 0
    while True:
        try:
            full_text: list[str] = []
            for chunk in _client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=contents,
                config=cfg,
            ):
                if chunk.text:
                    full_text.append(chunk.text)
            return "".join(full_text).strip()
        except Exception as e:
            attempt += 1
            wait = min(2 * attempt, 30)
            print(f"\n  [Gemini] attempt {attempt} failed: {type(e).__name__}: {e}")
            print(f"  [Gemini] retrying in {wait}s...")
            time.sleep(wait)


async def _gemini_text(
    prompt: str,
    temperature: float = 0.0,
) -> str:
    """Run the sync Gemini call in a thread so retrieval (async) can overlap."""
    return await asyncio.to_thread(_gemini_text_sync, prompt, temperature)


async def _gemini_yes_no(prompt: str) -> bool:
    """Call Gemini and return True if answer starts with YES."""
    ans = await _gemini_text(prompt)
    return ans.upper().startswith("YES")


async def _gemini_identify_needs(question: str) -> list[str]:
    """Decompose a multi-hop question into ordered sub-questions.

    Uses the same prompt as llm_service.identify_information_needs().
    """
    prompt = f"""You are a question analysis expert. Analyze this question and identify what intermediate information you would need to find in a knowledge base to answer it.

IMPORTANT CONTEXT:
- This is a PERSONAL knowledge base containing notes, experiences, learnings, and extracted entities
- Information may be incomplete - we can only answer from what exists in the knowledge base
- Focus on finding the MOST CRITICAL intermediate facts needed
- If the question seems unanswerable without external knowledge, still identify what we'd need if it exists

# QUESTION
{question}

# TASK
Break down the question into a sequence of information needs. Each need should be a specific question that, when answered, provides information needed for the final answer.

CRITICAL RULES:
1. PRESERVE SPECIFICITY: If the question mentions specific names, roles, or attributes, KEEP them in your sub-questions
   - Bad: "Who starred in X?" (too vague)
   - Good: "Who portrayed [character name] in X?" (preserves the specific role)
2. DON'T OVER-DECOMPOSE: If the question already tells you something, don't ask about it again
   - If question says "who played the main character in film X", don't ask "what character did they play"
3. PRESERVE QUESTION TYPE: If the original asks "what city?", don't change it to "is X in a city?" (yes/no)
   - Bad: "Is [person] based in New York?"
   - Good: "What city in New York is [person] based in?"
4. NO FINAL COMPARISON QUESTIONS: For "Were X and Y both...?" or "Did X and Y share...", DON'T add a final question asking if they match
   - Just ask about each entity separately - the synthesis will handle the comparison
   - Bad: "1. What is X's nationality? 2. What is Y's nationality? 3. Are they the same?"
   - Good: "1. What is X's nationality? 2. What is Y's nationality?"
5. THINK ABOUT DEPENDENCIES: If question B requires info from question A, list A first
   - Example: Must find "who wrote X" before asking "when was [author] born"
6. Use placeholders like [actress], [director], [person], [author] for entities discovered in previous steps
   - These will be filled in with actual names as we retrieve
   - NEVER use vague back-references like "that series", "that person", "the author", "the director"
   - Bad:  "2. Within that series, what are the companion books called?"
   - Good: "2. What companion books are part of [series]?"
7. Keep it simple - usually 1-3 information needs (rarely 4+)
   - If the question already contains ALL the filter criteria needed to describe the entity ("What [type] that [has X] and [does Y]?"), it is a SINGLE-HOP question — the ENTIRE question is itself the lookup. Do NOT break it into sub-questions.
   - Example of SINGLE-HOP: "What science fantasy series told in first person has companion books about enslaved alien worlds?"
     → 1 need: "What science fantasy series told in first person has companion books about enslaved alien worlds?"
   - Example of TWO-HOP: "What award did the author of X win?" (need to find the author first, then the award)
   - Single-hop: 1 need (direct fact lookup)
   - Two-hop: 2 needs (find entity, then find fact about entity)
   - Three-hop: 3 needs (rare, only for very complex chains)
8. Return ONLY the list of questions, one per line, numbered

# EXAMPLES
Question: "What university did the founder of Tesla attend?"
Information Needs:
1. Who founded Tesla?
2. What university did [founder] attend?

Question: "Were Marie Curie and Albert Einstein both born in Europe?"
Information Needs:
1. Where was Marie Curie born?
2. Where was Albert Einstein born?

Question: "The author who wrote 'Pride and Prejudice' lived in what English county?"
Information Needs:
1. Who wrote 'Pride and Prejudice'?
2. What English county did [author] live in?

Question: "What award did the physicist who discovered radioactivity receive?"
Information Needs:
1. Who discovered radioactivity?
2. What award did [physicist] receive?

Question: "When was the film directed by Christopher Nolan released?"
Information Needs:
1. What film did Christopher Nolan direct?
2. When was [film] released?

Question: "What young adult series is told in first person and has companion books about enslaved alien worlds?"
Information Needs:
1. What young adult series is told in first person and has companion books about enslaved alien worlds?

Now analyze the question above and list the information needs:
"""
    raw = await _gemini_text(prompt, temperature=0.1)
    needs = []
    for line in raw.split("\n"):
        m = re.match(r"^\d+[\.\)]\s+(.+)$", line.strip())
        if m:
            needs.append(m.group(1).strip())
    if not needs:
        needs = [ln.strip() for ln in raw.split("\n") if ln.strip().endswith("?")]
    return needs if needs else [question]


async def _gemini_rewrite_back_refs(sub_questions: list[str]) -> list[str]:
    """Ask the LLM to replace any vague back-reference with [placeholder].

    Every sub-question after the first is sent to the LLM which returns it
    unchanged if there is nothing to rewrite.  Open-ended so that references
    like 'that car', 'that building', 'the company', etc. are caught.
    """
    if not sub_questions:
        return []
    rewritten = [sub_questions[0]]
    for q in sub_questions[1:]:
        prompt = (
            "Rewrite this question by replacing ANY vague reference to an "
            "unspecified entity — i.e. a noun phrase that uses a definite article or "
            "demonstrative ('that', 'the', 'those', 'this') to point at something "
            "that is NOT named or defined anywhere in the question itself "
            "(e.g. 'that series', 'the film', 'that car', 'the author', 'this work') "
            "— with a [placeholder] token in square brackets.\n"
            "If every noun phrase in the question refers to a clearly named entity, "
            "return the question UNCHANGED.\n\n"
            f"QUESTION: {q}\n\nREWRITTEN (one line only):"
        )
        result = (await _gemini_text(prompt)).split("\n")[0].strip()
        rewritten.append(result if result else q)
    return rewritten


async def _gemini_extract_name(
    question: str, verified_docs: list[dict], original_question: str = ""
) -> str:
    """Extract a short answer value from verified docs."""
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
        f"QUESTION: {question}\n\nANSWER (1–6 words):"
    )
    return (await _gemini_text(prompt)).split("\n")[0].strip()


async def _gemini_identify_answer_type(question: str) -> str:
    """Identify the type of answer the question requires."""
    prompt = (
        "What type of answer does this question require? "
        "Reply with one short phrase only — nothing else. No line breaks.\n"
        "Examples: 'a year', 'a person\\'s name', 'a song or album title', "
        "'yes or no', 'a number or count', 'a place name', "
        "'a job title or role', 'an award or distinction', 'a company name'.\n\n"
        f"Question: {question}\n\nAnswer type:"
    )
    raw = await _gemini_text(prompt)
    # Gemini sometimes emits a newline mid-phrase (e.g. "yes or\nno").
    # Collapse all whitespace to single spaces so the synthesis prompt stays intact.
    return " ".join(raw.split())


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
    info_needs = await _gemini_identify_needs(question)
    info_needs = await _gemini_rewrite_back_refs(info_needs)

    L.log(f"\n[Step 1] Sub-questions identified ({len(info_needs)}):")
    for i, n in enumerate(info_needs, 1):
        L.log(f"  {i}. {n}")

    # ── Step 2: retrieve → verify per sub-question ───────────────────────────
    step_records = []
    prev_short_answers: list[str] = []

    for step_idx, raw_need in enumerate(info_needs, 1):
        need = _substitute_placeholders(raw_need, prev_short_answers)

        if need != raw_need:
            L.log(f"\n[Step 2.{step_idx}] Sub-question (filled): {need}")
        else:
            L.log(f"\n[Step 2.{step_idx}] Sub-question: {need}")

        docs = await retrieval_service.hybrid_search(need, top_k=TOP_K)

        # Verify candidates concurrently within this step
        async def _check(doc):
            text = _candidate_text(doc)
            if not text:
                return None
            check_prompt = (
                f"GOAL: We are trying to answer: {question}\n\n"
                f"SUB-QUESTION: To do that, we need to know: {need}\n\n"
                f"PASSAGE:\n{text}\n\n"
                "Does this passage contain explicit text that answers the sub-question? "
                "Judge ONLY by what is written in the passage — do NOT use outside knowledge. "
                "Reply YES or NO only."
            )
            if await _gemini_yes_no(check_prompt):
                return doc
            return None

        verified = []
        for d in docs:
            r = await _check(d)
            if r is not None:
                verified.append(r)

        L.log("  Potential answers:")
        if verified:
            for doc in verified:
                node_name = doc.get("original_obj", {}).get("name", "?")
                L.log(f"    {node_name}: {_clean_text(doc)}")
        else:
            L.log("    (none)")

        short_answer = ""
        if verified:
            short_answer = await _gemini_extract_name(
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
    answer_type = await _gemini_identify_answer_type(question)
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
        "You are answering a multi-hop question using retrieved evidence below.\n\n"
        f"{synthesis_block}"
        f"Final question: {question}\n\n"
        f"ANSWER TYPE CONSTRAINT: This question requires {answer_type}. "
        f"Your FINAL: answer MUST be {answer_type} — do not substitute a related "
        "entity, person, or broader concept instead.\n\n"
        f"{SYNTHESIS_RULES}\n\n"
        "First write 1-2 sentences of reasoning that end with a clear statement "
        "of your answer, then on a new line write:\n"
        "FINAL: <your answer (must match the conclusion in your reasoning)>"
    )

    raw_response = await _gemini_text(synthesis_prompt)

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
        description="Hop-Pipeline v6 (Gemini): sequential Gemini-backed evaluation"
    )
    parser.add_argument(
        "--dataset", default="hotpotqa", choices=["hotpotqa", "musique"]
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--echo", action="store_true")
    parser.add_argument(
        "--resume",
        metavar="JSON",
        default=None,
        help="Path to a previous run's JSON file. Already-completed question IDs are "
        "skipped and the new results are merged with the old ones.",
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
    log_path = results_dir / f"hop_v6_gemini_{args.dataset}{limit_tag}_{timestamp}.txt"
    json_path = (
        results_dir / f"hop_v6_gemini_{args.dataset}{limit_tag}_{timestamp}.json"
    )

    L = Logger(log_path, echo=args.echo)
    L.log(f"Hop-Pipeline v6 (Gemini) — {args.dataset.upper()}")
    L.log(f"Model     : {GEMINI_MODEL}")
    L.log(f"Started   : {datetime.now().isoformat()}")
    L.log(f"Questions : {len(test_cases)}")
    L.log("=" * 70)

    # ── resume: load previously completed results ──────────────────────────
    completed: dict[str, dict] = {}  # id -> result
    if args.resume:
        resume_path = Path(args.resume)
        if resume_path.exists():
            with open(resume_path) as f:
                prev = json.load(f)
            for r in prev.get("results", []):
                completed[r["id"]] = r
            L.log(
                f"Resuming  : loaded {len(completed)} completed results from {resume_path.name}"
            )
            L.log("=" * 70)
        else:
            print(f"Warning: --resume file not found: {resume_path}")

    results: list[dict] = list(completed.values())  # seed with already-done

    def _save_checkpoint():
        """Overwrite the JSON file with current results after every question."""
        total_so_far = len(results)
        fuzzy_so_far = sum(1 for r in results if r["fuzzy_match"])
        exact_so_far = sum(1 for r in results if r["exact_match"])
        f1_so_far = sum(r["f1"] for r in results) / total_so_far if total_so_far else 0
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "model": GEMINI_MODEL,
            "dataset": args.dataset,
            "num_tests": total_so_far,
            "metrics": {
                "fuzzy_match": fuzzy_so_far / total_so_far if total_so_far else 0,
                "exact_match": exact_so_far / total_so_far if total_so_far else 0,
                "avg_f1": f1_so_far,
                "fuzzy_count": fuzzy_so_far,
                "exact_count": exact_so_far,
            },
            "results": results,
        }
        results_dir.mkdir(exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(snapshot, f, indent=2)

    pbar = tqdm(total=len(test_cases), desc="Evaluating", unit="q")
    for entry in test_cases:
        qid = entry.get("id", "")
        if qid in completed:
            pbar.update(1)  # already done in a previous run
            continue
        result = await run_pipeline(entry, L)
        results.append(result)
        _save_checkpoint()  # write after every question
        fuzzy_so_far = sum(1 for r in results if r["fuzzy_match"])
        pbar.set_postfix(fuzzy=f"{fuzzy_so_far}/{len(results)}")
        pbar.update(1)
    pbar.close()

    L.log()
    L.log("=" * 70)
    L.log("SUMMARY")
    L.log("=" * 70)

    total = len(results)
    fuzzy_n = sum(1 for r in results if r["fuzzy_match"])
    exact_n = sum(1 for r in results if r["exact_match"])
    avg_f1 = sum(r["f1"] for r in results) / total if total else 0

    L.log(f"Total      : {total}")
    L.log(f"Model      : {GEMINI_MODEL}")
    L.log(f"Fuzzy      : {fuzzy_n}/{total}  ({fuzzy_n/total:.1%})")
    L.log(f"Exact      : {exact_n}/{total}  ({exact_n/total:.1%})")
    L.log(f"Avg F1     : {avg_f1:.3f}")

    failures = [r for r in results if not r["fuzzy_match"]]
    L.log(f"\nFailures   : {len(failures)}")
    for r in failures:
        L.log(f"  ✗  {r['question'][:65]}...")
        L.log(f"       Expected : {r['expected']}")
        L.log(f"       Got      : {r['final_answer'][:80]}")
        L.log()

    results_dir.mkdir(exist_ok=True)
    summary = {
        "timestamp": datetime.now().isoformat(),
        "model": GEMINI_MODEL,
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
    print(
        f"RESULTS  ({args.dataset.upper()}, {total} questions, model: {GEMINI_MODEL})"
    )
    print(f"{'='*60}")
    print(f"  Fuzzy Match : {fuzzy_n}/{total}  ({fuzzy_n/total:.1%})")
    print(f"  Exact Match : {exact_n}/{total}  ({exact_n/total:.1%})")
    print(f"  Avg F1      : {avg_f1:.3f}")
    print(f"\n  Log  → {log_path}")
    print(f"  JSON → {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
