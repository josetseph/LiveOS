#!/usr/bin/env python3
"""
Batch ingest all notes from the notes/ directory with guaranteed sequential processing.

Usage:
    python batch_ingest.py
    python batch_ingest.py --resume  # Resume from last successful note
    python batch_ingest.py --dry-run  # Preview without sending
"""

import argparse
import time
import requests
import json
import re
from pathlib import Path
from datetime import datetime, timezone

# Configuration
API_URL = "http://localhost:8000/api/v1/ingest"
NOTES_DIR = Path(__file__).parent / "notes"
LOG_FILE = Path(__file__).parent.parent / "backend" / "logs" / "ingestion.log"
PROGRESS_FILE = Path(__file__).parent / ".batch_progress.json"


def clean_obsidian_content(content: str) -> str:
    """
    Remove Obsidian-specific metadata and navigation elements.

    1. Remove YAML frontmatter (--- ... ---)
    2. Remove Previous/Next Note sections
    """
    # Remove YAML frontmatter
    # Pattern: --- at start, anything until closing ---
    content = re.sub(
        r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL | re.MULTILINE
    )

    # Remove "Previous Note" and "Next Note" sections (various formats)
    # Pattern 1: ## Previous Note \n[[link]]
    content = re.sub(
        r"^##?\s*Previous\s+Note\s*\n\[\[.*?\]\]\s*\n?",
        "",
        content,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Pattern 2: ## Next Note \n[[link]]
    content = re.sub(
        r"^##?\s*Next\s+Note\s*\n\[\[.*?\]\]\s*\n?",
        "",
        content,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Pattern 3: Previous Note: [[link]]
    content = re.sub(
        r"^Previous\s+Note:\s*\[\[.*?\]\]\s*\n?",
        "",
        content,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Pattern 4: Next Note: [[link]]
    content = re.sub(
        r"^Next\s+Note:\s*\[\[.*?\]\]\s*\n?",
        "",
        content,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Pattern 5: # Linked Notes section with both Previous and Next
    content = re.sub(
        r"^##?\s*Linked\s+Notes\s*\n(##?\s*Previous\s+Note\s*\n\[\[.*?\]\]\s*\n?)?(##?\s*Next\s+Note\s*\n\[\[.*?\]\]\s*\n?)?",
        "",
        content,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    # Clean up excessive newlines (more than 2 consecutive)
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


def send_note(
    content: str,
    created_at: str = None,
    title: str = None,
    dry_run: bool = False,
):
    """
    Send a single note to the ingestion endpoint.

    Args:
        content: Note content
        created_at: Optional creation timestamp
        title: Optional custom title (if not provided, backend generates one)
        dry_run: If True, don't actually send
    """

    if not content.strip():
        return None, "Empty content"

    payload = {"content": content.strip()}

    if created_at:
        payload["created_at"] = created_at

    if title:
        payload["title"] = title

    if dry_run:
        return {
            "note_id": "DRY-RUN",
            "status": "would_ingest",
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        }, None

    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Connection error - is the backend running?"
    except requests.exceptions.HTTPError as e:
        return None, f"HTTP {response.status_code}: {response.text}"
    except Exception as e:
        return None, str(e)


def wait_for_ingestion_success(note_id: str, initial_pos: int, timeout: int = 2000):
    """
    Tail the ingestion log file from initial_pos and wait for SUCCESS message.
    Returns True if found within timeout, False otherwise.
    """
    if not LOG_FILE.exists():
        print(f"    Log file not found: {LOG_FILE}")
        print(f"      Waiting 30s as fallback...")
        time.sleep(30)
        return True

    start_time = time.time()
    # "Marked Note as Processed" is logged immediately after the note is saved
    # to Postgres — before the spring layout — so we don't wait 30-90s extra.
    success_pattern = f"[Ingestion] Marked Note {note_id} as Processed"
    failure_pattern = f"[Ingestion] FAILURE note_id={note_id}"

    print(f"   ⏳ Waiting for ingestion to complete...", end="", flush=True)

    with open(LOG_FILE, "r") as f:
        f.seek(initial_pos)

        while True:
            if time.time() - start_time > timeout:
                print(f" timeout ({timeout}s)")
                return False

            line = f.readline()
            if line:
                if success_pattern in line:
                    print(" ✅")
                    return True
                if failure_pattern in line:
                    print(f" ❌ failed")
                    return False
            else:
                # Force Python to drop its internal read buffer so the next
                # readline() actually re-checks the OS file cache.
                f.seek(f.tell())
                time.sleep(0.1)


def extract_date_from_filename(filename: str) -> str:
    """
    Extract ISO date from filename patterns like:
    - 2024-01-15-my-note.txt
    - note-2024-01-15.md
    - 20240115_meeting.txt

    Returns ISO datetime string or None if no date found.
    """
    # Pattern 1: YYYY-MM-DD with dashes
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", filename)
    if match:
        year, month, day = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day))
            return dt.isoformat() + "Z"
        except ValueError:
            pass

    # Pattern 2: YYYYMMDD without separators
    match = re.search(r"(\d{4})(\d{2})(\d{2})", filename)
    if match:
        year, month, day = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day))
            return dt.isoformat() + "Z"
        except ValueError:
            pass

    return None


def save_progress(filename: str, note_id: str):
    """Save progress to allow resuming later."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(
            {
                "last_processed_file": filename,
                "last_note_id": note_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )


def load_progress():
    """Load saved progress."""
    if not PROGRESS_FILE.exists():
        return None
    try:
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    except:
        return None


def clear_progress():
    """Clear progress file after successful completion."""
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


def batch_ingest(
    notes_dir: Path = None,
    dry_run: bool = False,
    resume: bool = False,
    limit: int = None,
):
    """Batch ingest all notes from the specified directory in chronological order."""

    # Use provided directory or default
    target_dir = notes_dir if notes_dir else NOTES_DIR

    if not target_dir.exists():
        print(f"❌ Error: Notes directory not found: {target_dir}")
        print(f"   Creating directory...")
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"   ✅ Directory created. Please add .txt or .md files to it.")
        return

    # Find all text and markdown files
    note_files = list(target_dir.glob("*.txt")) + list(target_dir.glob("*.md"))

    if not note_files:
        print(f"📂 No notes found in {target_dir}")
        print(f"   Add .txt or .md files to the directory")
        return

    # Sort files by extracted date (chronologically - earliest first)
    def sort_key(file_path):
        date_str = extract_date_from_filename(file_path.name)
        if date_str:
            try:
                # Parse the ISO datetime and make it offset-naive for comparison
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.replace(tzinfo=None)
            except:
                pass
        # Files without dates go to end (use offset-naive max)
        return datetime.max

    note_files.sort(key=sort_key)

    # Handle resume
    start_index = 0
    if resume:
        progress = load_progress()
        if progress:
            last_file = progress.get("last_processed_file")
            print(f"📥 Resuming from last processed: {last_file}")
            # Find index of last processed file
            for i, note_file in enumerate(note_files):
                if note_file.name == last_file:
                    start_index = i + 1  # Start from next file
                    break
            if start_index == 0:
                print(
                    f"    Could not find last processed file, starting from beginning"
                )
        else:
            print(f"   ℹ️  No progress file found, starting from beginning")

    if start_index >= len(note_files):
        print(f"✅ All notes already processed!")
        clear_progress()
        return

    # Apply limit if specified
    end_index = len(note_files)
    if limit is not None:
        end_index = min(start_index + limit, len(note_files))

    print(
        f"{'🔍' if dry_run else '📦'} Processing {end_index - start_index} note(s) (sorted by date)"
    )
    print(f"{'   (DRY RUN - not actually sending)' if dry_run else ''}\n")

    results = {"success": 0, "failed": 0, "skipped": 0}

    for i in range(start_index, end_index):
        note_file = note_files[i]
        filename = note_file.name
        print(f"[{i + 1}/{len(note_files)}] Processing: {filename}")

        try:
            with open(note_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"   ❌ Failed to read file: {e}")
            results["failed"] += 1
            continue

        # Clean Obsidian metadata
        original_length = len(content)
        content = clean_obsidian_content(content)
        cleaned_length = len(content)

        if original_length != cleaned_length:
            print(
                f"   🧹 Cleaned metadata ({original_length - cleaned_length} chars removed)"
            )

        # Extract date from filename (auto-date enabled by default)
        created_at = extract_date_from_filename(filename)
        if created_at:
            print(f"   📅 Date: {created_at}")

        # Extract title from filename (remove extension)
        title = filename.rsplit(".", 1)[0] if "." in filename else filename

        # Capture log position BEFORE sending so no SUCCESS line can slip by
        initial_pos = LOG_FILE.stat().st_size if LOG_FILE.exists() else 0

        result, error = send_note(
            content, created_at=created_at, title=title, dry_run=dry_run
        )

        if error:
            print(f"   ❌ Error: {error}")
            results["failed"] += 1
            # Don't save progress on failure - allow retry
        elif result:
            note_id = result["note_id"]
            print(f"   ✅ Sent: {note_id}")
            print(
                f"      Preview: {content.strip()}{'...' if len(content) > 80 else ''}"
            )

            if not dry_run:
                # Wait for ingestion to complete before proceeding
                success = wait_for_ingestion_success(note_id, initial_pos, timeout=3600)
                if not success:
                    print("    Failed to confirm completion - stopping batch process")
                    print("   ‼️ Check logs for last processed note")
                    print("   💡 Resume with: python batch_ingest.py --resume")
                    return
                # Save progress only after confirmed success
                save_progress(filename, note_id)

            results["success"] += 1
        else:
            print(f"    Skipped: Empty content")
            results["skipped"] += 1

        print()

    # Summary
    print("=" * 60)
    print("📊 Batch Ingestion Summary")
    print("=" * 60)
    print(f"✅ Successful: {results['success']}")
    print(f"❌ Failed:     {results['failed']}")
    print(f" Skipped:    {results['skipped']}")
    print(f"📝 Total:      {len(note_files) - start_index}")

    if results["failed"] == 0 and not dry_run:
        print(f"\n🎉 All notes processed successfully!")
        clear_progress()
    elif not dry_run:
        print(f"\n💡 Resume with: python batch_ingest.py --resume")


def main():
    parser = argparse.ArgumentParser(
        description="Batch ingest all notes in chronological order with sequential processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python batch_ingest.py                           # Process notes/ directory
  python batch_ingest.py /path/to/notes           # Process custom directory
  python batch_ingest.py --dry-run                # Preview without sending
  python batch_ingest.py --resume                 # Resume from last successful note
  python batch_ingest.py --resume --limit 5       # Process next 5 notes only
  
Features:
  - Automatic date extraction from filenames (YYYY-MM-DD)
  - Chronological processing (earliest first)
  - Waits for each note to fully ingest before sending next
  - Progress tracking with resume capability
  - 10-minute timeout per note
  - Obsidian metadata cleaning (YAML frontmatter, navigation links)
        """,
    )

    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=None,
        help="Directory containing notes to ingest (default: notes/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without actually sending notes"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last successfully processed note",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of notes to process",
    )

    args = parser.parse_args()

    batch_ingest(
        notes_dir=args.directory,
        dry_run=args.dry_run,
        resume=args.resume,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
