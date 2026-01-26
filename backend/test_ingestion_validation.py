"""
Integration test to verify data validation in full ingestion pipeline.
Tests that a note with messy data gets properly standardized.
"""

import sys

sys.path.insert(0, "/Users/joey/Projects/LiveOS/backend")

from app.schemas.extraction import Extraction, Task, ExternalReference, Entity, Concept
from app.utils.data_validation import standardize_extraction


def test_messy_extraction():
    """Simulate LLM extracting data with all the problematic patterns."""

    print("\n" + "=" * 60)
    print("Integration Test: Full Pipeline Validation")
    print("=" * 60)

    # Simulate messy LLM extraction with all the problems we fixed
    messy_extraction = Extraction(
        summary="Test note with messy extracted data",
        domain="Professional",
        entities=[
            Entity(name="Test Company", type="Organization", importance=0.8),
        ],
        concepts=[
            Concept(name="Project Management", definition="Managing projects"),
        ],
        tasks=[
            Task(
                description="Fix the login bug", status="done"
            ),  # Should become "Complete"
            Task(
                description="Review PR #123", status="PENDING"
            ),  # Should become "Todo"
            Task(
                description="Deploy to production", status="in-progress"
            ),  # Should become "In Progress"
            Task(
                description="Cancel old feature", status="x"
            ),  # Should become "Cancelled"
            Task(description="New task", status=None),  # Should become "Todo"
            Task(
                description="Weird status task", status="weird_value"
            ),  # Should become "Todo"
        ],
        references=[
            # Empty title but has content - should get generated title
            ExternalReference(
                title="",
                content="The best way to predict the future is to invent it.",
                source="Alan Kay",
                type="Quote",
            ),
            # Empty title, has source - should get generated title
            ExternalReference(
                title="", content="", source="Martin Fowler", type="Book"
            ),
            # Has title - should not change
            ExternalReference(
                title="Clean Code",
                content="A Handbook of Agile Software Craftsmanship",
                source="Robert C. Martin",
                type="Book",
            ),
        ],
    )

    print("\n📥 BEFORE STANDARDIZATION:")
    print(f"\nTask Statuses:")
    for i, task in enumerate(messy_extraction.tasks, 1):
        print(f"  {i}. '{task.description[:40]}...' → status: '{task.status}'")

    print(f"\nReference Titles:")
    for i, ref in enumerate(messy_extraction.references, 1):
        title_preview = ref.title if ref.title else "(empty)"
        print(f"  {i}. {title_preview}")

    # Apply standardization (this is what happens in extraction_node)
    clean_extraction = standardize_extraction(messy_extraction)

    print("\n📤 AFTER STANDARDIZATION:")
    print(f"\nTask Statuses:")
    for i, task in enumerate(clean_extraction.tasks, 1):
        print(f"  {i}. '{task.description[:40]}...' → status: '{task.status}'")

    print(f"\nReference Titles:")
    for i, ref in enumerate(clean_extraction.references, 1):
        print(f"  {i}. {ref.title}")

    # Verify standardization
    print("\n" + "=" * 60)
    print("VALIDATION CHECKS:")
    print("=" * 60)

    # Check 1: All task statuses are standardized
    valid_statuses = {"Todo", "Complete", "In Progress", "Cancelled"}
    all_valid = all(task.status in valid_statuses for task in clean_extraction.tasks)

    if all_valid:
        print("✓ All task statuses standardized to valid values")
    else:
        print("✗ FAILED: Some task statuses not standardized")
        for task in clean_extraction.tasks:
            if task.status not in valid_statuses:
                print(f"   Invalid: '{task.status}'")

    # Check 2: Expected status conversions
    expected_statuses = ["Complete", "Todo", "In Progress", "Cancelled", "Todo", "Todo"]
    actual_statuses = [task.status for task in clean_extraction.tasks]

    if actual_statuses == expected_statuses:
        print("✓ Status conversions correct:")
        conversions = [
            "done → Complete",
            "PENDING → Todo",
            "in-progress → In Progress",
            "x → Cancelled",
            "None → Todo",
            "weird_value → Todo",
        ]
        for conv in conversions:
            print(f"   • {conv}")
    else:
        print(f"✗ FAILED: Expected {expected_statuses}, got {actual_statuses}")

    # Check 3: All references have titles
    all_have_titles = all(
        ref.title and ref.title.strip() for ref in clean_extraction.references
    )

    if all_have_titles:
        print("✓ All references have non-empty titles")
    else:
        print("✗ FAILED: Some references have empty titles")

    # Check 4: Empty titles were generated correctly
    ref1 = clean_extraction.references[0]
    ref2 = clean_extraction.references[1]
    ref3 = clean_extraction.references[2]

    checks_passed = 0
    checks_total = 3

    if "Reference:" in ref1.title and "predict the future" in ref1.title:
        print(f"✓ Empty title + content → '{ref1.title}'")
        checks_passed += 1
    else:
        print(f"✗ FAILED: Ref 1 title generation: '{ref1.title}'")

    if "Book by Martin Fowler" in ref2.title:
        print(f"✓ Empty title + source → '{ref2.title}'")
        checks_passed += 1
    else:
        print(f"✗ FAILED: Ref 2 title generation: '{ref2.title}'")

    if ref3.title == "Clean Code":
        print(f"✓ Existing title preserved → '{ref3.title}'")
        checks_passed += 1
    else:
        print(f"✗ FAILED: Ref 3 should preserve title: '{ref3.title}'")

    print("\n" + "=" * 60)
    final_checks = (
        all_valid
        and (actual_statuses == expected_statuses)
        and all_have_titles
        and (checks_passed == checks_total)
    )

    if final_checks:
        print("✅ INTEGRATION TEST PASSED")
        print("Data validation pipeline working correctly!")
    else:
        print("❌ INTEGRATION TEST FAILED")
        print("Some validations did not pass")

    print("=" * 60)

    return final_checks


if __name__ == "__main__":
    success = test_messy_extraction()
    sys.exit(0 if success else 1)
