"""
Diagnose specific issues found in verification
"""

from app.services.graph import graph_service

print("\n" + "=" * 80)
print("ISSUE DIAGNOSIS")
print("=" * 80 + "\n")

# Issue 1: Task naming and status
print("🔍 ISSUE 1: TASK NODES")
print("-" * 80)

# Check task structure
task_structure_query = """
MATCH (t:Task)
RETURN t.name as name, 
       t.description as description, 
       t.status as status
LIMIT 10
"""
results = graph_service.execute_query(task_structure_query)
print("\nSample Task Structure:")
for i, row in enumerate(results[:5], 1):
    print(f"{i}. Name: {row.get('name', 'NULL')}")
    print(f"   Description: {row.get('description', 'NULL')[:60]}")
    print(f"   Status: {row.get('status', 'NULL')}")
    print()

# Count tasks by status
status_query = """
MATCH (t:Task)
RETURN t.status as status, count(*) as count
ORDER BY count DESC
"""
results = graph_service.execute_query(status_query)
print("\nTask Status Distribution:")
for row in results:
    status = row["status"] if row["status"] else "NULL"
    print(f"  {status}: {row['count']}")

# Issue 2: Empty Reference
print("\n\n🔍 ISSUE 2: EMPTY REFERENCE")
print("-" * 80)

empty_ref_query = """
MATCH (r:Reference)
WHERE r.summary IS NULL OR size(r.summary) = 0
RETURN r.name as name, 
       r.summary as summary,
       r.content as content,
       id(r) as internal_id
"""
results = graph_service.execute_query(empty_ref_query)
if results:
    print(f"\nFound {len(results)} empty reference(s):")
    for row in results:
        print(f"  Name: '{row.get('name', 'NULL')}'")
        print(f"  Summary: '{row.get('summary', 'NULL')}'")
        print(f"  Content: '{row.get('content', 'NULL')}'")
        print(f"  Internal ID: {row.get('internal_id')}")
else:
    print("No empty references found")

# Check if tasks have duplicates
print("\n\n🔍 ISSUE 3: DUPLICATE TASK DESCRIPTIONS")
print("-" * 80)

duplicate_query = """
MATCH (t:Task)
WITH t.description as desc, collect(t) as tasks
WHERE size(tasks) > 1
RETURN desc, size(tasks) as count
ORDER BY count DESC
LIMIT 10
"""
results = graph_service.execute_query(duplicate_query)
if results:
    print(f"\nFound {len(results)} duplicate task descriptions:")
    for row in results:
        print(f"  '{row['desc'][:60]}...': {row['count']} copies")
else:
    print("No duplicate descriptions found")

print("\n" + "=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80 + "\n")
