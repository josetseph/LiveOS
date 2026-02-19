"""
Test PaddleOCR-VL vision model with cv.pdf
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.services.multimedia import MultimediaService


async def test_ocr_on_pdf():
    """Test PaddleOCR-VL on cv.pdf"""
    print(f"🔍 Testing {settings.MODEL_VISION} on cv.pdf\n")

    # Initialize multimedia service
    multimedia = MultimediaService()

    # Path to cv.pdf (adjust if needed)
    pdf_path = Path("cv.pdf")

    if not pdf_path.exists():
        print(f"❌ Error: cv.pdf not found at {pdf_path.absolute()}")
        print("Please place cv.pdf in the backend directory")
        return

    print(f"📄 Processing: {pdf_path.absolute()}\n")

    try:
        # Use the multimedia service for OCR
        result = multimedia.extract_text_from_pdf(str(pdf_path))

        print("=" * 80)
        print("OCR RESULT:")
        print("=" * 80)
        print(result)
        print("=" * 80)

        # Print stats
        word_count = len(result.split())
        char_count = len(result)
        print(f"\n📊 Stats:")
        print(f"   - Characters: {char_count:,}")
        print(f"   - Words: {word_count:,}")
        print(f"   - Lines: {len(result.splitlines())}")

    except Exception as e:
        print(f"❌ Error during OCR: {e}")
        import traceback

        traceback.print_exc()


async def compare_models():
    """Compare PaddleOCR-VL vs GLM-OCR"""
    print("🔬 Comparing PaddleOCR-VL vs GLM-OCR\n")

    pdf_path = Path("cv.pdf")
    if not pdf_path.exists():
        print("❌ cv.pdf not found")
        return

    models_to_test = [
        "MedAIBase/PaddleOCR-VL:0.9b",
        # "deepseek-ocr:latest",
        "glm-ocr:latest",
    ]

    results = {}

    for model in models_to_test:
        print(f"\n{'='*80}")
        print(f"Testing: {model}")
        print("=" * 80)

        # Temporarily override MODEL_VISION
        original_model = settings.MODEL_VISION
        settings.MODEL_VISION = model

        multimedia = MultimediaService()

        try:
            import time

            start = time.time()
            result = multimedia.extract_text_from_pdf(str(pdf_path))
            duration = time.time() - start

            results[model] = {
                "text": result,
                "duration": duration,
                "words": len(result.split()),
                "chars": len(result),
            }

            print(f"\n⏱️  Duration: {duration:.2f}s")
            print(f"📊 Words: {results[model]['words']:,}")
            print(f"📝 Preview:\n{result[:500]}...")

        except Exception as e:
            print(f"❌ Error: {e}")
            results[model] = {"error": str(e)}

        # Restore original
        settings.MODEL_VISION = original_model

    # Summary comparison
    print(f"\n\n{'='*80}")
    print("COMPARISON SUMMARY")
    print("=" * 80)

    for model, data in results.items():
        print(f"\n{model}:")
        if "error" in data:
            print(f"  ❌ Failed: {data['error']}")
        else:
            print(f"  ⏱️  Speed: {data['duration']:.2f}s")
            print(f"  📊 Words: {data['words']:,}")
            print(f"  📏 Length: {data['chars']:,} chars")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test OCR models")
    parser.add_argument("--compare", action="store_true", help="Compare OCR models")
    args = parser.parse_args()

    if args.compare:
        asyncio.run(compare_models())
    else:
        asyncio.run(test_ocr_on_pdf())
