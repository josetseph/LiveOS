import asyncio
import os
import sys

# Ensure backend directory is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.graph import graph_service
from app.services.llm import llm_service
from app.services.embedding import embedding_service
from app.core.database import AsyncSessionLocal
from app.models.note import Note
from sqlalchemy import select


async def main():
    print("=== Starting Summary Repair Script ===")

    # 1. Find Bad Nodes in Graph
    print("Scanning graph for bad summaries...")
    query = """
    MATCH (n:Note)
    WHERE n.summary CONTAINS "Please provide" 
       OR n.summary CONTAINS "You provided no note content"
       OR n.summary CONTAINS "I need the text"
       OR n.summary CONTAINS "provide the message"
    RETURN n.id as id, n.summary as summary, n.title as title
    """
    bad_nodes = graph_service.execute_query(query)
    print(f"Found {len(bad_nodes)} notes with potentially bad summaries.")

    if not bad_nodes:
        print("No bad summaries found. Exiting.")
        return

    async with AsyncSessionLocal() as session:
        for node in bad_nodes:
            note_id = node["id"]
            old_summary = node["summary"]
            print(f"\nProcessing Note {note_id}...")
            print(f"  [Old Summary]: {old_summary[:60]}...")

            # 2. Fetch Content from Postgres
            stmt = select(Note).where(Note.id == note_id)
            result = await session.execute(stmt)
            note_obj = result.scalar_one_or_none()

            new_summary = "No content provided."
            content_found = False

            if not note_obj:
                print("  -> Note not found in Postgres.")
            elif not note_obj.content or not note_obj.content.strip():
                print("  -> Postgres content is empty.")
            else:
                print(f"  -> Content found ({len(note_obj.content)} chars).")
                content_found = True

            # 3. Analyze Body Content
            is_corrupted = False
            if content_found:
                lower_content = note_obj.content.lower().strip()
                print(f"  [RAW CONTENT]: {note_obj.content!r}")
                if (
                    "please provide" in lower_content
                    or "you provided no" in lower_content
                    or "i need the text" in lower_content
                    or len(lower_content) < 10
                ):
                    is_corrupted = True
                    print(
                        "  -> DETECTED CORRUPTED CONTENT (Content is likely an LLM error message)."
                    )

            # 3b. Re-summarize or Fix
            if is_corrupted or not content_found:
                new_summary = (
                    "Ingestion Error: No valid content was captured for this note."
                )
                print(f"  -> Setting Error Summary: {new_summary}")
            else:
                try:
                    # Calling synchronous summarize
                    print("  -> generating summary...")
                    new_summary = llm_service.summarize(note_obj.content)
                    print(f"  [New Summary]: {new_summary}")
                except Exception as e:
                    print(f"  -> LLM Error: {e}")
                    continue

            # 4. Re-embed and Update Graph
            # If content was empty, we still update summary to "No content provided" to fix the "Please provide..." text.
            title = (
                note_obj.title
                if note_obj and note_obj.title
                else (node.get("title") or "Untitled")
            )

            try:
                # generate embedding for new summary
                text_to_embed = f"{title}: {new_summary}"
                new_vector = embedding_service.embed_query(text_to_embed)

                update_query = """
                MATCH (n:Note {id: $id})
                SET n.summary = $summary, n.embedding = $vector
                """
                graph_service.execute_query(
                    update_query,
                    {"id": note_id, "summary": new_summary, "vector": new_vector},
                )
                print(f"  -> Graph updated successfully.")
            except Exception as e:
                print(f"  -> Graph Update Error: {e}")

    graph_service.close()
    print("\n=== Repair Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
