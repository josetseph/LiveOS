"""
Quick test of the new iterative information-discovery retrieval.
Tests the Shirley Temple question that previously failed.
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(__file__))

from app.workflows.chat import chat_workflow


async def test_information_discovery():
    """Test multi-step question that requires iterative retrieval"""

    test_questions = [
        "What government position was held by the woman who portrayed Corliss Archer in the film Kiss and Tell?",
        "Were Scott Derrickson and Ed Wood of the same nationality?",
        'The director of the romantic comedy "Big Stone Gap" is based in what New York city?',
    ]

    print("=" * 80)
    print("INFORMATION-DISCOVERY RETRIEVAL TEST")
    print("=" * 80)

    for i, question in enumerate(test_questions, 1):
        print(f"\n\n{'='*80}")
        print(f"TEST {i}: {question}")
        print(f"{'='*80}\n")

        try:
            result = await chat_workflow.chat(question)

            print(f"INFORMATION NEEDS IDENTIFIED:")
            for j, need in enumerate(result.get("information_needs", []), 1):
                print(f"  {j}. {need}")

            print(f"\nDISCOVERED ENTITIES:")
            discovered = result.get("discovered_entities", {})
            if discovered:
                for key, value in discovered.items():
                    print(f"  {key} = {value}")
            else:
                print("  (none)")

            print(f"\nFINAL ANSWER:")
            print(result["answer"])

        except Exception as e:
            print(f"ERROR: {e}")
            import traceback

            traceback.print_exc()

    print(f"\n\n{'='*80}")
    print("TEST COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(test_information_discovery())
