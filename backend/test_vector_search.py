from app.services.embedding import embedding_service
from app.services.graph import graph_service
from app.core.database import AsyncSessionLocal
from app.models.note import Note
from sqlalchemy import select
import asyncio

# Embed the query
query = "seveightech"
vector = embedding_service.embed_query(query)

print(f"Query: '{query}'")
print(f"Vector size: {len(vector)}")

# Try vector search WITHOUT min_score filter

# Retrieve id, score, and content
result = graph_service.execute_query(
    """
CALL db.index.vector.queryNodes('note_vector_index', 10, $vector)
YIELD node, score
RETURN node.id as id, node.summary as content, score
ORDER BY score DESC
LIMIT 10
""",
    {"vector": vector},
)

print(f"\nTop 10 results (no score filter):")
for r in result:
    content_preview = (
        (r["content"][:80] + "...")
        if r["content"] and len(r["content"]) > 80
        else r["content"]
    )
    print(
        f"  Score: {r['score']:.4f} - Note: {r['id'][:8]}... | Content: {content_preview}"
    )

# Now with min_score=0.75

# Retrieve id, score, and content with min_score filter
result_filtered = graph_service.execute_query(
    """
CALL db.index.vector.queryNodes('note_vector_index', 10, $vector)
YIELD node, score
WHERE score >= 0.75
RETURN node.id as id, node.summary as content, score
ORDER BY score DESC
""",
    {"vector": vector},
)

print(f"\nWith min_score >= 0.8:")
print(f"  Found: {len(result_filtered)} results")


async def fetch_note_contents(note_ids):
    """Fetch full note content from PostgreSQL"""
    async with AsyncSessionLocal() as session:
        stmt = select(Note.id, Note.content).where(Note.id.in_(note_ids))
        result = await session.execute(stmt)
        rows = result.all()
        return {row.id: row.content for row in rows}


# Get full content from PostgreSQL for filtered results
if result_filtered:
    note_ids = [r["id"] for r in result_filtered]
    content_map = asyncio.run(fetch_note_contents(note_ids))

    for r in result_filtered:
        full_content = content_map.get(r["id"], "")
        content_preview = full_content
        print(f"\n  Score: {r['score']:.4f}")
        print(f"  Note ID: {r['id']}")
        print(f"  Summary: {r['content']}")
        print(f"  Full Content Preview: {content_preview}")
