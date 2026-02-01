from app.services.retrieval import retrieval_service
from app.services.llm import llm_service
from app.core.logging_config import get_component_logger

logger = get_component_logger("ChatWorkflow")


class ChatWorkflow:
    async def chat(self, user_query: str) -> dict:
        import time

        start_time = time.perf_counter()
        logger.info(f"\n[Chat] Started processing query: '{user_query}'")

        # 1. Hybrid Retrieval (includes relationship expansion before reranking)
        t0 = time.perf_counter()
        top_docs = await retrieval_service.hybrid_search(user_query)
        t1 = time.perf_counter()
        logger.info(
            f"[Chat] Retrieval took: {t1 - t0:.4f}s (Docs found: {len(top_docs)})"
        )

        # 2. Synthesis
        # context = "\n\n".join([d["text"] for d in top_docs])  # DEPRECATED: Now passing structured docs

        answer = ""
        if not top_docs:
            answer = (
                "I couldn't find any relevant context in your brain to answer that."
            )
            logger.info("[Chat] No context found. Skipping generation.")
        else:
            t2 = time.perf_counter()
            # Pass FULL structured docs to LLM for smart formatting
            answer = await llm_service.synthesize(top_docs, user_query)
            t3 = time.perf_counter()
            logger.info(f"[Chat] Generation took: {t3 - t2:.4f}s")

            # 3. Append References (Post-Processing)
            # Deduplicate references by Note ID
            # Sources: 1) direct note_id on doc (recent notes), 2) linked_notes from graph nodes
            seen_refs = set()
            references = []

            # Debug: Count how many docs have linked_notes
            docs_with_notes = sum(1 for d in top_docs if d.get("linked_notes"))
            total_linked = sum(len(d.get("linked_notes", [])) for d in top_docs)
            logger.debug(
                f"[Chat] Reference extraction: {docs_with_notes}/{len(top_docs)} docs have linked_notes, {total_linked} total notes"
            )

            for d in top_docs:
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

            if references:
                answer += "\n\n### References\n" + "\n".join(references)

        logger.info(
            f"[Chat] Total pipeline duration: {time.perf_counter() - start_time:.4f}s\n"
        )
        return {
            "query": user_query,
            "answer": answer,
            "context": top_docs,  # Return full objects for potential debug/frontend usage
        }


chat_workflow = ChatWorkflow()
