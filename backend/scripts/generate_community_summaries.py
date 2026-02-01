"""
Generate summaries for existing Community nodes.
Run once to backfill summaries for communities that were created before
summary generation was added to the ingestion pipeline.
"""

from app.services.graph import graph_service
from app.services.llm import llm_service


def main():
    # Get existing communities
    communities = graph_service.execute_query(
        """
        MATCH (c:Community)
        RETURN c.name as name, c.domain as domain
    """
    )

    print(f"Found {len(communities)} communities")

    for comm in communities:
        name = comm["name"]
        domain = comm["domain"]
        print(f"\nProcessing: {name}")

        # Get members
        data = graph_service.get_community_summary(name)
        if not data or not data.get("top_members"):
            print("  No members found")
            continue

        # Build context from member summaries
        members = data.get("top_members", [])
        contexts = []
        for m in members[:10]:
            if m and m.get("summary"):
                contexts.append(
                    f"- {m.get('name')} ({m.get('label')}): {m.get('summary')}"
                )

        if not contexts:
            print("  No member summaries found")
            continue

        print(f"  Found {len(contexts)} members with summaries")

        # Generate summary
        context_text = "\n".join(contexts)
        summary_input = f"""This is a {domain} knowledge cluster containing:

{context_text}

Summarize the common themes and key insights that connect these items."""

        summary = llm_service.summarize(summary_input)
        themes = [m.get("name") for m in members[:5] if m and m.get("name")]

        graph_service.update_community_summary(name, summary.strip(), themes)
        print(f"  Summary: {summary[:100]}...")


if __name__ == "__main__":
    main()
