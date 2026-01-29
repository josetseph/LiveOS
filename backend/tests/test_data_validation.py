"""
Test script to verify data validation utilities work correctly.
"""

import sys

sys.path.insert(0, "/Users/joey/Projects/LiveOS/backend")

from app.utils.data_validation import (
    standardize_task_status,
    generate_unique_task_name,
    validate_reference_summary,
    standardize_extraction,
)
from app.schemas.extraction import Task, ExternalReference, Extraction


def test_task_status_standardization():
    """Test that all status variations map correctly."""
    print("\n=== Testing Task Status Standardization ===")

    test_cases = [
        # Todo variants
        ("todo", "Todo"),
        ("TODO", "Todo"),
        ("pending", "Todo"),
        ("Pending", "Todo"),
        ("open", "Todo"),
        (None, "Todo"),
        ("", "Todo"),
        # Complete variants
        ("complete", "Complete"),
        ("completed", "Complete"),
        ("Completed", "Complete"),
        ("done", "Complete"),
        ("Done", "Complete"),
        ("finished", "Complete"),
        ("✓", "Complete"),
        # In Progress variants
        ("in progress", "In Progress"),
        ("In-Progress", "In Progress"),
        ("active", "In Progress"),
        ("ongoing", "In Progress"),
        # Cancelled variants
        ("cancelled", "Cancelled"),
        ("canceled", "Cancelled"),
        ("x", "Cancelled"),
        ("❌", "Cancelled"),
        ("blocked", "Cancelled"),
        ("abandoned", "Cancelled"),
        # Edge cases
        ("weird_status", "Todo"),  # Unknown defaults to Todo
    ]

    passed = 0
    failed = 0

    for input_status, expected in test_cases:
        result = standardize_task_status(input_status)
        if result == expected:
            passed += 1
            print(f"✓ '{input_status}' → '{result}'")
        else:
            failed += 1
            print(f"✗ '{input_status}' → '{result}' (expected '{expected}')")

    print(f"\nStatus Tests: {passed} passed, {failed} failed")
    return failed == 0


def test_unique_task_names():
    """Test that task names are unique and readable."""
    print("\n=== Testing Unique Task Name Generation ===")

    test_cases = [
        ("Complete ceruba integration", "abc123"),
        (
            "Very long task description that should be truncated at fifty characters exactly",
            "def456",
        ),
        ("Short", "xyz789"),
        ("", "empty1"),
    ]

    for desc, task_id in test_cases:
        name = generate_unique_task_name(desc, task_id)
        print(f"Description: '{desc[:60]}...' → Name: '{name}'")

        # Verify uniqueness constraint
        assert len(name) <= 59, f"Name too long: {len(name)} chars"
        assert "_" in name, "Name should contain underscore separator"

    # Test that different IDs produce different names for same description
    name1 = generate_unique_task_name("Same description", "id1")
    name2 = generate_unique_task_name("Same description", "id2")
    assert name1 != name2, "Different IDs should produce different names"
    print(f"✓ Uniqueness verified: '{name1}' != '{name2}'")

    print("\nTask Name Tests: All passed")
    return True


def test_reference_validation():
    """Test that empty references get proper titles."""
    print("\n=== Testing Reference Summary Validation ===")

    test_cases = [
        # Empty title, has content
        ExternalReference(
            title="", content="God is with me", source="Unknown", type="Quote"
        ),
        # Empty title, has source
        ExternalReference(title="", content="", source="John Doe", type="Book"),
        # Empty everything
        ExternalReference(title="", content="", source="", type="Paper"),
        # Already has title (should not change)
        ExternalReference(
            title="The Art of War", content="...", source="Sun Tzu", type="Book"
        ),
    ]

    for i, ref in enumerate(test_cases, 1):
        validated = validate_reference_summary(ref)
        print(f"Test {i}:")
        print(
            f"  Before: title='{ref.title}', content='{ref.content[:30]}...', source='{ref.source}'"
        )
        print(f"  After:  title='{validated.title}'")
        assert (
            validated.title and validated.title.strip()
        ), f"Test {i} failed: title still empty"

    print("\nReference Validation Tests: All passed")
    return True


def test_full_extraction_standardization():
    """Test standardization on a complete extraction."""
    print("\n=== Testing Full Extraction Standardization ===")

    extraction = Extraction(
        summary="Test note",
        domain="Personal",
        tasks=[
            Task(description="Task 1", status="done"),  # Should become "Complete"
            Task(description="Task 2", status="PENDING"),  # Should become "Todo"
            Task(
                description="Task 3", status="in-progress"
            ),  # Should become "In Progress"
            Task(description="Task 4", status=None),  # Should become "Todo"
        ],
        references=[
            ExternalReference(
                title="", content="Some quote", source="Author", type="Quote"
            ),
            ExternalReference(
                title="Valid Title", content="Content", source="Source", type="Paper"
            ),
        ],
    )

    print(f"Before standardization:")
    print(f"  Task statuses: {[t.status for t in extraction.tasks]}")
    print(f"  Reference titles: {[r.title for r in extraction.references]}")

    standardized = standardize_extraction(extraction)

    print(f"\nAfter standardization:")
    print(f"  Task statuses: {[t.status for t in standardized.tasks]}")
    print(f"  Reference titles: {[r.title for r in standardized.references]}")

    # Verify all statuses are standardized
    assert standardized.tasks[0].status == "Complete"
    assert standardized.tasks[1].status == "Todo"
    assert standardized.tasks[2].status == "In Progress"
    assert standardized.tasks[3].status == "Todo"

    # Verify reference got a title
    assert standardized.references[0].title and standardized.references[0].title.strip()
    assert standardized.references[1].title == "Valid Title"  # Should not change

    print("\nFull Extraction Tests: All passed")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Data Validation Utilities Test Suite")
    print("=" * 60)

    all_passed = True
    all_passed &= test_task_status_standardization()
    all_passed &= test_unique_task_names()
    all_passed &= test_reference_validation()
    all_passed &= test_full_extraction_standardization()

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 60)
