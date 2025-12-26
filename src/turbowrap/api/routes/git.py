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


class CommitDiff(BaseModel):
    """Commit diff content."""

    diff: str


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
