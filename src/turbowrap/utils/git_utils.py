"""Git operations utilities."""

import hashlib
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from ..config import get_settings
from ..exceptions import CloneError, RepositoryError, SyncError

logger = logging.getLogger(__name__)


class GitStatus(BaseModel):
    """Git repository status."""

    model_config = ConfigDict(frozen=True)

    branch: str = Field(..., min_length=1, description="Current branch name")
    is_clean: bool = Field(..., description="True if working directory is clean")
    ahead: int = Field(default=0, ge=0, description="Commits ahead of remote")
    behind: int = Field(default=0, ge=0, description="Commits behind remote")
    modified: list[str] = Field(default_factory=list, description="Modified files (unstaged)")
    staged: list[str] = Field(default_factory=list, description="Staged files")
    untracked: list[str] = Field(default_factory=list, description="Untracked files")

    @property
    def has_changes(self) -> bool:
        """Check if there are any local changes."""
        return not self.is_clean or self.ahead > 0


class CommitInfo(BaseModel):
    """Git commit information for API responses."""

    sha: str
    message: str
    author: str
    date: str
    pushed: bool = True  # True if commit exists on remote


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


@dataclass
class GitOperationResult:
    """Result of a complex git operation (merge/smart push)."""

    success: bool
    message: str
    output: str | None = None
    ai_resolved: bool = False


def _get_git_env() -> dict[str, str]:
    """Get environment with git terminal prompts disabled."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    return env


def run_git_command(
    repo_path: Path,
    command: list[str],
    timeout: int = 60,
    check: bool = True,
    capture_output: bool = True,
) -> str:
    """Run a git command in the repository directory with robust handling.

    Args:
        repo_path: Path to the repository
        command: Git command as list (e.g., ['branch', '--show-current'])
        timeout: Command timeout in seconds
        check: If True, raise exception on non-zero exit code
        capture_output: If True, return stdout.

    Returns:
        Command output as string (if capture_output=True)

    Raises:
        RuntimeError: If command fails and check=True
    """
    try:
        env = _get_git_env()
        # Ensure 'git' is part of command if not already
        full_cmd = ["git"] + command if command[0] != "git" else command

        result = subprocess.run(
            full_cmd,
            cwd=repo_path,
            capture_output=capture_output,
            text=True,
            check=check,
            timeout=timeout,
            env=env,
        )
        return result.stdout.rstrip() if capture_output and result.stdout else ""

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else "Unknown error"
        error_msg = re.sub(r"https://[^@]+@", "https://***@", error_msg)

        if "Authentication failed" in error_msg or "could not read Username" in error_msg:
            raise SyncError(
                "Git authentication failed. Configure credentials with: "
                "git config --global credential.helper osxkeychain"
            ) from e

        if check:
            raise RuntimeError(f"Git command failed: {error_msg}") from e
        return ""

    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Git command timed out after {timeout}s: {' '.join(command)}") from e


def parse_github_url(url: str) -> GitHubRepo:
    """Parse GitHub URL to extract owner and repo name.

    Args:
        url: GitHub URL (https or git@).

    Returns:
        GitHubRepo with parsed info.
    """
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


def get_repo_hash(url: str, workspace_path: str | None = None) -> str:
    """Generate a unique hash for repository URL and optional workspace.

    Args:
        url: Repository URL.
        workspace_path: Optional workspace path for monorepos.

    Returns:
        Short hash string.
    """
    # Include workspace_path in hash to generate unique paths for monorepo apps
    hash_input = url
    if workspace_path:
        hash_input = f"{url}::{workspace_path}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:12]


def get_local_path(url: str, workspace_path: str | None = None) -> Path:
    """Get local path for cloned repository.

    Args:
        url: Repository URL.
        workspace_path: Optional workspace path for monorepos.
                       When provided, generates a unique folder for each workspace.

    Returns:
        Path where repo should be cloned.
    """
    settings = get_settings()
    try:
        repo_info = parse_github_url(url)
        repo_hash = get_repo_hash(url, workspace_path)
        # Include sanitized workspace in folder name for clarity
        if workspace_path:
            # Replace / with - for folder name (e.g., apps/helpdesk -> apps-helpdesk)
            ws_suffix = workspace_path.replace("/", "-").replace("\\", "-")
            return settings.repos_dir / f"{repo_info.name}-{ws_suffix}-{repo_hash}"
        return settings.repos_dir / f"{repo_info.name}-{repo_hash}"
    except RepositoryError:
        # Fallback for non-github URLs
        repo_hash = get_repo_hash(url, workspace_path)
        return settings.repos_dir / f"repo-{repo_hash}"


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

    clean_url = re.sub(r"https://[^@]+@github\.com/", "https://github.com/", url)

    # Convert https://github.com/owner/repo.git to https://token@github.com/owner/repo.git
    if clean_url.startswith("https://github.com/"):
        return clean_url.replace("https://github.com/", f"https://{token}@github.com/")
    return url


def get_default_branch(url: str, token: str | None = None) -> str:
    """Detect the default branch of a remote repository.

    Uses `git ls-remote --symref` to find the HEAD reference.

    Args:
        url: GitHub repository URL.
        token: Optional GitHub token for private repos.

    Returns:
        Default branch name (e.g., 'main', 'master').
        Falls back to 'main' if detection fails.
    """
    auth_url = _get_auth_url(url, token)

    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", auth_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_get_git_env(),
        )

        if result.returncode == 0:
            # Output format: "ref: refs/heads/master\tHEAD"
            for line in result.stdout.splitlines():
                if line.startswith("ref: refs/heads/"):
                    branch = line.split("ref: refs/heads/")[1].split()[0]
                    logger.info(f"Detected default branch for {url}: {branch}")
                    return branch

        logger.warning(f"Could not detect default branch for {url}, falling back to 'main'")
        return "main"

    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        logger.warning(f"Error detecting default branch for {url}: {e}, falling back to 'main'")
        return "main"


def install_git_hooks(repo_path: Path, api_base_url: str = "http://localhost:8000") -> None:
    """Install git hooks to notify the UI on git operations.

    Installs hooks for:
    - post-commit: after local commits
    - post-merge: after git pull/merge
    - post-checkout: after branch change
    - post-rewrite: after rebase/amend

    Args:
        repo_path: Path to the git repository.
        api_base_url: Base URL for the API server.
    """
    hooks_dir = repo_path / ".git" / "hooks"
    if not hooks_dir.exists():
        logger.warning(f"Hooks dir not found: {hooks_dir}")
        return

    # Hook script template - calls the API to notify UI
    hook_template = f"""#!/bin/sh
