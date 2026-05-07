#!/usr/bin/env python3
"""
Send a note to the LiveOS ingestion endpoint.

Usage:
    python send_note.py "Your note content here"
    python send_note.py "Your note" --date "2024-01-15"
    echo "Your note" | python send_note.py
    python send_note.py --file note.txt
"""

import argparse
import sys
import requests

# Configuration
API_URL = "http://localhost:8000/api/v1/ingest"


def send_note(content: str, created_at: str = None):
    """Send a note to the ingestion endpoint."""

    if not content.strip():
        print("❌ Error: Note content cannot be empty")
        sys.exit(1)

    payload = {"content": content.strip()}

    if created_at:
        payload["created_at"] = created_at

    try:
        print(f"📤 Sending note to {API_URL}...")
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()

        result = response.json()
        print(f"\n✅ Note ingested successfully!")
        print(f"   Note ID: {result['note_id']}")
        print(f"   Status: {result['status']}")
        print(f"   Created: {result['created_at']}")
        print(f"\n📝 Content preview:")
        print(f"   {content}{'...' if len(content) > 100 else ''}")

    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Could not connect to {API_URL}")
        print(
            "   Make sure the backend server is running (uvicorn app.main:app --reload)"
        )
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        print(f"   Response: {response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Send a note to LiveOS ingestion endpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python send_note.py "Today I learned about Python decorators"
  python send_note.py "Meeting notes" --date "2024-01-15 14:30"
  python send_note.py --file my-note.txt
  echo "Quick note" | python send_note.py
        """,
    )

    parser.add_argument(
        "content", nargs="?", help="Note content (or use --file or stdin)"
    )
    parser.add_argument("-f", "--file", help="Read note content from a file")
    parser.add_argument(
        "-d", "--date", help="Custom creation date (ISO format or natural language)"
    )

    args = parser.parse_args()

    # Get content from argument, file, or stdin
    content = None

    if args.file:
        try:
            with open(args.file, "r") as f:
                content = f.read()
        except FileNotFoundError:
            print(f"❌ Error: File not found: {args.file}")
            sys.exit(1)
    elif args.content:
        content = args.content
    elif not sys.stdin.isatty():
        # Read from stdin
        content = sys.stdin.read()
    else:
        print("❌ Error: No content provided")
        print('   Use: python send_note.py "Your note"')
        print("   Or:  python send_note.py --file note.txt")
        print('   Or:  echo "Note" | python send_note.py')
        sys.exit(1)

    send_note(content, args.date)


if __name__ == "__main__":
    main()
