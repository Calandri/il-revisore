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
    python -m turbowrap.scripts.git_tools stash [pop|list|drop]
    python -m turbowrap.scripts.git_tools abort [merge|rebase|cherry-pick]
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Exit codes for agents to understand
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_CONFLICT = 2
EXIT_DIRTY_WORKTREE = 3
EXIT_NETWORK_ERROR = 4


def run_git(args: list[str], cwd: str | None = None, timeout: int = 120) -> tuple[bool, str, str]:
    """Run a git command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd or Path.cwd(),
            timeout=timeout,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return False, stdout, stderr
        return True, stdout, stderr
    except subprocess.TimeoutExpired:
        return False, "", "TIMEOUT: Command took too long (network issue?)"
    except FileNotFoundError:
        return False, "", "ERROR: git command not found. Is git installed?"
    except Exception as e:
        return False, "", f"EXCEPTION: {e}"


def is_git_repo() -> bool:
    """Check if current directory is a git repository."""
    ok, _, _ = run_git(["rev-parse", "--git-dir"])
    return ok


def has_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes."""
    ok, out, _ = run_git(["status", "--porcelain"])
    return ok and bool(out.strip())


def has_staged_changes() -> bool:
    """Check if there are staged changes."""
    ok, out, _ = run_git(["diff", "--cached", "--name-only"])
    return ok and bool(out.strip())


def get_current_branch() -> str | None:
    """Get the current branch name, or None if detached HEAD."""
    ok, out, _ = run_git(["branch", "--show-current"])
    return out if ok and out else None


def is_detached_head() -> bool:
    """Check if we're in detached HEAD state."""
    return get_current_branch() is None


def branch_exists_locally(branch: str) -> bool:
    """Check if a branch exists locally."""
    ok, out, _ = run_git(["branch", "--list", branch])
    return ok and branch in out


def branch_exists_remotely(branch: str, remote: str = "origin") -> bool:
    """Check if a branch exists on remote."""
    ok, out, _ = run_git(["ls-remote", "--heads", remote, branch])
    return ok and bool(out.strip())


def is_merge_in_progress() -> bool:
    """Check if there's a merge in progress."""
    git_dir = Path(".git")
    return (git_dir / "MERGE_HEAD").exists()


def is_rebase_in_progress() -> bool:
    """Check if there's a rebase in progress."""
    git_dir = Path(".git")
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def print_error(msg: str) -> None:
    """Print error message."""
    print(f"ERROR: {msg}", file=sys.stderr)


def print_warning(msg: str) -> None:
    """Print warning message."""
    print(f"WARNING: {msg}", file=sys.stderr)


def create_branch(name: str, base: str | None = None) -> int:
    """Create a new branch and switch to it."""
    # Pre-flight checks
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if is_merge_in_progress():
        print_error("Merge in progress. Run 'git_tools abort merge' first.")
        return EXIT_ERROR

    if is_rebase_in_progress():
        print_error("Rebase in progress. Run 'git_tools abort rebase' first.")
        return EXIT_ERROR

    # Check for uncommitted changes
    if has_uncommitted_changes():
        print_warning("You have uncommitted changes. They will be carried to the new branch.")

    # First, make sure we're on the base branch
    if base:
        ok, out, err = run_git(["checkout", base])
        if not ok:
            # Maybe local branch is behind, try fetching
            if "conflict" in err.lower() or "overwritten" in err.lower():
                print_error(f"Cannot checkout {base}: uncommitted changes would be overwritten")
                print("SUGGESTION: Commit or stash your changes first:")
                print("  git_tools commit -m 'WIP' --add-all")
                print("  # OR")
                print("  git_tools stash")
                return EXIT_DIRTY_WORKTREE
            print_error(f"Failed to checkout {base}: {err or out}")
            return EXIT_ERROR

        # Pull latest
        ok, out, err = run_git(["pull", "--rebase"])
        if not ok:
            if "conflict" in err.lower():
                print_error(f"Conflict during pull: {err}")
                print("SUGGESTION: Resolve conflicts then continue:")
                print("  git add <resolved-files>")
                print("  git rebase --continue")
                return EXIT_CONFLICT
            print_warning(f"Pull failed (continuing anyway): {err}")

    # Check if branch already exists locally
    if branch_exists_locally(name):
        print(f"Branch '{name}' already exists locally. Switching to it...")
        ok, out, err = run_git(["checkout", name])
        if not ok:
            print_error(f"Failed to checkout: {err or out}")
            return EXIT_ERROR
        print(f"SUCCESS: Switched to existing branch '{name}'")
        return EXIT_SUCCESS

    # Create and switch to new branch
    ok, out, err = run_git(["checkout", "-b", name])
    if not ok:
        print_error(f"Failed to create branch: {err or out}")
        return EXIT_ERROR

    print(f"SUCCESS: Created and switched to branch '{name}'")
    return EXIT_SUCCESS