# TurboWrap git hook - auto-installed
# Notifies the UI when git operations occur
curl -s -X POST "{api_base_url}/api/git/notify?event_type=$1&repo_path={repo_path}" > /dev/null 2>&1 &
"""

    hooks_to_install = {
        "post-commit": "commit",
        "post-merge": "merge",
        "post-checkout": "checkout",
        "post-rewrite": "rewrite",
    }

    for hook_name, event_type in hooks_to_install.items():
        hook_path = hooks_dir / hook_name
        hook_content = hook_template.replace("$1", event_type)

        # Don't overwrite existing hooks, append instead
        if hook_path.exists():
            existing_content = hook_path.read_text()
            if "TurboWrap git hook" in existing_content:
                continue  # Already installed
            # Append to existing hook
            hook_content = existing_content.rstrip() + "\n\n" + hook_content
        else:
            hook_content = hook_content

        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)  # Make executable

    logger.info(f"[GitHooks] Installed hooks in {repo_path}")


def clone_repo(
    url: str,
    branch: str = "main",
    token: str | None = None,
    target_path: Path | None = None,
    workspace_path: str | None = None,
) -> Path:
    """Clone a GitHub repository.

    Args:
        url: GitHub repository URL.
        branch: Branch to clone. If "main" (default), auto-detects the default branch.
        token: Optional GitHub token.
        target_path: Optional explicit code path.
        workspace_path: Optional workspace path for monorepos.
                       Creates a separate clone folder for each workspace.

    Returns:
        Path to cloned repository.
    """
    local_path = target_path if target_path else get_local_path(url, workspace_path)

    if local_path.exists():
        return pull_repo(local_path, token)

    local_path.parent.mkdir(parents=True, exist_ok=True)

    clone_url = _get_auth_url(url, token)

    # Auto-detect default branch when using the default "main"
    effective_branch = branch
    if branch == "main":
        detected_branch = get_default_branch(url, token)
        if detected_branch != "main":
            logger.info(f"Auto-detected default branch '{detected_branch}' for {url}")
            effective_branch = detected_branch

    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                effective_branch,
                "--single-branch",
                clone_url,
                str(local_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=_get_git_env(),
        )
        # Install git hooks for UI notifications
        install_git_hooks(local_path)
        return local_path
    except subprocess.CalledProcessError as e:
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
    original_url = None

    try:
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
            if token and original_url:
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
        auth_errors = [
            "Authentication failed",
            "could not read Username",
            "could not read Password",
            "terminal prompts disabled",
            "Invalid username or password",
            "Bad credentials",
        ]
        if any(err in error_msg for err in auth_errors):
            raise SyncError(
                "TOKEN_EXPIRED: GitHub token scaduto o non valido. "
                "Rigenerare il token in Settings > Developer settings > Personal access tokens"
            ) from e
        raise SyncError(f"Failed to pull: {error_msg}") from e


def push_repo(repo_path: Path, message: str = "Update") -> None:
    """Push changes to remote.

    Args:
        repo_path: Path to local repository.
        message: Commit message.
    """
    if not repo_path.exists():
        raise SyncError(f"Repository not found: {repo_path}")

    try:
        run_git_command(repo_path, ["add", "-A"])
        try:
            run_git_command(repo_path, ["commit", "-m", message])
        except RuntimeError:
            pass

        run_git_command(repo_path, ["push"])
    except RuntimeError as e:
        raise SyncError(f"Failed to push: {e}") from e


def get_current_branch(repo_path: Path) -> str:
    """Get current branch name."""
    try:
        return run_git_command(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    except RuntimeError:
        return "unknown"


def list_branches(repo_path: Path, include_remote: bool = True) -> list[str]:
    """List all branches."""
    if not repo_path.exists():
        raise RepositoryError(f"Repository not found: {repo_path}")

    try:
        try:
            run_git_command(repo_path, ["fetch", "--prune"], timeout=60)
        except RuntimeError:
            pass  # Ignore fetch errors (offline)

        args = ["branch", "-a"] if include_remote else ["branch"]
        output = run_git_command(repo_path, args)

        branches = set()
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("* "):
                line = line[2:]
            if line.startswith("remotes/origin/"):
                branch_name = line[15:]
                if branch_name.startswith("HEAD"):
                    continue
                branches.add(branch_name)
            else:
                branches.add(line)

        return sorted(branches)
    except RuntimeError as e:
        raise RepositoryError(f"Failed to list branches: {e}") from e


def is_branch_merged(repo_path: Path, branch: str, target: str = "main") -> bool:
    """Check if a branch has been merged into target branch.

    Uses git merge-base --is-ancestor to verify if all commits
    in branch are reachable from target.

    Args:
        repo_path: Path to the repository.
        branch: Branch name to check.
        target: Target branch (default: main).

    Returns:
        True if branch is merged into target, False otherwise.
    """
    if not repo_path.exists():
        return False

    try:
        # First, fetch to ensure we have latest remote state
        run_git_command(repo_path, ["fetch", "--prune"], timeout=30, check=False)

        # Try local branch first, then remote
        branch_ref = branch
        try:
            run_git_command(repo_path, ["rev-parse", "--verify", branch])
        except RuntimeError:
            # Try remote branch
            branch_ref = f"origin/{branch}"
            try:
                run_git_command(repo_path, ["rev-parse", "--verify", branch_ref])
            except RuntimeError:
                # Branch doesn't exist locally or remotely - consider it "merged" (deleted)
                logger.debug(f"Branch {branch} not found, considering as merged/deleted")
                return True

        # Check if branch is ancestor of target
        # git merge-base --is-ancestor <branch> <target>
        # Returns 0 if branch is ancestor (merged), non-zero otherwise
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch_ref, target],
            cwd=repo_path,
            capture_output=True,
            env=_get_git_env(),
        )
        return result.returncode == 0

    except Exception as e:
        logger.warning(f"Error checking if {branch} is merged into {target}: {e}")
        return False


def is_commit_in_branch(repo_path: Path, commit_sha: str, branch: str = "main") -> bool:
    """Check if a commit exists in a branch.

    Uses git branch --contains to verify if the commit is reachable from the branch.

    Args:
        repo_path: Path to the repository.
        commit_sha: Commit SHA (full or short).
        branch: Branch to check (default: main).

    Returns:
        True if commit is in branch, False otherwise.
    """
    if not repo_path.exists() or not commit_sha:
        return False

    try:
        # Fetch to ensure we have latest remote state
        run_git_command(repo_path, ["fetch", "--prune"], timeout=30, check=False)

        # Check if commit exists
        try:
            run_git_command(repo_path, ["rev-parse", "--verify", commit_sha])
        except RuntimeError:
            logger.debug(f"Commit {commit_sha} not found in repo")
            return False

        # git branch --contains <commit> checks which branches contain this commit
        # We check if our target branch is in the list
        output = run_git_command(
            repo_path,
            ["branch", "-a", "--contains", commit_sha],
            check=False,
        )

        # Parse output - each line is a branch name (with * for current)
        branches_containing = []
        for line in output.split("\n"):
            line = line.strip().lstrip("* ")
            if line:
                # Handle remotes/origin/main -> main
                if line.startswith("remotes/origin/"):
                    line = line.replace("remotes/origin/", "")
                branches_containing.append(line)

        # Check if target branch (or master as fallback) contains the commit
        target_branches = [branch]
        if branch == "main":
            target_branches.append("master")
        elif branch == "master":
            target_branches.append("main")

        for target in target_branches:
            if target in branches_containing:
                logger.debug(f"Commit {commit_sha} found in branch {target}")
                return True

        logger.debug(f"Commit {commit_sha} not in {branch}, found in: {branches_containing}")
        return False

    except Exception as e:
        logger.warning(f"Error checking if commit {commit_sha} is in {branch}: {e}")
        return False


def get_commits_ahead(repo_path: Path, branch: str, target: str = "main") -> int:
    """Count commits in branch that are not in target.

    Args:
        repo_path: Path to the repository.
        branch: Branch name to check.
        target: Target branch (default: main).

    Returns:
        Number of commits ahead, or 0 if branch not found.
    """
    if not repo_path.exists():
        return 0

    try:
        # Try local branch first, then remote
        branch_ref = branch
        try:
            run_git_command(repo_path, ["rev-parse", "--verify", branch])
        except RuntimeError:
            branch_ref = f"origin/{branch}"
            try:
                run_git_command(repo_path, ["rev-parse", "--verify", branch_ref])
            except RuntimeError:
                return 0

        # git rev-list --count target..branch
        output = run_git_command(
            repo_path,
            ["rev-list", "--count", f"{target}..{branch_ref}"],
        )
        return int(output.strip()) if output.strip() else 0

    except (RuntimeError, ValueError) as e:
        logger.warning(f"Error counting commits ahead for {branch}: {e}")
        return 0


def get_branch_commits(
    repo_path: Path,
    branch: str,
    target: str = "main",
    max_commits: int = 10,
) -> list[dict[str, str]]:
    """Get list of commits in branch not in target.

    Args:
        repo_path: Path to the repository.
        branch: Branch name.
        target: Target branch (default: main).
        max_commits: Maximum commits to return.

    Returns:
        List of commit dicts with sha, message, author, date.
    """
    if not repo_path.exists():
        return []

    try:
        # Try local branch first, then remote
        branch_ref = branch
        try:
            run_git_command(repo_path, ["rev-parse", "--verify", branch])
        except RuntimeError:
            branch_ref = f"origin/{branch}"

        # git log target..branch --format="%H|%s|%an|%ci"
        output = run_git_command(
            repo_path,
            [
                "log",
                f"{target}..{branch_ref}",
                f"--max-count={max_commits}",
                "--format=%H|%s|%an|%ci",
            ],
        )

        commits = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commits.append(
                    {
                        "sha": parts[0][:8],
                        "message": parts[1][:80],
                        "author": parts[2],
                        "date": parts[3],
                    }
                )

        return commits

    except RuntimeError as e:
        logger.warning(f"Error getting commits for {branch}: {e}")
        return []


def delete_branch(repo_path: Path, branch: str, force: bool = False) -> bool:
    """Delete a local and remote branch.

    Args:
        repo_path: Path to the repository.
        branch: Branch name to delete.
        force: Force delete even if not fully merged.

    Returns:
        True if successful, False otherwise.
    """
    if not repo_path.exists():
        return False

    try:
        # Delete local branch if exists
        try:
            flag = "-D" if force else "-d"
            run_git_command(repo_path, ["branch", flag, branch], check=False)
            logger.info(f"Deleted local branch: {branch}")
        except RuntimeError:
            pass  # Branch might not exist locally

        # Delete remote branch
        try:
            run_git_command(repo_path, ["push", "origin", "--delete", branch])
            logger.info(f"Deleted remote branch: {branch}")
        except RuntimeError as e:
            if "remote ref does not exist" not in str(e):
                logger.warning(f"Failed to delete remote branch {branch}: {e}")
                return False

        return True

    except Exception as e:
        logger.error(f"Error deleting branch {branch}: {e}")
        return False


def checkout_branch(repo_path: Path, branch: str) -> str:
    """Checkout a branch in the repository.

    Args:
        repo_path: Path to repository.
        branch: Branch name to checkout.

    Returns:
        The branch name that was checked out.

    Raises:
        RepositoryError: If checkout fails.
    """
    if not repo_path.exists():
        raise RepositoryError(f"Repository not found: {repo_path}")

    try:
        # First try to checkout local branch
        result = subprocess.run(
            ["git", "checkout", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            env=_get_git_env(),
        )

        if result.returncode != 0:
            # Maybe it's a remote branch, try to create tracking branch
            result = subprocess.run(
                ["git", "checkout", "-b", branch, f"origin/{branch}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                env=_get_git_env(),
            )

            if result.returncode != 0:
                raise RepositoryError(f"Failed to checkout branch '{branch}': {result.stderr}")

        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo_path,
            capture_output=True,
            env=_get_git_env(),
        )

        return branch
    except subprocess.CalledProcessError as e:
        raise RepositoryError(f"Failed to checkout branch '{branch}': {e.stderr}") from e


def get_repo_status(repo_path: Path) -> GitStatus:
    """Get detailed repository status."""
    branch = get_current_branch(repo_path)
    try:
        status_out = run_git_command(repo_path, ["status", "--porcelain"])
        is_clean = not bool(status_out.strip())

        modified = []
        staged = []
        untracked = []

        for line in status_out.split("\n"):
            if not line:
                continue
            if len(line) < 4:
                continue

            x = line[0]
            y = line[1]
            # Handle edge cases where separator might be missing
            if len(line) > 2 and line[2] == " ":
                filepath = line[3:].strip()
            else:
                # Fallback: split on first space after status codes
                filepath = line[2:].lstrip().strip()

            if not filepath:
                continue

            if x == "?" and y == "?":
                untracked.append(filepath)
                continue

            # Check index (Staged)
            if x in ("M", "A", "R", "C", "D"):
                staged.append(filepath)

            # Check worktree (Modified)
            if y in ("M", "D"):
                modified.append(filepath)

        ahead = behind = 0
        try:
            ahead_str = run_git_command(repo_path, ["rev-list", "--count", "@{u}..HEAD"])
            ahead = int(ahead_str)
            behind_str = run_git_command(repo_path, ["rev-list", "--count", "HEAD..@{u}"])
            behind = int(behind_str)
        except (RuntimeError, ValueError):
            pass

        return GitStatus(
            branch=branch,
            is_clean=is_clean,
            ahead=ahead,
            behind=behind,
            modified=modified,
            staged=staged,
            untracked=untracked,
        )

    except RuntimeError:
        return GitStatus(
            branch=branch,
            is_clean=True,
        )


async def resolve_conflicts_with_gemini(
    repo_path: Path,
    context_desc: str = "merge/rebase",
    op_id: str | None = None,
) -> GitOperationResult:
    """Resolve current directory conflicts using Gemini Flash.

    Args:
        repo_path: Repository with conflicts.
        context_desc: Description of operation (e.g. "Merge from feature-x").
        op_id: Operation ID for logging.

    Returns:
        GitOperationResult.
    """
    op_id = op_id or str(uuid.uuid4())
    logger.info(f"Resolving conflicts in {repo_path} using Gemini Flash")

    try:
        status_out = run_git_command(repo_path, ["status", "--porcelain"])
        conflicting_files = [
            line[3:].strip()
            for line in status_out.split("\n")
            if line.startswith("UU ") or line.startswith("AA ")
        ]
    except RuntimeError as e:
        return GitOperationResult(success=False, message=f"Failed to check status: {e}")

    if not conflicting_files:
        return GitOperationResult(
            success=True, message="No conflicting files found", ai_resolved=False
        )

    # 2. Build Prompt
    prompt = f"""You are an intelligent git conflict resolver.
