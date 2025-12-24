"""Git utilities for the Fix Issue system."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Git operation error."""

    pass


class GitUtils:
    """Git operations for fix workflow."""

    def __init__(self, repo_path: Path):
        """Initialize with repository path."""
        self.repo_path = repo_path

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git command."""
        cmd = ["git", *args]
        try:
            return subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=check,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Git command failed: {' '.join(cmd)}")
            logger.error(f"stderr: {e.stderr}")
            raise GitError(f"Git command failed: {e.stderr}") from e

    def get_current_branch(self) -> str:
        """Get current branch name."""
        result = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def branch_exists(self, branch_name: str) -> bool:
        """Check if branch exists."""
        result = self._run_git("branch", "--list", branch_name, check=False)
        return bool(result.stdout.strip())

    def create_branch(self, branch_name: str, from_branch: str | None = None) -> str:
        """
        Create and checkout a new branch.

        Args:
            branch_name: Name of the new branch
            from_branch: Base branch (defaults to current)

        Returns:
            Name of created branch
        """
        if self.branch_exists(branch_name):
            logger.info(f"Branch {branch_name} already exists, checking out")
            self._run_git("checkout", branch_name)
        else:
            if from_branch:
                self._run_git("checkout", "-b", branch_name, from_branch)
            else:
                self._run_git("checkout", "-b", branch_name)
            logger.info(f"Created and checked out branch: {branch_name}")

        return branch_name

    def checkout_branch(self, branch_name: str) -> None:
        """Checkout an existing branch."""
        self._run_git("checkout", branch_name)
        logger.info(f"Checked out branch: {branch_name}")

    def has_uncommitted_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        result = self._run_git("status", "--porcelain")
        return bool(result.stdout.strip())

    def stage_file(self, file_path: str) -> None:
        """Stage a file for commit."""
        self._run_git("add", file_path)
        logger.info(f"Staged file: {file_path}")

    def commit(self, message: str) -> str:
        """
        Create a commit with the given message.

        Returns:
            Commit SHA
        """
        self._run_git("commit", "-m", message)
        result = self._run_git("rev-parse", "HEAD")
        sha = result.stdout.strip()
        logger.info(f"Created commit: {sha[:8]} - {message}")
        return sha

    def get_file_diff(self, file_path: str, staged: bool = False) -> str:
        """Get diff for a file."""
        args = ["diff"]
        if staged:
            args.append("--staged")
        args.append(file_path)
        result = self._run_git(*args, check=False)
        return result.stdout

    def stage_all(self) -> None:
        """Stage all changes for commit."""
        self._run_git("add", "-A")
        logger.info("Staged all changes")

    def get_diff(self, staged: bool = True) -> str:
        """
        Get diff of all changes.

        Args:
            staged: If True, get diff of staged changes. Otherwise working tree.

        Returns:
            Diff as string
        """
        args = ["diff"]
        if staged:
            args.append("--staged")
        result = self._run_git(*args, check=False)
        return result.stdout

    def get_diff_stat(self, staged: bool = True) -> str:
        """Get diff stats (files changed, insertions, deletions)."""
        args = ["diff", "--stat"]
        if staged:
            args.append("--staged")
        result = self._run_git(*args, check=False)
        return result.stdout

    def discard_all_changes(self) -> None:
        """Discard all uncommitted changes."""
        # Discard staged changes
        self._run_git("reset", "HEAD", check=False)
        # Discard working tree changes
        self._run_git("checkout", "--", ".", check=False)
        # Remove untracked files
        self._run_git("clean", "-fd", check=False)
        logger.info("Discarded all uncommitted changes")

    def stash_changes(self, message: str | None = None) -> bool:
        """
        Stash uncommitted changes.

        Returns:
            True if changes were stashed, False if nothing to stash
        """
        if not self.has_uncommitted_changes():
            return False

        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        self._run_git(*args)
        logger.info("Stashed uncommitted changes")
        return True

    def stash_pop(self) -> None:
        """Pop the latest stash."""
        self._run_git("stash", "pop")
        logger.info("Popped stash")

    def get_remote_url(self) -> str | None:
        """Get the remote origin URL."""
        result = self._run_git("remote", "get-url", "origin", check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def push_branch(self, branch_name: str, set_upstream: bool = True) -> None:
        """Push branch to remote."""
        args = ["push"]
        if set_upstream:
            args.extend(["-u", "origin", branch_name])
        else:
            args.extend(["origin", branch_name])
        self._run_git(*args)
        logger.info(f"Pushed branch: {branch_name}")


def generate_fix_branch_name(task_id: str) -> str:
    """
    Generate branch name for fix session.

    Format: fix/<task_id>
    """
    # Sanitize task_id (remove special chars, truncate)
    safe_id = "".join(c if c.isalnum() or c == "-" else "-" for c in task_id)
    safe_id = safe_id[:20]  # Truncate to reasonable length
    return f"fix/{safe_id}"


def generate_commit_message(issue_code: str, title: str) -> str:
    """
    Generate commit message for a fix.

    Format: [FIX] BE-CRIT-001: Issue title
    """
    # Truncate title if too long
    max_title_len = 60
    if len(title) > max_title_len:
        title = title[: max_title_len - 3] + "..."

    return f"[FIX] {issue_code}: {title}"