def commit(message: str, add_all: bool = False) -> int:
    """Create a commit with the given message."""
    # Pre-flight checks
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if is_merge_in_progress():
        print_warning("Merge in progress - this will complete the merge commit")

    if is_rebase_in_progress():
        print_error("Rebase in progress. Use 'git rebase --continue' instead.")
        return EXIT_ERROR

    if is_detached_head():
        print_warning("You are in detached HEAD state. Commit will not be on any branch.")

    # Check for changes
    ok, status, err = run_git(["status", "--porcelain"])
    if not ok:
        print_error(f"Failed to get status: {err}")
        return EXIT_ERROR

    if not status.strip() and not is_merge_in_progress():
        print("Nothing to commit, working tree clean")
        return EXIT_SUCCESS

    # Add all if requested
    if add_all:
        ok, out, err = run_git(["add", "-A"])
        if not ok:
            print_error(f"Failed to stage changes: {err or out}")
            return EXIT_ERROR
        print("Staged all changes")

    # Check if there are staged changes (unless merge in progress)
    if not is_merge_in_progress() and not has_staged_changes():
        print_error("No staged changes to commit. Use --add-all or git add first.")
        return EXIT_ERROR

    # Commit
    ok, out, err = run_git(["commit", "-m", message])
    if not ok:
        # Check for pre-commit hook failures
        if "hook" in err.lower():
            print_error(f"Pre-commit hook failed: {err}")
            print("SUGGESTION: Fix the issues reported by the hook, then retry.")
            return EXIT_ERROR
        # Check for empty commit
        if "nothing to commit" in err.lower() or "nothing to commit" in out.lower():
            print("Nothing to commit (pre-commit hook may have modified files)")
            # Try again if add_all was requested
            if add_all:
                ok2, _, _ = run_git(["add", "-A"])
                if ok2:
                    ok, out, err = run_git(["commit", "-m", message])
                    if ok:
                        print(f"SUCCESS: Committed (after re-staging): {message}")
                        ok, log, _ = run_git(["log", "-1", "--oneline"])
                        if ok:
                            print(f"Commit: {log}")
                        return EXIT_SUCCESS
            return EXIT_SUCCESS
        print_error(f"Failed to commit: {err or out}")
        return EXIT_ERROR

    print(f"SUCCESS: Committed: {message}")

    # Show commit info
    ok, log, _ = run_git(["log", "-1", "--oneline"])
    if ok:
        print(f"Commit: {log}")

    return EXIT_SUCCESS


def pull(rebase: bool = False) -> int:
    """Pull latest changes from remote."""
    # Pre-flight checks
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if is_merge_in_progress():
        print_error("Merge in progress. Complete or abort it first.")
        return EXIT_ERROR

    if is_rebase_in_progress():
        print_error("Rebase in progress. Complete or abort it first.")
        return EXIT_ERROR

    current = get_current_branch()
    if not current:
        print_error("Cannot pull in detached HEAD state")
        return EXIT_ERROR

    # Check for uncommitted changes if rebasing
    if rebase and has_uncommitted_changes():
        print_error("Cannot rebase with uncommitted changes. Commit or stash first.")
        return EXIT_DIRTY_WORKTREE

    args = ["pull"]
    if rebase:
        args.append("--rebase")

    ok, out, err = run_git(args, timeout=180)  # Longer timeout for network
    if not ok:
        combined = f"{out} {err}".lower()
        if "conflict" in combined:
            print_error("CONFLICT detected during pull")
            print(err or out)
            print("\nSUGGESTION: Resolve conflicts manually, then run:")
            print("  git add <resolved-files>")
            if rebase:
                print("  git rebase --continue")
            else:
                print("  git commit")
            return EXIT_CONFLICT
        if "timeout" in combined:
            print_error("Network timeout. Check your connection.")
            return EXIT_NETWORK_ERROR
        if "could not resolve" in combined or "unable to access" in combined:
            print_error(f"Network error: {err or out}")
            return EXIT_NETWORK_ERROR
        if "no tracking" in combined or "no upstream" in combined:
            print_error(f"No upstream branch configured for '{current}'")
            print(f"SUGGESTION: git push -u origin {current}")
            return EXIT_ERROR
        print_error(f"Pull failed: {err or out}")
        return EXIT_ERROR

    print(f"SUCCESS: Pull successful on '{current}'")
    if out:
        # Filter verbose output
        lines = out.split("\n")
        for line in lines[:10]:  # Limit output
            if line.strip():
                print(f"  {line}")
        if len(lines) > 10:
            print(f"  ... and {len(lines) - 10} more lines")
    return EXIT_SUCCESS


