#!/usr/bin/env python3
"""CLI tool for AI test generation operations.

Called by LLM via /create_test command to create branches, save tests, and run them.

Usage:
    python -m turbowrap.scripts.test_tool branch --suite-id UUID --name "test-feature"
    python -m turbowrap.scripts.test_tool save --suite-id UUID --test-file path/to/test.py
    python -m turbowrap.scripts.test_tool run --suite-id UUID
    python -m turbowrap.scripts.test_tool commit --suite-id UUID --message "Add tests for X"
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from turbowrap.db.models import Repository, TestSuite  # noqa: E402
from turbowrap.db.session import get_session_local  # noqa: E402


def _get_repo_path(suite_id: str) -> tuple[str | None, str | None]:
    """Get repository path for a test suite."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
        if not suite:
            return None, f"Test suite not found: {suite_id}"

        repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
        if not repo:
            return None, f"Repository not found for suite: {suite_id}"

        return repo.local_path, None
    finally:
        db.close()


def _run_git(repo_path: str, *args: str) -> tuple[bool, str]:
    """Run a git command in the repository."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False, result.stderr or result.stdout
        return True, result.stdout
    except Exception as e:
        return False, str(e)


def create_branch(suite_id: str, branch_name: str) -> dict[str, Any]:
    """Create a new branch for test development."""
    repo_path, error = _get_repo_path(suite_id)
    if error or not repo_path:
        return {"success": False, "error": error or "Repository path not found"}

    # Ensure branch name is valid
    safe_name = branch_name.replace(" ", "-").lower()
    if not safe_name.startswith("test") and not safe_name.startswith("feat/test"):
        safe_name = f"feat/test-{safe_name}"

    # Fetch latest
    _run_git(repo_path, "fetch", "origin")

    # Create and checkout branch from main
    success, output = _run_git(repo_path, "checkout", "-b", safe_name, "origin/main")
    if not success:
        # Maybe branch exists, try just checkout
        success, output = _run_git(repo_path, "checkout", safe_name)
        if not success:
            return {"success": False, "error": f"Failed to create branch: {output}"}

    return {
        "success": True,
        "branch": safe_name,
        "repo_path": repo_path,
        "message": f"Created and checked out branch '{safe_name}'",
    }


def save_test_file(suite_id: str, test_file: str, content: str | None = None) -> dict[str, Any]:
    """Save a test file and stage it for commit."""
    repo_path, error = _get_repo_path(suite_id)
    if error or not repo_path:
        return {"success": False, "error": error or "Repository path not found"}

    test_path = Path(test_file)

    # If content provided, write it
    if content:
        # Make path absolute if relative
        if not test_path.is_absolute():
            test_path = Path(repo_path) / test_path

        # Ensure parent directory exists
        test_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        test_path.write_text(content, encoding="utf-8")

    # Verify file exists
    abs_path = test_path if test_path.is_absolute() else Path(repo_path) / test_path
    if not abs_path.exists():
        return {"success": False, "error": f"Test file not found: {test_file}"}

    # Stage the file
    rel_path = test_path if not test_path.is_absolute() else test_path.relative_to(repo_path)
    success, output = _run_git(repo_path, "add", str(rel_path))
    if not success:
        return {"success": False, "error": f"Failed to stage file: {output}"}

    return {
        "success": True,
        "file": str(rel_path),
        "repo_path": repo_path,
        "message": f"Test file saved and staged: {rel_path}",
    }


def run_tests(suite_id: str, test_path: str | None = None) -> dict[str, Any]:
    """Run tests for the suite."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
        if not suite:
            return {"success": False, "error": f"Test suite not found: {suite_id}"}

        repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
        if not repo:
            return {"success": False, "error": "Repository not found"}

        repo_path = repo.local_path
        framework = suite.framework

        # Build test command
        if test_path:
            target = test_path
        else:
            target = suite.path or "tests/"

        if framework == "pytest":
            cmd = ["pytest", target, "-v", "--tb=short"]
        elif framework in ("vitest", "jest"):
            cmd = ["npx", framework, "run", target]
        elif framework == "playwright":
            cmd = ["npx", "playwright", "test", target]
        else:
            cmd = ["pytest", target, "-v"]  # Default to pytest

        # Run tests
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": " ".join(cmd),
            "message": "Tests passed!" if result.returncode == 0 else "Some tests failed",
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Test execution timed out (300s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def commit_tests(suite_id: str, message: str) -> dict[str, Any]:
    """Commit the staged test files."""
    repo_path, error = _get_repo_path(suite_id)
    if error or not repo_path:
        return {"success": False, "error": error or "Repository path not found"}

    # Check if there are staged changes
    success, output = _run_git(repo_path, "diff", "--cached", "--name-only")
    if not output.strip():
        return {"success": False, "error": "No staged changes to commit"}

    # Commit with message
    full_message = f"{message}\n\n🤖 Generated with TurboWrap AI Test Generator"
    success, output = _run_git(repo_path, "commit", "-m", full_message)
    if not success:
        return {"success": False, "error": f"Commit failed: {output}"}

    # Get commit hash
    _, commit_hash = _run_git(repo_path, "rev-parse", "HEAD")

    return {
        "success": True,
        "commit": commit_hash.strip()[:8],
        "message": message,
        "full_output": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Test generation CLI tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Branch command
    branch_parser = subparsers.add_parser("branch", help="Create a test branch")
    branch_parser.add_argument("--suite-id", required=True, help="Test suite UUID")
    branch_parser.add_argument("--name", required=True, help="Branch name")

    # Save command
    save_parser = subparsers.add_parser("save", help="Save test file")
    save_parser.add_argument("--suite-id", required=True, help="Test suite UUID")
    save_parser.add_argument("--test-file", required=True, help="Path to test file")
    save_parser.add_argument("--content", help="Test file content (optional)")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run tests")
    run_parser.add_argument("--suite-id", required=True, help="Test suite UUID")
    run_parser.add_argument("--path", help="Specific test path (optional)")

    # Commit command
    commit_parser = subparsers.add_parser("commit", help="Commit test changes")
    commit_parser.add_argument("--suite-id", required=True, help="Test suite UUID")
    commit_parser.add_argument("--message", required=True, help="Commit message")

    args = parser.parse_args()

    if args.command == "branch":
        result = create_branch(suite_id=args.suite_id, branch_name=args.name)
    elif args.command == "save":
        result = save_test_file(
            suite_id=args.suite_id,
            test_file=args.test_file,
            content=args.content,
        )
    elif args.command == "run":
        result = run_tests(suite_id=args.suite_id, test_path=args.path)
    elif args.command == "commit":
        result = commit_tests(suite_id=args.suite_id, message=args.message)
    else:
        result = {"success": False, "error": f"Unknown command: {args.command}"}

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
