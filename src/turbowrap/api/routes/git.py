"""Git operations routes for repository activity tracking."""

import logging
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import Repository
from ..deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/git", tags=["git"])


class CommitInfo(BaseModel):
    """Git commit information."""

    sha: str
    message: str
    author: str
    date: str


class BranchInfo(BaseModel):
    """Current branch information."""

    branch: str


class BranchListInfo(BaseModel):
    """List of all branches."""

    current: str
    branches: list[str]


class CommitFileInfo(BaseModel):
    """File changed in a commit."""

    filename: str
    status: str  # A=added, M=modified, D=deleted, R=renamed
    additions: int
    deletions: int


class CommitDiff(BaseModel):
    """Commit diff content."""

    diff: str


class CheckoutRequest(BaseModel):
    """Branch checkout request."""

    branch: str


class MergeRequest(BaseModel):
    """Merge request."""

    branch: str  # Branch to merge into current


class StashRequest(BaseModel):
    """Stash request."""

    message: str | None = None


class StashPopRequest(BaseModel):
    """Stash pop/drop request."""

    index: int = 0


class StashEntry(BaseModel):
    """Stash entry info."""

    index: int
    message: str
    date: str


class GitWorkingStatus(BaseModel):
    """Working directory status."""

    modified: list[str]
    staged: list[str]
    untracked: list[str]
    ahead: int
    behind: int


class GitOperationResult(BaseModel):
    """Result of a git operation."""

    success: bool
    message: str
    output: str | None = None


def run_git_command(repo_path: Path, command: list[str]) -> str:
    """Run a git command in the repository directory.

    Args:
        repo_path: Path to the repository
        command: Git command as list (e.g., ['branch', '--show-current'])

    Returns:
        Command output as string

    Raises:
        HTTPException: If command fails
    """
    try:
        result = subprocess.run(
            ["git"] + command, cwd=repo_path, capture_output=True, text=True, check=True, timeout=10
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Git command failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Git command timed out")


@router.get("/repositories")
def list_repositories(db: Session = Depends(get_db)):
    """List all active repositories with basic info."""
    repos = (
        db.query(Repository)
        .filter(Repository.deleted_at.is_(None), Repository.status == "active")
        .all()
    )

    result = []
    for repo in repos:
        path = repo.local_path
        path_exists = Path(path).exists() if path else False
        logger.debug(f"[git/repos] {repo.name}: path={path}, exists={path_exists}")
        result.append(
            {
                "id": repo.id,
                "name": repo.name,
                "path": str(path) if path else None,
                "path_exists": path_exists,
            }
        )

    return result


@router.get("/repositories/{repo_id}/branch", response_model=BranchInfo)
def get_current_branch(repo_id: str, db: Session = Depends(get_db)):
    """Get the current branch for a repository."""
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        logger.warning(f"[git/branch] Repository not found: {repo_id}")
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path) if repo.local_path else None
    if not repo_path or not repo_path.exists():
        logger.warning(f"[git/branch] Path not found for {repo.name}: {repo.local_path}")
        raise HTTPException(status_code=404, detail=f"Repository path not found: {repo.local_path}")

    try:
        branch = run_git_command(repo_path, ["branch", "--show-current"])
        return BranchInfo(branch=branch or "HEAD")
    except HTTPException as e:
        logger.error(f"[git/branch] Git command failed for {repo.name}: {e.detail}")
        raise


