#!/usr/bin/env python3
"""
Test the improved alias detection prompt with known false positive cases.
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.alias_detector import alias_detector


async def test_cases():
    """Test the alias detector with known challenging cases."""
    
    test_cases = [
        # Should be YES (true aliases)
        {
            "name": "True Alias: Giuseppe Verdi → Verdi",
            "entity1": "Giuseppe Verdi",
            "context1": "Italian opera composer, born 1813, composed La Traviata and Aida",
            "entity2": "Verdi",
            "context2": "Composer of operas like Rigoletto, born in Italy in early 1800s",
            "expected": "YES",
        },
        {
            "name": "True Alias: ExxonMobil → Exxon",
            "entity1": "ExxonMobil",
            "context1": "Oil and gas company formed from 1999 merger of Exxon and Mobil",
            "entity2": "Exxon",
            "context2": "Brand name used by ExxonMobil for its downstream operations and retail",
            "expected": "YES",
        },
        # Should be NO (generic vs specific)
        {
            "name": "False Positive: home government → Japanese government",
            "entity1": "home government",
            "context1": "The government of a country to which a diplomatic mission is accountable",
            "entity2": "Japanese government",
            "context2": "The government of Japan, responsible for domestic and foreign policy",
            "expected": "NO",
        },
        {
            "name": "False Positive: home government → federal government",
            "entity1": "home government",
            "context1": "The government of a country to which a diplomatic mission belongs",
            "entity2": "federal government",
            "context2": "A government system with power divided between national and regional authorities",
            "expected": "NO",
        },
        # Should be NO (related but different)
        {
            "name": "False Positive: vihuela → viol",
            "entity1": "vihuela",
            "context1": "A plucked stringed instrument from 15th-16th century Spain, with gut strings and frets",
            "entity2": "viol",
            "context2": "A bowed stringed instrument from Renaissance period, with gut strings, used in chamber music",
            "expected": "NO",
        },
    ]
    
    print("\n" + "=" * 80)
    print("TESTING IMPROVED ALIAS DETECTION PROMPT")
    print("=" * 80 + "\n")
    
    results = {"correct": 0, "incorrect": 0, "total": 0}
    
    for i, test in enumerate(test_cases, 1):
        print(f"{i}. {test['name']}")
        print(f"   Entity 1: {test['entity1']}")
        print(f"   Entity 2: {test['entity2']}")
        print(f"   Expected: {test['expected']}")
        
        is_same, reason, confidence = await alias_detector.compare_entities_with_llm(
            test["entity1"], test["context1"],
            test["entity2"], test["context2"]
        )
        
        actual = "YES" if is_same else "NO"
        is_correct = actual == test["expected"]
        results["total"] += 1
        
        if is_correct:
            results["correct"] += 1
            status = "✅ CORRECT"
        else:
            results["incorrect"] += 1
            status = "❌ WRONG"
        
        print(f"   Actual: {actual} (confidence: {confidence:.2%}) {status}")
        print(f"   Reason: {reason}")
        print()
        
        # Small delay to avoid rate limits
        await asyncio.sleep(0.5)
    
    # Summary
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Correct: {results['correct']}/{results['total']} ({results['correct']/results['total']*100:.1f}%)")
    print(f"Incorrect: {results['incorrect']}/{results['total']}")
    print()
    
    if results["correct"] == results["total"]:
        print("✅ All test cases passed! Prompt improvements are working.")
    else:
        print("⚠️ Some test cases failed. Prompt may need further refinement.")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(test_cases())
