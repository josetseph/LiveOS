"""
Final cleanup of remaining edge cases in existing graph data.
"""

import sys

sys.path.insert(0, "/Users/joey/Projects/LiveOS/backend")

from app.services.graph import graph_service
from app.utils.data_validation import generate_unique_task_name


def fix_remaining_issues():
    """Fix the last remaining data quality issues."""

    print("\n" + "=" * 60)
    print("Final Data Quality Cleanup")
    print("=" * 60)

    # 1. Fix remaining "Completed" tasks (should be "Complete")
    print("\n1. Fixing 'Completed' → 'Complete' status...")
    query_fix_status = """
    MATCH (t:Task)
    WHERE t.status = 'Completed'
    SET t.status = 'Complete'
    RETURN count(*) as fixed
    """
    result = graph_service.execute_query(query_fix_status)
    print(f"   ✓ Fixed {result[0]['fixed']} tasks")

    # 2. Fix duplicate task names
    print("\n2. Fixing duplicate task names...")

    # Get all duplicate names
    query_get_dupes = """
    MATCH (t:Task)
    WITH t.name as name, collect(t) as tasks
    WHERE size(tasks) > 1
    RETURN name, tasks
    """
    dupes = graph_service.execute_query(query_get_dupes)

    fixed_count = 0
    for dup in dupes:
        tasks = dup["tasks"]
        print(f"   Fixing '{dup['name'][:60]}...' ({len(tasks)} duplicates)")

        # Generate new unique names for each task
        for task in tasks:
            task_id = task["id"]
            description = task.get("description", "Untitled")
            new_name = generate_unique_task_name(description, task_id)

            query_update = """
            MATCH (t:Task {id: $task_id})
            SET t.name = $new_name
            """
            graph_service.execute_query(
                query_update, {"task_id": task_id, "new_name": new_name}
            )
            fixed_count += 1

    print(f"   ✓ Fixed {fixed_count} duplicate task names")

    # 3. Fix empty reference
    print("\n3. Fixing empty reference title...")
    query_fix_ref = """
    MATCH (r:Reference)
    WHERE r.title IS NULL OR r.title = '' OR r.name IS NULL OR r.name = ''
    SET r.title = CASE 
        WHEN r.content IS NOT NULL AND r.content <> '' 
        THEN 'Reference: ' + substring(r.content, 0, 50)
        WHEN r.source IS NOT NULL AND r.source <> ''
        THEN coalesce(r.type, 'Reference') + ' by ' + r.source
        ELSE 'Untitled ' + coalesce(r.type, 'Reference')
    END,
    r.name = CASE 
        WHEN r.content IS NOT NULL AND r.content <> '' 
        THEN 'Reference: ' + substring(r.content, 0, 50)
        WHEN r.source IS NOT NULL AND r.source <> ''
        THEN coalesce(r.type, 'Reference') + ' by ' + r.source
        ELSE 'Untitled ' + coalesce(r.type, 'Reference')
    END
    RETURN count(*) as fixed
    """
    result = graph_service.execute_query(query_fix_ref)
    print(f"   ✓ Fixed {result[0]['fixed']} references")

    print("\n" + "=" * 60)
    print("Cleanup Complete - All Issues Fixed")
    print("=" * 60)


if __name__ == "__main__":
    fix_remaining_issues()

    # Re-run verification
    print("\n\nRe-running verification...")
    import verify_quality

    verify_quality.verify_current_graph_quality()
