"""
Debug script to test extraction with detailed logging.
Tests the same extraction flow that's hanging during ingestion.
"""

import sys
import os
import asyncio
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.llm import llm_service
from app.schemas.extraction import Extraction


def log(msg):
    """Print with timestamp"""
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")


async def test_extraction():
    """Test extraction with the Colorado Buffaloes note"""

    # Read the test file
    test_file_path = "tests/benchmark/hotpotqa_notes/2015_16 Colorado Buffaloes men_s basketball team.md"
    log(f"Reading file: {test_file_path}")

    with open(test_file_path, "r") as f:
        content = f.read()

    log(f"File content length: {len(content)} characters")
    log(f"Content preview: {content[:100]}...")

    # Construct the same prompt used in ingestion_agent.py
    prompt = f"""
    Analyze the following user note and extract structured metadata.
    You are the "Knowledge Architect" - your job is to build isolated, content-rich knowledge nodes.
    
    DOMAIN CATEGORIZATION (Choose ONE - CRITICAL):
    Classify based on the PRIMARY SUBJECT MATTER, not the writing style or tone.
    
    - "Academic": The main content is learning material, concepts, theories, research, or educational topics
      Examples: explaining algorithms, discussing papers, studying theories, learning new concepts
      
    - "Professional": The main content is about work, projects, business decisions, or professional activities  
      Examples: team meetings, project updates, technical architecture decisions, work tasks
      
    - "Personal": The main content is personal reflections, emotions, life events, or relationships
      Examples: journal entries about feelings, personal goals unrelated to work/study, daily life reflections

    - "Creative": Poems, song lyrics, or fictional sketches.
      * RULE: Do NOT extract literal Tasks or Entities from metaphors (e.g., "carrying the sun" is not a task).
      * RULE: Extract 'Persona' traits based on the emotional subtext and themes.
      * RULE: Save the full text as an 'ExternalReference':
        - type: "Poem"
        - title: [Original Title or Generated Essence]
        - content: [Full Text]
        - source: "User"

    - "Dreams": Dream journals, nightmares, subconscious imagery, or recurring dream patterns.
      * RULE: Extract symbolic Entities (people, places, objects) that appeared in the dream
      * RULE: Extract Concepts for recurring themes or symbols (e.g., "flying", "water", "chase")
      * RULE: Do NOT extract Tasks from dream narratives (dreams are not actionable)
      * RULE: Extract Persona traits reflecting emotional states during/after the dream
      * FOCUS: Capture symbolic imagery, emotional tone, and recurring patterns
    
    IMPORTANT: A note written in first person ("I learned about X") that explains academic concepts should be classified as Academic, not Personal. Similarly, "We decided in the meeting to use X" should be Professional, not Personal. Look at WHAT the note is about, not HOW it's written.
    
    RULES:
    1. Return ONLY a single valid JSON object.
    
    2. ENTITY EXTRACTION (CRITICAL - ISOLATED CONTEXT):
       - TYPES: Person, Place, Tool, Organization, Anonymous
       - ANONYMOUS ENTITIES: If someone is described but not named (e.g., "the guy who stole from me", "my neighbor"), 
         extract them with type "Anonymous" and a descriptive name (e.g., "The Thief", "My Neighbor").
       - **isolated_context**: For EACH entity, provide ALL sentences/paragraphs that discuss THIS entity specifically.
         * Include sentences where the entity is named
         * Include follow-up sentences using pronouns (he/she/they/him/her) that refer to THIS entity
         * EXCLUDE sentences about OTHER entities, even if in the same paragraph
         * This is the MOST IMPORTANT field - it determines what goes into the entity's knowledge node
       
       EXAMPLE:
       Note: "I like John. He is my friend. The guy who stole from me, I hate him."
       Entities:
       - name: "John", type: "Person", isolated_context: "I like John. He is my friend."
       - name: "The Thief", type: "Anonymous", isolated_context: "The guy who stole from me, I hate him."
       
       EXAMPLE 2 (Multi-paragraph):
       Note: "I saw John today. He was happy about his math test results.
       
       I wish I was as good as he was in maths. I kind of envy him."
       Entities:
       - name: "John", type: "Person", isolated_context: "I saw John today. He was happy about his math test results. I wish I was as good as he was in maths. I kind of envy him."
       (All paragraphs relate to John via pronouns)
    
    3. CONCEPT EXTRACTION:
       - Abstract themes, topics, or emotional states
       - EXAMPLES: "Health", "Work", "Productivity", "Stochastic Processes", "Machine Learning"
       - **isolated_context**: All sentences discussing this concept specifically
       
    4. TASK EXTRACTION:
       - Specific actionable goals mentioned.
       - **name**: Short label for the task (e.g., "Complete svtlottery", "Pay rent")
       - **description**: Optional longer explanation (can be same as name if short)
       - **status**: Use ONLY these standardized values: "Todo", "Complete", "In Progress", "Cancelled"
       - Do NOT use: "done", "pending", "finished", "open", or any other variations
       - If status is unclear, use "Todo"
       - **isolated_context**: All sentences discussing this task specifically
       
    5. PERSONA EXTRACTION (for Personal domain only):
       - Traits about the user's emotional state, personality, or mindset
       - **trait**: The trait itself (e.g., "lonely", "motivated", "anxious")
       - **isolated_context**: Sentences showing evidence of this trait
    
    6. REFERENCES: For Academic/Professional domains - extract external citations, quotes, papers, books.
       - **type**: "Paper", "Book", "Quote", "Video", "Song", "Poem"
       - **title**: REQUIRED - Full title of the work (cannot be empty)
       - **content**: The actual quote or key excerpt (if applicable)
       - **source**: Author/Artist/Creator name
       - **isolated_context**: Sentences discussing or mentioning this reference
       
    7. RELATIONSHIPS: Extract connections between the nodes you identify above.
       - source_name: The name of the first node (must match an entity, concept, task, or person extracted above)
       - source_type: Type of first node (Person, Task, Entity, Concept, Event)
       - target_name: The name of the second node (must match another extracted node)
       - target_type: Type of second node
       - relationship_type: The type of relationship (see examples below)
       - confidence: 0.0-1.0 (how certain you are about this relationship)
       - context: Brief text snippet showing this relationship
       
       RELATIONSHIP TYPE EXAMPLES:
       * Person↔Person: knows, friends_with, works_with, manages, reports_to, married_to, siblings_with
       * Person↔Task: assigned_to, created_by, completed_by, blocked_by
       * Task↔Task: depends_on, blocks, relates_to, prerequisite_for
       * Entity↔Entity: part_of, contains, related_to
       * Concept↔Concept: prerequisite_for, related_to, contradicts, similar_to
       * Person↔Concept: interested_in, expert_in, learning, teaches
       * Task↔Concept: involves, requires_knowledge_of
       * Entity↔Concept: implements, based_on, example_of
       
       CRITICAL: Only extract relationships where BOTH nodes were identified in the extraction above!
       
    8. CRITICAL: Extract text snippets exactly as they appear. Do NOT wrap values in extra quotes. 
       Example: {{"quote": "I am happy"}}, NOT {{"quote": ""I am happy""}}.
    9. NO COMMENTARY: Do not explain your errors or apologize. Return ONLY valid JSON.
    10. ENGLISH ONLY: All output keys and values MUST be in English.

    CONTENT:
    "{content}"

    """

    log(f"Prompt length: {len(prompt)} characters")
    log(f"LLM Provider: {llm_service.provider}")
    log(f"Has gemini_client: {hasattr(llm_service, 'gemini_client')}")
    log(f"Has timeout configured: Check llm.py initialization")

    log("=" * 80)
    log("STARTING EXTRACTION...")
    log("=" * 80)

    try:
        start_time = datetime.now()
        log(f"Calling llm_service.extract_structured() at {start_time}")

        # Call the extraction method (this is what's hanging)
        extraction = await asyncio.to_thread(
            llm_service.extract_structured, prompt, Extraction
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        log("=" * 80)
        log(f"EXTRACTION COMPLETED in {duration:.2f}s")
        log("=" * 80)

        if extraction:
            log(f"Domain: {extraction.domain}")
            log(f"Entities: {len(extraction.entities)}")
            log(f"Concepts: {len(extraction.concepts)}")
            log(f"References: {len(extraction.references)}")
            log(f"Tasks: {len(extraction.tasks)}")
            log(f"Relationships: {len(extraction.relationships)}")

            # Print first entity as example
            if extraction.entities:
                log(
                    f"\nFirst entity: {extraction.entities[0].name} ({extraction.entities[0].type})"
                )
        else:
            log("ERROR: Extraction returned None")

    except asyncio.TimeoutError as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        log("=" * 80)
        log(f"TIMEOUT ERROR after {duration:.2f}s: {e}")
        log("=" * 80)

    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        log("=" * 80)
        log(f"ERROR after {duration:.2f}s: {type(e).__name__}: {e}")
        log("=" * 80)
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    log("Starting extraction debug test")
    log(f"Python version: {sys.version}")
    log(f"Working directory: {os.getcwd()}")

    asyncio.run(test_extraction())

    log("Test completed")
