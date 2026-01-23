from datetime import datetime
from app.core.logging_config import get_component_logger

# Setup Logger
logger = get_component_logger("IngestionPipeline")

from app.schemas.extraction import Extraction, NoteInput
from app.workflows.agents.ingestion_agent import ingestion_agent
from app.services.graph import graph_service
from app.services.llm import llm_service
import uuid

import asyncio
from collections import defaultdict


class EntityLockManager:
    """
    Manages per-entity locks to prevent race conditions during summary updates.
    Ensures that multiple notes updating the same entity wait for each other.
    """

    def __init__(self):
        self._locks = defaultdict(asyncio.Lock)

    def get_lock(self, label: str, name: str):
        return self._locks[(label, name.lower().strip())]


entity_lock_manager = EntityLockManager()


class IngestionWorkflow:
    async def process_note(self, note_input: NoteInput, note_id: str = None):
        if not note_id:
            note_id = str(uuid.uuid4())
        logger.info(f"[{datetime.now()}] START: Ingesting Note {note_id}")

        # Trigger the LangGraph Agent
        initial_state = {
            "input": note_input,
            "content": "",
            "extraction": None,
            "embedding": None,
            "note_id": note_id,
            "created_at": None,
            "errors": [],
        }

        # Use ainvoke because the graph contains async nodes (multimodal_node)
        import time

        t_start = time.perf_counter()
        final_state = await ingestion_agent.ainvoke(initial_state)
        t_end = time.perf_counter()

        if final_state["errors"]:
            logger.error(
                f"[{datetime.now()}] FAILURE: Ingestion Failed for {note_id}: {final_state['errors']}"
            )
            raise Exception(f"Ingestion Agent Failed: {final_state['errors']}")

        # Mark as processed in Postgres
        await self._mark_note_processed(note_id)

        duration = t_end - t_start
        logger.info(f"\n[Ingestion] Total Pipeline Duration: {duration:.4f}s")
        logger.info(
            f"[{datetime.now()}] SUCCESS: Note {note_id} fully indexed in {duration:.2f}s."
        )
        return {
            "note_id": final_state["note_id"],
            "extraction": final_state["extraction"].model_dump(),
            "status": "success",
            "processed_content": final_state["content"],
        }

    # Internal helpers reused by the Agent
    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _update_note_content_postgres(self, note_id: str, content: str):
        """
        Updates the Note content in Postgres (The Body).
        Called by Agent when new text (transcription/OCR) is found.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(content=content)
                )
                await session.commit()
                logger.info(f"[Ingestion] Updated Postgres Content for Note {note_id}")
            except Exception as e:
                logger.error(f"Error updating Postgres content: {e}")
                raise e  # Re-raise for tenacity

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _update_note_title_postgres(self, note_id: str, title: str):
        """
        Updates the Note title in Postgres.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(title=title)
                )
                await session.commit()
                logger.info(
                    f"[Ingestion] Updated Postgres Title for Note {note_id}: '{title}'"
                )
            except Exception as e:
                logger.error(f"Error updating Postgres title: {repr(e)}")
                raise e

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _mark_note_processed(self, note_id: str):
        """
        Sets processed = True in Postgres to prevent re-runs.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(processed=True)
                )
                await session.commit()
                logger.info(f"[Ingestion] Marked Note {note_id} as Processed.")
            except Exception as e:
                logger.error(f"Error marking note processed: {e}")
                raise e

    def _write_ontology(
        self,
        note_id: str,
        content: str,
        extraction: Extraction,
        vector: list[float],
        created_at: str,
    ):
        # 0. Generate Title & Summary
        title = llm_service.generate_title(content)
        summary = llm_service.summarize(content)

        # Base Note Node (Neo4j - The Mind)
        query_note = """
        MERGE (n:Note {id: $id})
        SET n.summary = $summary,
            n.title = $title,
            n.sentiment = $sentiment,
            n.domain = $domain,
            n.created_at = $created_at,
            n.embedding = $vector
        """
        # Prune old relationships to ensure state matches current extraction
        query_prune = """
        MATCH (n:Note {id: $id})-[r]->() 
        WHERE type(r) IN ['MENTIONS', 'CONTRIBUTES_TO', 'PRODUCES_TASK', 'REVEALED_BY', 'CITES'] 
        DELETE r
        """
        graph_service.execute_query(query_prune, {"id": note_id})

        graph_service.execute_query(
            query_note,
            {
                "id": note_id,
                "summary": summary,
                "title": title,
                "sentiment": extraction.sentiment,
                "domain": extraction.domain,
                "created_at": created_at,
                "vector": vector,
            },
        )

        # 1. ENTITIES (Batch)
        if extraction.entities:
            # Generate embeddings for entities
            from app.services.embedding import embedding_service

            entity_embeddings = {}
            for e in extraction.entities:
                text_to_embed = f"{e.name} ({e.type})"
                entity_embeddings[e.name] = embedding_service.embed_query(text_to_embed)

            query_entities = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            MERGE (e:Entity {name: item.name})
            ON CREATE SET e.type = item.type, e.importance = item.importance
            SET e:Indexable, e.embedding = item.embedding
            MERGE (n)-[r:MENTIONS]->(e)
            SET r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            # Prepare dict list
            entity_data = [
                {
                    "name": e.name,
                    "type": e.type,
                    "importance": e.importance,
                    "embedding": entity_embeddings[e.name],
                }
                for e in extraction.entities
            ]
            graph_service.execute_query(
                query_entities,
                {"data": entity_data, "note_id": note_id, "created_at": created_at},
            )

        # 2. CONCEPTS (Batch with Academic Relationships)
        if extraction.concepts:
            # Generate embeddings for concepts
            from app.services.embedding import embedding_service

            concept_embeddings = {}
            for c in extraction.concepts:
                text_to_embed = f"{c.name}: {c.definition or ''}"
                concept_embeddings[c.name.title()] = embedding_service.embed_query(
                    text_to_embed
                )

            query_concepts = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            MERGE (c:Concept {name: item.name})
            ON CREATE SET c.definition = item.definition
            SET c:Indexable, c.embedding = item.embedding
            MERGE (n)-[r:CONTRIBUTES_TO]->(c)
            SET r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            concept_data = [
                {
                    "name": c.name.title(),
                    "definition": c.definition,
                    "embedding": concept_embeddings[c.name.title()],
                }
                for c in extraction.concepts
            ]
            graph_service.execute_query(
                query_concepts,
                {"data": concept_data, "note_id": note_id, "created_at": created_at},
            )

            # ACADEMIC RELATIONSHIPS: Link concepts based on definition text hints
            # For example: "builds on X", "contradicts Y", "extends Z"
            # This is a simplified heuristic - could be improved with LLM reasoning
            for concept in extraction.concepts:
                definition_lower = (
                    concept.definition.lower() if concept.definition else ""
                )

                # Check for prerequisite keywords
                if any(
                    keyword in definition_lower
                    for keyword in [
                        "requires",
                        "builds on",
                        "extends",
                        "based on",
                        "assumes",
                    ]
                ):
                    # Try to find referenced concepts in the definition
                    query_prereq = """
                    MATCH (c1:Concept {name: $concept_name})
                    MATCH (c2:Concept)
                    WHERE c2.name <> $concept_name 
                      AND toLower(c2.name) IN [word IN split(toLower($definition), ' ') | word]
                    MERGE (c1)-[r:PREREQUISITE_FOR]->(c2)
                    SET r.created_at = $created_at
                    """
                    graph_service.execute_query(
                        query_prereq,
                        {
                            "concept_name": concept.name.title(),
                            "definition": concept.definition,
                            "created_at": created_at,
                        },
                    )

                # Check for contradiction keywords
                if any(
                    keyword in definition_lower
                    for keyword in [
                        "contradicts",
                        "opposes",
                        "differs from",
                        "challenges",
                    ]
                ):
                    query_contradict = """
                    MATCH (c1:Concept {name: $concept_name})
                    MATCH (c2:Concept)
                    WHERE c2.name <> $concept_name 
                      AND toLower(c2.name) IN [word IN split(toLower($definition), ' ') | word]
                    MERGE (c1)-[r:CONTRADICTS]->(c2)
                    SET r.created_at = $created_at
                    """
                    graph_service.execute_query(
                        query_contradict,
                        {
                            "concept_name": concept.name.title(),
                            "definition": concept.definition,
                            "created_at": created_at,
                        },
                    )

        # 3. TASKS (Batch)
        if extraction.tasks:
            # Generate embeddings for tasks
            from app.services.embedding import embedding_service

            task_embeddings = []
            for t in extraction.tasks:
                text_to_embed = f"Task: {t.description} (Status: {t.status})"
                task_embeddings.append(embedding_service.embed_query(text_to_embed))

            query_tasks = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            // Create Task with 'name' for generic visualization fallback
            CREATE (t:Task:Indexable {id: item.task_id, description: item.desc, name: item.name, status: item.status, due_date: item.due_date, created_at: $created_at, embedding: item.embedding})
            MERGE (n)-[r:PRODUCES_TASK]->(t)
            SET r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            task_data = [
                # Truncate description for 'name' visualization (50 chars)
                {
                    "task_id": str(uuid.uuid4()),
                    "desc": t.description,
                    "name": (
                        (t.description[:47] + "...")
                        if len(t.description) > 50
                        else t.description
                    ),
                    "status": t.status,
                    "due_date": t.due_date,
                    "embedding": task_embeddings[i],
                }
                for i, t in enumerate(extraction.tasks)
            ]
            graph_service.execute_query(
                query_tasks,
                {"data": task_data, "note_id": note_id, "created_at": created_at},
            )

        # 4. PERSONA (Batch)
        if extraction.persona_traits:
            # Generate embeddings for persona traits
            from app.services.embedding import embedding_service

            persona_embeddings = {}
            for t in extraction.persona_traits:
                text_to_embed = (
                    f"Personality trait: {t.trait}. Evidence: {t.evidence_quote or ''}"
                )
                persona_embeddings[t.trait] = embedding_service.embed_query(
                    text_to_embed
                )

            query_persona = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            // Generic visualization uses 'name'
            MERGE (p:Persona {trait: item.trait})
            ON CREATE SET p.name = item.trait
            SET p:Indexable, p.embedding = item.embedding
            MERGE (p)-[r:REVEALED_BY]->(n)
            SET r.quote = item.quote, 
                r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            persona_data = [
                {
                    "trait": t.trait,
                    "quote": t.evidence_quote,
                    "embedding": persona_embeddings[t.trait],
                }
                for t in extraction.persona_traits
            ]
            graph_service.execute_query(
                query_persona,
                {"data": persona_data, "note_id": note_id, "created_at": created_at},
            )

        # 5. EXTERNAL REFERENCES (New for Academic/Professional domains)
        if extraction.references:
            # Generate embeddings for references
            from app.services.embedding import embedding_service

            reference_embeddings = {}
            for ref in extraction.references:
                text_to_embed = f"{ref.title}: {ref.content or ''} (Source: {ref.source or 'Unknown'})"
                ref_key = f"{ref.title}|{ref.source or 'Unknown'}"
                reference_embeddings[ref_key] = embedding_service.embed_query(
                    text_to_embed
                )

            query_references = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            MERGE (r:Reference {title: item.title, source: item.source})
            ON CREATE SET r.type = item.type, r.content = item.content
            SET r:Indexable, r.embedding = item.embedding, r.name = item.title
            MERGE (n)-[rel:CITES]->(r)
            SET rel.created_at = $created_at,
                rel.valid_from = $created_at,
                rel.status = 'active'
            """
            reference_data = [
                {
                    "title": ref.title,
                    "type": ref.type,
                    "content": ref.content,
                    "source": ref.source or "Unknown",
                    "embedding": reference_embeddings[
                        f"{ref.title}|{ref.source or 'Unknown'}"
                    ],
                }
                for ref in extraction.references
            ]
            graph_service.execute_query(
                query_references,
                {"data": reference_data, "note_id": note_id, "created_at": created_at},
            )

        return title

    async def _update_neighborhoods(
        self, concepts, entities, tasks, persona_traits, references, new_content: str
    ):
        """
        Refreshes the summaries of concepts, entities, tasks, personas, and references affected by this note.
        Parallelizes updates to reduce total latency.
        """
        tasks_list = []

        # Update Concepts
        for concept in concepts or []:
            name = concept.name.strip().title()
            if not name:
                continue
            tasks_list.append(self._update_node_summary("Concept", name, new_content))

        # Update Entities
        for entity in entities or []:
            name = entity.name.strip()
            if not name:
                continue
            tasks_list.append(self._update_node_summary("Entity", name, new_content))

        # Update Tasks
        for task in tasks or []:
            desc = task.description.strip()
            if not desc:
                continue
            tasks_list.append(
                self._update_node_summary(
                    "Task", desc, new_content, identifier_key="description"
                )
            )

        # Update Personas
        for trait in persona_traits or []:
            t_text = trait.trait.strip()
            if not t_text:
                continue
            tasks_list.append(
                self._update_node_summary(
                    "Persona", t_text, new_content, identifier_key="trait"
                )
            )

        # Update References
        for reference in references or []:
            ref_title = reference.title.strip()
            if not ref_title:
                continue
            tasks_list.append(
                self._update_node_summary(
                    "Reference", ref_title, new_content, identifier_key="title"
                )
            )

        if tasks_list:
            await asyncio.gather(*tasks_list)

    async def _update_node_summary(
        self, label: str, name: str, new_content: str, identifier_key: str = "name"
    ):
        async with entity_lock_manager.get_lock(label, name):
            # 1. Fetch existing summary
            # we run sync query in thread to avoid blocking loop
            import asyncio

            loop = asyncio.get_running_loop()

            def _get_existing():
                return graph_service.execute_query(
                    f"MATCH (n:{label} {{{identifier_key}: $name}}) RETURN n.summary as summary",
                    {"name": name},
                )

            res = await loop.run_in_executor(None, _get_existing)
            existing_summary = res[0].get("summary") if res else ""

            # 2. Get Context Window
            from app.utils.text_processing import get_entity_context

            context = get_entity_context(new_content, name, window=1)

            # 3. Generate Delta Update
            # update_summary is sync, run in thread
            def _call_llm():
                return llm_service.update_summary(
                    existing_summary or "None yet.", context, name, label
                )

            update_data = await loop.run_in_executor(None, _call_llm)

            # 4. Generate embedding for updated summary
            from app.services.embedding import embedding_service

            def _generate_embedding():
                # Use the updated summary + title for embedding
                text_to_embed = f"{update_data['title']}: {update_data['summary']}"
                return embedding_service.embed_query(text_to_embed)

            new_embedding = await loop.run_in_executor(None, _generate_embedding)

            # 5. Save back with updated embedding
            def _save_update():
                graph_service.execute_query(
                    f"MATCH (n:{label} {{{identifier_key}: $name}}) SET n.summary = $summary, n.title = $title, n.embedding = $embedding, n:Indexable",
                    {
                        "name": name,
                        "summary": update_data["summary"],
                        "title": update_data["title"],
                        "embedding": new_embedding,
                    },
                )

            await loop.run_in_executor(None, _save_update)
            logger.info(
                f"  Summary updated for {label}: {name} (Title: {update_data['title']})"
            )


ingestion_workflow = IngestionWorkflow()
