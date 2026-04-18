from app.services.retrieval import retrieval_service
from app.services.llm import llm_service
from app.core.log import get_logger
import time

logger = get_logger("ChatWorkflow")


def _doc_passage(doc: dict) -> str:
    """Extract the cleanest available text from a retrieved doc for LLM prompts."""
    node = doc.get("original_obj", {})
    text = (
        node.get("summary") or node.get("description") or doc.get("text", "")
    ).strip()
    return text


class ChatWorkflow:
    async def chat(self, user_query: str) -> dict:
        """
        Research-style retrieval loop:

        1. Generate a focused search query for the original question.
        2. Search, filter, expand neighbours, and distill a finding.
        3. Decide whether to answer now or issue a new focused search.
        4. Repeat up to the loop limit, then fall back to a final synthesis.
        """
        start_time = time.perf_counter()
        logger.info(f"\n[Chat] Started processing query: '{user_query}'")

        # ── Research loop retrieval ──────────────────────────────────────────
        t0 = time.perf_counter()
        final_answer, all_docs = await retrieval_service.retrieve_with_self_correction(
            user_query, top_k=50, max_hops=10, filter_docs=False
        )
        logger.info(
            f"[Chat] Research loop retrieval: {len(all_docs)} docs accumulated "
            f"in {time.perf_counter() - t0:.2f}s"
        )

        def _dedupe_docs(docs: list[dict]) -> list[dict]:
            seen_local: set[str] = set()
            deduped: list[dict] = []
            for doc in docs:
                doc_id = (
                    doc.get("original_obj", {}).get("name")
                    or doc.get("note_id")
                    or doc.get("text", "")[:100]
                )
                if doc_id and doc_id not in seen_local:
                    deduped.append(doc)
                    seen_local.add(doc_id)
            return deduped

        async def _run_structured_fallback(
            trigger_reason: str,
        ) -> tuple[str | None, list[dict]]:
            logger.info(
                f"[Chat] Triggering structured sub-question fallback ({trigger_reason})"
            )
            t_fb = time.perf_counter()
            fb_answer, fb_docs = (
                await retrieval_service.retrieve_with_structured_subquestions(
                    user_query,
                    top_k=50,
                )
            )
            logger.info(
                f"[Chat] Structured fallback: {len(fb_docs)} docs in "
                f"{time.perf_counter() - t_fb:.2f}s"
            )
            return fb_answer, fb_docs

        # Deduplicate docs
        unique_docs: list[dict] = _dedupe_docs(all_docs)

        logger.info(f"[Chat] Unique docs: {len(unique_docs)}")
        if unique_docs:
            print(f"\n🔍 CONTEXT ({len(unique_docs)} docs):")
            for i, doc in enumerate(unique_docs[:5]):
                print(
                    f"  {i+1}. [{doc.get('original_obj',{}).get('name','?')}] "
                    f"{_doc_passage(doc)[:150]}..."
                )

        # ── Answer assembly ──────────────────────────────────────────────────
        answer = ""
        if unique_docs:
            # Keep loop retrieval for context discovery, but always run
            # constrained synthesis so we still answer when loop control
            # fails to emit a direct final answer.
            answer_type = await llm_service.identify_answer_type(user_query)
            logger.info(f"[Chat] Answer type: '{answer_type}'")

            t_synth = time.perf_counter()
            synthesized = await llm_service.synthesize(
                unique_docs, user_query, answer_type=answer_type
            )
            logger.info(f"[Chat] Synthesis: {time.perf_counter() - t_synth:.2f}s")

            if synthesized and "FINAL:" in synthesized:
                answer = (
                    synthesized.split("FINAL:", 1)[1].strip().split("\n")[0].strip()
                )
            elif synthesized:
                answer = synthesized.strip().split("\n")[0].strip()

            if not answer and final_answer:
                logger.info(f"[Chat] Falling back to loop answer: '{final_answer}'")
                answer = final_answer

        if not answer:
            fallback_reason = "no loop context" if not unique_docs else "no loop answer"
            fb_answer, fb_docs = await _run_structured_fallback(fallback_reason)

            if fb_docs:
                unique_docs = _dedupe_docs(unique_docs + fb_docs)
                logger.info(f"[Chat] Fallback merged unique docs: {len(unique_docs)}")

            # Prefer synthesis over full merged context so we do not rely
            # on condensed per-step fallback answers.
            if unique_docs:
                answer_type = await llm_service.identify_answer_type(user_query)
                logger.info(f"[Chat] Fallback answer type: '{answer_type}'")
                t_synth_fb = time.perf_counter()
                synthesized_fb = await llm_service.synthesize(
                    unique_docs, user_query, answer_type=answer_type
                )
                logger.info(
                    f"[Chat] Fallback synthesis: {time.perf_counter() - t_synth_fb:.2f}s"
                )
                if synthesized_fb and "FINAL:" in synthesized_fb:
                    answer = (
                        synthesized_fb.split("FINAL:", 1)[1]
                        .strip()
                        .split("\n")[0]
                        .strip()
                    )
                elif synthesized_fb:
                    answer = synthesized_fb.strip().split("\n")[0].strip()

            if not answer and fb_answer:
                logger.info("[Chat] Falling back to structured fallback direct answer.")
                answer = fb_answer

            if not answer:
                answer = (
                    "I couldn't find any relevant context in your brain to answer that."
                    if not unique_docs
                    else "I couldn't find enough information to answer that."
                )
                logger.info(
                    "[Chat] Both primary and fallback retrieval paths exhausted."
                )

        # Append references
        references = self._extract_references(unique_docs)
        if references:
            answer += "\n\n### References\n" + "\n".join(references)

        total_time = time.perf_counter() - start_time
        logger.info(f"[Chat] Total pipeline duration: {total_time:.2f}s\n")

        return {
            "query": user_query,
            "answer": answer,
            "context": unique_docs,
            "information_needs": [user_query],
            "discovered_entities": {},
        }

    async def _verify_candidates(
        self,
        docs: list[dict],
        sub_question: str,
        original_question: str,
    ) -> list[dict]:
        """Per-candidate YES/NO verification (benchmark v4/v5 core pattern).

        For each retrieved doc, ask the LLM: does this passage explicitly
        answer the sub-question (judged only by the passage, not prior knowledge)?
        Candidates that fail are dropped so synthesis receives only relevant docs.
        Both the sub-question AND the original question are provided as GOAL context
        so the LLM can judge relevance at the right level of the chain.
        """
        verified: list[dict] = []
        for doc in docs:
            text = _doc_passage(doc)
            if not text:
                continue
            check_prompt = (
                f"GOAL: We are trying to answer: {original_question}\n\n"
                f"SUB-QUESTION: To do that, we need to know: {sub_question}\n\n"
                f"PASSAGE:\n{text}\n\n"
                "Does this passage contain explicit text that answers the sub-question? "
                "Judge ONLY by what is written in the passage — do NOT use outside knowledge. "
                "Reply YES or NO only."
            )
            try:
                ans = await llm_service.generate(
                    check_prompt, temperature=0.0, max_tokens=10
                )
                if ans.strip().upper().startswith("YES"):
                    verified.append(doc)
            except Exception as e:
                logger.debug(f"[Chat] YES/NO check failed: {e}")
        return verified

    def _extract_references(self, docs: list) -> list:
        """
        Extract unique note references from retrieved documents.
        """
        # Deduplicate references by Note ID
        # Sources: 1) direct note_id on doc (recent notes), 2) linked_notes from graph nodes
        seen_refs = set()
        references = []

        # Debug: Count how many docs have linked_notes
        docs_with_notes = sum(1 for d in docs if d.get("linked_notes"))
        total_linked = sum(len(d.get("linked_notes", [])) for d in docs)
        logger.debug(
            f"[Chat] Reference extraction: {docs_with_notes}/{len(docs)} docs have linked_notes, {total_linked} total notes"
        )

        for d in docs:
            # Source 1: Direct note reference (from recent notes)
            nid = d.get("note_id")
            title = d.get("title") or "Untitled Note"
            if nid and nid not in seen_refs:
                references.append(f"- [{title}](/notes/{nid})")
                seen_refs.add(nid)

            # Source 2: Linked notes from graph nodes (evidence grounding)
            for linked_note in d.get("linked_notes", []):
                lnid = linked_note.get("id")
                ltitle = linked_note.get("title") or "Untitled Note"
                if lnid and lnid not in seen_refs:
                    references.append(f"- [{ltitle}](/notes/{lnid})")
                    seen_refs.add(lnid)

        logger.info(f"[Chat] Found {len(references)} references for response")
        return references


chat_workflow = ChatWorkflow()
