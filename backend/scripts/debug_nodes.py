#!/usr/bin/env python3
"""
Debug script to inspect node summaries and content.
Usage: python scripts/debug_nodes.py "votex365,seveightech"
       python scripts/debug_nodes.py --query "How has my transition from SeveighTech to Votex365 affected my life?"
       python scripts/debug_nodes.py "votex365" --output report.txt
"""

import sys
import os
from datetime import datetime
from typing import Optional

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.graph import GraphService


# Output manager for file and/or console
class OutputManager:
    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath
        self.file = None
        self.lines = []

    def __enter__(self):
        if self.filepath:
            self.file = open(self.filepath, "w", encoding="utf-8")
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.close()
            print(f"\n📄 Output saved to: {self.filepath}")

    def print(self, text: str = ""):
        print(text)
        if self.file:
            self.file.write(text + "\n")
        self.lines.append(text)


# Global output manager (will be replaced in main if needed)
out: OutputManager = OutputManager()


def set_output_manager(manager: OutputManager):
    """Set the global output manager."""
    global out
    out = manager


def inspect_nodes(node_names: list[str], verbose: bool = True):
    """Inspect nodes by name and display their summaries and linked notes."""
    graph = GraphService()

    out.print("=" * 80)
    out.print("NODE INSPECTION REPORT")
    out.print("=" * 80)

    # Query to get node details including summary
    query = """
    UNWIND $names AS search_name
    MATCH (n:Indexable)
    WHERE toLower(n.name) CONTAINS toLower(search_name)
    OPTIONAL MATCH (note:Note)-[r]->(n)
    RETURN 
        n.name AS name,
        labels(n) AS labels,
        n.type AS type,
        n.summary AS summary,
        n.isolated_context AS isolated_context,
        n.definition AS definition,
        n.description AS description,
        n.status AS status,
        search_name AS matched_query,
        collect(DISTINCT {
            note_id: note.id,
            note_title: note.title,
            note_date: note.created_at
        })[0..5] AS linked_notes
    ORDER BY search_name, n.name
    """

    results = graph.execute_query(query, {"names": node_names})

    # Group by search term
    by_search_term = {}
    for row in results:
        term = row["matched_query"]
        if term not in by_search_term:
            by_search_term[term] = []
        by_search_term[term].append(row)

    for search_term, nodes in by_search_term.items():
        out.print(f"\n{'='*80}")
        out.print(f"SEARCH TERM: '{search_term}' - Found {len(nodes)} nodes")
        out.print("=" * 80)

        for node in nodes:
            name = node["name"]
            labels = [label for label in node["labels"] if label != "Indexable"]
            node_type = node["type"] or labels[0] if labels else "Unknown"

            out.print(f"\n{'─'*60}")
            out.print(f"📍 NODE: {name}")
            out.print(f"   Labels: {labels}")
            out.print(f"   Type: {node_type}")
            out.print(f"{'─'*60}")

            # Summary (FULL - not truncated)
            summary = node["summary"]
            if summary:
                out.print(f"\n📝 SUMMARY ({len(summary)} chars):")
                out.print(f"   {summary}")
            else:
                out.print("\n⚠️  NO SUMMARY")

            # Isolated Context (from extraction)
            context = node["isolated_context"]
            if context and verbose:
                out.print(f"\n📌 ISOLATED CONTEXT ({len(context)} chars):")
                out.print(f"   {context}")

            # Definition (for concepts)
            definition = node["definition"]
            if definition:
                out.print(f"\n📖 DEFINITION: {definition}")

            # Description (for tasks)
            description = node["description"]
            if description:
                out.print(f"\n📋 DESCRIPTION: {description}")

            # Status (for tasks)
            status = node["status"]
            if status:
                out.print(f"   Status: {status}")

            # Linked notes
            notes = [n for n in node["linked_notes"] if n.get("note_id")]
            if notes:
                out.print(f"\n🔗 LINKED NOTES ({len(notes)} shown):")
                for note in notes:
                    out.print(
                        f"   - {note.get('note_title', 'Untitled')} ({note.get('note_date', 'No date')})"
                    )

    out.print(f"\n{'='*80}")
    out.print("END OF REPORT")
    out.print("=" * 80)

    return by_search_term


