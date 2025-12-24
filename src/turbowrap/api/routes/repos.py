"""Repository routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ..schemas.repos import (
    RepoCreate,
    RepoResponse,
    RepoStatus,
    LinkCreate,
    LinkResponse,
    LinkedRepoSummary,
)
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
    """Clone a new repository.

    For private repos, provide a GitHub token via:
    - `token` field in request body, OR
    - `GITHUB_TOKEN` environment variable
    """
    manager = RepoManager(db)
    try:
        repo = manager.clone(data.url, data.branch, data.token)
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


# --- Repository Link Endpoints ---


@router.post("/{repo_id}/links", response_model=LinkResponse)
def create_link(
    repo_id: str,
    data: LinkCreate,
    db: Session = Depends(get_db),
):
    """Create a link from this repository to another.

    Link types:
    - `frontend_for`: This repo is the frontend for target backend
    - `backend_for`: This repo is the backend for target frontend
    - `shared_lib`: Target is a shared library used by this repo
    - `microservice`: Target is a related microservice
    - `monorepo_module`: Target is another module in same monorepo
    - `related`: Generic relationship
    """
    manager = RepoManager(db)
    try:
        link = manager.link_repositories(
            source_id=repo_id,
            target_id=data.target_repo_id,
            link_type=data.link_type.value,
            metadata=data.metadata,
        )
        return LinkResponse.model_validate(link)
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}/links", response_model=list[LinkedRepoSummary])
def list_linked_repos(
    repo_id: str,
    link_type: str | None = None,
    direction: str | None = None,
    db: Session = Depends(get_db),
):
    """List all repositories linked to this repository.

    Args:
        repo_id: Repository UUID
        link_type: Optional filter by link type (frontend_for, backend_for, etc.)
        direction: Optional filter: 'outgoing', 'incoming', or omit for both
    """
    manager = RepoManager(db)
    try:
        linked = manager.get_linked_repos(
            repo_id=repo_id,
            link_type=link_type,
            direction=direction,
        )
        return linked
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{repo_id}/links/{link_id}")
def delete_link(
    repo_id: str,
    link_id: str,
    db: Session = Depends(get_db),
):
    """Remove a repository link.

    The link must belong to this repository (as source).
    """
    manager = RepoManager(db)

    # Verify the link belongs to this repo
    link = manager.get_link(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link.source_repo_id != repo_id:
        raise HTTPException(
            status_code=403,
            detail="Link does not belong to this repository"
        )

    try:
        manager.unlink_repositories(link_id)
        return {"status": "deleted", "link_id": link_id}
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
