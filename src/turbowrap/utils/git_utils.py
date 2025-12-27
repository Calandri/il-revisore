"""Git operations utilities."""

import hashlib
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from ..config import get_settings
from ..exceptions import CloneError, RepositoryError, SyncError

logger = logging.getLogger(__name__)


def _get_git_env() -> dict[str, str]:
    """Get environment with git terminal prompts disabled."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    return env


class GitStatus(BaseModel):
    """Git repository status."""

    model_config = ConfigDict(frozen=True)

    branch: str = Field(..., min_length=1, description="Current branch name")
    is_clean: bool = Field(..., description="True if working directory is clean")
    ahead: int = Field(default=0, ge=0, description="Commits ahead of remote")
    behind: int = Field(default=0, ge=0, description="Commits behind remote")
    modified: list[str] = Field(default_factory=list, description="Modified files")
    untracked: list[str] = Field(default_factory=list, description="Untracked files")

    @property
    def has_changes(self) -> bool:
        """Check if there are any local changes."""
        return not self.is_clean or self.ahead > 0


class GitHubRepo(BaseModel):
    """Parsed GitHub repository info."""

    model_config = ConfigDict(frozen=True)

    owner: str = Field(..., min_length=1, max_length=100, description="Repository owner")
    name: str = Field(..., min_length=1, max_length=100, description="Repository name")
    full_name: str = Field(..., description="Full name (owner/name)")
    url: str = Field(..., description="HTTPS clone URL")

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str, info: ValidationInfo) -> str:
        """Ensure full_name matches owner/name format."""
        if "/" not in v:
            raise ValueError("full_name must be in format 'owner/name'")
        return v


def parse_github_url(url: str) -> GitHubRepo:
    """Parse GitHub URL to extract owner and repo name.

    Args:
        url: GitHub URL (https or git@).

    Returns:
        GitHubRepo with parsed info.

    Raises:
        RepositoryError: If URL is invalid.
    """
    # HTTPS: https://github.com/owner/repo.git
    # SSH: git@github.com:owner/repo.git
    patterns = [
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
        r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
    ]

    for pattern in patterns:
        match = re.match(pattern, url.strip())
        if match:
            owner, name = match.groups()
            return GitHubRepo(
                owner=owner,
                name=name,
                full_name=f"{owner}/{name}",
                url=f"https://github.com/{owner}/{name}.git",
            )

    raise RepositoryError(f"Invalid GitHub URL: {url}")


def get_repo_hash(url: str) -> str:
    """Generate a unique hash for repository URL.

    Args:
        url: Repository URL.

    Returns:
        Short hash string.
    """
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def get_local_path(url: str) -> Path:
    """Get local path for cloned repository.

    Args:
        url: Repository URL.

    Returns:
        Path where repo should be cloned.
    """
    settings = get_settings()
    repo_info = parse_github_url(url)
    repo_hash = get_repo_hash(url)
    return settings.repos_dir / f"{repo_info.name}-{repo_hash}"


def _get_auth_url(url: str, token: str | None = None) -> str:
    """Build authenticated URL if token provided.

    Args:
        url: GitHub repository URL.
        token: Optional GitHub token.

    Returns:
        URL with embedded token or original URL.
    """
    if not token:
        return url

    # Strip any existing token from URL first
    # Handles: https://ghp_xxx@github.com/... or https://github.com/...
    clean_url = re.sub(r"https://[^@]+@github\.com/", "https://github.com/", url)

    # Convert https://github.com/owner/repo.git to https://token@github.com/owner/repo.git
    if clean_url.startswith("https://github.com/"):
        return clean_url.replace("https://github.com/", f"https://{token}@github.com/")
    return url


def clone_repo(
    url: str,
    branch: str = "main",
    token: str | None = None,
    target_path: Path | None = None,
) -> Path:
    """Clone a GitHub repository.

    Args:
        url: GitHub repository URL.
        branch: Branch to clone.
        token: Optional GitHub token for private repos.
        target_path: Optional explicit path to clone to. If not provided,
                     uses get_local_path(url) to generate a path.

    Returns:
        Path to cloned repository.

    Raises:
        CloneError: If clone fails.
    """
    local_path = target_path if target_path else get_local_path(url)

    if local_path.exists():
        # Already cloned, just pull
        return pull_repo(local_path, token)

    local_path.parent.mkdir(parents=True, exist_ok=True)

    # Use authenticated URL if token provided
    clone_url = _get_auth_url(url, token)

    try:
        subprocess.run(
            ["git", "clone", "--branch", branch, "--single-branch", clone_url, str(local_path)],
            check=True,
            capture_output=True,
            text=True,
            env=_get_git_env(),
        )
        return local_path
    except subprocess.CalledProcessError as e:
        # Mask token in error message
        error_msg = e.stderr.replace(token, "***") if token else e.stderr
        if "Authentication failed" in error_msg or "could not read Username" in error_msg:
            raise CloneError(
                "Git authentication failed. Configure credentials with: "
                "git config --global credential.helper osxkeychain"
            ) from e
        raise CloneError(f"Failed to clone {url}: {error_msg}") from e


def pull_repo(repo_path: Path, token: str | None = None) -> Path:
    """Pull latest changes for a repository.

    Args:
        repo_path: Path to local repository.
        token: Optional GitHub token for private repos.

    Returns:
        Repository path.

    Raises:
        SyncError: If pull fails.
    """
    if not repo_path.exists():
        raise SyncError(f"Repository not found: {repo_path}")

    git_env = _get_git_env()
    try:
        # If token provided, temporarily update remote URL
        if token:
            # Get current remote URL
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            )
            original_url = result.stdout.strip()
            auth_url = _get_auth_url(original_url, token)

            # Temporarily set authenticated URL
            subprocess.run(
                ["git", "remote", "set-url", "origin", auth_url],
                cwd=repo_path,
                check=True,
                capture_output=True,
                env=git_env,
            )

        try:
            subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            )
        finally:
            # Restore clean URL (strip any token for security)
            if token:
                # Strip any token from URL before restoring
                clean_url = re.sub(
                    r"https://[^@]+@github\.com/", "https://github.com/", original_url
                )
                subprocess.run(
                    ["git", "remote", "set-url", "origin", clean_url],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    env=git_env,
                )

        return repo_path
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.replace(token, "***") if token else e.stderr
        if "Authentication failed" in error_msg or "could not read Username" in error_msg:
            raise SyncError(
                "Git authentication failed. Configure credentials with: "
                "git config --global credential.helper osxkeychain"
            ) from e
        raise SyncError(f"Failed to pull: {error_msg}") from e


def push_repo(repo_path: Path, message: str = "Update") -> None:
    """Push changes to remote.

    Args:
        repo_path: Path to local repository.
        message: Commit message.

    Raises:
        SyncError: If push fails.
    """
    if not repo_path.exists():
        raise SyncError(f"Repository not found: {repo_path}")

    git_env = _get_git_env()
    try:
        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            env=git_env,
        )

        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_path,
            check=True,
            capture_output=True,
            env=git_env,
        )

        # Push
        subprocess.run(
            ["git", "push"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            env=git_env,
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else "Unknown error"
        if "Authentication failed" in error_msg or "could not read Username" in error_msg:
            raise SyncError(
                "Git authentication failed. Configure credentials with: "
                "git config --global credential.helper osxkeychain"
            ) from e
        raise SyncError(f"Failed to push: {error_msg}") from e


async def smart_push_with_conflict_resolution(
    repo_path: Path,
    message: str = "Update via TurboWrap",
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Smart push that uses Claude CLI to resolve conflicts if needed.

    Flow:
    1. Stage and commit local changes
    2. Pull from remote
    3. If conflicts, launch Claude CLI to resolve them
    4. Push to remote

    Args:
        repo_path: Path to local repository.
        message: Commit message.
        api_key: Anthropic API key (optional, uses env if not provided).

    Returns:
        dict with status and details.
    """
    import asyncio
    import os

    result: dict[str, Any] = {
        "status": "success",
        "had_conflicts": False,
        "claude_resolved": False,
        "message": "",
    }

    if not repo_path.exists():
        raise SyncError(f"Repository not found: {repo_path}")

    git_env = _get_git_env()
    try:
        # 1. Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            env=git_env,
        )

        # 2. Commit (may fail if nothing to commit - that's ok)
        try:
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path,
                check=True,
                capture_output=True,
                env=git_env,
            )
        except subprocess.CalledProcessError:
            # Nothing to commit, continue anyway
            pass

        # 3. Pull with rebase to get remote changes
        pull_result = subprocess.run(
            ["git", "pull", "--no-rebase"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            env=git_env,
        )

        # 4. Check for conflicts
        if pull_result.returncode != 0 or "CONFLICT" in pull_result.stdout:
            result["had_conflicts"] = True

            # Check if there are actual conflict markers
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                env=git_env,
            )

            # UU = unmerged, both modified (conflict)
            has_conflicts = any(
                line.startswith("UU") or line.startswith("AA")
                for line in status_result.stdout.split("\n")
                if line.strip()
            )

            if has_conflicts:
                # Launch Claude CLI to resolve conflicts
                env = os.environ.copy()
                if api_key:
                    env["ANTHROPIC_API_KEY"] = api_key

                resolve_prompt = """You have merge conflicts to resolve. Please:

1. Read the conflicted files using git status
2. For each conflicted file, read it and resolve the conflict markers (<<<<<<<, =======, >>>>>>>)
3. Keep the best parts of both versions, or merge them logically
4. After resolving, run: git add <file> for each resolved file
5. Then commit with: git commit -m "Merge conflicts resolved"

Important: Output ONLY the commands you ran and a brief summary. No explanations needed."""

                process = await asyncio.create_subprocess_exec(
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(repo_path),
                    env=env,
                )

                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=resolve_prompt.encode()),
                    timeout=120,  # 2 minutes max
                )

                if process.returncode == 0:
                    result["claude_resolved"] = True
                    result["message"] = "Conflicts resolved by Claude"
                else:
                    raise SyncError(f"Claude failed to resolve conflicts: {stderr.decode()}")

        # 5. Push (with -u to set upstream if needed)
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            env=git_env,
        )

        result["message"] = "Push successful" + (
            " (conflicts resolved)" if result["claude_resolved"] else ""
        )
        return result

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else "Unknown error"
        if "Authentication failed" in error_msg or "could not read Username" in error_msg:
            raise SyncError(
                "Git authentication failed. Configure credentials with: "
                "git config --global credential.helper osxkeychain"
            ) from e
        raise SyncError(f"Failed to push: {error_msg}") from e


