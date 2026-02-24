"""
Test improved alias detection with:
1. Semantic similarity pre-filter (embedding-based)
2. Refined Chain-of-Thought prompt for smaller models
"""

import asyncio
import sys

sys.path.append(".")

from app.services.alias_detector import AliasDetectorService
from app.services.graph import graph_service
import numpy as np


async def test_improvements():
    detector = AliasDetectorService()

    # Test cases that failed before
    test_cases = [
        ("new brooklyn theatre", "new china news agency (ncna)"),
        ("new brooklyn theatre", "new orleans pelicans"),
        ("new brooklyn theatre", "new teen titans shorts"),
        ("new brooklyn theatre", "new world computing"),
    ]

    print("=" * 80)
    print("IMPROVED ALIAS DETECTION TEST")
    print("=" * 80)
    print("\nStage 1: Semantic Similarity Shield (embedding-based)")
    print("Stage 2: LLM with Chain-of-Thought prompt")
    print("=" * 80)

    for entity1, entity2 in test_cases:
        print(f"\n{'='*80}")
        print(f"TEST: '{entity1}' ↔ '{entity2}'")
        print("=" * 80)

        # Get entity data
        query = """
        MATCH (e:Entity {name: $name})
        RETURN e.summary as summary, e.type as entity_type, e.embedding as embedding
        """

        result1 = graph_service.execute_query(query, {"name": entity1})
        result2 = graph_service.execute_query(query, {"name": entity2})

        if not result1 or not result2:
            print(f"⚠️  Could not find entities in graph")
            continue

        context1 = result1[0].get("summary", "")
        context2 = result2[0].get("summary", "")
        type1 = result1[0].get("entity_type", "Unknown")
        type2 = result2[0].get("entity_type", "Unknown")
        embedding1 = result1[0].get("embedding")
        embedding2 = result2[0].get("embedding")

        print(f"\nEntity 1: {entity1} (type: {type1})")
        print(f"Context: {context1[:150]}...")
        print(f"\nEntity 2: {entity2} (type: {type2})")
        print(f"Context: {context2[:150]}...")

        # Test semantic shield
        if embedding1 and embedding2:
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)
            vec1_norm = vec1 / (np.linalg.norm(vec1) + 1e-9)
            vec2_norm = vec2 / (np.linalg.norm(vec2) + 1e-9)
            similarity = float(np.dot(vec1_norm, vec2_norm))

            print(f"\n📊 Semantic Similarity: {similarity:.3f}")

            if similarity < 0.65:
                print("🛡️  SEMANTIC SHIELD: BLOCKED (< 0.65 threshold)")
                print(
                    "✅ CORRECT - Would not reach LLM, saving time & preventing garbage"
                )
                continue
            else:
                print(
                    f"⚠️  Shield passed ({similarity:.3f} >= 0.65) - Proceeding to LLM..."
                )

        # Test LLM with new prompt
        relationship_type, reason = await detector.compare_entities_with_llm(
            entity1_name=entity1,
            entity1_context=context1,
            entity2_name=entity2,
            entity2_context=context2,
            semantic_similarity=similarity,
        )

        print(f"\n🤖 LLM Decision: {relationship_type or 'NONE'}")
        print(f"📝 Reasoning: {reason}")

        # Evaluate
        if relationship_type is None or relationship_type == "NONE":
            print("✅ CORRECT - Unrelated entities")
        else:
            print(f"❌ INCORRECT - Should be NONE, not {relationship_type}")

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    print("\n💡 Improvements:")
    print("1. ✅ Semantic Shield blocks garbage BEFORE LLM (saves time + quality)")
    print("2. ✅ CoT prompt forces 'list shared facts' before deciding")
    print("3. ✅ Explicit negative examples prevent name-matching hallucinations")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_improvements())
