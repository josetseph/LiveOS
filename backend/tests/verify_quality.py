"""
Quick verification that existing graph data maintains quality after implementing preventions.
"""

import sys

sys.path.insert(0, "/Users/joey/Projects/LiveOS/backend")

from app.services.graph import graph_service


def verify_current_graph_quality():
    """Check that previous fixes are still in effect."""

    print("\n" + "=" * 60)
    print("Graph Data Quality Verification")
    print("=" * 60)

    # 1. Task Status Distribution
    print("\n1. Task Status Distribution (should be 4 standard values):")
    query_status = """
    MATCH (t:Task)
    RETURN t.status as status, count(*) as count
    ORDER BY count DESC
    """
    results = graph_service.execute_query(query_status)

    total_tasks = sum(r["count"] for r in results)
    for row in results:
        status = row["status"]
        count = row["count"]
        pct = (count / total_tasks * 100) if total_tasks > 0 else 0
        print(f"   {status}: {count} ({pct:.1f}%)")

    # Check for non-standard values
    standard_statuses = {"Todo", "Complete", "In Progress", "Cancelled"}
    non_standard = [r for r in results if r["status"] not in standard_statuses]
    if non_standard:
        print(f"\n   ⚠️ WARNING: {len(non_standard)} non-standard status values found!")
        for r in non_standard:
            print(f"      - '{r['status']}': {r['count']} tasks")
    else:
        print(f"\n   ✓ All {total_tasks} tasks use standardized statuses")

    # 2. Duplicate Task Names
    print("\n2. Duplicate Task Names:")
    query_dupes = """
    MATCH (t:Task)
    WITH t.name as name, collect(t) as tasks
    WHERE size(tasks) > 1
    RETURN name, size(tasks) as duplicates
    ORDER BY duplicates DESC
    LIMIT 5
    """
    dupes = graph_service.execute_query(query_dupes)

    if dupes:
        print(f"   Found {len(dupes)} duplicate names:")
        for d in dupes:
            print(f"   - '{d['name']}': {d['duplicates']} tasks")
    else:
        print(f"   ✓ No duplicate task names found")

    # 3. Empty Reference Titles
    print("\n3. Empty Reference Titles:")
    query_refs = """
    MATCH (r:Reference)
    WHERE r.title IS NULL OR r.title = '' OR r.name IS NULL OR r.name = ''
    RETURN count(*) as empty_count
    """
    ref_result = graph_service.execute_query(query_refs)
    empty_count = ref_result[0]["empty_count"] if ref_result else 0

    if empty_count > 0:
        print(f"   ⚠️ WARNING: {empty_count} references with empty title/name")
    else:
        print(f"   ✓ All references have non-empty titles")

    # 4. Total Reference Count
    query_total_refs = """
    MATCH (r:Reference)
    RETURN count(*) as total
    """
    total_refs = graph_service.execute_query(query_total_refs)[0]["total"]
    print(f"   Total references: {total_refs}")

    print("\n" + "=" * 60)
    print("Verification Complete")
    print("=" * 60)


if __name__ == "__main__":
    verify_current_graph_quality()