def merge(branch: str, no_ff: bool = False) -> int:
    """Merge a branch into current branch."""
    # Pre-flight checks
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if is_merge_in_progress():
        print_error("Another merge is already in progress. Complete or abort it first.")
        print("SUGGESTION: git_tools abort merge")
        return EXIT_ERROR

    if is_rebase_in_progress():
        print_error("Rebase in progress. Complete or abort it first.")
        return EXIT_ERROR

    current = get_current_branch()
    if not current:
        print_error("Cannot merge in detached HEAD state")
        return EXIT_ERROR

    # Check if branch exists
    if not branch_exists_locally(branch):
        # Try fetching from remote
        print(f"Branch '{branch}' not found locally. Fetching from remote...")
        ok, _, err = run_git(["fetch", "origin", branch], timeout=60)
        if not ok:
            print_error(f"Branch '{branch}' not found locally or remotely")
            return EXIT_ERROR
        branch = f"origin/{branch}"

    # Check for uncommitted changes
    if has_uncommitted_changes():
        print_error("Cannot merge with uncommitted changes. Commit or stash first.")
        return EXIT_DIRTY_WORKTREE

    print(f"Merging '{branch}' into '{current}'...")

    args = ["merge", branch]
    if no_ff:
        args.append("--no-ff")

    ok, out, err = run_git(args)
    if not ok:
        combined = f"{out} {err}".lower()
        if "conflict" in combined:
            # Get list of conflicting files
            ok2, files, _ = run_git(["diff", "--name-only", "--diff-filter=U"])
            print_error("CONFLICT during merge!")
            if files:
                print("Conflicting files:")
                for f in files.split("\n")[:10]:
                    if f.strip():
                        print(f"  - {f}")
            print("\nSUGGESTION: Resolve conflicts manually:")
            print("  1. Edit conflicting files")
            print("  2. git add <resolved-files>")
            print("  3. git commit")
            print("  OR abort with: git_tools abort merge")
            return EXIT_CONFLICT
        if "not something we can merge" in combined:
            print_error(f"Branch '{branch}' does not exist")
            return EXIT_ERROR
        if "already up to date" in combined:
            print("Already up to date - nothing to merge")
            return EXIT_SUCCESS
        print_error(f"Merge failed: {err or out}")
        return EXIT_ERROR

    print(f"SUCCESS: Merged '{branch}' into '{current}'")
    if out:
        # Show summary
        lines = [ln for ln in out.split("\n") if ln.strip()][:5]
        for line in lines:
            print(f"  {line}")
    return EXIT_SUCCESS


def push(force: bool = False, set_upstream: bool = False) -> int:
    """Push current branch to remote."""
    # Pre-flight checks
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if is_merge_in_progress():
        print_error("Merge in progress. Complete it before pushing.")
        return EXIT_ERROR

    if is_rebase_in_progress():
        print_error("Rebase in progress. Complete it before pushing.")
        return EXIT_ERROR

    branch = get_current_branch()
    if not branch:
        print_error("Cannot push in detached HEAD state")
        return EXIT_ERROR

    # Warning for force push to main/master
    if force and branch in ("main", "master"):
        print_warning(f"Force pushing to '{branch}' is dangerous!")

    args = ["push"]
    if force:
        args.append("--force-with-lease")  # Safer than --force
    if set_upstream:
        args.extend(["-u", "origin", branch])

    ok, out, err = run_git(args, timeout=180)  # Longer timeout for network
    if not ok:
        combined = f"{out} {err}".lower()

        # Check if we need to set upstream
        if "no upstream" in combined or "set-upstream" in combined:
            print(f"Setting upstream for branch '{branch}'...")
            ok, out, err = run_git(["push", "-u", "origin", branch], timeout=180)
            if not ok:
                print_error(f"Push failed: {err or out}")
                return EXIT_ERROR
        # Check for rejected push (remote has new commits)
        elif "rejected" in combined or "non-fast-forward" in combined:
            print_error("Push rejected - remote has newer commits")
            print("SUGGESTION: Pull first, then push:")
            print("  git_tools pull --rebase")
            print("  git_tools push")
            print("  OR force push (DANGEROUS): git_tools push --force")
            return EXIT_ERROR
        # Check for network errors
        elif "timeout" in combined:
            print_error("Network timeout. Check your connection.")
            return EXIT_NETWORK_ERROR
        elif "could not resolve" in combined or "unable to access" in combined:
            print_error(f"Network error: {err or out}")
            return EXIT_NETWORK_ERROR
        # Check for permission errors
        elif "permission denied" in combined or "403" in combined:
            print_error("Permission denied. Check your credentials.")
            return EXIT_ERROR
        else:
            print_error(f"Push failed: {err or out}")
            return EXIT_ERROR

    print(f"SUCCESS: Pushed branch '{branch}' to remote")
    return EXIT_SUCCESS


