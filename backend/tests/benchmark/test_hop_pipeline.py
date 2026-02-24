"""
Careful Multi-Hop Retrieval Pipeline — diagnostic test for first 5 HotPotQA questions.

For each question the pipeline:
  1. Asks the LLM what sub-questions need to be answered (info needs).
  2. For each sub-question:
       a. Searches the graph (hybrid_search) with a generous top_k.
       b. For every candidate result, asks the LLM "does this specifically answer
          the sub-question?" and keeps only the ones that pass.
       c. If a subsequent sub-question has a [placeholder], substitutes in the
          verified short-answer(s) from the previous step.
  3. Presents the original question + all sub-questions + verified evidence to the
     LLM for final synthesis.
"""

import asyncio
import json
import re
import sys
import os
from pathlib import Path

# ── allow running from anywhere inside the backend tree ─────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.retrieval import retrieval_service
from app.services.llm import llm_service
from tests.benchmark.evaluate import compute_answer_f1, extract_answer_from_response

# ── first 5 questions from the latest benchmark run ─────────────────────────
HOTPOT_QUESTIONS = [
    {
        "question": "Were Scott Derrickson and Ed Wood of the same nationality?",
        "expected": "yes",
    },
    {
        "question": "What government position was held by the woman who portrayed Corliss Archer in the film Kiss and Tell?",
        "expected": "Chief of Protocol",
    },
    {
        "question": "What science fantasy young adult series, told in first person, has a set of companion books narrating the stories of enslaved worlds and alien species?",
        "expected": "Animorphs",
    },
    {
        "question": "Are the Laleli Mosque and Esma Sultan Mansion located in the same neighborhood?",
        "expected": "no",
    },
    {
        "question": 'The director of the romantic comedy "Big Stone Gap" is based in what New York city?',
        "expected": "Greenwich Village, New York City",
    },
]

TOP_K = 20  # candidates per sub-question search


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _candidate_text(doc: dict) -> str:
    """Return plain text for a retrieved doc in the format 'node_name: summary'.

    Uses the raw node summary instead of the retrieval-formatted text so the LLM
    doesn't see internal labels like [Consensus - Entity: ...] or [Node: ...].
    """
    node = doc.get("original_obj", {})
    name = node.get("name", "")
    summary = node.get("summary") or node.get("description", "")
    if name and summary:
        return f"{name}: {summary}"
    if name:
        return name
    return doc.get("text", "").strip()


def _ask_llm_yes_no(prompt: str) -> bool:
    """Synchronously call the LLM and return True if the answer starts with YES."""
    model = llm_service._get_model_for_task("reasoning")
    try:
        if llm_service.provider == "gemini":
            from google.genai import types

            resp = llm_service.gemini_client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=10),
            )
            ans = resp.text.strip().upper()
        else:
            extra_body = {"keep_alive": -1} if llm_service.provider == "ollama" else {}
            resp = llm_service.chat_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10,
                extra_body=extra_body,
            )
            ans = resp.choices[0].message.content.strip().upper()
        return ans.startswith("YES")
    except Exception as e:
        print(f"      [LLM] yes/no call failed: {e}")
        return False


def _ask_llm_text(prompt: str, max_tokens: int = 300) -> str:
    """Synchronously call the LLM and return the response text."""
    model = llm_service._get_model_for_task("reasoning")
    try:
        if llm_service.provider == "gemini":
            from google.genai import types

            resp = llm_service.gemini_client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0, max_output_tokens=max_tokens
                ),
            )
            return resp.text.strip()
        else:
            extra_body = {"keep_alive": -1} if llm_service.provider == "ollama" else {}
            resp = llm_service.chat_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=max_tokens,
                extra_body=extra_body,
            )
            return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"      [LLM] text call failed: {e}")
        return ""


def _extract_name_only(
    question: str, verified_docs: list[dict], original_question: str = ""
) -> str:
    """Return a short value that answers the sub-question.

    original_question is the top-level question and is used to infer the
    required granularity of the answer.  For example, if the original question
    asks about neighborhoods, a location answer should be extracted at
    neighborhood level rather than returning the full address.
    """
    context = "\n\n".join(_candidate_text(d) for d in verified_docs[:3])
    granularity_hint = ""
    if original_question:
        granularity_hint = (
            f'\nIMPORTANT: The final question is: "{original_question}"\n'
            f"Extract only the part of the answer that is relevant to that "
            f"question's granularity (e.g. if the final question compares "
            f"neighborhoods, return the neighborhood name only — not the full address)."
        )
    prompt = (
        f"Answer the question below with ONLY the name or value — "
        f"no sentence, no explanation.{granularity_hint}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"ANSWER (1–6 words):"
    )
    return _ask_llm_text(prompt, max_tokens=20).split("\n")[0].strip()


def _substitute_placeholders(text: str, prev_answers: list[str]) -> str:
    """Replace all [placeholder] tokens with the most recent previous answer."""
    if prev_answers and re.search(r"\[[^\]]+\]", text):
        latest = prev_answers[-1]
        text = re.sub(r"\[[^\]]+\]", latest, text)
    return text


