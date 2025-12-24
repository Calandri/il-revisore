#!/usr/bin/env python3
"""
TurboWrap - AI-Powered Code Review with 5 Specialized Reviewers.

This is the main CLI entry point that uses the turbowrap package.

Reviewers:
    - reviewer_be_architecture: Backend architecture (SOLID, layers, coupling)
    - reviewer_be_quality: Backend quality (linting, security, performance)
    - reviewer_fe_architecture: Frontend architecture (React patterns, state)
    - reviewer_fe_quality: Frontend quality (type safety, performance)
    - analyst_func: Functional analysis (business logic, requirements)

Each reviewer goes through a Challenger Loop where Gemini validates Claude's
output until satisfaction reaches 99% or max iterations.

Usage:
    python turbowrap.py /path/to/repo [--output ./output]
    python turbowrap.py /path/to/repo --no-challenger  # Skip challenger loop
    python turbowrap.py /path/to/repo --no-functional  # Skip functional analysis

Example:
    python turbowrap.py ~/code/my-project
    python turbowrap.py ~/code/my-project --output ./reviews
"""

import argparse
import asyncio
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="TurboWrap - AI-Powered Code Review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Reviewers:
    - reviewer_be_architecture: Backend architecture review
    - reviewer_be_quality: Backend code quality review
    - reviewer_fe_architecture: Frontend architecture review
    - reviewer_fe_quality: Frontend code quality review
    - analyst_func: Functional/business logic analysis

Environment Variables:
    GOOGLE_API_KEY or GEMINI_API_KEY: For Gemini Flash (challenger)
    ANTHROPIC_API_KEY: For Claude Opus (reviewers)

Examples:
    python turbowrap.py ~/code/my-project
    python turbowrap.py ~/code/my-project --output ./reviews
    python turbowrap.py ~/code/my-project --no-challenger
    python turbowrap.py ~/code/my-project --no-functional
        """
    )
    parser.add_argument(
        "repo_path",
        type=Path,
        help="Path to repository to review"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output directory (default: <repo>/.reviews)"
    )
    parser.add_argument(
        "--no-challenger",
        action="store_true",
        help="Disable challenger loop (faster but less thorough)"
    )
    parser.add_argument(
        "--no-functional",
        action="store_true",
        help="Skip functional analysis reviewer"
    )
    parser.add_argument(
        "--satisfaction-threshold",
        type=int,
        default=99,
        help="Challenger satisfaction threshold 0-100 (default: 99)"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "both"],
        default="both",
        help="Output format (default: both)"
    )

    args = parser.parse_args()

    # Validate repo path
    repo_path = args.repo_path.resolve()
    if not repo_path.exists():
        print(f"Error: Repository path not found: {repo_path}")
        sys.exit(1)

    output_dir = args.output or (repo_path / ".reviews")

    # Print banner
    print("=" * 60)
    print("TurboWrap - AI-Powered Code Review")
    print("=" * 60)
    print(f"   Repository: {repo_path}")
    print(f"   Output: {output_dir}")
    print(f"   Challenger: {'Enabled' if not args.no_challenger else 'Disabled'}")
    print(f"   Functional: {'Enabled' if not args.no_functional else 'Disabled'}")
    print("=" * 60)

    # Import here to avoid slow startup for --help
    try:
        from turbowrap.review.orchestrator import Orchestrator
        from turbowrap.review.models.review import (
            ReviewRequest,
            ReviewRequestSource,
            ReviewOptions,
        )
        from turbowrap.review.report_generator import ReportGenerator
    except ImportError as e:
        print(f"Error: Failed to import turbowrap package: {e}")
        print("Make sure you're running from the project root or have installed the package.")
        sys.exit(1)

    # Build request
    request = ReviewRequest(
        type="directory",
        source=ReviewRequestSource(directory=str(repo_path)),
        options=ReviewOptions(
            include_functional=not args.no_functional,
            challenger_enabled=not args.no_challenger,
            satisfaction_threshold=args.satisfaction_threshold,
            output_format=args.format,
        ),
    )

    # Run review
    print("\nStarting review...")
    print("   Reviewers will run in parallel with challenger loop")
    print("")

    try:
        orchestrator = Orchestrator()
        report = asyncio.run(orchestrator.review(request))
    except Exception as e:
        print(f"\nError during review: {e}")
        sys.exit(1)

    # Generate output
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        files_dict = ReportGenerator.save_report(report, output_dir, formats=[args.format])
        files = list(files_dict.values())
    except Exception as e:
        print(f"\nError generating report: {e}")
        # Fallback: save raw JSON
        import json
        fallback_path = output_dir / "report_raw.json"
        fallback_path.write_text(report.model_dump_json(indent=2))
        print(f"   Saved fallback: {fallback_path}")
        files = [fallback_path]

    # Print summary
    print("\n" + "=" * 60)
    print("Review Complete!")
    print("=" * 60)
    print(f"   Recommendation: {report.summary.recommendation.value}")
    print(f"   Score: {report.summary.score:.1f}/10")
    print("")
    print("   Issues:")
    print(f"      Critical: {report.summary.severity.critical}")
    print(f"      High: {report.summary.severity.high}")
    print(f"      Medium: {report.summary.severity.medium}")
    print(f"      Low: {report.summary.severity.low}")
    print("")

    if report.challenger.enabled:
        print("   Challenger Loop:")
        print(f"      Total iterations: {report.challenger.total_iterations}")
        print(f"      Avg satisfaction: {report.challenger.average_satisfaction:.1f}%")
        print(f"      Convergence: {report.challenger.convergence_status.value if report.challenger.convergence_status else 'N/A'}")
        print("")

    print("   Reviewers:")
    for reviewer in report.reviewers:
        status_emoji = "✅" if reviewer.status == "completed" else "❌"
        print(f"      {status_emoji} {reviewer.name}: {reviewer.issues_found} issues")
    print("")

    print("   Output files:")
    for f in files:
        print(f"      📄 {f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
