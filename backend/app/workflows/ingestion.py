import logging
from datetime import datetime

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IngestionPipeline")

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
        if not note_id: note_id = str(uuid.uuid4())
        logger.info(f"[{datetime.now()}] START: Ingesting Note {note_id}")

        # Trigger the LangGraph Agent
        initial_state = {
            "input": note_input,
            "content": "",
            "extraction": None,
            "embedding": None,
            "note_id": note_id,
            "created_at": None,
            "errors": []
        }
        
        # Use ainvoke because the graph contains async nodes (multimodal_node)
        import time
        t_start = time.perf_counter()
        final_state = await ingestion_agent.ainvoke(initial_state)
        t_end = time.perf_counter()
        
        if final_state["errors"]:
            logger.error(f"[{datetime.now()}] FAILURE: Ingestion Failed for {note_id}: {final_state['errors']}")
            raise Exception(f"Ingestion Agent Failed: {final_state['errors']}")
            
        # Mark as processed in Postgres
        await self._mark_note_processed(note_id)

        duration = t_end - t_start
        print(f"\n[Ingestion] Total Pipeline Duration: {duration:.4f}s")
        logger.info(f"[{datetime.now()}] SUCCESS: Note {note_id} fully indexed in {duration:.2f}s.")
        return {
            "note_id": final_state["note_id"],
            "extraction": final_state["extraction"].model_dump(),
            "status": "success",
            "processed_content": final_state["content"]
        }

    # Internal helpers reused by the Agent
    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
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
                print(f"[Ingestion] Updated Postgres Content for Note {note_id}")
            except Exception as e:
                print(f"Error updating Postgres content: {e}")
                raise e # Re-raise for tenacity

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
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
                print(f"[Ingestion] Updated Postgres Title for Note {note_id}: '{title}'")
            except Exception as e:
                print(f"Error updating Postgres title: {repr(e)}")
                raise e

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
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
                print(f"[Ingestion] Marked Note {note_id} as Processed.")
            except Exception as e:
                print(f"Error marking note processed: {e}")
                raise e

    def _write_ontology(self, note_id: str, content: str, extraction: Extraction, vector: list[float], created_at: str):
        # 0. Generate Title & Summary
        title = llm_service.generate_title(content)
        summary = llm_service.summarize(content)

        # Sync Title to Postgres (User Request)
        # We need to run this async, but _write_ontology is sync? 
        # Wait, _write_ontology is called from storage_node which is async def but calls it directly.
        # storage_node DOES NOT await _write_ontology because it is not async. 
        # But _update_note_content_postgres IS async.
        # I need to verify if I can call async from here or if I should do it in the agent.
        # Actually, let's just use the sync version or fire-and-forget?
        # Better: use the existing graph_service to write to Neo4j, but for Postgres we need async session.
        # I will assume I can run the update loop here or better, add a helper.
        # Let's inspect call site. storage_node calls ingestion_workflow._write_ontology.
        # I should change _write_ontology to be async and await it in storage_node.
        
        # Base Note Node (Neo4j - The Mind)
        query_note = """
        MERGE (n:Note {id: $id})
        SET n.summary = $summary,
            n.title = $title,
            n.sentiment = $sentiment,
            n.created_at = $created_at,
            n.embedding = $vector
        """
        # Prune old relationships to ensure state matches current extraction
        query_prune = """
        MATCH (n:Note {id: $id})-[r]->() 
        WHERE type(r) IN ['MENTIONS', 'CONTRIBUTES_TO', 'PRODUCES_TASK', 'REVEALED_BY'] 
        DELETE r
        """
        graph_service.execute_query(query_prune, {"id": note_id})

        graph_service.execute_query(query_note, {
            "id": note_id,
            "summary": summary,
            "title": title,
            "sentiment": extraction.sentiment,
            "created_at": created_at,
            "vector": vector
        })



        # 1. ENTITIES (Batch)
        if extraction.entities:
            query_entities = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            MERGE (e:Entity {name: item.name})
            ON CREATE SET e.type = item.type, e.importance = item.importance
            MERGE (n)-[r:MENTIONS]->(e)
            SET r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            # Prepare dict list
            entity_data = [
                {"name": e.name, "type": e.type, "importance": e.importance} 
                for e in extraction.entities
            ]
            graph_service.execute_query(query_entities, {
                "data": entity_data,
                "note_id": note_id, 
                "created_at": created_at
            })

        # 2. CONCEPTS (Batch)
        if extraction.concepts:
            query_concepts = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            MERGE (c:Concept {name: item.name})
            ON CREATE SET c.definition = item.definition
            MERGE (n)-[r:CONTRIBUTES_TO]->(c)
            SET r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            concept_data = [
                {"name": c.name.title(), "definition": c.definition} 
                for c in extraction.concepts
            ]
            graph_service.execute_query(query_concepts, {
                "data": concept_data,
                "note_id": note_id,
                "created_at": created_at
            })

        # 3. TASKS (Batch)
        if extraction.tasks:
            query_tasks = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            // Create Task with 'name' for generic visualization fallback
            CREATE (t:Task {id: item.task_id, description: item.desc, name: item.name, status: item.status, due_date: item.due_date, created_at: $created_at})
            MERGE (n)-[r:PRODUCES_TASK]->(t)
            SET r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            task_data = [
                # Truncate description for 'name' visualization (50 chars)
                {"task_id": str(uuid.uuid4()), "desc": t.description, "name": (t.description[:47] + "...") if len(t.description) > 50 else t.description, "status": t.status, "due_date": t.due_date}
                for t in extraction.tasks
            ]
            graph_service.execute_query(query_tasks, {
                "data": task_data,
                "note_id": note_id,
                "created_at": created_at
            })

        # 4. PERSONA (Batch)
        if extraction.persona_traits:
            query_persona = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            // Generic visualization uses 'name'
            MERGE (p:Persona {trait: item.trait})
            ON CREATE SET p.name = item.trait
            MERGE (p)-[r:REVEALED_BY]->(n)
            SET r.quote = item.quote, 
                r.created_at = $created_at,
                r.valid_from = $created_at,
                r.status = 'active'
            """
            persona_data = [
                {"trait": t.trait, "quote": t.evidence_quote}
                for t in extraction.persona_traits
            ]
            graph_service.execute_query(query_persona, {
                "data": persona_data,
                "note_id": note_id, 
                "created_at": created_at
            })

        return title


    async def _update_neighborhoods(self, concepts, entities, tasks, persona_traits, new_content: str):
        """
        Refreshes the summaries of concepts, entities, tasks, and personas affected by this note.
        Parallelizes updates to reduce total latency.
        """
        tasks_list = []
        
        # Update Concepts
        for concept in (concepts or []):
            name = concept.name.strip().title()
            if not name: continue
            tasks_list.append(self._update_node_summary("Concept", name, new_content))

        # Update Entities
        for entity in (entities or []):
            name = entity.name.strip()
            if not name: continue
            tasks_list.append(self._update_node_summary("Entity", name, new_content))

        # Update Tasks
        for task in (tasks or []):
            desc = task.description.strip()
            if not desc: continue
            tasks_list.append(self._update_node_summary("Task", desc, new_content, identifier_key="description"))

        # Update Personas
        for trait in (persona_traits or []):
            t_text = trait.trait.strip()
            if not t_text: continue
            tasks_list.append(self._update_node_summary("Persona", t_text, new_content, identifier_key="trait"))

        if tasks_list:
            await asyncio.gather(*tasks_list)

    async def _update_node_summary(self, label: str, name: str, new_content: str, identifier_key: str = "name"):
        async with entity_lock_manager.get_lock(label, name):
            # 1. Fetch existing summary
            # we run sync query in thread to avoid blocking loop
            import asyncio
            loop = asyncio.get_running_loop()
            
            def _get_existing():
                return graph_service.execute_query(
                    f"MATCH (n:{label} {{{identifier_key}: $name}}) RETURN n.summary as summary",
                    {"name": name}
                )
            
            res = await loop.run_in_executor(None, _get_existing)
            existing_summary = res[0].get('summary') if res else ""
            
            # 2. Get Context Window
            from app.utils.text_processing import get_entity_context
            context = get_entity_context(new_content, name, window=1)
            
            # 3. Generate Delta Update
            # update_summary is sync, run in thread
            def _call_llm():
                return llm_service.update_summary(
                    existing_summary or "None yet.",
                    context,
                    name,
                    label
                )
            
            update_data = await loop.run_in_executor(None, _call_llm)
            
            # 4. Save back
            def _save_update():
                graph_service.execute_query(
                    f"MATCH (n:{label} {{{identifier_key}: $name}}) SET n.summary = $summary, n.title = $title",
                    {"name": name, "summary": update_data["summary"], "title": update_data["title"]}
                )
                
            await loop.run_in_executor(None, _save_update)
            print(f"  Summary updated for {label}: {name} (Title: {update_data['title']})")

ingestion_workflow = IngestionWorkflow()