# Matches loose back-references like "that series", "those companion books", "the author"
# Allows an optional intervening word (e.g. "those companion books", "that same person")
def _rewrite_back_references(sub_questions: list[str]) -> list[str]:
    """Post-process sub-questions to replace vague back-references with [placeholder].

    Every sub-question after the first is passed to the LLM which returns it
    unchanged if there is nothing to rewrite.  This is intentionally open-ended
    so that back-references like 'that car', 'that building', 'the company', etc.
    are caught — not just the limited set a regex could enumerate.
    """
    if not sub_questions:
        return []
    rewritten = [sub_questions[0]]
    for q in sub_questions[1:]:
        prompt = (
            f"Rewrite this question by replacing ANY vague reference to an "
            f"unspecified entity — i.e. a noun phrase that uses a definite article or "
            f"demonstrative ('that', 'the', 'those', 'this') to point at something "
            f"that is NOT named or defined anywhere in the question itself "
            f"(e.g. 'that series', 'the film', 'that car', 'the author', 'this work') "
            f"— with a [placeholder] token in square brackets.\n"
            f"If every noun phrase in the question refers to a clearly named entity, "
            f"return the question UNCHANGED.\n\n"
            f"QUESTION: {q}\n\n"
            f"REWRITTEN (one line only):"
        )
        result = _ask_llm_text(prompt, max_tokens=60).split("\n")[0].strip()
        final = result if result else q
        if final != q:
            print(f"  [back-ref rewrite] '{q}' → '{final}'")
        rewritten.append(final)
    return rewritten


# ─────────────────────────────────────────────────────────────────────────────
#  Core pipeline
# ─────────────────────────────────────────────────────────────────────────────


