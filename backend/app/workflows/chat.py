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
        Agentic self-correcting retrieval pipeline:

        1. retrieve_with_self_correction runs up to 3 iterative hops:
           - Initial hybrid search (entity match + vector + type-first 2nd-hop expansion)
           - LLM sufficiency check: "Can you answer? If not, what bridge entity is missing?"
           - Targeted bridge-entity search on missing entity → merge → repeat
        2. Identify answer type (yes/no / place / person / year …)
        3. Synthesize with SYNTHESIS_RULES + ANSWER TYPE CONSTRAINT + FINAL: format
        """
        start_time = time.perf_counter()
        logger.info(f"\n[Chat] Started processing query: '{user_query}'")

        # ── Agentic retrieval (self-correcting multi-hop) ─────────────────────
        t0 = time.perf_counter()
        all_retrieved_docs = await retrieval_service.retrieve_with_self_correction(
            user_query, top_k=12, max_hops=3, filter_docs=False
        )
        logger.info(
            f"[Chat] Agentic retrieval: {len(all_retrieved_docs)} docs "
            f"in {time.perf_counter() - t0:.2f}s"
        )
        if all_retrieved_docs:
            top = all_retrieved_docs[0]
            print(
                f"\n🔍 TOP RESULT: [{top.get('original_obj',{}).get('name','?')}] "
                f"{_doc_passage(top)[:200]}..."
            )

        # Deduplicate by node name / note id
        seen_ids: set[str] = set()
        unique_docs: list[dict] = []
        for doc in all_retrieved_docs:
            doc_id = (
                doc.get("original_obj", {}).get("name")
                or doc.get("note_id")
                or doc.get("text", "")[:100]
            )
            if doc_id not in seen_ids:
                unique_docs.append(doc)
                seen_ids.add(doc_id)

        logger.info(
            f"[Chat] Unique docs for synthesis: {len(unique_docs)} "
            f"(from {len(all_retrieved_docs)} total)"
        )
        if unique_docs:
            print(f"\n🔍 FINAL CONTEXT ({len(unique_docs)} docs):")
            for i, doc in enumerate(unique_docs[:5]):
                print(
                    f"  {i+1}. [{doc.get('original_obj',{}).get('name','?')}] "
                    f"{_doc_passage(doc)[:150]}..."
                )

        # ── Step 3: identify answer type + synthesize ────────────────────────
        answer = ""
        if not unique_docs:
            answer = (
                "I couldn't find any relevant context in your brain to answer that."
            )
            logger.info("[Chat] No context found.")
        else:
            # Identify the type of answer needed — injected as a hard constraint
            # into the synthesis prompt (key improvement from benchmark v4/v5)
            answer_type = await llm_service.identify_answer_type(user_query)
            logger.info(f"[Chat] Answer type: '{answer_type}'")

            t_synth = time.perf_counter()
            answer = await llm_service.synthesize(
                unique_docs, user_query, answer_type=answer_type
            )
            logger.info(f"[Chat] Synthesis: {time.perf_counter() - t_synth:.2f}s")

            # Extract the FINAL: answer when the synthesis prompt produced one
            # (benchmark mode prompt always produces 'FINAL: <answer>')
            if "FINAL:" in answer:
                parts = answer.split("FINAL:", 1)
                answer = parts[1].strip().split("\n")[0].strip()

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
            "discovered_entities": {},  # kept for API response compatibility
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
