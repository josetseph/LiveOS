"""
Test Whisper models for audio transcription
"""

import asyncio
import sys
import time
from pathlib import Path
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.services.multimedia import MultimediaService


async def test_whisper_on_audio():
    """Test current Whisper model on an audio file"""
    print(f"🔍 Testing {settings.MODEL_WHISPER_LOCAL} on audio\n")

    # Initialize multimedia service
    multimedia = MultimediaService()

    # Look for common audio files in CWD, script dir, or project root
    search_paths = [
        Path("."),
        Path(__file__).parent,
        Path(__file__).parent.parent.parent,
    ]

    audio_files = []
    for path in search_paths:
        audio_files.extend(
            list(path.glob("*.mp3"))
            + list(path.glob("*.wav"))
            + list(path.glob("*.m4a"))
        )
        if audio_files:
            break

    if not audio_files:
        print(f"❌ Error: No audio files (.mp3, .wav, .m4a) found in search paths")
        print("Please place a test audio file in the project root or backend/tests/")
        return

    audio_path = audio_files[0]
    print(f"🎵 Processing: {audio_path.absolute()}\n")

    try:
        start_time = time.time()
        result = multimedia.transcribe_audio(str(audio_path))
        duration = time.time() - start_time

        print("=" * 80)
        print("TRANSCRIPTION RESULT:")
        print("=" * 80)
        print(result)
        print("=" * 80)

        # Print stats
        word_count = len(result.split())
        print(f"\n📊 Stats:")
        print(f"   - Duration: {duration:.2f}s")
        print(f"   - Words: {word_count:,}")
        print(f"   - Speed: {word_count / duration * 60:.0f} words/min")

    except Exception as e:
        print(f"❌ Error during transcription: {e}")
        import traceback

        traceback.print_exc()


async def compare_models():
    """Compare Whisper models"""
    print("🔬 Comparing Whisper Models\n")

    # Look for common audio files in CWD, script dir, or project root
    search_paths = [
        Path("."),
        Path(__file__).parent,
        Path(__file__).parent.parent.parent,
    ]

    audio_files = []
    for path in search_paths:
        audio_files.extend(
            list(path.glob("*.mp3"))
            + list(path.glob("*.wav"))
            + list(path.glob("*.m4a"))
        )
        if audio_files:
            break

    if not audio_files:
        print(f"❌ No audio files found")
        return

    audio_path = audio_files[0]
    print(f"🎵 Using audio file: {audio_path.name}")

    models_to_test = [
        {"local": "whisper-large-v3", "hf": "openai/whisper-large-v3"},
        {"local": "whisper-large-v3-turbo", "hf": "openai/whisper-large-v3-turbo"},
    ]

    results = {}

    for model_config in models_to_test:
        local_name = model_config["local"]
        hf_name = model_config["hf"]

        print(f"\n{'='*80}")
        print(f"Testing: {local_name} ({hf_name})")
        print("=" * 80)

        # Temporarily override settings
        original_local = settings.MODEL_WHISPER_LOCAL
        original_hf = settings.MODEL_WHISPER_HF

        settings.MODEL_WHISPER_LOCAL = local_name
        settings.MODEL_WHISPER_HF = hf_name

        # Create new instance to force reload model
        multimedia = MultimediaService()

        try:
            start = time.time()
            # This will trigger model load
            result = multimedia.transcribe_audio(str(audio_path))
            duration = time.time() - start

            results[local_name] = {
                "text": result,
                "duration": duration,
                "words": len(result.split()),
                "chars": len(result),
            }

            print(f"\n⏱️  Duration: {duration:.2f}s")
            print(f"📊 Words: {results[local_name]['words']:,}")
            print(f"📝 Preview:\n{result[:500]}...")

        except Exception as e:
            print(f"❌ Error: {e}")
            results[local_name] = {"error": str(e)}

        # Restore original settings
        settings.MODEL_WHISPER_LOCAL = original_local
        settings.MODEL_WHISPER_HF = original_hf

    # Summary comparison
    print(f"\n\n{'='*80}")
    print("COMPARISON SUMMARY")
    print("=" * 80)

    for model, data in results.items():
        print(f"\n{model}:")
        if "error" in data:
            print(f"  ❌ Failed: {data['error']}")
        else:
            print(f"  ⏱️  Time: {data['duration']:.2f}s")
            print(f"  📊 Words: {data['words']:,}")
            print(f"  ⚡ Speed: {data['words'] / data['duration'] * 60:.0f} words/min")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Whisper models")
    parser.add_argument(
        "--compare", action="store_true", help="Compare whisper-large-v3 vs turbo"
    )
    args = parser.parse_args()

    if args.compare:
        asyncio.run(compare_models())
    else:
        asyncio.run(test_whisper_on_audio())
