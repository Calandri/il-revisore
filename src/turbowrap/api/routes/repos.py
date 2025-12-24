"""Repository routes."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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


# --- File Management Schemas ---

class FileInfo(BaseModel):
    """File information."""
    name: str
    path: str
    type: str  # 'file' or 'directory'
    size: Optional[int] = None
    extension: Optional[str] = None


class FileContent(BaseModel):
    """File content response."""
    path: str
    content: str
    size: int
    encoding: str = "utf-8"


class FileWriteRequest(BaseModel):
    """Request to write file content."""
    content: str
    commit_message: Optional[str] = None


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


# --- File Management Endpoints ---

ALLOWED_EXTENSIONS = {'.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.py', '.js', '.ts', '.html', '.css'}
MAX_FILE_SIZE = 1024 * 1024  # 1MB


@router.get("/{repo_id}/files", response_model=list[FileInfo])
def list_files(
    repo_id: str,
    path: str = Query(default="", description="Subdirectory path"),
    pattern: str = Query(default="*", description="Glob pattern to filter files"),
    db: Session = Depends(get_db),
):
    """List files in a repository directory.

    Args:
        repo_id: Repository UUID
        path: Subdirectory path (relative to repo root)
        pattern: Glob pattern to filter files (e.g., '*.md', 'STRUCTURE*')
    """
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    target_path = repo_path / path

    # Security: ensure we stay within repo directory
    try:
        target_path = target_path.resolve()
        repo_path = repo_path.resolve()
        if not str(target_path).startswith(str(repo_path)):
            raise HTTPException(status_code=400, detail="Invalid path")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    files = []
    if target_path.is_file():
        # Single file
        files.append(FileInfo(
            name=target_path.name,
            path=str(target_path.relative_to(repo_path)),
            type="file",
            size=target_path.stat().st_size,
            extension=target_path.suffix,
        ))
    else:
        # Directory listing
        for item in sorted(target_path.glob(pattern)):
            # Skip hidden files and .git
            if item.name.startswith('.'):
                continue

            rel_path = str(item.relative_to(repo_path))
            if item.is_dir():
                files.append(FileInfo(
                    name=item.name,
                    path=rel_path,
                    type="directory",
                ))
            else:
                files.append(FileInfo(
                    name=item.name,
                    path=rel_path,
                    type="file",
                    size=item.stat().st_size,
                    extension=item.suffix,
                ))

    return files


@router.get("/{repo_id}/files/tree")
def get_file_tree(
    repo_id: str,
    extensions: str = Query(default=".md", description="Comma-separated extensions to include"),
    db: Session = Depends(get_db),
):
    """Get a tree of files matching specified extensions.

    Returns a flat list of all matching files in the repository.
    """
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    ext_list = [ext.strip() for ext in extensions.split(',')]

    files = []
    for ext in ext_list:
        if not ext.startswith('.'):
            ext = '.' + ext
        for item in repo_path.rglob(f'*{ext}'):
            # Skip hidden and .git
            if any(part.startswith('.') for part in item.parts):
                continue

            rel_path = str(item.relative_to(repo_path))
            files.append(FileInfo(
                name=item.name,
                path=rel_path,
                type="file",
                size=item.stat().st_size,
                extension=item.suffix,
            ))

    return sorted(files, key=lambda f: f.path)


@router.get("/{repo_id}/files/content", response_model=FileContent)
def read_file(
    repo_id: str,
    path: str = Query(..., description="File path relative to repo root"),
    db: Session = Depends(get_db),
):
    """Read file content.

    Only text files are supported. Binary files will return an error.
    """
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    file_path = repo_path / path

    # Security check
    try:
        file_path = file_path.resolve()
        repo_path = repo_path.resolve()
        if not str(file_path).startswith(str(repo_path)):
            raise HTTPException(status_code=400, detail="Invalid path")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    # Check file size
    size = file_path.stat().st_size
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_FILE_SIZE // 1024}KB)")

    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not a text file")

    return FileContent(
        path=path,
        content=content,
        size=size,
    )


@router.put("/{repo_id}/files/content")
def write_file(
    repo_id: str,
    path: str = Query(..., description="File path relative to repo root"),
    data: FileWriteRequest = ...,
    db: Session = Depends(get_db),
):
    """Write file content.

    Updates an existing file or creates a new one.
    Optionally commits the change with the provided message.
    """
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    file_path = repo_path / path

    # Security check
    try:
        file_path = file_path.resolve()
        repo_path_resolved = repo_path.resolve()
        if not str(file_path).startswith(str(repo_path_resolved)):
            raise HTTPException(status_code=400, detail="Invalid path")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    # Check extension is allowed
    ext = file_path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Check content size
    if len(data.content.encode('utf-8')) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Content too large (max {MAX_FILE_SIZE // 1024}KB)")

    # Write file
    is_new = not file_path.exists()
    file_path.write_text(data.content, encoding='utf-8')

    # Optionally commit
    committed = False
    if data.commit_message:
        import subprocess
        try:
            # Stage the file
            subprocess.run(
                ['git', 'add', str(file_path)],
                cwd=str(repo_path),
                check=True,
                capture_output=True,
            )
            # Commit
            subprocess.run(
                ['git', 'commit', '-m', data.commit_message],
                cwd=str(repo_path),
                check=True,
                capture_output=True,
            )
            committed = True
        except subprocess.CalledProcessError as e:
            # File written but commit failed
            pass

    return {
        "status": "created" if is_new else "updated",
        "path": path,
        "size": len(data.content.encode('utf-8')),
        "committed": committed,
    }
