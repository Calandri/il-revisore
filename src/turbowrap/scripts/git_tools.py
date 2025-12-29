#!/usr/bin/env python3
"""Git tools for AI agents.

This module provides simple, error-handling Git operations for AI agents.
Use these instead of raw Bash commands to reduce costs and handle errors gracefully.

Usage:
    python -m turbowrap.scripts.git_tools create-branch <branch_name> [--from <base>]
    python -m turbowrap.scripts.git_tools commit -m "message" [--add-all]
    python -m turbowrap.scripts.git_tools pull [--rebase]
    python -m turbowrap.scripts.git_tools merge <branch> [--no-ff]
    python -m turbowrap.scripts.git_tools push [--force]
    python -m turbowrap.scripts.git_tools status
    python -m turbowrap.scripts.git_tools checkout <branch>
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_git(args: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Run a git command and return (success, output)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd or Path.cwd(),
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            error = result.stderr.strip() or output
            return False, f"Error: {error}"
        return True, output
    except Exception as e:
        return False, f"Exception: {e}"


def create_branch(name: str, base: str | None = None) -> int:
    """Create a new branch and switch to it."""
    # First, make sure we're on the base branch
    if base:
        ok, out = run_git(["checkout", base])
        if not ok:
            print(f"Failed to checkout {base}: {out}")
            return 1
        # Pull latest
        ok, out = run_git(["pull", "--rebase"])
        if not ok:
            print(f"Warning: pull failed: {out}")

    # Check if branch already exists
    ok, out = run_git(["branch", "--list", name])
    if ok and name in out:
        print(f"Branch '{name}' already exists. Switching to it...")
        ok, out = run_git(["checkout", name])
        if not ok:
            print(f"Failed to checkout: {out}")
            return 1
        print(f"Switched to existing branch '{name}'")
        return 0

    # Create and switch to new branch
    ok, out = run_git(["checkout", "-b", name])
    if not ok:
        print(f"Failed to create branch: {out}")
        return 1

    print(f"Created and switched to branch '{name}'")
    return 0


def commit(message: str, add_all: bool = False) -> int:
    """Create a commit with the given message."""
    # Check for changes
    ok, status = run_git(["status", "--porcelain"])
    if not ok:
        print(f"Failed to get status: {status}")
        return 1

    if not status.strip():
        print("Nothing to commit, working tree clean")
        return 0

    # Add all if requested
    if add_all:
        ok, out = run_git(["add", "-A"])
        if not ok:
            print(f"Failed to stage changes: {out}")
            return 1
        print("Staged all changes")

    # Check if there are staged changes
    ok, staged = run_git(["diff", "--cached", "--name-only"])
    if not staged.strip():
        print("No staged changes to commit. Use --add-all or git add first.")
        return 1

    # Commit
    ok, out = run_git(["commit", "-m", message])
    if not ok:
        print(f"Failed to commit: {out}")
        return 1

    print(f"Committed: {message}")

    # Show commit info
    ok, log = run_git(["log", "-1", "--oneline"])
    if ok:
        print(f"Commit: {log}")

    return 0


def pull(rebase: bool = False) -> int:
    """Pull latest changes from remote."""
    args = ["pull"]
    if rebase:
        args.append("--rebase")

    ok, out = run_git(args)
    if not ok:
        if "conflict" in out.lower():
            print(f"CONFLICT detected during pull: {out}")
            print("\nResolve conflicts manually, then run:")
            print("  git add <resolved-files>")
            print("  git rebase --continue  # if rebasing")
            return 1
        print(f"Pull failed: {out}")
        return 1

    print("Pull successful")
    if out:
        print(out)
    return 0


def merge(branch: str, no_ff: bool = False) -> int:
    """Merge a branch into current branch."""
    # Check current branch
    ok, current = run_git(["branch", "--show-current"])
    if not ok:
        print(f"Failed to get current branch: {current}")
        return 1

    print(f"Merging '{branch}' into '{current}'...")

    args = ["merge", branch]
    if no_ff:
        args.append("--no-ff")

    ok, out = run_git(args)
    if not ok:
        if "conflict" in out.lower():
            print(f"CONFLICT during merge: {out}")
            print("\nResolve conflicts manually:")
            print("  1. Edit conflicting files")
            print("  2. git add <resolved-files>")
            print("  3. git commit")
            return 1
        print(f"Merge failed: {out}")
        return 1

    print(f"Successfully merged '{branch}' into '{current}'")
    if out:
        print(out)
    return 0


def push(force: bool = False, set_upstream: bool = False) -> int:
    """Push current branch to remote."""
    # Get current branch
    ok, branch = run_git(["branch", "--show-current"])
    if not ok:
        print(f"Failed to get current branch: {branch}")
        return 1

    args = ["push"]
    if force:
        args.append("--force")
    if set_upstream:
        args.extend(["-u", "origin", branch])

    ok, out = run_git(args)
    if not ok:
        # Check if we need to set upstream
        if "no upstream" in out.lower() or "set-upstream" in out.lower():
            print(f"Setting upstream for branch '{branch}'...")
            ok, out = run_git(["push", "-u", "origin", branch])
            if not ok:
                print(f"Push failed: {out}")
                return 1
        else:
            print(f"Push failed: {out}")
            return 1

    print(f"Pushed branch '{branch}' to remote")
    return 0


def status() -> int:
    """Show git status."""
    ok, out = run_git(["status", "--short", "--branch"])
    if not ok:
        print(f"Failed to get status: {out}")
        return 1

    print(out if out else "Clean working tree")
    return 0


def checkout(branch: str) -> int:
    """Checkout a branch."""
    ok, out = run_git(["checkout", branch])
    if not ok:
        # Maybe it's a remote branch
        ok, out = run_git(["checkout", "-t", f"origin/{branch}"])
        if not ok:
            print(f"Failed to checkout '{branch}': {out}")
            return 1

    print(f"Switched to branch '{branch}'")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Git tools for AI agents")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # create-branch
    p_branch = subparsers.add_parser("create-branch", help="Create a new branch")
    p_branch.add_argument("name", help="Branch name")
    p_branch.add_argument("--from", dest="base", default="main", help="Base branch (default: main)")

    # commit
    p_commit = subparsers.add_parser("commit", help="Create a commit")
    p_commit.add_argument("-m", "--message", required=True, help="Commit message")
    p_commit.add_argument("--add-all", action="store_true", help="Stage all changes before commit")

    # pull
    p_pull = subparsers.add_parser("pull", help="Pull from remote")
    p_pull.add_argument("--rebase", action="store_true", help="Use rebase instead of merge")

    # merge
    p_merge = subparsers.add_parser("merge", help="Merge a branch")
    p_merge.add_argument("branch", help="Branch to merge")
    p_merge.add_argument(
        "--no-ff", action="store_true", help="Create merge commit even if fast-forward"
    )

    # push
    p_push = subparsers.add_parser("push", help="Push to remote")
    p_push.add_argument("--force", action="store_true", help="Force push")
    p_push.add_argument("-u", "--set-upstream", action="store_true", help="Set upstream")

    # status
    subparsers.add_parser("status", help="Show status")

    # checkout
    p_checkout = subparsers.add_parser("checkout", help="Checkout a branch")
    p_checkout.add_argument("branch", help="Branch name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "create-branch":
        return create_branch(args.name, args.base)
    if args.command == "commit":
        return commit(args.message, args.add_all)
    if args.command == "pull":
        return pull(args.rebase)
    if args.command == "merge":
        return merge(args.branch, args.no_ff)
    if args.command == "push":
        return push(args.force, getattr(args, "set_upstream", False))
    if args.command == "status":
        return status()
    if args.command == "checkout":
        return checkout(args.branch)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