@router.get("/repositories/{repo_id}/commits", response_model=list[CommitInfo])
def get_commits(
    repo_id: str, limit: int = Query(default=5, ge=1, le=50), db: Session = Depends(get_db)
):
    """Get recent commits for a repository.

    Args:
        repo_id: Repository ID
        limit: Number of commits to retrieve (1-50)
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        logger.warning(f"[git/commits] Repository not found: {repo_id}")
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path) if repo.local_path else None
    if not repo_path or not repo_path.exists():
        logger.warning(f"[git/commits] Path not found for {repo.name}: {repo.local_path}")
        raise HTTPException(status_code=404, detail=f"Repository path not found: {repo.local_path}")

    try:
        # Get commits with format: sha|message|author|date
        git_log_format = "--pretty=format:%H|%s|%an|%aI"
        output = run_git_command(repo_path, ["log", git_log_format, f"-n{limit}"])

        commits = []
        for line in output.split("\n"):
            if not line:
                continue

            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append(
                    CommitInfo(sha=parts[0], message=parts[1], author=parts[2], date=parts[3])
                )

        return commits
    except HTTPException as e:
        logger.error(f"[git/commits] Git command failed for {repo.name}: {e.detail}")
        raise


@router.get("/repositories/{repo_id}/branches", response_model=BranchListInfo)
def list_branches(repo_id: str, db: Session = Depends(get_db)):
    """List all branches for a repository."""
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path) if repo.local_path else None
    if not repo_path or not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository path not found")

    # Get current branch
    current = run_git_command(repo_path, ["branch", "--show-current"]) or "HEAD"

    # Get all local branches
    output = run_git_command(repo_path, ["branch", "--format=%(refname:short)"])
    branches = [b.strip() for b in output.split("\n") if b.strip()]

    # Also get remote branches (without origin/ prefix for cleaner display)
    try:
        remote_output = run_git_command(repo_path, ["branch", "-r", "--format=%(refname:short)"])
        for branch in remote_output.split("\n"):
            branch = branch.strip()
            if branch and not branch.startswith("origin/HEAD"):
                # Remove origin/ prefix
                clean_name = branch.replace("origin/", "")
                if clean_name not in branches:
                    branches.append(clean_name)
    except HTTPException:
        pass  # Remote branches not available

    return BranchListInfo(current=current, branches=sorted(branches))


@router.get("/repositories/{repo_id}/commits/{sha}/files", response_model=list[CommitFileInfo])
def get_commit_files(repo_id: str, sha: str, db: Session = Depends(get_db)):
    """Get list of files changed in a commit with stats."""
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path) if repo.local_path else None
    if not repo_path or not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository path not found")

    # Get file status (A/M/D/R)
    status_output = run_git_command(repo_path, ["diff-tree", "--no-commit-id", "--name-status", "-r", sha])

    # Get numstat for additions/deletions
    numstat_output = run_git_command(repo_path, ["show", "--numstat", "--format=", sha])

    # Parse status
    status_map: dict[str, str] = {}
    for line in status_output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            status = parts[0][0]  # First char: A, M, D, R
            filename = parts[-1]  # Last part is filename (handles renames)
            status_map[filename] = status

    # Parse numstat
    files: list[CommitFileInfo] = []
    for line in numstat_output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            additions = int(parts[0]) if parts[0] != "-" else 0
            deletions = int(parts[1]) if parts[1] != "-" else 0
            filename = parts[2]
            status = status_map.get(filename, "M")
            files.append(CommitFileInfo(
                filename=filename,
                status=status,
                additions=additions,
                deletions=deletions
            ))

    return files


@router.get("/repositories/{repo_id}/commits/{sha}/diff", response_model=CommitDiff)
def get_commit_diff(repo_id: str, sha: str, db: Session = Depends(get_db)):
    """Get the diff for a specific commit.

    Args:
        repo_id: Repository ID
        sha: Commit SHA (can be short or full)
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository path not found")

    # Get the diff for this commit
    run_git_command(repo_path, ["show", "--pretty=format:", "--stat", sha])

    # Also get the full diff with changes
    full_diff = run_git_command(repo_path, ["show", sha])

    return CommitDiff(diff=full_diff)


# ============================================================================
# Git Operations (write operations)
# ============================================================================


def _get_repo_path(repo_id: str, db: Session) -> Path:
    """Get repository path or raise 404."""
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path) if repo.local_path else None
    if not repo_path or not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository path not found")

    return repo_path


@router.get("/repositories/{repo_id}/status", response_model=GitWorkingStatus)
def get_working_status(repo_id: str, db: Session = Depends(get_db)):
    """Get working directory status (modified, staged, untracked files)."""
    repo_path = _get_repo_path(repo_id, db)

    # Get modified files (not staged)
    modified_output = run_git_command(repo_path, ["diff", "--name-only"])
    modified = [f for f in modified_output.split("\n") if f.strip()]

    # Get staged files
    staged_output = run_git_command(repo_path, ["diff", "--cached", "--name-only"])
    staged = [f for f in staged_output.split("\n") if f.strip()]

    # Get untracked files
    untracked_output = run_git_command(repo_path, ["ls-files", "--others", "--exclude-standard"])
    untracked = [f for f in untracked_output.split("\n") if f.strip()]

    # Get ahead/behind counts
    ahead, behind = 0, 0
    try:
        status_output = run_git_command(repo_path, ["status", "-sb"])
        # Parse "[ahead N, behind M]" from first line
        if "[" in status_output:
            bracket_content = status_output.split("[")[1].split("]")[0]
            if "ahead" in bracket_content:
                ahead = int(bracket_content.split("ahead")[1].split(",")[0].split("]")[0].strip())
            if "behind" in bracket_content:
                behind = int(bracket_content.split("behind")[1].split(",")[0].split("]")[0].strip())
    except (HTTPException, ValueError, IndexError):
        pass

    return GitWorkingStatus(
        modified=modified,
        staged=staged,
        untracked=untracked,
        ahead=ahead,
        behind=behind
    )