def get_current_branch(repo_path: Path) -> str:
    """Get current branch name.

    Args:
        repo_path: Path to repository.

    Returns:
        Branch name.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            env=_get_git_env(),
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def get_repo_status(repo_path: Path) -> GitStatus:
    """Get repository status.

    Args:
        repo_path: Path to repository.

    Returns:
        GitStatus object.
    """
    branch = get_current_branch(repo_path)

    try:
        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            env=_get_git_env(),
        )
        is_clean = len(result.stdout.strip()) == 0

        # Parse modified/untracked
        modified = []
        untracked = []
        for line in result.stdout.strip().split("\n"):
            if line:
                status = line[:2]
                filepath = line[2:].lstrip()
                if status.startswith("?"):
                    # Check if it's a directory - if so, list files inside
                    full_path = repo_path / filepath
                    if full_path.is_dir():
                        # Expand directory to show individual files
                        for child in full_path.rglob("*"):
                            if child.is_file():
                                rel_path = str(child.relative_to(repo_path))
                                untracked.append(rel_path)
                    else:
                        untracked.append(filepath)
                else:
                    modified.append(filepath)

        return GitStatus(
            branch=branch,
            is_clean=is_clean,
            modified=modified,
            untracked=untracked,
        )
    except subprocess.CalledProcessError:
        return GitStatus(branch=branch, is_clean=True, modified=[], untracked=[])


# =============================================================================
# Classes merged from review/utils/git_utils.py
# =============================================================================


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


class RepoGitUtils:
    """Git utility functions for repository operations.

    This class provides git operations on a specific repository path.
    Use for diff analysis, commit info, PR parsing, etc.
    """

    def __init__(self, repo_path: str | Path | None = None):
        """
        Initialize RepoGitUtils.

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
            env=_get_git_env(),
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            # Detect auth errors
            if "Authentication failed" in error_msg or "could not read Username" in error_msg:
                raise RuntimeError(
                    "Git authentication failed. Configure credentials with: "
                    "git config --global credential.helper osxkeychain"
                )
            raise RuntimeError(f"Git command failed: {error_msg}")
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


# Backwards compatibility alias
GitUtils = RepoGitUtils
