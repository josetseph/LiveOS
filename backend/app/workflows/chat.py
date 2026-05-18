"""Research-loop chat workflow: iterative retrieval, sub-question synthesis, and attribution."""

# pylint: disable=wrong-import-order
import time

from app.core.database import AsyncSessionLocal
from app.core.log import get_logger
from app.models.note import Note
from app.services.retrieval import retrieval_service
from sqlalchemy import select

logger = get_logger("ChatWorkflow")


def _doc_passage(doc: dict) -> str:
    """Extract the cleanest available text from a retrieved doc for LLM prompts."""
    node = doc.get("original_obj", {})
    text = (
        node.get("summary") or node.get("description") or doc.get("text", "")
    ).strip()
    return text


class ChatWorkflow:  # pylint: disable=too-few-public-methods
    """Iterative research-loop workflow: retrieve, synthesise, and attribute sources per turn."""

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
                    or doc.get("text", "")
                )
                if doc_id and doc_id not in seen_local:
                    deduped.append(doc)
                    seen_local.add(doc_id)
            return deduped

        # Deduplicate docs
        unique_docs: list[dict] = _dedupe_docs(all_docs)

        # Precision guard: the answer is already synthesised inside the pipeline.
        # For references and returned context we only expose the highest-confidence
        # docs so that irrelevant graph-expansion neighbours don't dilute precision.
        # Sort by the rerank_score already attached by _apply_reranker_logging;
        # unscored docs (expanded neighbours) fall to the bottom (score = 0).
        MAX_CONTEXT_DOCS = 6  # pylint: disable=invalid-name
        if len(unique_docs) > MAX_CONTEXT_DOCS:
            unique_docs = sorted(
                unique_docs,
                key=lambda d: d.get("rerank_score", 0.0),
                reverse=True,
            )[:MAX_CONTEXT_DOCS]

        logger.info(f"[Chat] Unique docs: {len(unique_docs)}")
        if unique_docs:
            logger.debug(
                "Context (%d docs): %s",
                len(unique_docs),
                [
                    f"{i+1}. [{doc.get('original_obj', {}).get('name', '?')}] {_doc_passage(doc)}"
                    for i, doc in enumerate(unique_docs)
                ],
            )

        # ── Answer assembly ──────────────────────────────────────────────────
        # Do not synthesize from raw docs in chat workflow. The only valid answer
        # synthesis is the structured final synthesis over sub-question results
        # (pipeline final_answer / structured fallback fb_answer).
        answer = ""
        if final_answer:
            logger.info(
                f"[Chat] Using pipeline answer directly (structured synthesis): "
                f"'{final_answer}'"
            )
            answer = final_answer

        if not answer:
            answer = (
                "I couldn't find any relevant information in the knowledge base to answer that."
                if not unique_docs
                else "I couldn't find enough information to answer that."
            )
            logger.info("[Chat] Iterative loop exhausted — no answer produced.")

        # Only cite notes from docs that the reranker individually scored.
        # Graph-expansion docs are added after reranking and carry no rerank_score;
        # their linked_notes are graph neighbours that were never verified as relevant
        # to the question, so they inflate the reference list without adding precision.
        for doc in unique_docs:
            if "rerank_score" not in doc:
                doc["linked_notes"] = []

        # Append references
        references = await self._extract_references(unique_docs)
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

    async def _extract_references(self, docs: list) -> list:
        """
        Extract unique note references from retrieved documents.
        Looks up real titles from Postgres for any linked note that lacks a title
        in the graph (note nodes in Neo4j don't store the title property).
        """
        # Deduplicate references by Note ID from graph-node linked_notes.
        seen_refs: set[str] = set()
        id_to_title: dict[str, str | None] = {}

        # Collect all note IDs we'll need titles for
        for d in docs:
            for linked_note in d.get("linked_notes", []):
                lnid = linked_note.get("id")
                if lnid:
                    id_to_title.setdefault(lnid, linked_note.get("title"))

        # Batch-fetch titles from Postgres for any note with a missing title
        missing_ids = [nid for nid, t in id_to_title.items() if not t]
        if missing_ids:
            try:
                async with AsyncSessionLocal() as session:
                    rows = await session.execute(
                        select(Note.id, Note.title).where(Note.id.in_(missing_ids))
                    )
                    for row_id, row_title in rows:
                        if row_title:
                            id_to_title[row_id] = row_title
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug(f"[Chat] Note title lookup failed: {e}")

        references = []
        for d in docs:
            for linked_note in d.get("linked_notes", []):
                lnid = linked_note.get("id")
                if lnid and lnid not in seen_refs:
                    ltitle = id_to_title.get(lnid) or "Untitled Note"
                    references.append(f"- [{ltitle}](/notes/{lnid})")
                    seen_refs.add(lnid)

        logger.info(f"[Chat] Found {len(references)} references for response")
        return references


chat_workflow = ChatWorkflow()
