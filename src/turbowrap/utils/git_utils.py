"""Git operations utilities."""

import hashlib
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field, ConfigDict, field_validator

from ..config import get_settings
from ..exceptions import CloneError, SyncError, RepositoryError


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
    def validate_full_name(cls, v: str, info) -> str:
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

    # Convert https://github.com/owner/repo.git to https://token@github.com/owner/repo.git
    if url.startswith("https://github.com/"):
        return url.replace("https://github.com/", f"https://{token}@github.com/")
    return url


def clone_repo(url: str, branch: str = "main", token: str | None = None) -> Path:
    """Clone a GitHub repository.

    Args:
        url: GitHub repository URL.
        branch: Branch to clone.
        token: Optional GitHub token for private repos.

    Returns:
        Path to cloned repository.

    Raises:
        CloneError: If clone fails.
    """
    local_path = get_local_path(url)

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
        )
        return local_path
    except subprocess.CalledProcessError as e:
        # Mask token in error message
        error_msg = e.stderr.replace(token, "***") if token else e.stderr
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
            )
            original_url = result.stdout.strip()
            auth_url = _get_auth_url(original_url, token)

            # Temporarily set authenticated URL
            subprocess.run(
                ["git", "remote", "set-url", "origin", auth_url],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

        try:
            subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            # Restore original URL (without token) for security
            if token:
                subprocess.run(
                    ["git", "remote", "set-url", "origin", original_url],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                )

        return repo_path
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.replace(token, "***") if token else e.stderr
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

    try:
        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Push
        subprocess.run(
            ["git", "push"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise SyncError(f"Failed to push: {e.stderr}") from e


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
        )
        is_clean = len(result.stdout.strip()) == 0

        # Parse modified/untracked
        modified = []
        untracked = []
        for line in result.stdout.strip().split("\n"):
            if line:
                status = line[:2]
                filepath = line[3:]
                if status.startswith("?"):
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
