"""
Git utilities for TurboWrap.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PRInfo:
    """Information about a Pull Request."""

    owner: str
    repo: str
    number: int
    url: str


@dataclass
class CommitInfo:
    """Information about a commit."""

    sha: str
    short_sha: str
    author: str
    email: str
    message: str
    date: str


class GitUtils:
    """Git utility functions."""

    def __init__(self, repo_path: str | Path | None = None):
        """
        Initialize GitUtils.

        Args:
            repo_path: Path to git repository (defaults to cwd)
        """
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()

    def _run_git(self, *args: str) -> str:
        """Run a git command and return output."""
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Git command failed: {result.stderr}")
        return result.stdout.strip()

    def get_changed_files(
        self,
        base_ref: str | None = None,
        head_ref: str = "HEAD",
    ) -> list[str]:
        """
        Get list of changed files between refs.

        Args:
            base_ref: Base reference (branch/commit), defaults to merge-base with main
            head_ref: Head reference, defaults to HEAD

        Returns:
            List of changed file paths
        """
        if base_ref is None:
            # Find merge base with main/master
            try:
                base_ref = self._run_git("merge-base", "main", head_ref)
            except RuntimeError:
                try:
                    base_ref = self._run_git("merge-base", "master", head_ref)
                except RuntimeError:
                    # Fall back to comparing with HEAD~1
                    base_ref = f"{head_ref}~1"

        output = self._run_git("diff", "--name-only", base_ref, head_ref)
        return output.split("\n") if output else []

    def get_diff(
        self,
        base_ref: str | None = None,
        head_ref: str = "HEAD",
        files: list[str] | None = None,
    ) -> str:
        """
        Get diff between refs.

        Args:
            base_ref: Base reference
            head_ref: Head reference
            files: Specific files to diff

        Returns:
            Diff output
        """
        args = ["diff", base_ref or "HEAD~1", head_ref]
        if files:
            args.extend(["--", *files])
        return self._run_git(*args)

    def get_file_content(self, file_path: str, ref: str = "HEAD") -> str:
        """
        Get file content at specific ref.

        Args:
            file_path: Path to file
            ref: Git reference

        Returns:
            File content
        """
        return self._run_git("show", f"{ref}:{file_path}")

    def get_current_branch(self) -> str:
        """Get current branch name."""
        return self._run_git("branch", "--show-current")

    def get_current_commit(self) -> CommitInfo:
        """Get current commit info."""
        format_str = "%H|%h|%an|%ae|%s|%ci"
        output = self._run_git("log", "-1", f"--format={format_str}")
        parts = output.split("|")
        return CommitInfo(
            sha=parts[0],
            short_sha=parts[1],
            author=parts[2],
            email=parts[3],
            message=parts[4],
            date=parts[5],
        )

    def get_repo_name(self) -> str:
        """Get repository name from remote URL."""
        try:
            remote_url = self._run_git("remote", "get-url", "origin")
            # Handle SSH and HTTPS URLs
            match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", remote_url)
            if match:
                return match.group(1)
        except RuntimeError:
            pass
        return self.repo_path.name

    def is_git_repo(self) -> bool:
        """Check if current directory is a git repository."""
        try:
            self._run_git("rev-parse", "--git-dir")
            return True
        except RuntimeError:
            return False

    @staticmethod
    def parse_pr_url(url: str) -> PRInfo | None:
        """
        Parse a GitHub PR URL.

        Args:
            url: GitHub PR URL

        Returns:
            PRInfo or None if invalid URL
        """
        # Match patterns like:
        # https://github.com/owner/repo/pull/123
        # https://github.com/owner/repo/pull/123/files
        match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)",
            url,
        )
        if match:
            return PRInfo(
                owner=match.group(1),
                repo=match.group(2),
                number=int(match.group(3)),
                url=url,
            )
        return None

    def get_staged_files(self) -> list[str]:
        """Get list of staged files."""
        output = self._run_git("diff", "--cached", "--name-only")
        return output.split("\n") if output else []

    def get_untracked_files(self) -> list[str]:
        """Get list of untracked files."""
        output = self._run_git("ls-files", "--others", "--exclude-standard")
        return output.split("\n") if output else []
