#!/usr/bin/env python3
"""
CLI entry point for TurboWrap tools.

Usage:
    python -m turbowrap.tools structure /path/to/repo
    python -m turbowrap.tools structure /path/to/repo --depth 2
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="TurboWrap tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Structure generator command
    struct_parser = subparsers.add_parser(
        "structure",
        help="Generate STRUCTURE.md documentation files",
        description="""
Generate STRUCTURE.md files for a repository.

Creates documentation files in each directory containing code files,
with file statistics, extracted elements, and repository type detection.
        """,
    )
    struct_parser.add_argument(
        "repo_path",
        type=Path,
        help="Path to repository to analyze",
    )
    struct_parser.add_argument(
        "--depth",
        "-d",
        type=int,
        default=3,
        help="Maximum directory depth (default: 3)",
    )
    struct_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=5,
        help="Number of parallel workers (default: 5)",
    )
    struct_parser.add_argument(
        "--no-gemini",
        action="store_true",
        help="Skip Gemini Flash element extraction (faster, stats only)",
    )

    args = parser.parse_args()

    if args.command == "structure":
        run_structure_generator(args)
    else:
        parser.print_help()
        sys.exit(1)


def run_structure_generator(args):
    """Run structure generator command."""
    from turbowrap.tools.structure_generator import StructureGenerator

    repo_path = args.repo_path.resolve()
    if not repo_path.exists():
        print(f"Error: Path not found: {repo_path}")
        sys.exit(1)

    print("=" * 60)
    print("TurboWrap - Structure Generator")
    print("=" * 60)
    print(f"   Repository: {repo_path}")
    print(f"   Max depth: {args.depth}")
    print(f"   Workers: {args.workers}")
    print(f"   Gemini: {'Disabled' if args.no_gemini else 'Enabled'}")
    print("=" * 60)

    # Initialize Gemini client (default: enabled)
    gemini_client = None
    if not args.no_gemini:
        try:
            import os

            from google import genai

            api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if api_key:
                # Simple client wrapper for generate() method
                class SimpleGeminiClient:
                    def __init__(self):
                        self.client = genai.Client(api_key=api_key)
                        self.model = "gemini-3-flash-preview"

                    def generate(self, prompt: str) -> str:
                        response = self.client.models.generate_content(
                            model=self.model,
                            contents=[{"role": "user", "parts": [{"text": prompt}]}],
                        )
                        return response.text

                gemini_client = SimpleGeminiClient()
                print("   Gemini Flash client initialized")
            else:
                print("   Warning: GOOGLE_API_KEY not set, skipping Gemini")
        except ImportError:
            print("   Warning: google-genai not installed, skipping Gemini")

    # Run generator
    generator = StructureGenerator(
        repo_path=repo_path,
        max_depth=args.depth,
        max_workers=args.workers,
        gemini_client=gemini_client,
    )

    generated = generator.generate(verbose=True)

    print("\n" + "=" * 60)
    print(f"Generated {len(generated)} STRUCTURE.md files")
    print("=" * 60)


if __name__ == "__main__":
    main()
