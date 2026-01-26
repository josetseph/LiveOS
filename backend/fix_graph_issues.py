"""
Fix identified issues in the knowledge graph
"""

from app.services.graph import graph_service

print("\n" + "=" * 80)
print("FIXING GRAPH ISSUES")
print("=" * 80 + "\n")

# Fix 1: Standardize Task Status
print("🔧 FIX 1: Standardizing Task Status")
print("-" * 80)

status_mapping = {
    # Complete variants
    "complete": "Complete",
    "completed": "Complete",
    "COMPLETED": "Complete",
    "Complete": "Complete",
    "DONE": "Complete",
    "Done": "Complete",
    "done": "Complete",
    "✅": "Complete",
    "fixed": "Complete",
    # Incomplete/Todo variants
    "incomplete": "Todo",
    "Incomplete": "Todo",
    "TODO": "Todo",
    "todo": "Todo",
    "Todo": "Todo",
    "Pending": "Todo",
    "pending": "Todo",
    "OPEN": "Todo",
    "open": "Todo",
    "Open": "Todo",
    # In Progress
    "in progress": "In Progress",
    # Cancelled/Invalid
    "x": "Cancelled",
    "❌": "Cancelled",
    "[-]": "Cancelled",
    # Null/invalid
    "null": "Todo",
    "string|null": "Todo",
    "string": "Todo",
}

for old_status, new_status in status_mapping.items():
    query = f"""
    MATCH (t:Task)
    WHERE t.status = '{old_status}'
    SET t.status = '{new_status}'
    RETURN count(t) as updated
    """
    try:
        result = graph_service.execute_query(query)
        if result and result[0]["updated"] > 0:
            print(
                f"  ✓ Standardized '{old_status}' → '{new_status}': {result[0]['updated']} tasks"
            )
    except Exception as e:
        print(f"  ✗ Error updating '{old_status}': {e}")

# Set null status to Todo
null_query = """
MATCH (t:Task)
WHERE t.status IS NULL
SET t.status = 'Todo'
RETURN count(t) as updated
"""
result = graph_service.execute_query(null_query)
if result and result[0]["updated"] > 0:
    print(f"  ✓ Set null status → 'Todo': {result[0]['updated']} tasks")

# Fix 2: Generate unique Task names
print("\n🔧 FIX 2: Generating Unique Task Names")
print("-" * 80)

# Use description hash for uniqueness
task_name_query = """
MATCH (t:Task)
WHERE t.name = t.description OR t.name IS NULL
WITH t, substring(t.description, 0, 50) + '_' + toString(id(t)) as unique_name
SET t.name = unique_name
RETURN count(t) as updated
"""
try:
    result = graph_service.execute_query(task_name_query)
    if result:
        print(f"  ✓ Generated unique names for {result[0]['updated']} tasks")
except Exception as e:
    print(f"  ✗ Error: {e}")
    # Fallback: simpler approach
    print("  Trying alternative method...")
    alt_query = """
    MATCH (t:Task)
    SET t.name = 'task_' + toString(id(t))
    RETURN count(t) as updated
    """
    result = graph_service.execute_query(alt_query)
    if result:
        print(f"  ✓ Generated unique IDs for {result[0]['updated']} tasks")

# Fix 3: Add summary to empty Reference
print("\n🔧 FIX 3: Fixing Empty Reference")
print("-" * 80)

empty_ref_fix = """
MATCH (r:Reference)
WHERE r.summary IS NULL OR size(r.summary) = 0
SET r.summary = CASE 
    WHEN r.content IS NOT NULL THEN 'Reference content: ' + r.content
    ELSE 'Empty reference node'
END
RETURN count(r) as fixed
"""
result = graph_service.execute_query(empty_ref_fix)
if result:
    print(f"  ✓ Fixed {result[0]['fixed']} empty reference(s)")

# Verification
print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80 + "\n")

# Check status distribution
status_check = """
MATCH (t:Task)
RETURN t.status as status, count(*) as count
ORDER BY count DESC
"""
results = graph_service.execute_query(status_check)
print("Updated Task Status Distribution:")
for row in results:
    print(f"  {row['status']}: {row['count']}")

# Check for duplicate names
duplicate_check = """
MATCH (t:Task)
WITH t.name as name, collect(t) as tasks
WHERE size(tasks) > 1
RETURN count(*) as duplicate_count
"""
result = graph_service.execute_query(duplicate_check)
if result:
    dup_count = result[0]["duplicate_count"]
    if dup_count == 0:
        print(f"\n✅ No duplicate task names")
    else:
        print(f"\n⚠️  Still have {dup_count} duplicate task names")

# Check references
ref_check = """
MATCH (r:Reference)
WHERE r.summary IS NULL OR size(r.summary) = 0
RETURN count(r) as empty_count
"""
result = graph_service.execute_query(ref_check)
if result:
    empty = result[0]["empty_count"]
    if empty == 0:
        print(f"✅ All references have summaries")
    else:
        print(f"⚠️  Still have {empty} empty references")

print("\n" + "=" * 80)
print("FIXES COMPLETE")
print("=" * 80 + "\n")