@router.post("/repositories/{repo_id}/checkout", response_model=GitOperationResult)
def checkout_branch(repo_id: str, request: CheckoutRequest, db: Session = Depends(get_db)):
    """Checkout a branch."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["checkout", request.branch])
        return GitOperationResult(success=True, message=f"Switched to branch '{request.branch}'", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.post("/repositories/{repo_id}/fetch", response_model=GitOperationResult)
def fetch_remote(repo_id: str, db: Session = Depends(get_db)):
    """Fetch from remote."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["fetch", "--all", "--prune"])
        return GitOperationResult(success=True, message="Fetched from remote", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.post("/repositories/{repo_id}/pull", response_model=GitOperationResult)
def pull_remote(repo_id: str, db: Session = Depends(get_db)):
    """Pull from remote."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["pull"])
        return GitOperationResult(success=True, message="Pulled from remote", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.post("/repositories/{repo_id}/push", response_model=GitOperationResult)
def push_remote(repo_id: str, db: Session = Depends(get_db)):
    """Push to remote."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["push"])
        return GitOperationResult(success=True, message="Pushed to remote", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.post("/repositories/{repo_id}/merge", response_model=GitOperationResult)
def merge_branch(repo_id: str, request: MergeRequest, db: Session = Depends(get_db)):
    """Merge a branch into current."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["merge", request.branch])
        return GitOperationResult(success=True, message=f"Merged '{request.branch}'", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.get("/repositories/{repo_id}/stash", response_model=list[StashEntry])
def list_stashes(repo_id: str, db: Session = Depends(get_db)):
    """List all stashes."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["stash", "list", "--format=%gd|%s|%aI"])
        stashes = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            if len(parts) >= 2:
                # Extract index from stash@{N}
                index_str = parts[0].replace("stash@{", "").replace("}", "")
                try:
                    index = int(index_str)
                except ValueError:
                    index = 0
                stashes.append(StashEntry(
                    index=index,
                    message=parts[1] if len(parts) > 1 else "",
                    date=parts[2] if len(parts) > 2 else ""
                ))
        return stashes
    except HTTPException:
        return []


@router.post("/repositories/{repo_id}/stash", response_model=GitOperationResult)
def create_stash(repo_id: str, request: StashRequest | None = None, db: Session = Depends(get_db)):
    """Create a new stash."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        cmd = ["stash", "push"]
        if request and request.message:
            cmd.extend(["-m", request.message])
        output = run_git_command(repo_path, cmd)
        return GitOperationResult(success=True, message="Changes stashed", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.post("/repositories/{repo_id}/stash/pop", response_model=GitOperationResult)
def pop_stash(repo_id: str, request: StashPopRequest | None = None, db: Session = Depends(get_db)):
    """Pop a stash (apply and remove)."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        index = request.index if request else 0
        output = run_git_command(repo_path, ["stash", "pop", f"stash@{{{index}}}"])
        return GitOperationResult(success=True, message="Stash applied and removed", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.post("/repositories/{repo_id}/stash/drop", response_model=GitOperationResult)
def drop_stash(repo_id: str, request: StashPopRequest | None = None, db: Session = Depends(get_db)):
    """Drop a stash (remove without applying)."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        index = request.index if request else 0
        output = run_git_command(repo_path, ["stash", "drop", f"stash@{{{index}}}"])
        return GitOperationResult(success=True, message="Stash dropped", output=output)
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)


@router.post("/repositories/{repo_id}/reset", response_model=GitOperationResult)
def reset_changes(repo_id: str, db: Session = Depends(get_db)):
    """Discard all local changes (git checkout -- . && git clean -fd)."""
    repo_path = _get_repo_path(repo_id, db)

    try:
        # Discard tracked file changes
        run_git_command(repo_path, ["checkout", "--", "."])
        # Remove untracked files
        run_git_command(repo_path, ["clean", "-fd"])
        return GitOperationResult(success=True, message="All changes discarded")
    except HTTPException as e:
        return GitOperationResult(success=False, message=e.detail)
