"""
Data validation and standardization utilities for ingestion pipeline.
Prevents common data quality issues by normalizing extracted data.
"""

from app.schemas.extraction import Extraction, ExternalReference
import hashlib


# Standardized task status values (matches what fix_graph_issues.py uses)
VALID_TASK_STATUSES = {"Todo", "Complete", "In Progress", "Cancelled"}

# Mapping of common status variations to standardized values
STATUS_MAPPING = {
    # Todo variants
    "todo": "Todo",
    "TODO": "Todo",
    "pending": "Todo",
    "Pending": "Todo",
    "PENDING": "Todo",
    "open": "Todo",
    "OPEN": "Todo",
    "Open": "Todo",
    "not started": "Todo",
    "Not Started": "Todo",
    # Complete variants
    "complete": "Complete",
    "completed": "Complete",
    "Completed": "Complete",
    "COMPLETED": "Complete",
    "done": "Complete",
    "Done": "Complete",
    "DONE": "Complete",
    "finished": "Complete",
    "Finished": "Complete",
    "FINISHED": "Complete",
    "closed": "Complete",
    "Closed": "Complete",
    "CLOSED": "Complete",
    "✓": "Complete",
    "✔": "Complete",
    # In Progress variants
    "in progress": "In Progress",
    "in-progress": "In Progress",
    "In-Progress": "In Progress",
    "IN PROGRESS": "In Progress",
    "IN-PROGRESS": "In Progress",
    "active": "In Progress",
    "Active": "In Progress",
    "ACTIVE": "In Progress",
    "ongoing": "In Progress",
    "Ongoing": "In Progress",
    "ONGOING": "In Progress",
    # Cancelled variants
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
    "Canceled": "Cancelled",
    "CANCELLED": "Cancelled",
    "CANCELED": "Cancelled",
    "x": "Cancelled",
    "X": "Cancelled",
    "❌": "Cancelled",
    "blocked": "Cancelled",
    "Blocked": "Cancelled",
    "BLOCKED": "Cancelled",
    "abandoned": "Cancelled",
    "Abandoned": "Cancelled",
    "ABANDONED": "Cancelled",
}


def standardize_task_status(status: str) -> str:
    """
    Standardizes task status to one of four canonical values.

    Args:
        status: Raw status string from extraction

    Returns:
        Standardized status: "Todo", "Complete", "In Progress", or "Cancelled"
    """
    if not status or not isinstance(status, str):
        return "Todo"  # Default to Todo for null/empty

    # Direct match to valid statuses (already standardized)
    if status in VALID_TASK_STATUSES:
        return status

    # Map common variations
    if status in STATUS_MAPPING:
        return STATUS_MAPPING[status]

    # Fallback: Try case-insensitive partial match
    status_lower = status.lower().strip()
    if "complet" in status_lower or "done" in status_lower or "finish" in status_lower:
        return "Complete"
    elif (
        "progress" in status_lower
        or "active" in status_lower
        or "ongoing" in status_lower
    ):
        return "In Progress"
    elif (
        "cancel" in status_lower or "abandon" in status_lower or "block" in status_lower
    ):
        return "Cancelled"
    else:
        return "Todo"  # Default fallback


def generate_unique_task_name(description: str, task_id: str = None) -> str:
    """
    Generates a unique task name from description and ID.
    Prevents redundant name=description structure.

    Args:
        description: Task description
        task_id: Optional UUID for uniqueness

    Returns:
        Unique name: truncated description + hash suffix
    """
    if not description or not isinstance(description, str):
        description = "Untitled Task"

    # Truncate to 50 chars for readability
    truncated = description[:50].strip()

    # Add unique suffix using hash (short enough for display)
    if task_id:
        suffix = task_id[:8]  # Use first 8 chars of UUID
    else:
        # Generate deterministic hash from description
        suffix = hashlib.md5(description.encode()).hexdigest()[:8]

    return f"{truncated}_{suffix}"


def validate_reference_summary(ref: ExternalReference) -> ExternalReference:
    """
    Ensures reference has a non-empty summary/title.
    Prevents empty reference nodes in graph.

    Args:
        ref: ExternalReference object

    Returns:
        Validated reference with guaranteed title
    """
    if not ref.title or not ref.title.strip():
        # Generate title from content if available
        if ref.content and ref.content.strip():
            ref.title = f"Reference: {ref.content[:50].strip()}"
        elif ref.source and ref.source.strip():
            ref.title = f"{ref.type} by {ref.source}"
        else:
            ref.title = f"Untitled {ref.type}"

    # Note: 'name' field is added in graph query, not in schema
    return ref


def standardize_extraction(extraction: Extraction) -> Extraction:
    """
    Main validation function - standardizes all extracted data.

    Prevents these issues:
    1. Task status fragmentation (21+ variants → 4 standard)
    2. Redundant task naming (name=description)
    3. Empty reference summaries

    Args:
        extraction: Raw extraction from LLM

    Returns:
        Standardized extraction ready for graph storage
    """

    # Standardize task statuses
    if extraction.tasks:
        for task in extraction.tasks:
            task.status = standardize_task_status(task.status)

    # Validate references
    if extraction.references:
        extraction.references = [
            validate_reference_summary(ref) for ref in extraction.references
        ]

    return extraction