def status() -> int:
    """Show git status."""
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    # Show branch and tracking info
    ok, out, _ = run_git(["status", "--short", "--branch"])
    if not ok:
        print_error("Failed to get status")
        return EXIT_ERROR

    # Add context about in-progress operations
    if is_merge_in_progress():
        print("*** MERGE IN PROGRESS ***")
    if is_rebase_in_progress():
        print("*** REBASE IN PROGRESS ***")
    if is_detached_head():
        print("*** DETACHED HEAD ***")

    print(out if out else "Clean working tree")
    return EXIT_SUCCESS


def checkout(branch: str) -> int:
    """Checkout a branch."""
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if is_merge_in_progress():
        print_error("Merge in progress. Complete or abort it first.")
        return EXIT_ERROR

    if is_rebase_in_progress():
        print_error("Rebase in progress. Complete or abort it first.")
        return EXIT_ERROR

    # Try local checkout first
    ok, out, err = run_git(["checkout", branch])
    if ok:
        print(f"SUCCESS: Switched to branch '{branch}'")
        return EXIT_SUCCESS

    # Check if it's a dirty worktree issue
    combined = f"{out} {err}".lower()
    if "overwritten" in combined or "conflict" in combined:
        print_error("Cannot checkout: uncommitted changes would be overwritten")
        print("SUGGESTION: Commit or stash your changes first:")
        print("  git_tools commit -m 'WIP' --add-all")
        print("  # OR")
        print("  git_tools stash")
        return EXIT_DIRTY_WORKTREE

    # Maybe it's a remote branch - try tracking it
    if branch_exists_remotely(branch):
        print(f"Creating local branch '{branch}' tracking origin...")
        ok, out, err = run_git(["checkout", "-t", f"origin/{branch}"])
        if ok:
            print(f"SUCCESS: Switched to branch '{branch}' (tracking origin)")
            return EXIT_SUCCESS
        print_error(f"Failed to track remote branch: {err or out}")
        return EXIT_ERROR

    print_error(f"Branch '{branch}' not found locally or remotely")
    return EXIT_ERROR


def stash(action: str | None = None, message: str | None = None) -> int:
    """Manage git stash."""
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if action is None or action == "push":
        # Stash current changes
        if not has_uncommitted_changes():
            print("No local changes to stash")
            return EXIT_SUCCESS
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        ok, out, err = run_git(args)
        if not ok:
            print_error(f"Failed to stash: {err or out}")
            return EXIT_ERROR
        print("SUCCESS: Stashed changes")
        return EXIT_SUCCESS

    if action == "pop":
        ok, out, err = run_git(["stash", "pop"])
        if not ok:
            if "conflict" in f"{out} {err}".lower():
                print_error("Conflict when applying stash")
                print("SUGGESTION: Resolve conflicts, then drop the stash:")
                print("  git_tools stash drop")
                return EXIT_CONFLICT
            if "no stash" in f"{out} {err}".lower():
                print("No stash entries to pop")
                return EXIT_SUCCESS
            print_error(f"Failed to pop stash: {err or out}")
            return EXIT_ERROR
        print("SUCCESS: Applied and removed top stash")
        return EXIT_SUCCESS

    if action == "list":
        ok, out, _ = run_git(["stash", "list"])
        if out:
            print("Stash entries:")
            for line in out.split("\n")[:10]:
                print(f"  {line}")
        else:
            print("No stash entries")
        return EXIT_SUCCESS

    if action == "drop":
        ok, out, err = run_git(["stash", "drop"])
        if not ok:
            if "no stash" in f"{out} {err}".lower():
                print("No stash entries to drop")
                return EXIT_SUCCESS
            print_error(f"Failed to drop stash: {err or out}")
            return EXIT_ERROR
        print("SUCCESS: Dropped top stash entry")
        return EXIT_SUCCESS

    print_error(f"Unknown stash action: {action}")
    print("Valid actions: push, pop, list, drop")
    return EXIT_ERROR


