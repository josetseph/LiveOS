#!/usr/bin/env python3
"""
Monitor alias detection progress in real-time.

Shows:
- Total IS_SAME_AS links created
- Recent activity (last 10 links)
- Processing rate (links per hour)
- Estimated time remaining
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import graph_service


def monitor_progress():
    """Show current alias detection progress."""

    print("\n" + "=" * 80)
    print("ALIAS DETECTION PROGRESS MONITOR")
    print("=" * 80)
    print(f"Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Total links created
    total_query = """
    MATCH ()-[r:IS_SAME_AS]->()
    RETURN count(r) as total
    """
    total_result = graph_service.execute_query(total_query, {})
    total_links = total_result[0]["total"] if total_result else 0

    print(f"Total IS_SAME_AS links created: {total_links}")

    # Recent links (last hour)
    recent_query = """
    MATCH ()-[r:IS_SAME_AS]->()
    WHERE r.detected_at >= datetime() - duration({hours: 1})
    RETURN count(r) as recent
    """
    recent_result = graph_service.execute_query(recent_query, {})
    recent_links = recent_result[0]["recent"] if recent_result else 0

    print(f"Links created in last hour: {recent_links}")
    print(f"Processing rate: {recent_links} links/hour")

    # Last 10 links created
    last_links_query = """
    MATCH (a)-[r:IS_SAME_AS]->(c)
    WHERE r.detected_at IS NOT NULL
    RETURN a.name as alias,
           c.name as canonical,
           r.detected_at as created_at,
           r.confidence as confidence
    ORDER BY r.detected_at DESC
    LIMIT 10
    """
    last_links = graph_service.execute_query(last_links_query, {})

    if last_links:
        print("\n" + "-" * 80)
        print("MOST RECENT LINKS (Last 10):")
        print("-" * 80)
        for i, link in enumerate(last_links, 1):
            created_at = link["created_at"]
            time_str = (
                created_at.strftime("%H:%M:%S")
                if hasattr(created_at, "strftime")
                else str(created_at)
            )
            print(
                f"{i:2d}. {time_str} | '{link['alias']}' -> '{link['canonical']}' "
                f"(conf: {link['confidence']:.2f})"
            )
    else:
        print("\nNo recent links found. Process may not be running.")

    # Entities without IS_SAME_AS
    remaining_query = """
    MATCH (e:Entity)
    WHERE NOT (e)-[:IS_SAME_AS]->()
      AND e.summary IS NOT NULL
      AND size(e.summary) > 20
    RETURN count(e) as remaining
    """
    remaining_result = graph_service.execute_query(remaining_query, {})
    remaining = remaining_result[0]["remaining"] if remaining_result else 0

    # Total entities that need checking
    total_query = """
    MATCH (e:Entity)
    WHERE e.summary IS NOT NULL
      AND size(e.summary) > 20
    RETURN count(e) as total
    """
    total_result = graph_service.execute_query(total_query, {})
    total_entities = total_result[0]["total"] if total_result else 0

    processed = total_entities - remaining
    progress_pct = (processed / total_entities * 100) if total_entities > 0 else 0

    print("\n" + "-" * 80)
    print("PROGRESS ESTIMATE:")
    print("-" * 80)
    print(f"Total entities to process: {total_entities}")
    print(f"Entities processed: {processed}")
    print(f"Entities remaining: {remaining}")
    print(f"Progress: {progress_pct:.1f}%")

    # Estimate time remaining
    if recent_links > 0 and remaining > 0:
        # Assume similar rate: recent_links per hour
        # But we process entities, not just create links
        # Rough estimate: if we created X links in last hour, we processed ~5X entities (assuming 20% match rate)
        estimated_entities_per_hour = recent_links * 5 if recent_links > 0 else 10
        hours_remaining = (
            remaining / estimated_entities_per_hour
            if estimated_entities_per_hour > 0
            else 0
        )
        completion_time = datetime.now() + timedelta(hours=hours_remaining)

        print(
            f"\nEstimated completion: {completion_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(
            f"Time remaining: ~{hours_remaining:.1f} hours ({hours_remaining*60:.0f} minutes)"
        )
    elif remaining == 0:
        print("\n✅ All entities processed!")
    else:
        print("\n⚠️  No recent activity detected. Process may be stuck or not running.")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    try:
        monitor_progress()
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
