#!/usr/bin/env python3
"""
Prepare MuSiQue dataset for LiveOS ingestion and evaluation.

MuSiQue (Multi-hop Questions via Composition) tests 2-4 hop reasoning.
Uses the LongBench version which has longer contexts.

Usage:
    python tests/benchmark/prepare_musique.py --limit 50
"""

import argparse
import json
import os
import re
from pathlib import Path
from tqdm import tqdm

try:
    from datasets import load_dataset
except ImportError:
    print("❌ Please install datasets: pip install datasets")
    exit(1)


def split_into_paragraphs(context: str) -> list[str]:
    """
    Split long context into individual paragraphs.
    MuSiQue contexts often have multiple articles concatenated.
    """
    # Split on double newlines or article-like boundaries
    paragraphs = re.split(r"\n\n+|\n(?=[A-Z][a-z]+ [A-Z])", context)

    # Filter out empty or too-short paragraphs
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 50]

    return paragraphs


def extract_title_from_paragraph(paragraph: str, index: int) -> str:
    """Extract or generate a title for a paragraph."""
    # Try to find a title-like first line
    lines = paragraph.split("\n")
    first_line = lines[0].strip()

    # If first line looks like a title (short, no period)
    if len(first_line) < 100 and not first_line.endswith("."):
        return first_line

    # Otherwise, use first few words
    words = first_line.split()[:5]
    return " ".join(words) + f" (Part {index})"


def prepare_notes(dataset, output_dir: Path, limit: int = None) -> list:
    """
    Convert MuSiQue entries into individual note files.

    Returns list of test cases with questions and expected answers.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing notes
    for f in output_dir.glob("*.md"):
        f.unlink()

    test_cases = []
    created_notes = {}  # filename -> content hash to avoid duplicates

    entries = list(dataset.select(range(min(limit or len(dataset), len(dataset)))))

    print(f"📝 Preparing {len(entries)} MuSiQue entries...")

    for i, entry in enumerate(tqdm(entries)):
        question = entry["input"]
        context = entry["context"]
        answer = (
            entry["answers"][0] if entry.get("answers") else entry.get("answer", "")
        )

        # Split context into paragraphs
        paragraphs = split_into_paragraphs(context)

        # Create notes from paragraphs
        note_files = []
        for j, para in enumerate(paragraphs):
            title = extract_title_from_paragraph(para, j)

            # Sanitize filename
            safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
            safe_title = safe_title[:60]
            filename = f"q{i:03d}_p{j:02d}_{safe_title}.md"
            filepath = output_dir / filename

            # Create note content
            note_content = f"# {title}\n\n{para}\n"

            # Check for duplicates by content hash
            content_hash = hash(para)
            if content_hash not in created_notes.values():
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(note_content)
                created_notes[filename] = content_hash
                note_files.append(filename)

        # Determine hop count from question structure (heuristic)
        # MuSiQue questions often have nested structure
        hop_count = min(4, max(2, len(paragraphs) // 2))

        # Create test case
        test_cases.append(
            {
                "id": f"musique_{i}",
                "question": question,
                "answer": answer,
                "hop_count": hop_count,
                "context_length": len(context),
                "paragraph_count": len(paragraphs),
                "notes": note_files,
            }
        )

    print(f"✓ Created {len(created_notes)} unique notes")
    print(f"✓ Prepared {len(test_cases)} test cases")

    return test_cases


def main():
    parser = argparse.ArgumentParser(description="Prepare MuSiQue for LiveOS testing")
    parser.add_argument(
        "--limit", type=int, default=50, help="Limit number of examples to process"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="tests/benchmark/musique_notes",
        help="Output directory for notes",
    )

    args = parser.parse_args()

    # Setup paths
    base_dir = Path(__file__).parent.parent.parent
    output_dir = base_dir / args.output_dir
    manifest_path = output_dir.parent / "musique_manifest.json"

    # Load dataset from HuggingFace
    print("⬇️  Loading MuSiQue from LongBench...")
    try:
        dataset = load_dataset("THUDM/LongBench", "musique", split="test")
        print(f"   Found {len(dataset)} examples")
    except Exception as e:
        print(f"❌ Failed to load dataset: {e}")
        print("   Try: pip install datasets")
        return

    # Prepare notes and test cases
    test_cases = prepare_notes(dataset, output_dir, limit=args.limit)

    # Calculate statistics
    avg_hops = sum(tc["hop_count"] for tc in test_cases) / len(test_cases)
    avg_paragraphs = sum(tc["paragraph_count"] for tc in test_cases) / len(test_cases)

    # Save manifest
    manifest = {
        "dataset": "MuSiQue (LongBench)",
        "num_examples": len(test_cases),
        "avg_hop_count": round(avg_hops, 1),
        "avg_paragraphs": round(avg_paragraphs, 1),
        "notes_dir": str(output_dir.relative_to(base_dir)),
        "test_cases": test_cases,
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n✅ MuSiQue preparation complete!")
    print(f"   Notes directory: {output_dir}")
    print(f"   Test manifest: {manifest_path}")
    print(f"   Average hop count: {avg_hops:.1f}")
    print(f"\n📋 Next steps:")
    print(
        f"   1. Ingest notes: python batch-note-processing/batch_ingest.py {output_dir}"
    )
    print(f"   2. Run evaluation: python tests/benchmark/evaluate.py --dataset musique")


if __name__ == "__main__":
    main()