async def run_pipeline(entry: dict) -> dict:
    question = entry["question"]
    expected = entry["expected"]

    print(f"\n{'='*70}")
    print(f"QUESTION : {question}")
    print(f"EXPECTED : {expected}")
    print(f"{'='*70}")

    # ── Step 1: decompose into sub-questions ─────────────────────────────────
    info_needs = await llm_service.identify_information_needs(question)
    info_needs = _rewrite_back_references(
        info_needs
    )  # Q3: convert back-refs → [placeholder]
    print(f"\n[Step 1] Sub-questions identified ({len(info_needs)}):")
    for i, n in enumerate(info_needs, 1):
        print(f"  {i}. {n}")

    # ── Step 2: for each sub-question, retrieve → filter ─────────────────────
    step_records = []  # one dict per sub-question
    prev_short_answers = []  # short entity answers for placeholder substitution

    for step_idx, raw_need in enumerate(info_needs, 1):
        # substitute any [placeholder] from the previous step
        need = _substitute_placeholders(raw_need, prev_short_answers)

        if need != raw_need:
            print(f"\n[Step 2.{step_idx}] Sub-question (filled): {need}")
        else:
            print(f"\n[Step 2.{step_idx}] Sub-question: {need}")

        # 2a – retrieve candidates
        docs = await retrieval_service.hybrid_search(need, top_k=TOP_K)

        # 2b – for each candidate, ask LLM whether it answers the sub-question
        verified = []
        for doc_idx, doc in enumerate(docs):
            text = _candidate_text(doc)
            if not text:
                continue
            node_name = doc.get("original_obj", {}).get("name", "?")
            check_prompt = (
                f"GOAL: We are trying to answer: {question}\n\n"
                f"SUB-QUESTION: To do that, we need to know: {need}\n\n"
                f"PASSAGE:\n{text}\n\n"
                f"Does this passage contain explicit text that answers the sub-question? "
                f"Judge ONLY by what is written in the passage — do NOT use outside knowledge. "
                f"Reply YES or NO only."
            )
            is_answer = _ask_llm_yes_no(check_prompt)
            if is_answer:
                verified.append(doc)

        print(f"  Potential answers:")
        if verified:
            for doc in verified:
                node_name = doc.get("original_obj", {}).get("name", "?")
                obj = doc.get("original_obj", {})
                raw = (obj.get("summary") or doc.get("text", "")).strip()
                clean = re.sub(r"^\[.*?\](?:\s*\([^)]*\))?\s*:\s*", "", raw).strip()
                print(f"    {node_name}: {clean}")
        else:
            print(f"    (none)")

        # 2c – extract short name for next-step placeholder substitution
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
                "verified_texts": [_candidate_text(d) for d in verified],
                "short_answer": short_answer,
            }
        )

    # ── Step 3: final synthesis ───────────────────────────────────────────────
    print(f"\n[Step 3] Final synthesis...")

    # Build synthesis input — sub-question + full evidence, same format as the logs
    synthesis_parts = []
    for i, rec in enumerate(step_records, 1):
        synthesis_parts.append(f"Sub-question {i}: {rec['sub_question']}")
        if rec["verified_docs"]:
            for doc in rec["verified_docs"]:
                node_name = doc.get("original_obj", {}).get("name", "?")
                obj = doc.get("original_obj", {})
                raw = (obj.get("summary") or doc.get("text", "")).strip()
                clean = re.sub(r"^\[.*?\](?:\s*\([^)]*\))?\s*:\s*", "", raw).strip()
                synthesis_parts.append(f"  - {node_name}: {clean}")
        else:
            synthesis_parts.append("  (no answers found)")
        synthesis_parts.append("")

    synthesis_block = "\n".join(synthesis_parts)

    synthesis_prompt = (
        f"You are answering a multi-hop question using retrieved evidence below.\n\n"
        f"{synthesis_block}"
        f"Final question: {question}\n\n"
        f"Use the specific details in the evidence above to answer precisely.\n"
        f"RULE 1 (YES/NO): If the question asks whether two things share the same property, "
        f"extract the specific value for each from the evidence (e.g. the exact neighborhood, "
        f"not just the city), then compare. ALL same \u2192 YES. ANY differ \u2192 NO. "
        f"Never output the compared value.\n"
        f"RULE 2 (COMPARISON): If the question asks which had more/fewer/greater/less/older/younger, "
        f"compare the values, then output the WINNER\u2019S NAME \u2014 not the metric. "
        f"For age: born in an EARLIER year = OLDER (e.g. born 1965 is older than born 1970).\n"
        f"RULE 3 (MULTI-HOP): The final answer comes from the last relevant sub-question. "
        f"Bridge entities found along the way are NOT the final answer.\n"
        f"RULE 4 (ANSWER TYPE): Match the exact type of thing the question asks for \u2014 "
        f"never substitute a related entity:\n"
        f"  - \u201cWhat song/award/title/distinction...\u201d \u2192 output the song/award/title, NOT the person associated with it\n"
        f"  - \u201cHow many / what population...\u201d \u2192 output the number, NOT the entity being counted\n"
        f"  - \u201cWhat city/neighbourhood...\u201d \u2192 output the city/location, NOT a building or institution inside it\n"
        f"  - \u201cWhat position/role/office...\u201d \u2192 output the title, NOT the person who held it\n"
        f"RULE 5 (SPECIFICITY): Use the most specific value the evidence supports. "
        f"If the evidence says \u201cformed in Fujioka, Gunma\u201d, answer with \u201cFujioka, Gunma\u201d \u2014 not \u201cJapan\u201d. "
        f"If the evidence gives a specific street/neighbourhood, do not broaden to city or country.\n"
        f"RULE 6 (PAST vs CURRENT): If the question asks about a past or former state "
        f"(e.g. \u201cformerly known as\u201d, \u201cfrom 1988 to 1996\u201d, \u201cat the time\u201d), answer with "
        f"the historical value from that period \u2014 not the current name or current value.\n\n"
        f"First write 1-2 sentences of reasoning that end with a clear statement "
        f"of your answer, then on a new line write:\n"
        f"FINAL: <your answer (must match the conclusion in your reasoning)>"
    )

    raw_response = _ask_llm_text(synthesis_prompt, max_tokens=300)

    # Parse reasoning and final answer
    reasoning = raw_response.strip()
    final_answer = raw_response.strip()
    if "FINAL:" in raw_response:
        parts = raw_response.split("FINAL:", 1)
        reasoning = parts[0].strip()
        final_answer = parts[1].strip().split("\n")[0].strip()

    print(f"\n  REASONING    : {reasoning}")
    print(f"  FINAL ANSWER : {final_answer}")
    print(f"  EXPECTED     : {expected}")

    # fuzzy check: standard word-overlap OR F1 >= 0.5 (catches aliases / partial dates)
    exp_lower = expected.lower()
    ans_lower = final_answer.lower()
    exp_words = [w for w in exp_lower.split() if len(w) > 3]
    extracted = extract_answer_from_response(final_answer)
    f1 = compute_answer_f1(extracted, expected)
    fuzzy_pass = (
        (exp_lower in ans_lower)
        or (ans_lower in exp_lower)
        or (bool(exp_words) and all(w in ans_lower for w in exp_words))
        or f1 >= 0.5
    )
    print(f"  F1           : {f1:.2f}")
    print(f"  FUZZY PASS   : {fuzzy_pass}")

    return {
        "question": question,
        "expected": expected,
        "final_answer": final_answer,
        "fuzzy_pass": fuzzy_pass,
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
    results = []
    for entry in HOTPOT_QUESTIONS:
        result = await run_pipeline(entry)
        results.append(result)

    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for r in results if r["fuzzy_pass"])
    print(f"Passed: {passed} / {len(results)}")
    for r in results:
        mark = "✓" if r["fuzzy_pass"] else "✗"
        print(f"  {mark}  Q: {r['question'][:60]}...")
        print(f"       Expected: {r['expected']}")
        print(f"       Got:      {r['final_answer'][:80]}")
        print()

    # save to file
    out_path = Path(__file__).parent / "results" / "hop_pipeline_test.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
