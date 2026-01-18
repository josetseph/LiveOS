#!/usr/bin/env python3
"""
Batch ingest all notes from the notes/ directory.

Usage:
    python batch_ingest.py
    python batch_ingest.py --delay 2  # Add 2 second delay between notes
    python batch_ingest.py --dry-run  # Preview without sending
"""

import argparse
import sys
import os
import time
import requests
from pathlib import Path
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000/api/v1/ingest"
NOTES_DIR = Path(__file__).parent / "notes"


def send_note(
    content: str, filename: str, created_at: str = None, dry_run: bool = False
):
    """Send a single note to the ingestion endpoint."""

    if not content.strip():
        return None, "Empty content"

    payload = {"content": content.strip()}

    if created_at:
        payload["created_at"] = created_at

    if dry_run:
        return {
            "note_id": "DRY-RUN",
            "status": "would_ingest",
            "created_at": created_at or datetime.utcnow().isoformat(),
        }, None

    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Connection error - is the backend running?"
    except requests.exceptions.HTTPError as e:
        return None, f"HTTP {response.status_code}: {response.text[:100]}"
    except Exception as e:
        return None, str(e)


def extract_date_from_filename(filename: str):
    """
    Try to extract date from filename patterns like:
    - 2024-01-15-note.txt
    - note-2024-01-15.md
    - 20240115_note.txt
    """
    import re

    # Pattern: YYYY-MM-DD
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

    # Pattern: YYYYMMDD
    match = re.search(r"(\d{4})(\d{2})(\d{2})", filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

    return None


def batch_ingest(delay: float = 0, dry_run: bool = False, auto_date: bool = False):
    """Batch ingest all notes from the notes directory."""

    if not NOTES_DIR.exists():
        print(f"❌ Error: Notes directory not found: {NOTES_DIR}")
        print(f"   Creating directory...")
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"   ✅ Directory created. Please add .txt or .md files to it.")
        return

    # Find all text and markdown files
    note_files = list(NOTES_DIR.glob("*.txt")) + list(NOTES_DIR.glob("*.md"))

    if not note_files:
        print(f"📂 No notes found in {NOTES_DIR}")
        print(f"   Add .txt or .md files to the notes/ directory")
        return

    print(f"{'🔍' if dry_run else '📦'} Found {len(note_files)} note(s) in {NOTES_DIR}")
    print(f"{'   (DRY RUN - not actually sending)' if dry_run else ''}\n")

    results = {"success": 0, "failed": 0, "skipped": 0}

    for i, note_file in enumerate(note_files, 1):
        filename = note_file.name
        print(f"[{i}/{len(note_files)}] Processing: {filename}")

        try:
            with open(note_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"   ❌ Failed to read file: {e}")
            results["failed"] += 1
            continue

        # Try to extract date from filename if auto-date is enabled
        created_at = None
        if auto_date:
            created_at = extract_date_from_filename(filename)
            if created_at:
                print(f"   📅 Extracted date: {created_at}")

        result, error = send_note(content, filename, created_at, dry_run)

        if error:
            print(f"   ❌ Error: {error}")
            results["failed"] += 1
        elif result:
            print(f"   ✅ Ingested: {result['note_id']}")
            print(
                f"      Preview: {content[:80].strip()}{'...' if len(content) > 80 else ''}"
            )
            results["success"] += 1
        else:
            print(f"   ⚠️  Skipped: Empty content")
            results["skipped"] += 1

        # Add delay between notes to avoid overwhelming the system
        if delay > 0 and i < len(note_files):
            print(f"   ⏳ Waiting {delay}s...")
            time.sleep(delay)

        print()

    # Summary
    print("=" * 60)
    print("📊 Batch Ingestion Summary")
    print("=" * 60)
    print(f"✅ Successful: {results['success']}")
    print(f"❌ Failed:     {results['failed']}")
    print(f"⚠️  Skipped:    {results['skipped']}")
    print(f"📝 Total:      {len(note_files)}")

    if dry_run:
        print("\n💡 This was a dry run. Use without --dry-run to actually ingest.")


def main():
    parser = argparse.ArgumentParser(
        description="Batch ingest all notes from notes/ directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python batch_ingest.py
  python batch_ingest.py --delay 1
  python batch_ingest.py --dry-run
  python batch_ingest.py --auto-date --delay 0.5
  
File naming for auto-date extraction:
  2024-01-15-my-note.txt       → Uses 2024-01-15
  note-2024-01-15.md           → Uses 2024-01-15
  20240115_meeting.txt         → Uses 2024-01-15
  random-note.txt              → Uses current time
        """,
    )

    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=0,
        help="Delay in seconds between each note (default: 0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without actually sending notes"
    )
    parser.add_argument(
        "--auto-date",
        action="store_true",
        help="Automatically extract dates from filenames (YYYY-MM-DD pattern)",
    )

    args = parser.parse_args()

    batch_ingest(delay=args.delay, dry_run=args.dry_run, auto_date=args.auto_date)


if __name__ == "__main__":
    main()
