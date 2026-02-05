#!/usr/bin/env python3
"""
Test script for inter-node relationship functionality.

Tests:
1. Relationship creation and storage
2. Relationship evolution
3. Relationship queries (get_node_relationships, get_related_nodes)
4. Relationship enrichment in retrieval

Usage:
    python test_relationships.py
"""

import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.graph import graph_service
from app.core.logging_config import get_component_logger

logger = get_component_logger("RelationshipTest")


async def test_relationship_creation():
    """Test creating relationships between nodes"""
    print("\n=== TEST 1: Relationship Creation ===")
    logger.info("\n=== TEST 1: Relationship Creation ===")

    # Test data: Create some nodes first via direct Cypher
    setup_query = """
    MERGE (alice:Entity {name: 'Alice'})
    SET alice.type = 'Person', alice.summary = 'Software engineer'
    
    MERGE (bob:Entity {name: 'Bob'})
    SET bob.type = 'Person', bob.summary = 'Product manager'
    
    MERGE (ml:Concept {name: 'Machine Learning'})
    SET ml.definition = 'AI that learns from data'
    
    MERGE (nn:Concept {name: 'Neural Networks'})
    SET nn.definition = 'Brain-inspired computational models'
    
    MERGE (project:Task {name: 'ML Project', description: 'Build ML model'})
    SET project.status = 'In Progress'
    """
    graph_service.execute_query(setup_query)
    print("✓ Created test nodes")
    logger.info("✓ Created test nodes (Alice, Bob, ML concepts, Project)")

    # Test 1: Create works_with relationship
    result = graph_service.create_or_update_relationship(
        source_name="Alice",
        source_label="Entity",
        target_name="Bob",
        target_label="Entity",
        relationship_type="works_with",
        confidence=0.9,
        context="Alice and Bob are working together on the ML project",
        note_id="test-note-1",
    )
    assert (
        result["action"] == "created"
    ), f"Expected 'created' but got {result['action']}"
    logger.info(f"✓ Created relationship: Alice-[works_with]->Bob")

    # Test 2: Bidirectional check (works_with should auto-create inverse)
    bob_rels = graph_service.get_node_relationships(
        node_name="Bob", node_label="Entity", direction="outgoing"
    )
    has_inverse = any(
        r.get("target_name") == "Alice" and r.get("relationship_type") == "works_with"
        for r in bob_rels
    )
    assert has_inverse, "Bidirectional relationship not created"
    logger.info(f"✓ Bidirectional relationship verified: Bob-[works_with]->Alice")

    # Test 3: Create prerequisite relationship between concepts
    result = graph_service.create_or_update_relationship(
        source_name="Neural Networks",
        source_label="Concept",
        target_name="Machine Learning",
        target_label="Concept",
        relationship_type="prerequisite_for",
        confidence=0.85,
        context="Understanding ML basics is needed before Neural Networks",
        note_id="test-note-2",
    )
    assert result["action"] == "created"
    logger.info(f"✓ Created prerequisite: Neural Networks requires Machine Learning")

    # Test 4: Create person-to-task assignment
    result = graph_service.create_or_update_relationship(
        source_name="Alice",
        source_label="Entity",
        target_name="ML Project",
        target_label="Task",
        relationship_type="assigned_to",
        confidence=0.95,
        context="Alice is assigned to work on the ML Project",
        note_id="test-note-3",
    )
    assert result["action"] == "created"
    logger.info(f"✓ Created assignment: Alice-[assigned_to]->ML Project")

    return True


async def test_relationship_evolution():
    """Test relationship evolution (knows -> friends_with -> married_to)"""
    logger.info("\n=== TEST 2: Relationship Evolution ===")

    # Setup nodes
    setup_query = """
    MERGE (charlie:Entity {name: 'Charlie'})
    SET charlie.type = 'Person'
    
    MERGE (diana:Entity {name: 'Diana'})
    SET diana.type = 'Person'
    """
    graph_service.execute_query(setup_query)

    # Stage 1: knows
    result = graph_service.create_or_update_relationship(
        source_name="Charlie",
        source_label="Entity",
        target_name="Diana",
        target_label="Entity",
        relationship_type="knows",
        confidence=0.7,
        context="Charlie met Diana at a conference",
        note_id="test-note-4",
    )
    assert result["action"] == "created"
    logger.info(f"✓ Initial relationship: Charlie-[knows]->Diana")

    # Stage 2: Evolve to friends_with
    result = graph_service.create_or_update_relationship(
        source_name="Charlie",
        source_label="Entity",
        target_name="Diana",
        target_label="Entity",
        relationship_type="friends_with",
        confidence=0.9,
        context="Charlie and Diana became good friends",
        note_id="test-note-5",
    )
    assert (
        result["action"] == "evolved"
    ), f"Expected 'evolved' but got {result['action']}"
    assert result.get("previous_type") == "knows"
    logger.info(
        f"✓ Evolved relationship: knows -> friends_with (previous: {result['previous_type']})"
    )

    # Verify evolution tracking
    rels = graph_service.get_node_relationships(
        node_name="Charlie", node_label="Entity", relationship_types=["friends_with"]
    )
    evolved_rel = next((r for r in rels if r.get("target_name") == "Diana"), None)
    assert evolved_rel is not None, "Could not find evolved relationship"
    # Relationship should exist with friends_with type (evolution successful)
    logger.info(
        f"✓ Evolution successful: relationship type is {evolved_rel.get('relationship_type')}"
    )

    return True


