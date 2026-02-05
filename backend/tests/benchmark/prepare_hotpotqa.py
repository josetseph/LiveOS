#!/usr/bin/env python3
"""
Prepare HotpotQA dataset for LiveOS ingestion and evaluation.

Downloads and converts HotpotQA into:
1. Individual note files for ingestion
2. A test manifest with questions and ground truth answers

Usage:
    python tests/benchmark/prepare_hotpotqa.py --limit 100
    python tests/benchmark/prepare_hotpotqa.py --split dev --limit 50
"""

import argparse
import json
import os
import requests
from pathlib import Path
from tqdm import tqdm

# HotpotQA download URLs
HOTPOTQA_URLS = {
    "dev": "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
    "train": "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_train_v1.1.json",
}


def download_hotpotqa(split: str, cache_dir: Path) -> Path:
    """Download HotpotQA dataset if not already cached."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"hotpot_{split}.json"

    if cache_path.exists():
        print(f"✓ Using cached {split} split: {cache_path}")
        return cache_path

    url = HOTPOTQA_URLS[split]
    print(f"⬇️  Downloading HotpotQA {split} split...")
    print(f"   URL: {url}")

    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))
    with open(cache_path, "wb") as f:
        with tqdm(total=total_size, unit="B", unit_scale=True) as pbar:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                pbar.update(len(chunk))

    print(f"✓ Downloaded to {cache_path}")
    return cache_path


def prepare_notes(data: list, output_dir: Path, limit: int = None) -> list:
    """
    Convert HotpotQA entries into individual note files.

    Returns list of test cases with questions and expected answers.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing notes
    for f in output_dir.glob("*.md"):
        f.unlink()

    test_cases = []
    created_notes = set()

    entries = data[:limit] if limit else data

    print(f"📝 Preparing {len(entries)} HotpotQA entries...")

    for entry in tqdm(entries):
        question = entry["question"]
        answer = entry["answer"]
        supporting_facts = entry.get("supporting_facts", [])
        question_type = entry.get("type", "unknown")  # bridge or comparison
        level = entry.get("level", "unknown")  # easy, medium, hard

        # Track which paragraphs are "supporting facts" (ground truth for retrieval)
        supporting_titles = {sf[0] for sf in supporting_facts}

        # Create notes from context paragraphs
        note_files = []
        for title, sentences in entry["context"]:
            # Sanitize filename
            safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
            safe_title = safe_title[:80]  # Limit length
            filename = f"{safe_title}.md"
            filepath = output_dir / filename

            # Combine sentences into note content
            content = " ".join(sentences)

            # Add title as header for better context
            note_content = f"# {title}\n\n{content}\n"

            # Only create if we haven't already (titles can repeat across questions)
            if filename not in created_notes:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(note_content)
                created_notes.add(filename)

            note_files.append(
                {
                    "filename": filename,
                    "title": title,
                    "is_supporting": title in supporting_titles,
                }
            )

        # Create test case
        test_cases.append(
            {
                "id": entry.get("_id", str(len(test_cases))),
                "question": question,
                "answer": answer,
                "type": question_type,
                "level": level,
                "supporting_facts": list(supporting_titles),
                "all_notes": [n["filename"] for n in note_files],
                "required_notes": [
                    n["filename"] for n in note_files if n["is_supporting"]
                ],
            }
        )

    print(f"✓ Created {len(created_notes)} unique notes")
    print(f"✓ Prepared {len(test_cases)} test cases")

    return test_cases


def main():
    parser = argparse.ArgumentParser(description="Prepare HotpotQA for LiveOS testing")
    parser.add_argument(
        "--split",
        choices=["dev", "train"],
        default="dev",
        help="Dataset split to use (dev is smaller, ~7k examples)",
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Limit number of examples to process"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="tests/benchmark/hotpotqa_notes",
        help="Output directory for notes",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="tests/benchmark/.cache",
        help="Cache directory for downloaded files",
    )

    args = parser.parse_args()

    # Setup paths
    base_dir = Path(__file__).parent.parent.parent
    output_dir = base_dir / args.output_dir
    cache_dir = base_dir / args.cache_dir
    manifest_path = output_dir.parent / "hotpotqa_manifest.json"

    # Download dataset
    data_path = download_hotpotqa(args.split, cache_dir)

    # Load data
    print(f"📖 Loading {args.split} data...")
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"   Found {len(data)} total examples")

    # Prepare notes and test cases
    test_cases = prepare_notes(data, output_dir, limit=args.limit)

    # Save manifest
    manifest = {
        "dataset": "HotpotQA",
        "split": args.split,
        "num_examples": len(test_cases),
        "notes_dir": str(output_dir.relative_to(base_dir)),
        "test_cases": test_cases,
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n✅ HotpotQA preparation complete!")
    print(f"   Notes directory: {output_dir}")
    print(f"   Test manifest: {manifest_path}")
    print(f"\n📋 Next steps:")
    print(
        f"   1. Ingest notes: python batch-note-processing/batch_ingest.py {output_dir}"
    )
    print(
        f"   2. Run evaluation: python tests/benchmark/evaluate.py --dataset hotpotqa"
    )


if __name__ == "__main__":
    main()
