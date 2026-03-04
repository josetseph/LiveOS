import asyncio
import uuid
from collections import defaultdict
from datetime import datetime

from app.core.log import get_logger
from app.schemas.extraction import Extraction, NoteInput
from app.services.graph import graph_service
from app.services.llm import llm_service
from app.services.alias_detector import alias_detector
from app.workflows.agents.ingestion_agent import ingestion_agent

logger = get_logger("IngestionPipeline")


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
    async def _update_note_domain_postgres(self, note_id: str, domain: str):
        """
        Syncs the extracted domain to Postgres.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.note import Note
        from sqlalchemy import update

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    update(Note).where(Note.id == note_id).values(domain=domain)
                )
                await session.commit()
                logger.info(
                    f"[Ingestion] Updated Postgres Domain for Note {note_id}: '{domain}'"
                )
            except Exception as e:
                logger.error(f"Error updating Postgres domain: {e}")
                raise e

    async def process_note(self, note_input: NoteInput, note_id: str = None):
        if not note_id:
            note_id = str(uuid.uuid4())
        logger.info(f"[{datetime.now()}] START: Ingesting Note {note_id}")

        # Trigger the LangGraph Agent
        initial_state = {
            "input": note_input,
            "content": "",
            "extraction": None,
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

        # Notify ingestion tracker for auto-scheduled alias detection
        from app.services.ingestion_tracker import ingestion_tracker

        ingestion_tracker.mark_ingestion_complete()

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
        created_at: str,
        custom_title: str = None,
    ):
        # 0. Generate or use provided Title & Summary
        if custom_title:
            title = custom_title
            logger.info(f"[Ingestion] Using provided title: '{title}'")
        else:
            title = llm_service.generate_title(content)
            logger.info(f"[Ingestion] Generated title: '{title}'")
        summary = llm_service.summarize(content)

        # Base Note Node (Neo4j - The Mind)
        # NOTE: Note embeddings commented out (unused in retrieval - only node embeddings searched)
        query_note = """
        MERGE (n:Note {id: $id})
        SET n.summary = $summary,
            n.title = $title,
            n.sentiment = $sentiment,
            n.domain = $domain,
            n.created_at = $created_at
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
                # "vector": vector,  # Commented out - note embeddings unused
            },
        )

        # Helper to normalize names: strip # prefix, extra whitespace, and lowercase
        def normalize_name(name: str) -> str:
            """Normalize names to prevent duplicates like #svtlottery vs Svtlottery vs SVTLottery.

            All node names are stored in lowercase for consistent merging.
            """
            if not name:
                return ""
            # Remove leading # (common in task references like #project)
            # Then lowercase for consistent storage
            name = name.lstrip("#").strip().lower()
            return name

        # 1. ENTITIES (Batch)
        if extraction.entities:
            # Generate embeddings for entities
            from app.services.embedding import embedding_service

            entity_embeddings = {}
            for e in extraction.entities:
                normalized_name = normalize_name(e.name)
                text_to_embed = f"{normalized_name} ({e.type})"
                entity_embeddings[normalized_name] = embedding_service.embed_query(
                    text_to_embed
                )

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
                r.is_active = true
            """
            # Prepare dict list with normalized names
            entity_data = [
                {
                    "name": normalize_name(e.name),
                    "type": e.type,
                    "importance": e.importance,
                    "embedding": entity_embeddings[normalize_name(e.name)],
                }
                for e in extraction.entities
            ]
            graph_service.execute_query(
                query_entities,
                {"data": entity_data, "note_id": note_id, "created_at": created_at},
            )

            # ALIAS DETECTION: Disabled - too risky for false positives
            # The deterministic find_name_variants() handles common patterns
            # (Bob→Robert, Jr. variants, etc.) without LLM-based guessing
            # self._detect_and_create_aliases(extraction.entities, note_id)

        # 2. CONCEPTS (Batch with Academic Relationships)
        if extraction.concepts:
            # Generate embeddings for concepts
            from app.services.embedding import embedding_service

            concept_embeddings = {}
            for c in extraction.concepts:
                normalized_name = c.name.lower().strip()
                text_to_embed = f"{normalized_name}: {c.definition or ''}"
                concept_embeddings[normalized_name] = embedding_service.embed_query(
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
                r.is_active = true
            """
            concept_data = [
                {
                    "name": c.name.lower().strip(),
                    "definition": c.definition,
                    "embedding": concept_embeddings[c.name.lower().strip()],
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
                            "concept_name": concept.name.lower().strip(),
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
                            "concept_name": concept.name.lower().strip(),
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
                # Use name if available, fall back to description
                task_label = t.name or t.description or "Untitled Task"
                text_to_embed = f"Task: {task_label} (Status: {t.status})"
                task_embeddings.append(embedding_service.embed_query(text_to_embed))

            query_tasks = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            // MERGE by normalized name to update existing tasks
            MERGE (t:Task {name: item.name})
            ON CREATE SET 
                t.id = item.task_id,
                t:Indexable,
                t.created_at = $created_at
            // Always update these fields (latest note wins)
            SET t.description = CASE WHEN item.desc <> '' THEN item.desc ELSE t.description END,
                t.status = item.status,
                t.due_date = CASE WHEN item.due_date IS NOT NULL THEN item.due_date ELSE t.due_date END,
                t.isolated_context = item.isolated_context,
                t.embedding = item.embedding,
                t.updated_at = $created_at
            MERGE (n)-[r:PRODUCES_TASK]->(t)
            SET r.created_at = $created_at,
                r.valid_from = $created_at,
                r.is_active = true
            """
            # Use task.name if available, otherwise generate from description
            from app.utils.data_validation import generate_unique_task_name

            def normalize_task_name(name: str) -> str:
                """Normalize task names for consistent merging.
                - Strips # prefix (e.g., 'complete #svtlottery' -> 'complete svtlottery')
                - Lowercases for consistent storage
                """
                if not name:
                    return ""
                # Remove # symbols from task names, then lowercase
                name = name.replace("#", "").strip().lower()
                return name

            task_data = [
                {
                    "task_id": str(uuid.uuid4()),
                    "name": normalize_task_name(t.name)
                    or normalize_task_name(
                        generate_unique_task_name(t.description, str(uuid.uuid4()))
                    ),
                    "desc": t.description,
                    "status": t.status,  # Already standardized in extraction_node
                    "due_date": t.due_date,
                    "isolated_context": getattr(t, "isolated_context", "") or "",
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
                # Normalize trait to lowercase
                trait_lower = t.trait.strip().lower()
                if not trait_lower:
                    continue

                # Use isolated_context if available, fall back to legacy evidence_quote
                context = (
                    getattr(t, "isolated_context", "")
                    or getattr(t, "evidence_quote", "")
                    or ""
                )
                text_to_embed = f"Personality trait: {trait_lower}. Evidence: {context}"
                persona_embeddings[trait_lower] = embedding_service.embed_query(
                    text_to_embed
                )

            query_persona = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            // Generic visualization uses 'name'
            MERGE (p:Persona {trait: item.trait})
            ON CREATE SET p.name = item.trait
            SET p:Indexable, p.embedding = item.embedding, p.isolated_context = item.isolated_context
            MERGE (p)-[r:REVEALED_BY]->(n)
            SET r.quote = item.isolated_context, 
                r.created_at = $created_at,
                r.valid_from = $created_at,
                r.is_active = true
            """
            persona_data = [
                {
                    "trait": t.trait.strip().lower(),
                    "isolated_context": getattr(t, "isolated_context", "")
                    or getattr(t, "evidence_quote", "")
                    or "",
                    "embedding": persona_embeddings[t.trait.strip().lower()],
                }
                for t in extraction.persona_traits
                if t.trait.strip().lower() in persona_embeddings
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
                # Normalize title and source to lowercase
                title_lower = ref.title.strip().lower()
                if not title_lower:
                    continue
                source_lower = (ref.source or "Unknown").strip().lower()

                text_to_embed = (
                    f"{title_lower}: {ref.content or ''} (Source: {source_lower})"
                )
                ref_key = f"{title_lower}|{source_lower}"
                reference_embeddings[ref_key] = embedding_service.embed_query(
                    text_to_embed
                )

            query_references = """
            MERGE (n:Note {id: $note_id})
            WITH n
            UNWIND $data AS item
            MERGE (r:Reference {title: item.title, source: item.source})
            ON CREATE SET r.type = item.type, r.content = item.content
            SET r:Indexable, r.embedding = item.embedding, r.name = item.title, r.isolated_context = item.isolated_context
            MERGE (n)-[rel:CITES]->(r)
            SET rel.created_at = $created_at,
                rel.valid_from = $created_at,
                rel.status = 'active'
            """
            reference_data = []
            for ref in extraction.references:
                title_lower = ref.title.strip().lower()
                if not title_lower:
                    continue
                source_lower = (ref.source or "Unknown").strip().lower()
                ref_key = f"{title_lower}|{source_lower}"

                if ref_key in reference_embeddings:
                    reference_data.append(
                        {
                            "title": title_lower,
                            "type": ref.type,
                            "content": ref.content,
                            "source": source_lower,
                            "isolated_context": getattr(ref, "isolated_context", "")
                            or "",
                            "embedding": reference_embeddings[ref_key],
                        }
                    )

            graph_service.execute_query(
                query_references,
                {"data": reference_data, "note_id": note_id, "created_at": created_at},
            )

        # 6. RELATIONSHIPS (New - Inter-node connections)
        if extraction.relationships:
            logger.info(
                f"[Ingestion] Creating {len(extraction.relationships)} relationships..."
            )

            # Map extracted node types to Neo4j labels
            type_mapping = {
                "Person": "Entity",  # Person entities are stored as Entity nodes
                "Place": "Entity",
                "Tool": "Entity",
                "Organization": "Entity",
                "Entity": "Entity",
                "Concept": "Concept",
                "Task": "Task",
                "Event": "Entity",  # Events treated as entities
            }

            for rel in extraction.relationships:
                try:
                    # Validate required fields
                    if not rel.source_name or not rel.target_name:
                        logger.warning(
                            f"[Relationship] Skipping - missing source or target name: "
                            f"{rel.source_name} -> {rel.target_name}"
                        )
                        continue

                    # Default to "relates_to" if no relationship type provided
                    rel_type = (
                        rel.relationship_type.strip() if rel.relationship_type else ""
                    )
                    if not rel_type:
                        rel_type = "relates_to"
                        logger.warning(
                            f"[Relationship] No type provided for {rel.source_name} -> {rel.target_name}, "
                            f"defaulting to 'relates_to'"
                        )

                    # Map types to Neo4j labels
                    source_label = type_mapping.get(rel.source_type, "Entity")
                    target_label = type_mapping.get(rel.target_type, "Entity")

                    # Normalize names to lowercase to match node storage
                    source_name_normalized = rel.source_name.lower().strip()
                    target_name_normalized = rel.target_name.lower().strip()

                    # Create or update relationship with bi-temporal support
                    # event_time = when this fact became true (note's date)
                    result = graph_service.create_or_update_relationship(
                        source_name=source_name_normalized,
                        source_label=source_label,
                        target_name=target_name_normalized,
                        target_label=target_label,
                        relationship_type=rel_type,
                        confidence=rel.confidence,
                        context=rel.context,
                        note_id=note_id,
                        event_time=created_at,  # When the fact became true
                    )

                    logger.info(
                        f"[Relationship] {result['action']}: "
                        f"({source_name_normalized})-[{rel_type}]->({target_name_normalized})"
                    )

                except Exception as e:
                    logger.error(
                        f"[Relationship] Failed to create relationship "
                        f"{rel.source_name}->{rel.target_name}: {e}"
                    )
                    continue

        # 7. COMMUNITY ASSIGNMENT
        # Group extracted nodes into domain-based communities
        self._assign_to_communities(extraction, content)

        return title

    def _detect_and_create_aliases(
        self, entities: list, note_id: str, min_confidence: float = 0.8
    ):
        """
        Detect and create ALIAS_OF relationships for entities that might refer to the same real-world entity.

        This is called during ingestion after entities are created/merged.
        For each Person entity, we check if existing entities might be aliases.

        Args:
            entities: List of Entity objects from extraction
            note_id: ID of the note being ingested
            min_confidence: Minimum confidence threshold for creating alias relationships
        """
        from app.services.llm import llm_service

        # Helper to normalize names
        def normalize_name(name: str) -> str:
            if not name:
                return ""
            return name.lstrip("#").strip().lower()

        # Only check Person entities with multi-word names (most likely to have aliases)
        person_entities = [
            e
            for e in entities
            if e.type.lower() == "person" and len(e.name.split()) >= 2
        ]

        if not person_entities:
            return

        logger.info(
            f"[Alias] Checking {len(person_entities)} Person entities for potential aliases..."
        )

        for entity in person_entities:
            entity_name = normalize_name(entity.name)

            try:
                # Find potential aliases in the graph
                potential_aliases = graph_service.find_potential_aliases(
                    entity_name=entity_name, entity_type=entity.type, limit=5
                )

                if not potential_aliases:
                    continue

                logger.info(
                    f"[Alias] Found {len(potential_aliases)} potential aliases for '{entity_name}': "
                    f"{[p['name'] for p in potential_aliases]}"
                )

                # Get the summary of the new entity for context
                entity_summary = entity.isolated_context or ""

                for potential in potential_aliases:
                    potential_name = potential.get("name", "")
                    potential_summary = potential.get("summary", "") or ""

                    # Skip if already an alias
                    existing_aliases = graph_service.get_aliases(entity_name)
                    if any(a["name"] == potential_name for a in existing_aliases):
                        logger.debug(
                            f"[Alias] {entity_name} <-> {potential_name} already linked"
                        )
                        continue

                    # Use LLM to verify if they're truly the same entity
                    is_same, confidence = llm_service.verify_alias(
                        name1=entity_name,
                        name2=potential_name,
                        context1=entity_summary,
                        context2=potential_summary,
                    )

                    if is_same and confidence >= min_confidence:
                        # Create bidirectional ALIAS_OF relationship
                        result = graph_service.create_alias_relationship(
                            name1=entity_name,
                            name2=potential_name,
                            confidence=confidence,
                            note_id=note_id,
                        )
                        logger.info(
                            f"[Alias] {result['action'].upper()}: "
                            f"'{entity_name}' <-> '{potential_name}' (confidence={confidence:.2f})"
                        )
                    else:
                        logger.debug(
                            f"[Alias] Rejected: '{entity_name}' <-> '{potential_name}' "
                            f"(same={is_same}, confidence={confidence:.2f})"
                        )

            except Exception as e:
                logger.warning(
                    f"[Alias] Failed to check aliases for '{entity_name}': {e}"
                )
                continue

    def _assign_to_communities(self, extraction: Extraction, content: str):
        """
        Assign extracted nodes to domain-based communities.

        Communities are high-level groupings (Professional, Academic, Personal, Creative, Dreams)
        that provide summarized context for broad queries.
        """
        from app.services.llm import llm_service

        # Detect the domain of this note's content
        domain = llm_service.detect_domain(content)

        # Collect all node names from this extraction
        node_names = []

        for entity in extraction.entities or []:
            if entity.name and entity.name.strip():
                node_names.append(entity.name.strip().title())

        for concept in extraction.concepts or []:
            if concept.name and concept.name.strip():
                node_names.append(concept.name.strip().title())

        if not node_names:
            return

        # Create/update domain community
        community_name = f"{domain} Knowledge"

        try:
            graph_service.create_or_update_community(
                name=community_name,
                domain=domain,
                member_names=node_names,
            )
            logger.info(
                f"[Community] Assigned {len(node_names)} nodes to '{community_name}'"
            )

            # Generate/update community summary based on member nodes
            self._update_community_summary(community_name, domain)

        except Exception as e:
            logger.warning(f"[Community] Failed to assign to community: {e}")

    def _update_community_summary(self, community_name: str, domain: str):
        """
        Generate a high-level summary for a community based on its member nodes.
        """
        from app.services.llm import llm_service

        try:
            # Get community members with their summaries
            community_data = graph_service.get_community_summary(community_name)
            if not community_data or not community_data.get("top_members"):
                return

            # Gather member summaries for context
            member_contexts = []
            for member in community_data.get("top_members", []):
                if member and member.get("summary"):
                    member_contexts.append(
                        f"- {member.get('name')} ({member.get('label')}): {member.get('summary')}"
                    )

            if not member_contexts:
                return

            # Generate community-level summary using the summarize method
            context_text = "\n".join(member_contexts[:10])  # Limit to top 10
            summary_input = f"""This is a {domain} knowledge cluster containing:

{context_text}

Summarize the common themes and key insights that connect these items."""

            summary = llm_service.summarize(summary_input)
            if summary and summary.strip():
                # Extract themes from member names
                themes = [
                    m.get("name")
                    for m in community_data.get("top_members", [])[:5]
                    if m.get("name")
                ]

                # Generate embedding for the community summary
                from app.services.embedding import embedding_service

                community_embedding = embedding_service.embed_query(
                    f"Community: {community_name}. {summary.strip()}"
                )

                graph_service.update_community_summary(
                    community_name,
                    summary.strip(),
                    themes,
                    embedding=community_embedding,
                )
                logger.info(
                    f"[Community] Updated summary and embedding for '{community_name}'"
                )

        except Exception as e:
            logger.warning(
                f"[Community] Failed to generate summary for {community_name}: {e}"
            )

    async def _update_neighborhoods(
        self, concepts, entities, tasks, persona_traits, references, new_content: str
    ):
        """
        Refreshes the summaries of concepts, entities, tasks, personas, and references affected by this note.
        Parallelizes updates to reduce total latency.

        LLM-NATIVE ISOLATION: Uses the `isolated_context` field from the LLM extraction
        instead of trying to compute context windows in Python.
        """
        tasks_list = []

        # Update Concepts - use LLM-provided isolated_context
        for concept in concepts or []:
            # Normalize to match storage (lowercase)
            name = concept.name.strip().lower()
            if not name:
                continue
            # Use isolated_context from LLM if available, fall back to full content
            context = getattr(concept, "isolated_context", "") or new_content
            tasks_list.append(self._update_node_summary("Concept", name, context))

        # Update Entities - use LLM-provided isolated_context
        for entity in entities or []:
            name = entity.name.strip()
            if not name:
                continue
            # Normalize entity names to match storage (lowercase, strip # prefix)
            name = name.lstrip("#").strip().lower()
            # Use isolated_context from LLM if available, fall back to full content
            context = getattr(entity, "isolated_context", "") or new_content
            tasks_list.append(self._update_node_summary("Entity", name, context))

        # Update Tasks - use LLM-provided isolated_context
        def normalize_task_name(name: str) -> str:
            """Normalize task names for consistent lookup (must match storage normalization)"""
            if not name:
                return ""
            # Remove # symbols and lowercase to match how tasks are stored
            name = name.replace("#", "").strip().lower()
            return name

        for task in tasks or []:
            # Prefer name for node label, fall back to description
            raw_name = (task.name or task.description or "").strip()
            if not raw_name:
                continue
            # Normalize to match how tasks are stored in Neo4j
            name = normalize_task_name(raw_name)
            # Use isolated_context from LLM if available, fall back to full content
            context = getattr(task, "isolated_context", "") or new_content
            tasks_list.append(
                self._update_node_summary("Task", name, context, identifier_key="name")
            )

        # Update Personas - use LLM-provided isolated_context
        for trait in persona_traits or []:
            t_text = trait.trait.strip()
            if not t_text:
                continue
            # Use isolated_context from LLM if available, fall back to full content
            context = getattr(trait, "isolated_context", "") or new_content
            tasks_list.append(
                self._update_node_summary(
                    "Persona", t_text, context, identifier_key="trait"
                )
            )

        # Update References - use LLM-provided isolated_context
        for reference in references or []:
            ref_title = reference.title.strip()
            if not ref_title:
                continue
            # Use isolated_context from LLM if available, fall back to full content
            context = getattr(reference, "isolated_context", "") or new_content
            tasks_list.append(
                self._update_node_summary(
                    "Reference", ref_title, context, identifier_key="title"
                )
            )

        if tasks_list:
            # Use asyncio.gather for batch processing with Gemini's async API
            await asyncio.gather(*tasks_list)

    async def _update_node_summary(
        self,
        label: str,
        name: str,
        isolated_context: str,
        identifier_key: str = "name",
    ):
        """
        Updates a node's summary by accumulating ALL isolated contexts.

        APPROACH:
        1. Append new isolated_context to node's isolated_contexts list
        2. Generate fresh summary from ALL accumulated contexts
        3. Store both the list (for raw context retrieval) and summary (for distilled retrieval)

        This allows A/B testing: raw contexts vs LLM summaries.

        Args:
            label: Node label (Entity, Concept, Task, etc.)
            name: Node identifier
            isolated_context: Pre-isolated context from LLM extraction (already filtered)
            identifier_key: Property to match on (name, description, trait, title)
        """
        async with entity_lock_manager.get_lock(label, name):
            loop = asyncio.get_running_loop()

            # 1. Fetch existing isolated_contexts list
            def _get_existing():
                return graph_service.execute_query(
                    f"MATCH (n:{label} {{{identifier_key}: $name}}) RETURN n.isolated_contexts as isolated_contexts",
                    {"name": name},
                )

            res = await loop.run_in_executor(None, _get_existing)
            existing_contexts = res[0].get("isolated_contexts") if res else None

            # Initialize as list if doesn't exist
            if not existing_contexts:
                existing_contexts = []

            # 2. Append new context to list
            existing_contexts.append(isolated_context)

            # 3. Generate summary from ALL contexts joined together
            all_contexts_text = "\n\n".join(existing_contexts)

            summary_data = await llm_service.generate_entity_summary_async(
                all_contexts_text,
                name,
                label,
            )

            # [Improvement #4] Extract structured atomic facts for direct-match retrieval.
            # Runs synchronously in a thread so it doesn't block the event loop.
            def _extract_facts():
                return llm_service.extract_atomic_facts(all_contexts_text, name, label)

            facts_list = await loop.run_in_executor(None, _extract_facts)
            import json as _json

            facts_json = _json.dumps(facts_list) if facts_list else "[]"
            if facts_list:
                logger.info(
                    f"  [Ingestion] Extracted {len(facts_list)} atomic facts for {label}: {name}"
                )

            logger.info(
                f"  [Ingestion] Generated summary from {len(existing_contexts)} context(s) for {label}: {name}"
            )

            # 4. Generate embedding for summary
            from app.services.embedding import embedding_service

            def _generate_embedding():
                # Include atomic facts so fact-specific queries ("Where is X from?")
                # surface this node via vector search even when the summary is brief.
                facts_str = ""
                if facts_list:
                    facts_str = " Facts: " + "; ".join(
                        f"{f['property']}: {f['value']}" for f in facts_list
                    )
                text_to_embed = f"{summary_data['title']}: {summary_data['summary']}{facts_str}"
                # Use embed_documents (no instruction) for document indexing
                # Only queries should have instruction prefix (for Qwen3)
                return embedding_service.embed_documents([text_to_embed])[0]

            new_embedding = await loop.run_in_executor(None, _generate_embedding)

            # NOTE: isolated_context_embeddings removed after A/B testing
            # Testing showed sub-par/on-par performance vs summaries, adds overhead
            # Keeping only summary embeddings for vector search
            # context_embeddings = []  # Removed

            # 5. Save isolated_contexts list and summary (no context embeddings)
            def _save_update():
                graph_service.execute_query(
                    f"MATCH (n:{label} {{{identifier_key}: $name}}) "
                    f"SET n.isolated_contexts = $isolated_contexts, "
                    f"n.isolated_context_count = $context_count, "
                    f"n.summary = $summary, n.title = $title, n.embedding = $embedding, "
                    f"n.facts = $facts, n:Indexable",
                    {
                        "name": name,
                        "isolated_contexts": existing_contexts,
                        "context_count": len(existing_contexts),
                        "summary": summary_data["summary"],
                        "title": summary_data["title"],
                        "embedding": new_embedding,
                        "facts": facts_json,
                    },
                )

            await loop.run_in_executor(None, _save_update)
            logger.info(
                f"  Summary updated for {label}: {name} (Title: {summary_data['title']})"
            )

            # Trigger alias detection for all node types (non-blocking)
            # This runs in the background without slowing down ingestion
            asyncio.create_task(self._check_node_aliases(name, label, identifier_key))

    async def _check_node_aliases(
        self, node_value: str, node_label: str, identifier_property: str
    ):
        """
        Check if newly updated node might be an alias of existing nodes.
        Runs asynchronously in background without blocking ingestion.

        Args:
            node_value: Value of the node identifier (name/trait/title)
            node_label: Node label (Entity, Concept, Task, Persona, Reference)
            identifier_property: Property name (name, trait, title)
        """
        try:
            loop = asyncio.get_running_loop()

            # For Entity nodes, we need to get the type (Person, Place, etc.)
            # For other labels, type is None
            node_type = None
            if node_label == "Entity":

                def _get_entity_type():
                    result = graph_service.execute_query(
                        "MATCH (e:Entity {name: $name}) RETURN e.type as type",
                        {"name": node_value},
                    )
                    return result[0]["type"] if result else None

                node_type = await loop.run_in_executor(None, _get_entity_type)

                if not node_type:
                    logger.debug(
                        f"  [Alias] No type found for {node_value}, skipping alias check"
                    )
                    return

                logger.info(
                    f"  [Alias] Checking for aliases of: {node_value} ({node_label}:{node_type})"
                )
            else:
                logger.info(
                    f"  [Alias] Checking for aliases of: {node_value} ({node_label})"
                )

            # Call generic alias detection
            await alias_detector.detect_and_link_aliases_for_node(
                node_value=node_value,
                node_label=node_label,
                identifier_property=identifier_property,
                node_type=node_type,
            )
        except Exception as e:
            # Don't let alias detection errors break ingestion
            logger.warning(
                f"  [Alias] Failed to check aliases for {node_label} '{node_value}': {e}"
            )


ingestion_workflow = IngestionWorkflow()