Context: {context_desc}

The following files have merge conflicts:
{chr(10).join(f'- {f}' for f in conflicting_files)}

For EACH conflicting file:
1. Read the file to identify conflict markers (<<<<<<<, =======, >>>>>>>).
2. Understand the intent of both changes.
3. Edit the file to RESOLVE the conflict. Combine changes logically.
4. Remove all conflict markers.
5. Run `git add <file>` to stage the resolution.

Finally, when all files are resolved/staged:
- Verify no conflict markers remain.

Do NOT run 'git commit'. Just resolve and stage.
Start by reading the files.
"""

    # 3. Run Gemini (lazy import to avoid circular dependency)
    from ..llm.gemini import GeminiCLI

    gemini = GeminiCLI(
        working_dir=repo_path,
        model="flash",
        timeout=300,
        s3_prefix="git-conflicts",
    )

    result = await gemini.run(
        prompt=prompt,
        context_id=op_id,
        track_operation=True,
        operation_type="git_resolve",
        repo_name=repo_path.name,
    )

    if not result.success:
        return GitOperationResult(
            success=False, message=f"Gemini failed to resolve: {result.error}", output=result.output
        )

    try:
        status_out = run_git_command(repo_path, ["status", "--porcelain"])
        still_conflicting = [line for line in status_out.split("\n") if line.startswith("UU ")]

        if still_conflicting:
            return GitOperationResult(
                success=False,
                message=f"Partial resolution. {len(still_conflicting)} files still conflicting.",
                output=result.output,
            )

        return GitOperationResult(
            success=True,
            message="All conflicts resolved and staged by Gemini.",
            output=result.output,
            ai_resolved=True,
        )

    except RuntimeError as e:
        return GitOperationResult(
            success=False, message=f"Verification failed: {e}", output=result.output
        )


SMART_PUSH_INSTRUCTIONS_FILE = ".turbowrap/SMART_PUSH.md"

SMART_PUSH_INSTRUCTIONS_CONTENT = """# Smart Push Instructions

