from app.services.retrieval import retrieval_service
from app.services.llm import llm_service
from app.core.log import get_logger
import time
import re

logger = get_logger("ChatWorkflow")


class ChatWorkflow:
    async def chat(self, user_query: str) -> dict:
        """
        Iterative Information-Discovery Retrieval:

        1. Ask LLM what information it needs to answer the question
        2. For each information need:
           - Substitute discovered entities from previous steps
           - Retrieve relevant context
           - Extract key entities from results
        3. Synthesize final answer with all gathered context

        This handles complex multi-step questions like:
        "What government position was held by the woman who portrayed Corliss Archer?"
        """
        start_time = time.perf_counter()
        logger.info(f"\n[Chat] Started processing query: '{user_query}'")

        # Step 1: Identify information needs
        t0 = time.perf_counter()
        information_needs = await llm_service.identify_information_needs(user_query)
        t1 = time.perf_counter()
        logger.info(
            f"[Chat] Information needs identified in {t1 - t0:.2f}s: {len(information_needs)} steps"
        )

        # Step 2: Iteratively retrieve for each information need
        all_retrieved_docs = []
        discovered_entities = {}

        for step_num, info_need in enumerate(information_needs, 1):
            logger.info(
                f"\n[Chat] Step {step_num}/{len(information_needs)}: {info_need}"
            )

            # Substitute placeholders with discovered entities
            filled_query = info_need
            for placeholder, entity in discovered_entities.items():
                # Try to replace placeholders like [actress name], [person], etc.
                filled_query = re.sub(
                    r"\[" + re.escape(placeholder) + r"\]",
                    entity,
                    filled_query,
                    flags=re.IGNORECASE,
                )

            if filled_query != info_need:
                logger.info(f"[Chat]   Filled query: {filled_query}")

            # Retrieve for this information need
            t_ret_start = time.perf_counter()
            step_results = await retrieval_service.hybrid_search(
                filled_query, top_k=10  # Smaller retrieval per step
            )
            t_ret_end = time.perf_counter()
            logger.info(
                f"[Chat]   Retrieved {len(step_results)} docs in {t_ret_end - t_ret_start:.2f}s"
            )

            # Add to cumulative context
            all_retrieved_docs.extend(step_results)

            # Log sample of retrieved text for debugging
            if step_results and len(step_results) > 0:
                sample_text = step_results[0].get("text", "")[:300]
                node_name = (
                    step_results[0].get("original_obj", {}).get("name", "unknown")
                )
                print(f"\n📄 CONTEXT for '{filled_query}':")
                print(f"   [{node_name}] {sample_text}...")
                logger.info(f"[Chat]   Sample retrieval text: {sample_text}...")

            # Extract entities from this step's results
            if step_results:
                step_entities = await llm_service.extract_discovered_entities(
                    filled_query, step_results
                )
                discovered_entities.update(step_entities)
                if step_entities:
                    logger.info(f"[Chat]   Discovered: {list(step_entities.values())}")

        # Remove duplicates from all_retrieved_docs (by node name or note id)
        seen_ids = set()
        unique_docs = []
        for doc in all_retrieved_docs:
            # Identify by node name or note ID
            doc_id = (
                doc.get("original_obj", {}).get("name")
                or doc.get("note_id")
                or doc.get("text", "")[:100]
            )
            if doc_id not in seen_ids:
                unique_docs.append(doc)
                seen_ids.add(doc_id)

        logger.info(
            f"[Chat] Total unique docs retrieved: {len(unique_docs)} (from {len(all_retrieved_docs)} total)"
        )

        # Log summary of context for debugging
        if unique_docs:
            print(f"\n🔍 FINAL CONTEXT FOR SYNTHESIS ({len(unique_docs)} docs):")
            for i, doc in enumerate(unique_docs[:5]):  # Show first 5
                text_preview = doc.get("text", "")[:150]
                node_name = doc.get("original_obj", {}).get("name", "unknown")
                print(f"  {i+1}. [{node_name}] {text_preview}...")

            doc_summaries = []
            for i, doc in enumerate(unique_docs[:5]):  # Show first 5
                text_preview = doc.get("text", "")[:100]
                node_name = doc.get("original_obj", {}).get("name", "unknown")
                doc_summaries.append(f"  {i+1}. [{node_name}] {text_preview}...")
            logger.info(
                f"[Chat] Context preview (first 5 docs):\n" + "\n".join(doc_summaries)
            )

        # Step 3: Synthesize final answer
        answer = ""
        if not unique_docs:
            answer = (
                "I couldn't find any relevant context in your brain to answer that."
            )
            logger.info("[Chat] No context found after iterative retrieval.")
        else:
            t_synth_start = time.perf_counter()
            answer = await llm_service.synthesize(unique_docs, user_query)
            t_synth_end = time.perf_counter()
            logger.info(f"[Chat] Synthesis took: {t_synth_end - t_synth_start:.2f}s")

            # Append References
            references = self._extract_references(unique_docs)
            if references:
                answer += "\n\n### References\n" + "\n".join(references)

        total_time = time.perf_counter() - start_time
        logger.info(f"[Chat] Total pipeline duration: {total_time:.2f}s\n")

        return {
            "query": user_query,
            "answer": answer,
            "context": unique_docs,
            "information_needs": information_needs,  # For debugging
            "discovered_entities": discovered_entities,  # For debugging
        }

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
