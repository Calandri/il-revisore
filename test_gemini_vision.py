#!/usr/bin/env python3
"""Test script for Gemini Vision screenshot analysis.

Usage:
    python test_gemini_vision.py /path/to/screenshot1.png [/path/to/screenshot2.png ...]
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from turbowrap.llm.gemini import GeminiProClient


def test_screenshot_analysis(image_paths: list[str]):
    """Test Gemini Vision analysis with screenshots."""

    # Validate files exist
    for path in image_paths:
        if not Path(path).exists():
            print(f"❌ File not found: {path}")
            return

    print(f"🔍 Testing Gemini Vision with {len(image_paths)} screenshot(s)...")
    print(f"📁 Files: {', '.join(Path(p).name for p in image_paths)}\n")

    # Create client
    try:
        client = GeminiProClient()
        print(f"✅ GeminiProClient initialized (model: {client.model})\n")
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        return

    # Test context
    context = {
        "title": "Fix login button UI",
        "description": "The login button is not properly aligned and doesn't respond on mobile",
        "figma_link": "https://figma.com/file/example",
        "website_link": "https://app.example.com/login"
    }

    # Run analysis
    try:
        print("⏳ Analyzing screenshots with Gemini Vision API...\n")
        insights = client.analyze_screenshots(image_paths, context)

        print("=" * 80)
        print("📊 GEMINI VISION ANALYSIS")
        print("=" * 80)
        print(insights)
        print("=" * 80)
        print(f"\n✅ Analysis completed successfully!")
        print(f"📏 Response length: {len(insights)} characters")

    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_gemini_vision.py <screenshot1.png> [screenshot2.png ...]")
        print("\nExample:")
        print("  python test_gemini_vision.py /tmp/login.png /tmp/dashboard.png")
        sys.exit(1)

    image_paths = sys.argv[1:]
    test_screenshot_analysis(image_paths)
