"""Repository routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ..schemas.repos import RepoCreate, RepoResponse, RepoStatus
from ...core.repo_manager import RepoManager
from ...exceptions import RepositoryError

router = APIRouter(prefix="/repos", tags=["repositories"])


@router.get("", response_model=list[RepoResponse])
def list_repos(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List all repositories."""
    manager = RepoManager(db)
    repos = manager.list(status=status)
    return repos


@router.post("", response_model=RepoResponse)
def clone_repo(
    data: RepoCreate,
    db: Session = Depends(get_db),
):
    """Clone a new repository."""
    manager = RepoManager(db)
    try:
        repo = manager.clone(data.url, data.branch)
        return repo
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}", response_model=RepoResponse)
def get_repo(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """Get repository details."""
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.post("/{repo_id}/sync", response_model=RepoResponse)
def sync_repo(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """Sync (pull) repository."""
    manager = RepoManager(db)
    try:
        repo = manager.sync(repo_id)
        return repo
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}/status", response_model=RepoStatus)
def get_repo_status(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """Get detailed repository status."""
    manager = RepoManager(db)
    try:
        status = manager.get_status(repo_id)
        return status
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{repo_id}")
def delete_repo(
    repo_id: str,
    delete_local: bool = True,
    db: Session = Depends(get_db),
):
    """Delete a repository."""
    manager = RepoManager(db)
    try:
        manager.delete(repo_id, delete_local=delete_local)
        return {"status": "deleted", "id": repo_id}
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e))