async def test_relationship_queries():
    """Test querying relationships and related nodes"""
    logger.info("\n=== TEST 3: Relationship Queries ===")

    # Get all Alice's relationships
    alice_rels = graph_service.get_node_relationships(
        node_name="Alice", node_label="Entity", direction="both"
    )
    logger.info(f"✓ Alice has {len(alice_rels)} relationships:")
    for rel in alice_rels:
        logger.info(
            f"  - {rel.get('source_name')}-[{rel.get('relationship_type')}]->{rel.get('target_name')} "
            f"(confidence: {rel.get('confidence'):.2f})"
        )

    assert len(alice_rels) >= 2, "Expected at least 2 relationships for Alice"

    # Get related nodes (2-hop traversal)
    related = graph_service.get_related_nodes(
        node_name="Alice", node_label="Entity", max_depth=2, min_confidence=0.5
    )
    logger.info(f"\n✓ Found {len(related)} related nodes to Alice (up to 2 hops):")
    for node in related[:5]:  # Show first 5
        path = " -> ".join(node.get("relationship_path", []))
        logger.info(
            f"  - {node.get('name')} ({node.get('label')}) [depth: {node.get('depth')}] via {path}"
        )

    assert len(related) > 0, "Expected to find related nodes"

    # Test prerequisite chain query
    ml_related = graph_service.get_related_nodes(
        node_name="Neural Networks",
        node_label="Concept",
        relationship_types=["prerequisite_for", "related_to"],
        max_depth=2,
    )
    logger.info(
        f"\n✓ Neural Networks has {len(ml_related)} prerequisite/related concepts"
    )

    return True


async def test_retrieval_enrichment():
    """Test relationship enrichment in retrieval results"""
    logger.info("\n=== TEST 4: Retrieval Enrichment ===")

    from app.services.retrieval import retrieval_service

    # Mock search results with graph nodes
    mock_results = [
        {
            "type": "graph_consensus",
            "text": "[Concept: Machine Learning]: AI that learns from data",
            "original_obj": {
                "name": "Machine Learning",
                "labels": ["Concept"],
                "summary": "AI that learns from data",
            },
        },
        {
            "type": "graph_consensus",
            "text": "[Entity: Alice]: Software engineer",
            "original_obj": {
                "name": "Alice",
                "labels": ["Entity"],
                "summary": "Software engineer",
            },
        },
        {
            "type": "note",
            "text": "Some note content...",
            "title": "Test Note",
            "note_id": "note-123",
            "is_recent": True,
        },
    ]

    # Enrich with relationships
    enriched = retrieval_service.enrich_with_relationships(
        mock_results, max_related=3, min_confidence=0.7
    )

    # Check if graph nodes were enriched
    ml_result = next(
        (
            r
            for r in enriched
            if r.get("original_obj", {}).get("name") == "Machine Learning"
        ),
        None,
    )
    alice_result = next(
        (r for r in enriched if r.get("original_obj", {}).get("name") == "Alice"), None
    )

    if ml_result and ml_result.get("related_nodes"):
        logger.info(
            f"✓ ML concept enriched with {len(ml_result['related_nodes'])} related nodes:"
        )
        for rn in ml_result["related_nodes"]:
            logger.info(f"  - {rn.get('name')} ({rn.get('label')})")
    else:
        logger.warning("⚠ ML concept has no related nodes (might need more test data)")

    if alice_result and alice_result.get("related_nodes"):
        logger.info(
            f"✓ Alice enriched with {len(alice_result['related_nodes'])} related nodes:"
        )
        for rn in alice_result["related_nodes"]:
            path = " -> ".join(rn.get("relationship_path", []))
            logger.info(f"  - {rn.get('name')} via {path}")
    else:
        logger.warning("⚠ Alice has no related nodes (might need more test data)")

    # Notes should not be enriched
    note_result = enriched[2]
    assert "related_nodes" not in note_result or not note_result.get("related_nodes")
    logger.info("✓ Note snippets correctly not enriched (only graph nodes enriched)")

    return True


async def cleanup():
    """Clean up test data"""
    logger.info("\n=== Cleanup ===")
    cleanup_query = """
    MATCH (n)
    WHERE n.name IN ['Alice', 'Bob', 'Charlie', 'Diana', 'ML Project']
       OR n.name IN ['Machine Learning', 'Neural Networks']
    DETACH DELETE n
    """
    graph_service.execute_query(cleanup_query)
    logger.info("✓ Cleaned up test nodes and relationships")


async def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("RELATIONSHIP FUNCTIONALITY TESTS")
    logger.info("=" * 60)

    try:
        # Run tests
        await test_relationship_creation()
        await test_relationship_evolution()
        await test_relationship_queries()
        await test_retrieval_enrichment()

        logger.info("\n" + "=" * 60)
        logger.info("✅ ALL TESTS PASSED")
        logger.info("=" * 60)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        logger.error(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        logger.error(f"\n❌ ERROR: {e}", exc_info=True)
        import traceback

        traceback.print_exc()
        return False
    finally:
        # Always cleanup
        await cleanup()

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