def abort(operation: str) -> int:
    """Abort a merge, rebase, or cherry-pick."""
    if not is_git_repo():
        print_error("Not a git repository")
        return EXIT_ERROR

    if operation == "merge":
        if not is_merge_in_progress():
            print("No merge in progress to abort")
            return EXIT_SUCCESS
        ok, out, err = run_git(["merge", "--abort"])
        if not ok:
            print_error(f"Failed to abort merge: {err or out}")
            return EXIT_ERROR
        print("SUCCESS: Merge aborted")
        return EXIT_SUCCESS

    if operation == "rebase":
        if not is_rebase_in_progress():
            print("No rebase in progress to abort")
            return EXIT_SUCCESS
        ok, out, err = run_git(["rebase", "--abort"])
        if not ok:
            print_error(f"Failed to abort rebase: {err or out}")
            return EXIT_ERROR
        print("SUCCESS: Rebase aborted")
        return EXIT_SUCCESS

    if operation == "cherry-pick":
        ok, out, err = run_git(["cherry-pick", "--abort"])
        if not ok:
            if "no cherry-pick" in f"{out} {err}".lower():
                print("No cherry-pick in progress to abort")
                return EXIT_SUCCESS
            print_error(f"Failed to abort cherry-pick: {err or out}")
            return EXIT_ERROR
        print("SUCCESS: Cherry-pick aborted")
        return EXIT_SUCCESS

    print_error(f"Unknown operation to abort: {operation}")
    print("Valid operations: merge, rebase, cherry-pick")
    return EXIT_ERROR


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Git tools for AI agents - robust git operations with error handling",
        epilog="Exit codes: 0=success, 1=error, 2=conflict, 3=dirty worktree, 4=network error",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # create-branch
    p_branch = subparsers.add_parser(
        "create-branch", help="Create a new branch from base (default: main)"
    )
    p_branch.add_argument("name", help="Branch name to create")
    p_branch.add_argument("--from", dest="base", default="main", help="Base branch (default: main)")

    # commit
    p_commit = subparsers.add_parser("commit", help="Create a commit")
    p_commit.add_argument("-m", "--message", required=True, help="Commit message")
    p_commit.add_argument("--add-all", action="store_true", help="Stage all changes before commit")

    # pull
    p_pull = subparsers.add_parser("pull", help="Pull latest changes from remote")
    p_pull.add_argument("--rebase", action="store_true", help="Use rebase instead of merge")

    # merge
    p_merge = subparsers.add_parser("merge", help="Merge a branch into current branch")
    p_merge.add_argument("branch", help="Branch to merge")
    p_merge.add_argument(
        "--no-ff", action="store_true", help="Create merge commit even if fast-forward"
    )

    # push
    p_push = subparsers.add_parser("push", help="Push current branch to remote")
    p_push.add_argument("--force", action="store_true", help="Force push (uses --force-with-lease)")
    p_push.add_argument("-u", "--set-upstream", action="store_true", help="Set upstream")

    # status
    subparsers.add_parser("status", help="Show repository status")

    # checkout
    p_checkout = subparsers.add_parser("checkout", help="Checkout a branch")
    p_checkout.add_argument("branch", help="Branch name to checkout")

    # stash
    p_stash = subparsers.add_parser("stash", help="Manage git stash")
    p_stash.add_argument(
        "action",
        nargs="?",
        choices=["push", "pop", "list", "drop"],
        default="push",
        help="Stash action (default: push)",
    )
    p_stash.add_argument("-m", "--message", help="Stash message (for push)")

    # abort
    p_abort = subparsers.add_parser("abort", help="Abort a merge, rebase, or cherry-pick")
    p_abort.add_argument(
        "operation",
        choices=["merge", "rebase", "cherry-pick"],
        help="Operation to abort",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return EXIT_ERROR

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
    if args.command == "stash":
        return stash(args.action, getattr(args, "message", None))
    if args.command == "abort":
        return abort(args.operation)

    parser.print_help()
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
