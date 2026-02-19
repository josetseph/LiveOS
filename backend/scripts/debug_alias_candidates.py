#!/usr/bin/env python3
"""
Debug script to understand why alias detection finds no entities.
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import graph_service


async def main():
    print("\n" + "=" * 80)
    print("🔍 ALIAS DETECTION DEBUG")
    print("=" * 80 + "\n")
    
    # Check 1: Total entities
    print("1️⃣  Checking total entities...")
    result = graph_service.execute_query("MATCH (e:Entity) RETURN count(e) as total", {})
    total = result[0]["total"] if result else 0
    print(f"   Total entities in graph: {total}\n")
    
    if total == 0:
        print("❌ No entities found! You need to ingest some notes first.")
        return
    
    # Check 2: Entities with summaries
    print("2️⃣  Checking entities with summaries...")
    result = graph_service.execute_query(
        "MATCH (e:Entity) WHERE e.summary IS NOT NULL RETURN count(e) as total", {}
    )
    with_summary = result[0]["total"] if result else 0
    print(f"   Entities with summary: {with_summary}\n")
    
    # Check 3: Entities with long enough summaries
    print("3️⃣  Checking entities with long enough summaries (>20 chars)...")
    result = graph_service.execute_query(
        "MATCH (e:Entity) WHERE e.summary IS NOT NULL AND size(e.summary) > 20 RETURN count(e) as total", 
        {}
    )
    long_summary = result[0]["total"] if result else 0
    print(f"   Entities with summary > 20 chars: {long_summary}\n")
    
    # Check 4: Entities already linked
    print("4️⃣  Checking entities with IS_SAME_AS links...")
    result = graph_service.execute_query(
        "MATCH (e:Entity)-[:IS_SAME_AS]->() RETURN count(DISTINCT e) as total", {}
    )
    already_linked = result[0]["total"] if result else 0
    print(f"   Entities already linked: {already_linked}\n")
    
    # Check 5: Entities meeting ALL criteria
    print("5️⃣  Checking entities meeting ALL criteria (candidates for alias detection)...")
    result = graph_service.execute_query(
        """
        MATCH (e:Entity)
        WHERE NOT (e)-[:IS_SAME_AS]->()
          AND e.summary IS NOT NULL
          AND size(e.summary) > 20
        RETURN count(e) as total
        """,
        {}
    )
    candidates = result[0]["total"] if result else 0
    print(f"   Eligible candidates: {candidates}\n")
    
    if candidates == 0:
        print("❌ No candidates found! Reasons could be:")
        print(f"   • All {with_summary} entities with summaries are already linked")
        print(f"   • Only {long_summary} entities have summaries long enough")
        print()
    
    # Show sample entities
    print("6️⃣  Sample entities in your graph:\n")
    result = graph_service.execute_query(
        """
        MATCH (e:Entity)
        RETURN e.name as name, 
               e.entity_type as type, 
               size(e.summary) as summary_length,
               (e)-[:IS_SAME_AS]->() as has_alias
        ORDER BY summary_length DESC
        LIMIT 10
        """,
        {}
    )
    
    if result:
        for i, entity in enumerate(result, 1):
            alias_status = "✅" if entity["has_alias"] else "❌"
            summary_len = entity["summary_length"] if entity["summary_length"] else 0
            print(f"   {i:2d}. {entity['name']} ({entity['type']})")
            print(f"       Summary length: {summary_len} | Has alias link: {alias_status}")
        print()
    
    # Show similar names
    print("7️⃣  Looking for entities with similar names (potential aliases):\n")
    result = graph_service.execute_query(
        """
        MATCH (e1:Entity), (e2:Entity)
        WHERE e1.name <> e2.name
          AND e1.entity_type = e2.entity_type
          AND (
              e1.name CONTAINS e2.name 
              OR e2.name CONTAINS e1.name
              OR toLower(split(e1.name, ' ')[0]) = toLower(split(e2.name, ' ')[0])
          )
          AND NOT (e1)-[:IS_SAME_AS]-()
          AND NOT (e2)-[:IS_SAME_AS]-()
        RETURN DISTINCT e1.name as name1, e2.name as name2, e1.entity_type as type
        LIMIT 5
        """,
        {}
    )
    
    if result:
        for i, pair in enumerate(result, 1):
            print(f"   {i}. '{pair['name1']}' ↔ '{pair['name2']}' ({pair['type']})")
        print()
    else:
        print("   No obvious similar names found")
        print()
    
    # Final recommendation
    print("=" * 80)
    print("💡 RECOMMENDATIONS")
    print("=" * 80)
    
    if candidates == 0 and total > 0:
        if long_summary == 0:
            print("• No entities have summaries. Run ingestion to populate entity summaries.")
        elif already_linked == with_summary:
            print("• All entities with summaries are already linked!")
            print("• To re-run detection, delete existing links:")
            print("  MATCH ()-[r:IS_SAME_AS]->() DELETE r")
        else:
            print("• Check if entity summaries are being created during ingestion")
            print("• Verify that _update_node_summary() is being called")
    elif candidates > 0:
        print(f"✅ You have {candidates} candidates ready for alias detection!")
        print(f"   Run: python scripts/detect_aliases.py --limit {min(candidates, 100)}")
    else:
        print("• Ingest some notes first to create entities")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