You are a Git automation agent. Execute the following workflow autonomously.

## Workflow Steps

### 1. Check Status
```bash
git status
```
Review what files have changed.

```bash
git add -A
```

Create a meaningful commit message based on the changes:
```bash
git commit -m "<descriptive message based on changes>"
```
If nothing to commit, skip to step 4.

```bash
git pull --rebase
```

### 5. Handle Conflicts (if any)
If conflicts occur:
1. Read each conflicted file
2. Identify conflict markers: `<<<<<<<`, `=======`, `>>>>>>>`
3. Resolve by combining both changes logically
4. Remove all conflict markers
5. Stage resolved files: `git add <file>`
6. Continue rebase: `git rebase --continue`

```bash
git push
```
If push fails due to upstream, use:
```bash
git push -u origin HEAD
```

## Important Notes
- Always verify no conflict markers remain before committing
- If rebase fails completely, abort with `git rebase --abort`
- Report success or failure at the end
"""


def _ensure_smart_push_instructions(repo_path: Path) -> Path:
    """Ensure the smart push instructions MD file exists.

    Args:
        repo_path: Repository path.

    Returns:
        Path to the instructions file.
    """
    instructions_path = repo_path / SMART_PUSH_INSTRUCTIONS_FILE

    if not instructions_path.exists():
        instructions_path.parent.mkdir(parents=True, exist_ok=True)
        instructions_path.write_text(SMART_PUSH_INSTRUCTIONS_CONTENT)
        logger.info(f"Created smart push instructions: {instructions_path}")

    return instructions_path


async def smart_push(
    repo_path: Path,
    commit_message: str | None = None,
    op_id: str | None = None,
) -> GitOperationResult:
    """AI-powered smart push: delegates entire git workflow to Gemini Flash.

    The agent will autonomously:
    1. Stage all changes
    2. Commit with appropriate message
    3. Pull from remote (with rebase)
    4. Resolve any conflicts
    5. Push to remote

    Args:
        repo_path: Path to the repository.
        commit_message: Optional commit message hint for the agent.
        op_id: Operation ID for tracking.

    Returns:
        GitOperationResult with success status and details.
    """
    op_id = op_id or str(uuid.uuid4())

    if not repo_path.exists():
        return GitOperationResult(success=False, message=f"Repository not found: {repo_path}")

    # Ensure instructions file exists
    _ensure_smart_push_instructions(repo_path)

    # Build prompt
    prompt_parts = [
        f"Read the instructions in `{SMART_PUSH_INSTRUCTIONS_FILE}` and execute the workflow.",
    ]

    if commit_message:
        prompt_parts.append(f"Use this commit message hint: {commit_message}")

    prompt_parts.append("Start now. Report success or failure at the end.")

    prompt = "\n".join(prompt_parts)

    logger.info(f"[smart_push] Launching Gemini Flash for {repo_path.name}")

    from ..llm.gemini import GeminiCLI

    gemini = GeminiCLI(
        working_dir=repo_path,
        model="flash",
        timeout=300,
        s3_prefix="smart-push",
    )

    result = await gemini.run(
        prompt=prompt,
        context_id=op_id,
        track_operation=True,
        operation_type="smart_push",
        repo_name=repo_path.name,
    )

    if not result.success:
        return GitOperationResult(
            success=False,
            message=f"Smart push failed: {result.error}",
            output=result.output,
            ai_resolved=False,
        )

    # Verify push succeeded by checking if we're ahead of remote
    try:
        ahead_str = run_git_command(repo_path, ["rev-list", "--count", "@{u}..HEAD"])
        ahead = int(ahead_str) if ahead_str else 0

        if ahead > 0:
            return GitOperationResult(
                success=False,
                message=f"Push incomplete: still {ahead} commits ahead of remote",
                output=result.output,
                ai_resolved=True,
            )
    except (RuntimeError, ValueError):
        pass

    return GitOperationResult(
        success=True,
        message="Smart push completed successfully",
        output=result.output,
        ai_resolved=True,
    )


async def smart_push_with_conflict_resolution(
    repo_path: Path,
    message: str = "Update via TurboWrap",
    api_key: str | None = None,
) -> dict[str, Any]:
    """Deprecated: Use smart_push() instead."""
    result = await smart_push(repo_path, commit_message=message)
    return {
        "status": "success" if result.success else "failed",
        "had_conflicts": result.ai_resolved,
        "claude_resolved": False,
        "message": result.message,
    }


@dataclass
class PRInfo:
    """Information about a Pull Request."""

    owner: str
    repo: str
    number: int
    url: str


@dataclass
class RepoCommitInfo:
    """Detailed commit information for repository operations.

    Note: This is separate from CommitInfo (API model) to avoid conflicts.
    Use this for internal git log parsing, not API responses.
    """

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
            try:
                base_ref = self._run_git("merge-base", "main", head_ref)
            except RuntimeError:
                try:
                    base_ref = self._run_git("merge-base", "master", head_ref)
                except RuntimeError:
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

    def get_current_commit(self) -> RepoCommitInfo:
        """Get current commit info."""
        format_str = "%H|%h|%an|%ae|%s|%ci"
        output = self._run_git("log", "-1", f"--format={format_str}")
        parts = output.split("|")
        return RepoCommitInfo(
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


GitUtils = RepoGitUtils
