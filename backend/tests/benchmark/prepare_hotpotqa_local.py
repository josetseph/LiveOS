"""
Prepare HotpotQA benchmark data from local LongBench dataset.

Uses the local HotpotQA data from testing_data/longbeach/data-2/hotpotqa.jsonl
No downloading required.

Usage:
    python prepare_hotpotqa_local.py [--samples N] [--seed S]
"""

import json
import os
import random
import argparse
import re
from pathlib import Path


def parse_passages_from_context(context: str) -> list[dict]:
    """Parse individual passages from the concatenated context string."""
    passages = []

    # Split by "Passage N:" pattern
    parts = re.split(r"Passage \d+:\n", context)

    for i, part in enumerate(parts):
        if not part.strip():
            continue

        lines = part.strip().split("\n")
        if not lines:
            continue

        # First line is typically the title
        title = lines[0].strip()
        content = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if title or content:
            passages.append({"title": title, "content": content})

    return passages


def create_notes_from_hotpotqa(
    input_path: str, output_dir: str, num_samples: int = None, seed: int = 42
) -> list[dict]:
    """
    Convert HotpotQA data to notes and test cases.

    Args:
        input_path: Path to local hotpotqa.jsonl file
        output_dir: Directory to save notes and test cases
        num_samples: Number of samples to use (None = all)
        seed: Random seed for sampling

    Returns:
        List of test cases with question, answer, and context_ids
    """
    random.seed(seed)

    # Read local JSONL file
    print(f"Loading HotpotQA from {input_path}...")
    examples = []
    with open(input_path, "r") as f:
        for line in f:
            if line.strip():
                examples.append(json.loads(line))

    print(f"Loaded {len(examples)} examples")

    # Sample if requested
    if num_samples and num_samples < len(examples):
        examples = random.sample(examples, num_samples)
        print(f"Sampled {num_samples} examples")

    # Create output directories
    notes_dir = os.path.join(output_dir, "hotpotqa_notes")
    os.makedirs(notes_dir, exist_ok=True)

    test_cases = []
    note_counter = 0

    for idx, example in enumerate(examples):
        question = example.get("input", "")
        answers = example.get("answers", [])
        context = example.get("context", "")

        # Parse passages from context
        passages = parse_passages_from_context(context)

        if not passages or not question or not answers:
            continue

        context_ids = []

        # Create a note for each passage
        for passage in passages:
            title = passage["title"]
            content = passage["content"]

            # Skip empty passages
            if not content.strip():
                continue

            note_id = f"hotpotqa_{idx}_{note_counter}"
            note_filename = f"{note_id}.md"

            # Create markdown note
            note_content = f"# {title}\n\n{content}"

            with open(os.path.join(notes_dir, note_filename), "w") as f:
                f.write(note_content)

            context_ids.append(note_id)
            note_counter += 1

        # Create test case
        test_case = {
            "id": f"hotpotqa_{idx}",
            "question": question,
            "answer": answers[0] if isinstance(answers, list) else answers,
            "context_ids": context_ids,
            "type": "multi-hop",  # HotpotQA is known for multi-hop reasoning
            "num_hops": 2,  # HotpotQA typically requires 2-hop reasoning
        }
        test_cases.append(test_case)

    # Save test cases
    test_cases_path = os.path.join(output_dir, "hotpotqa_test_cases.json")
    with open(test_cases_path, "w") as f:
        json.dump(test_cases, f, indent=2)

    print(f"\nCreated {note_counter} notes from {len(test_cases)} test cases")
    print(f"Notes saved to: {notes_dir}")
    print(f"Test cases saved to: {test_cases_path}")

    # Stats
    avg_passages = note_counter / len(test_cases) if test_cases else 0
    print(f"\nStatistics:")
    print(f"  - Average passages per question: {avg_passages:.1f}")

    return test_cases


def main():
    parser = argparse.ArgumentParser(
        description="Prepare HotpotQA benchmark data from local files"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=30,
        help="Number of samples to prepare (default: 30)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for sampling (default: 42)"
    )
    args = parser.parse_args()

    # Paths relative to this script
    script_dir = Path(__file__).parent
    backend_dir = script_dir.parent.parent

    # Local HotpotQA file path
    input_path = (
        backend_dir / "testing_data" / "longbeach" / "data-2" / "hotpotqa.jsonl"
    )

    if not input_path.exists():
        print(f"Error: Local HotpotQA file not found at {input_path}")
        print(
            "Please ensure the testing_data/longbeach/data-2/hotpotqa.jsonl file exists."
        )
        return

    output_dir = script_dir

    test_cases = create_notes_from_hotpotqa(
        str(input_path), str(output_dir), num_samples=args.samples, seed=args.seed
    )

    print(f"\n✓ HotpotQA benchmark data prepared successfully!")
    print(f"\nNext steps:")
    print(
        f"1. Ingest notes: python ../batch-note-processing/batch_ingest.py tests/benchmark/hotpotqa_notes"
    )
    print(
        f"2. Run evaluation: python tests/benchmark/evaluate_ragas.py --dataset hotpotqa --use-ragas"
    )


if __name__ == "__main__":
    main()
