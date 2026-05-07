import asyncio
import uuid
from datetime import datetime, timezone

from app.core.log import get_logger
from app.models.feedback import Feedback
from app.models.note import Note
from app.schemas.feedback import FeedbackCreate
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("FeedbackService")

# Only ingest feedback where both relevance and quality meet this minimum.
_INGEST_THRESHOLD = 4


class FeedbackService:
    async def create_feedback(
        self, db: AsyncSession, feedback_input: FeedbackCreate
    ) -> Feedback:
        feedback = Feedback(
            query=feedback_input.query,
            response=feedback_input.response,
            relevance=feedback_input.relevance,
            quality=feedback_input.quality,
            comments=feedback_input.comments,
            node_ids_used=feedback_input.node_ids_used,
        )
        db.add(feedback)
        await db.commit()
        await db.refresh(feedback)

        if (
            feedback.relevance >= _INGEST_THRESHOLD
            and feedback.quality >= _INGEST_THRESHOLD
        ):
            note_id = str(uuid.uuid4())
            content = self._build_feedback_content(feedback)
            note = Note(
                id=note_id,
                content=content,
                domain="user_feedback",
                created_at=datetime.now(timezone.utc),
                processed=False,
            )
            db.add(note)
            await db.commit()

            asyncio.create_task(
                self._ingest_feedback_background(
                    note_id=note_id,
                    content=content,
                    node_ids_used=list(feedback.node_ids_used or []),
                )
            )

        return feedback

    @staticmethod
    def _build_feedback_content(feedback: Feedback) -> str:
        lines = [
            f"Q: {feedback.query}",
            f"A: {feedback.response}",
        ]
        if feedback.comments:
            lines.append(f"Comments: {feedback.comments}")
        return "\n".join(lines)

    async def _ingest_feedback_background(
        self,
        note_id: str,
        content: str,
        node_ids_used: list[str],
    ) -> None:
        """Ingest a high-quality feedback Q&A pair as a knowledge node and link it."""
        from app.schemas.extraction import NoteInput
        from app.services.graph import graph_service
        from app.workflows.ingestion import ingestion_workflow

        title = f"User Feedback — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        note_input = NoteInput(content=content, title=title)

        try:
            await ingestion_workflow.process_note(note_input, note_id)
            logger.info(f"[Feedback] Ingested feedback note {note_id}")
        except Exception as exc:
            logger.error(f"[Feedback] Ingestion failed for note {note_id}: {exc}")
            return

        if not node_ids_used:
            return

        # Find nodes extracted from the feedback note.
        extracted_query = """
        MATCH (note:Node {id: $note_id})-[:REFERENCES]->(n:Node)
        WHERE note.kind = 'note'
        RETURN n.id AS id, n.name AS name
        """
        extracted = graph_service.execute_query(extracted_query, {"note_id": note_id})
        if not extracted:
            logger.info(f"[Feedback] No extracted nodes found for note {note_id}")
            return

        # Look up target nodes by the IDs cited by the retrieval pipeline.
        target_query = """
        MATCH (n:Node)
        WHERE n.id IN $ids AND n.kind IN ['indexable', 'note']
        RETURN n.id AS id, n.name AS name
        """
        target_nodes = graph_service.execute_query(target_query, {"ids": node_ids_used})
        if not target_nodes:
            return

        created = 0
        for src in extracted:
            for tgt in target_nodes:
                if src["name"] == tgt["name"]:
                    continue
                nl = (
                    f"{src['name']} is related to {tgt['name']} "
                    f"via user feedback on a query about {tgt['name']}."
                )
                graph_service.create_or_update_relationship(
                    source_name=src["name"],
                    source_label="Indexable",
                    target_name=tgt["name"],
                    target_label="Indexable",
                    relationship_type="user feedback",
                    confidence=1.0,
                    strength=5.0,
                    relevance=5.0,
                    natural_language=nl,
                    note_id=note_id,
                )
                created += 1

        logger.info(
            f"[Feedback] Created {created} user_feedback relationships for note {note_id}"
        )


feedback_service = FeedbackService()