def check_duplicate_nodes():
    """Find nodes that differ only by case."""
    graph = GraphService()

    out.print("\n" + "=" * 80)
    out.print("DUPLICATE NODE CHECK (case-insensitive)")
    out.print("=" * 80)

    query = """
    MATCH (n:Indexable)
    WITH toLower(n.name) AS lower_name, collect(n.name) AS names, count(*) AS cnt
    WHERE cnt > 1
    RETURN lower_name, names, cnt
    ORDER BY cnt DESC
    LIMIT 50
    """

    results = graph.execute_query(query, {})

    if not results:
        out.print("\n✅ No duplicate nodes found!")
        return []

    out.print(f"\n⚠️  Found {len(results)} groups of duplicate nodes:\n")

    for row in results:
        lower_name = row["lower_name"]
        names = row["names"]
        count = row["cnt"]
        out.print(f"  '{lower_name}' has {count} versions:")
        for name in names:
            out.print(f"    - '{name}'")

    return results


def get_retrieval_debug_info(query: str):
    """Simulate what retrieval would find for a query."""

    out.print("\n" + "=" * 80)
    out.print(f"RETRIEVAL DEBUG FOR: '{query}'")
    out.print("=" * 80)

    # Simple entity extraction from query - just look for capitalized words
    # or common patterns
    import re

    # Extract words that might be entity names (capitalized or camelCase)
    potential_entities = re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b", query)
    # Also look for specific patterns like company names
    potential_entities.extend(
        re.findall(r"\b\w+365\b|\b\w+Tech\b", query, re.IGNORECASE)
    )

    # Deduplicate and lowercase for lookup
    entities = list(set([e.lower() for e in potential_entities]))

    if entities:
        out.print(f"\n🔍 Extracted potential entities: {entities}")
        inspect_nodes(entities)
    else:
        out.print("\n⚠️  No entities extracted from query")
        # Fallback to simple word extraction
        words = [w.strip().lower() for w in query.split() if len(w) > 4]
        out.print(f"Fallback - checking words: {words[:5]}")
        if words:
            inspect_nodes(words[:5])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Debug node contents in the knowledge graph"
    )
    parser.add_argument(
        "nodes", nargs="?", help="Comma-separated list of node names to inspect"
    )
    parser.add_argument(
        "--query", "-q", help="Analyze a query and inspect related nodes"
    )
    parser.add_argument(
        "--duplicates", "-d", action="store_true", help="Check for duplicate nodes"
    )
    parser.add_argument(
        "--brief", "-b", action="store_true", help="Brief output (no isolated context)"
    )
    parser.add_argument("--output", "-o", help="Save output to file (e.g., report.txt)")

    args = parser.parse_args()

    # Set up output file path
    output_file = args.output
    if not output_file and (args.query or args.nodes):
        # Auto-generate filename based on timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"logs/debug_nodes_{timestamp}.txt"

    # Create output manager and run
    output_manager = OutputManager(output_file)
    set_output_manager(output_manager)

    with output_manager:
        if args.duplicates:
            check_duplicate_nodes()

        if args.query:
            get_retrieval_debug_info(args.query)
        elif args.nodes:
            node_list = [n.strip() for n in args.nodes.split(",")]
            inspect_nodes(node_list, verbose=not args.brief)
        elif not args.duplicates:
            # Default: check common problematic nodes
            print("Usage examples:")
            print("  python scripts/debug_nodes.py 'votex365,seveightech'")
            print(
                "  python scripts/debug_nodes.py --query 'How has Votex365 affected my life?'"
            )
            print("  python scripts/debug_nodes.py --duplicates")
            print("  python scripts/debug_nodes.py 'votex365' --output report.txt")
            print("\nRunning duplicate check by default...")
            check_duplicate_nodes()
