"""Repository routes."""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from github import GithubException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.repo_manager import RepoManager
from ...exceptions import RepositoryError
from ...utils.git_utils import get_repo_status as get_git_status
from ...utils.github_browse import FolderListResponse, list_repo_folders
from ..deps import get_db, get_or_404
from ..schemas.repos import (
    ExternalLinkCreate,
    ExternalLinkResponse,
    ExternalLinkUpdate,
    FileStats,
    GitStatus,
    LinkCreate,
    LinkedRepoSummary,
    LinkResponse,
    LinkTypeEnum,
    RepoCreate,
    RepoResponse,
    RepoStatus,
)
from ..services.operation_tracker import OperationType, get_tracker

router = APIRouter(prefix="/repos", tags=["repositories"])


class FileInfo(BaseModel):
    """File information."""

    name: str
    path: str
    type: str  # 'file' or 'directory'
    size: int | None = None
    extension: str | None = None


class TreeNode(BaseModel):
    """Hierarchical file tree node for VS Code-like explorer."""

    name: str
    path: str
    type: Literal["file", "directory"]
    extension: str | None = None
    size: int | None = None
    children: list["TreeNode"] = []
    is_modified: bool = False
    is_untracked: bool = False


TreeNode.model_rebuild()


class FileDiff(BaseModel):
    """Diff for a single file."""

    path: str
    diff: str
    status: str  # 'modified', 'untracked', 'staged'
    additions: int = 0
    deletions: int = 0


class SymbolDefinition(BaseModel):
    """Symbol definition location."""

    symbol: str
    path: str
    line: int
    type: str  # 'function', 'class', 'import', 'variable'
    preview: str  # Line content preview
    confidence: float = 1.0  # How confident we are (1.0 = exact match)


class SymbolSearchResult(BaseModel):
    """Result of symbol search."""

    found: bool
    definitions: list[SymbolDefinition] = []
    message: str | None = None


class FileContent(BaseModel):
    """File content response."""

    path: str
    content: str
    size: int
    encoding: str = "utf-8"


class FileWriteRequest(BaseModel):
    """Request to write file content."""

    content: str
    commit_message: str | None = None


@router.get("", response_model=list[RepoResponse])
def list_repos(
    status: str | None = None,
    project: str | None = Query(default=None, description="Filter by project name"),
    db: Session = Depends(get_db),
) -> list[RepoResponse]:
    """List all repositories, optionally filtered by status or project."""
    manager = RepoManager(db)
    repos = manager.list_all(status=status, project_name=project)
    return [RepoResponse.model_validate(repo) for repo in repos]


@router.get("/github/folders", response_model=FolderListResponse)
def list_github_folders(
    url: str = Query(..., description="GitHub repository URL"),
    path: str = Query(default="", description="Subdirectory path to browse"),
    branch: str = Query(default="main", description="Branch to browse"),
    db: Session = Depends(get_db),
) -> FolderListResponse:
    """List folders in a GitHub repository for workspace path selection.

    Uses GitHub API to fetch directory structure before cloning.
    Useful for selecting monorepo workspace paths.

    Args:
        url: GitHub repository URL (e.g., https://github.com/owner/repo)
        path: Subdirectory path to list (default: root)
        branch: Branch to browse (default: main)

    Returns:
        List of folders with navigation info.

    Raises:
        401: GitHub token required for private repositories
        404: Repository or path not found
        403: Rate limit exceeded
    """
    from ...db.models import Setting

    # Get GitHub token from settings if available
    token_setting = db.query(Setting).filter(Setting.key == "github_token").first()
    token: str | None = str(token_setting.value) if token_setting else None

    try:
        return list_repo_folders(url, path, branch, token)
    except GithubException as e:
        if e.status == 401:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Token GitHub richiesto per repository private. Configuralo nelle Impostazioni."
                ),
            )
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail="Repository o percorso non trovato. Verifica l'URL e il branch.",
            )
        if e.status == 403:
            raise HTTPException(
                status_code=403,
                detail="Limite API GitHub raggiunto. Riprova tra qualche minuto.",
            )
        raise HTTPException(status_code=500, detail=f"Errore GitHub API: {e}")
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)) -> dict[str, Any]:
    """List all unique project names with their repository counts."""
    from sqlalchemy import func

    from ...db.models import Repository

    results = (
        db.query(Repository.project_name, func.count(Repository.id).label("repo_count"))
        .filter(Repository.project_name.isnot(None))
        .filter(Repository.deleted_at.is_(None))
        .group_by(Repository.project_name)
        .order_by(Repository.project_name)
        .all()
    )

    # Get repos without project
    unassigned = (
        db.query(func.count(Repository.id))
        .filter(Repository.project_name.is_(None))
        .filter(Repository.deleted_at.is_(None))
        .scalar()
    )

    return {
        "projects": [{"name": name, "repo_count": count} for name, count in results],
        "unassigned_count": unassigned,
    }


def _clone_repo_background(
    repo_id: str,
    url: str,
    branch: str,
    token: str | None,
    workspace_path: str | None,
) -> None:
    """Background task to clone repository.

    This runs after the endpoint returns, performing the actual git clone
    and updating the repository record with status='active' or 'error'.
    """
    from ...db.models import Repository
    from ...db.session import get_session_local

    logger = logging.getLogger(__name__)
    logger.info(f"[CLONE] Starting background clone for {url}")

    # Extract repo name from URL
    repo_name = url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    # Register with unified OperationTracker
    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.CLONE,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=repo_name,
        branch=branch,
        details={"workspace_path": workspace_path, "url": url},
    )

    # Get a new session for the background task
    session_factory = get_session_local()
    db: Session = session_factory()
    try:
        manager = RepoManager(db)
        manager.complete_clone(repo_id, url, branch, token, workspace_path)
        logger.info(f"[CLONE] Completed clone for {url}")
        tracker.complete(op_id, result={"workspace_path": workspace_path})
    except Exception as e:
        logger.error(f"[CLONE] Failed to clone {url}: {e}")
        tracker.fail(op_id, error=str(e))
        # Update status to error
        repo = db.query(Repository).filter(Repository.id == repo_id).first()
        if repo:
            repo.status = "error"  # type: ignore[assignment]
            repo.metadata_ = {"error": str(e)}  # type: ignore[assignment]
            db.commit()
    finally:
        db.close()


@router.post("", response_model=RepoResponse)
def clone_repo(
    data: RepoCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RepoResponse:
    """Clone a new repository (async - returns immediately).

    The clone operation runs in the background. The response includes
    the repository with status='cloning'. Poll the repository to check
    when it becomes 'active' (success) or 'error' (failed).

    For private repos, provide a GitHub token via:
    - `token` field in request body, OR
    - `GITHUB_TOKEN` environment variable

    For monorepos, provide `workspace_path` to scope operations to a subfolder.
    The same repo URL can be cloned multiple times with different workspace paths.
    """
    manager = RepoManager(db)
    try:
        # Create pending repo record (returns immediately)
        repo = manager.create_pending(
            data.url,
            data.branch,
            workspace_path=data.workspace_path,
        )

        if repo.status != "cloning":
            return RepoResponse.model_validate(repo)

        background_tasks.add_task(
            _clone_repo_background,
            str(repo.id),
            data.url,
            data.branch,
            data.token,
            data.workspace_path,
        )

        return RepoResponse.model_validate(repo)
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


class RepoUpdate(BaseModel):
    """Request to update repository metadata."""

    project_name: str | None = None
    repo_type: str | None = None


@router.get("/{repo_id}", response_model=RepoResponse)
def get_repo(
    repo_id: str,
    db: Session = Depends(get_db),
) -> RepoResponse:
    """Get repository details."""
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)
    return RepoResponse.model_validate(repo)


@router.patch("/{repo_id}", response_model=RepoResponse)
def update_repo(
    repo_id: str,
    data: RepoUpdate,
    db: Session = Depends(get_db),
) -> RepoResponse:
    """Update repository metadata (project_name, repo_type)."""
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    if data.project_name is not None:
        repo.project_name = data.project_name if data.project_name else None  # type: ignore[assignment]
    if data.repo_type is not None:
        repo.repo_type = data.repo_type if data.repo_type else None  # type: ignore[assignment]

    db.commit()
    db.refresh(repo)
    return RepoResponse.model_validate(repo)


@router.post("/{repo_id}/sync", response_model=RepoResponse)
def sync_repo(
    repo_id: str,
    db: Session = Depends(get_db),
) -> RepoResponse:
    """Sync (pull) repository."""
    from ...db.models import Repository

    manager = RepoManager(db)

    # Get repo info for tracking
    repo = get_or_404(db, Repository, repo_id)

    # Extract repo name - cast to str to satisfy mypy
    repo_url = cast(str, repo.url) if repo.url else ""
    repo_name_str = cast(str, repo.name) if repo.name else "unknown"
    extracted_name: str = repo_url.rstrip("/").split("/")[-1] if repo_url else repo_name_str
    if extracted_name.endswith(".git"):
        extracted_name = extracted_name[:-4]

    # Register with unified OperationTracker
    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.SYNC,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=extracted_name or "unknown",
    )

    try:
        result = manager.sync(repo_id)
        tracker.complete(op_id)
        return RepoResponse.model_validate(result)
    except RepositoryError as e:
        tracker.fail(op_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}/status", response_model=RepoStatus)
def get_repo_status(
    repo_id: str,
    db: Session = Depends(get_db),
) -> RepoStatus:
    """Get detailed repository status."""
    manager = RepoManager(db)
    try:
        status_dict = manager.get_status(repo_id)
        # Convert the dict to RepoStatus schema
        git_data = status_dict.get("git", {})
        git_status = GitStatus(
            branch=git_data.get("branch", "unknown"),
            is_clean=git_data.get("is_clean", True),
            modified=git_data.get("modified", []),
            untracked=git_data.get("untracked", []),
        )
        files_data = status_dict.get("files")
        file_stats: FileStats | None = None
        if files_data:
            file_stats = FileStats(
                be_files=files_data.get("be_files", 0),
                fe_files=files_data.get("fe_files", 0),
            )
        return RepoStatus(
            id=str(status_dict["id"]),
            name=str(status_dict["name"]),
            status=status_dict["status"],
            repo_type=status_dict.get("repo_type"),
            last_synced_at=status_dict.get("last_synced_at"),
            git=git_status,
            files=file_stats,
        )
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{repo_id}")
def delete_repo(
    repo_id: str,
    delete_local: bool = True,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete a repository."""
    manager = RepoManager(db)
    try:
        manager.delete(repo_id, delete_local=delete_local)
        return {"status": "deleted", "id": repo_id}
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{repo_id}/links", response_model=LinkResponse)
def create_link(
    repo_id: str,
    data: LinkCreate,
    db: Session = Depends(get_db),
) -> LinkResponse:
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
) -> list[LinkedRepoSummary]:
    """List all repositories linked to this repository.

    Args:
        repo_id: Repository UUID
        link_type: Optional filter by link type (frontend_for, backend_for, etc.)
        direction: Optional filter: 'outgoing', 'incoming', or omit for both
    """
    manager = RepoManager(db)
    try:
        linked_dicts = manager.get_linked_repos(
            repo_id=repo_id,
            link_type=link_type,
            direction=direction,
        )
        # Convert list of dicts to list of LinkedRepoSummary
        return [
            LinkedRepoSummary(
                id=str(item["id"]),
                name=str(item["name"]),
                repo_type=item.get("repo_type"),
                link_id=str(item["link_id"]),
                link_type=LinkTypeEnum(item["link_type"]),
                direction=item["direction"],
            )
            for item in linked_dicts
        ]
    except RepositoryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{repo_id}/links/{link_id}")
def delete_link(
    repo_id: str,
    link_id: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Remove a repository link.

    The link must belong to this repository (as source).
    """
    manager = RepoManager(db)

    link = manager.get_link(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link.source_repo_id != repo_id:
        raise HTTPException(status_code=403, detail="Link does not belong to this repository")

    try:
        manager.unlink_repositories(link_id)
        return {"status": "deleted", "link_id": link_id}
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{repo_id}/external-links", response_model=ExternalLinkResponse)
def create_external_link(
    repo_id: str,
    data: ExternalLinkCreate,
    db: Session = Depends(get_db),
) -> ExternalLinkResponse:
    """Add an external link to a repository.

    External link types:
    - `staging`: Staging environment URL
    - `production`: Production environment URL
    - `docs`: Documentation URL
    - `api`: API documentation (OpenAPI, etc.)
    - `admin`: Admin panel URL
    - `swagger`: Swagger UI URL
    - `graphql`: GraphQL playground URL
    - `monitoring`: Monitoring dashboard URL
    - `logs`: Log viewer URL
    - `ci_cd`: CI/CD pipeline URL
    - `other`: Other custom URL
    """
    from ...db.models import Repository, RepositoryExternalLink, generate_uuid

    get_or_404(db, Repository, repo_id)  # Validate repo exists

    # Create external link
    external_link = RepositoryExternalLink(
        id=generate_uuid(),
        repository_id=repo_id,
        link_type=data.link_type.value,
        url=data.url,
        label=data.label,
        is_primary=data.is_primary,
        metadata_=data.metadata,
    )
    db.add(external_link)
    db.commit()
    db.refresh(external_link)

    return ExternalLinkResponse.model_validate(external_link)


@router.get("/{repo_id}/external-links", response_model=list[ExternalLinkResponse])
def list_external_links(
    repo_id: str,
    link_type: str | None = Query(default=None, description="Filter by link type"),
    db: Session = Depends(get_db),
) -> list[ExternalLinkResponse]:
    """List all external links for a repository.

    Args:
        repo_id: Repository UUID
        link_type: Optional filter by link type (staging, production, docs, etc.)
    """
    from ...db.models import Repository, RepositoryExternalLink

    get_or_404(db, Repository, repo_id)  # Validate repo exists

    query = db.query(RepositoryExternalLink).filter(RepositoryExternalLink.repository_id == repo_id)
    if link_type:
        query = query.filter(RepositoryExternalLink.link_type == link_type)

    links = query.order_by(RepositoryExternalLink.created_at.desc()).all()
    return [ExternalLinkResponse.model_validate(link) for link in links]


@router.patch("/{repo_id}/external-links/{link_id}", response_model=ExternalLinkResponse)
def update_external_link(
    repo_id: str,
    link_id: str,
    data: ExternalLinkUpdate,
    db: Session = Depends(get_db),
) -> ExternalLinkResponse:
    """Update an external link."""
    from ...db.models import Repository, RepositoryExternalLink

    get_or_404(db, Repository, repo_id)  # Validate repo exists

    link = (
        db.query(RepositoryExternalLink)
        .filter(
            RepositoryExternalLink.id == link_id,
            RepositoryExternalLink.repository_id == repo_id,
        )
        .first()
    )

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    # Update fields that were provided
    if data.link_type is not None:
        link.link_type = data.link_type.value
    if data.url is not None:
        link.url = data.url
    if data.label is not None:
        link.label = data.label
    if data.is_primary is not None:
        link.is_primary = data.is_primary
    if data.metadata is not None:
        link.metadata_ = data.metadata

    db.commit()
    db.refresh(link)

    return ExternalLinkResponse.model_validate(link)


@router.delete("/{repo_id}/external-links/{link_id}")
def delete_external_link(
    repo_id: str,
    link_id: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete an external link."""
    from ...db.models import Repository, RepositoryExternalLink

    get_or_404(db, Repository, repo_id)  # Validate repo exists

    link = (
        db.query(RepositoryExternalLink)
        .filter(
            RepositoryExternalLink.id == link_id,
            RepositoryExternalLink.repository_id == repo_id,
        )
        .first()
    )

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    db.delete(link)
    db.commit()

    return {"status": "deleted", "link_id": link_id}


ALLOWED_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
}
MAX_FILE_SIZE = 1024 * 1024  # 1MB


@router.get("/{repo_id}/files", response_model=list[FileInfo])
def list_files(
    repo_id: str,
    path: str = Query(default="", description="Subdirectory path"),
    pattern: str = Query(default="*", description="Glob pattern to filter files"),
    db: Session = Depends(get_db),
) -> list[FileInfo]:
    """List files in a repository directory.

    Args:
        repo_id: Repository UUID
        path: Subdirectory path (relative to repo root)
        pattern: Glob pattern to filter files (e.g., '*.md', 'STRUCTURE*')
    """
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))
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

    files: list[FileInfo] = []
    if target_path.is_file():
        files.append(
            FileInfo(
                name=target_path.name,
                path=str(target_path.relative_to(repo_path)),
                type="file",
                size=target_path.stat().st_size,
                extension=target_path.suffix,
            )
        )
    else:
        for item in sorted(target_path.glob(pattern)):
            if item.name.startswith("."):
                continue

            rel_path = str(item.relative_to(repo_path))
            if item.is_dir():
                files.append(
                    FileInfo(
                        name=item.name,
                        path=rel_path,
                        type="directory",
                    )
                )
            else:
                files.append(
                    FileInfo(
                        name=item.name,
                        path=rel_path,
                        type="file",
                        size=item.stat().st_size,
                        extension=item.suffix,
                    )
                )

    return files


@router.get("/{repo_id}/files/tree")
def get_file_tree(
    repo_id: str,
    extensions: str = Query(default=".md", description="Comma-separated extensions to include"),
    db: Session = Depends(get_db),
) -> list[FileInfo]:
    """Get a tree of files matching specified extensions.

    Returns a flat list of all matching files in the repository.
    """
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))
    ext_list = [ext.strip() for ext in extensions.split(",")]

    files: list[FileInfo] = []
    for ext in ext_list:
        if not ext.startswith("."):
            ext = "." + ext
        for item in repo_path.rglob(f"*{ext}"):
            rel_path = item.relative_to(repo_path)
            # Skip hidden and .git directories (check relative path, not absolute)
            if any(part.startswith(".") for part in rel_path.parts):
                continue

            rel_path_str = str(rel_path)
            files.append(
                FileInfo(
                    name=item.name,
                    path=rel_path_str,
                    type="file",
                    size=item.stat().st_size,
                    extension=item.suffix,
                )
            )

    return sorted(files, key=lambda f: f.path)


def _build_tree_from_files(
    files: list[FileInfo],
    modified_files: set[str],
    untracked_files: set[str],
) -> TreeNode:
    """Build hierarchical tree from flat file list."""
    root = TreeNode(name="root", path="", type="directory", children=[])

    # Dictionary to track created directories
    dir_nodes: dict[str, TreeNode] = {"": root}

    for file in sorted(files, key=lambda f: f.path):
        parts = file.path.split("/")

        # Create directory nodes for all parent directories
        current_path = ""
        for _i, part in enumerate(parts[:-1]):
            parent_path = current_path
            current_path = f"{current_path}/{part}" if current_path else part

            if current_path not in dir_nodes:
                dir_node = TreeNode(
                    name=part,
                    path=current_path,
                    type="directory",
                    children=[],
                )
                dir_nodes[current_path] = dir_node
                dir_nodes[parent_path].children.append(dir_node)

        file_node = TreeNode(
            name=file.name,
            path=file.path,
            type="file",
            extension=file.extension,
            size=file.size,
            is_modified=file.path in modified_files,
            is_untracked=file.path in untracked_files,
        )

        parent_path = "/".join(parts[:-1])
        dir_nodes.get(parent_path, root).children.append(file_node)

    def sort_children(node: TreeNode) -> None:
        node.children.sort(key=lambda n: (n.type == "file", n.name.lower()))
        for child in node.children:
            if child.type == "directory":
                sort_children(child)

    sort_children(root)
    return root


@router.get("/{repo_id}/files/tree-hierarchy", response_model=TreeNode)
def get_file_tree_hierarchy(
    repo_id: str,
    extensions: str = Query(default=".md", description="Comma-separated extensions to include"),
    include_git_status: bool = Query(default=True, description="Include git modification status"),
    db: Session = Depends(get_db),
) -> TreeNode:
    """Get hierarchical file tree with git status.

    Returns a nested tree structure suitable for VS Code-like file explorer.
    Directories come first, sorted alphabetically.
    """
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))
    ext_list = [ext.strip() for ext in extensions.split(",")]

    # Get flat file list
    files: list[FileInfo] = []
    seen_paths: set[str] = set()  # Avoid duplicates when using '*'

    # Handle '*' for all files
    if "*" in ext_list:
        for item in repo_path.rglob("*"):
            if not item.is_file():
                continue
            rel_path = item.relative_to(repo_path)
            if any(part.startswith(".") for part in rel_path.parts):
                continue
            rel_path_str = str(rel_path)
            if rel_path_str not in seen_paths:
                seen_paths.add(rel_path_str)
                files.append(
                    FileInfo(
                        name=item.name,
                        path=rel_path_str,
                        type="file",
                        size=item.stat().st_size,
                        extension=item.suffix,
                    )
                )
    else:
        for ext in ext_list:
            if not ext.startswith("."):
                ext = "." + ext
            for item in repo_path.rglob(f"*{ext}"):
                rel_path = item.relative_to(repo_path)
                if any(part.startswith(".") for part in rel_path.parts):
                    continue

                rel_path_str = str(rel_path)
                files.append(
                    FileInfo(
                        name=item.name,
                        path=rel_path_str,
                        type="file",
                        size=item.stat().st_size,
                        extension=item.suffix,
                    )
                )

    # Get git status if requested
    modified_files: set[str] = set()
    untracked_files: set[str] = set()

    if include_git_status:
        try:
            git_status = get_git_status(repo_path)
            modified_files = set(git_status.modified)
            untracked_files = set(git_status.untracked)
        except Exception:
            pass

    return _build_tree_from_files(files, modified_files, untracked_files)


@router.get("/{repo_id}/files/diff", response_model=FileDiff)
def get_file_diff(
    repo_id: str,
    path: str = Query(..., description="File path relative to repo root"),
    staged: bool = Query(default=False, description="Get staged diff instead of working tree diff"),
    db: Session = Depends(get_db),
) -> FileDiff:
    """Get git diff for a specific file.

    Returns the diff content for uncommitted changes.
    For untracked files, returns the full file content as additions.
    """
    import subprocess

    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))
    file_path = repo_path / path

    # Security check
    try:
        file_path = file_path.resolve()
        repo_path_resolved = repo_path.resolve()
        if not str(file_path).startswith(str(repo_path_resolved)):
            raise HTTPException(status_code=400, detail="Invalid path")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Get git status to determine file status
    try:
        git_status = get_git_status(repo_path)
        is_untracked = path in git_status.untracked
    except Exception:
        is_untracked = False

    if is_untracked:
        status = "untracked"
    elif staged:
        status = "staged"
    else:
        status = "modified"

    # Get diff
    diff_content = ""
    additions = 0
    deletions = 0

    if is_untracked:
        # For untracked files, show full content as additions
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            diff_content = "\n".join(f"+{line}" for line in lines)
            additions = len(lines)
        except Exception:
            diff_content = ""
    else:
        # Get git diff
        try:
            args = ["git", "diff"]
            if staged:
                args.append("--staged")
            args.append(path)

            result = subprocess.run(
                args,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
            )
            diff_content = result.stdout

            for line in diff_content.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1
        except Exception:
            diff_content = ""

    return FileDiff(
        path=path,
        diff=diff_content,
        status=status,
        additions=additions,
        deletions=deletions,
    )


def _parse_python_imports(content: str) -> list[dict[str, Any]]:
    """Parse Python import statements and return structured data."""
    imports: list[dict[str, Any]] = []

    from_import_pattern = r"^from\s+([\w.]+)\s+import\s+(.+)$"
    import_pattern = r"^import\s+(.+)$"

    for line_num, line in enumerate(content.split("\n"), 1):
        line = line.strip()

        match = re.match(from_import_pattern, line)
        if match:
            module = match.group(1)
            names = [n.strip().split(" as ")[0].strip() for n in match.group(2).split(",")]
            for name in names:
                if name and name != "*":
                    imports.append(
                        {
                            "type": "from_import",
                            "module": module,
                            "name": name,
                            "line": line_num,
                        }
                    )
            continue

        match = re.match(import_pattern, line)
        if match:
            modules = [m.strip().split(" as ")[0].strip() for m in match.group(1).split(",")]
            for module in modules:
                if module:
                    imports.append(
                        {
                            "type": "import",
                            "module": module,
                            "name": module.split(".")[-1],
                            "line": line_num,
                        }
                    )

    return imports


def _resolve_python_module(
    module_path: str, repo_path: Path, current_file: str | None = None
) -> Path | None:
    """Resolve a Python module path to a file path."""
    parts = module_path.split(".")

    candidates: list[Path] = []

    direct_path = repo_path / "/".join(parts)
    candidates.append(direct_path.with_suffix(".py"))
    candidates.append(direct_path / "__init__.py")

    src_path = repo_path / "src" / "/".join(parts)
    candidates.append(src_path.with_suffix(".py"))
    candidates.append(src_path / "__init__.py")

    if current_file:
        current_dir = (repo_path / current_file).parent
        rel_path = current_dir / "/".join(parts)
        candidates.append(rel_path.with_suffix(".py"))
        candidates.append(rel_path / "__init__.py")

    module_file = parts[-1] + ".py"
    for item in repo_path.rglob(module_file):
        if not any(p.startswith(".") for p in item.relative_to(repo_path).parts):
            candidates.append(item)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def _find_symbol_definitions(
    symbol: str,
    repo_path: Path,
    file_extensions: list[str] | None = None,
) -> list[SymbolDefinition]:
    """Search for symbol definitions in the repository."""
    if file_extensions is None:
        file_extensions = [".py", ".js", ".ts", ".jsx", ".tsx"]

    definitions: list[SymbolDefinition] = []

    patterns: dict[str, list[tuple[str, str]]] = {
        ".py": [
            (rf"^def\s+{re.escape(symbol)}\s*\(", "function"),
            (rf"^class\s+{re.escape(symbol)}\s*[:\(]", "class"),
            (rf"^{re.escape(symbol)}\s*=", "variable"),
            (rf"^\s+def\s+{re.escape(symbol)}\s*\(", "method"),
        ],
        ".js": [
            (rf"function\s+{re.escape(symbol)}\s*\(", "function"),
            (rf"const\s+{re.escape(symbol)}\s*=", "variable"),
            (rf"let\s+{re.escape(symbol)}\s*=", "variable"),
            (rf"class\s+{re.escape(symbol)}\s*[{{\s]", "class"),
            (rf"{re.escape(symbol)}\s*:\s*function", "method"),
            (rf"{re.escape(symbol)}\s*\([^)]*\)\s*{{", "method"),
        ],
        ".ts": [
            (rf"function\s+{re.escape(symbol)}\s*[<\(]", "function"),
            (rf"const\s+{re.escape(symbol)}\s*[=:]", "variable"),
            (rf"let\s+{re.escape(symbol)}\s*[=:]", "variable"),
            (rf"class\s+{re.escape(symbol)}\s*[{{\s<]", "class"),
            (rf"interface\s+{re.escape(symbol)}\s*[{{\s<]", "interface"),
            (rf"type\s+{re.escape(symbol)}\s*[=<]", "type"),
            (
                rf"export\s+(?:default\s+)?(?:function|class|const|let|interface|type)\s+{re.escape(symbol)}",
                "export",
            ),
        ],
    }
    patterns[".jsx"] = patterns[".js"]
    patterns[".tsx"] = patterns[".ts"]

    for ext in file_extensions:
        if ext not in patterns:
            continue

        for file_path in repo_path.rglob(f"*{ext}"):
            rel_path = file_path.relative_to(repo_path)
            if any(p.startswith(".") or p == "node_modules" for p in rel_path.parts):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    for pattern, symbol_type in patterns[ext]:
                        if re.search(pattern, line):
                            definitions.append(
                                SymbolDefinition(
                                    symbol=symbol,
                                    path=str(rel_path),
                                    line=line_num,
                                    type=symbol_type,
                                    preview=line.strip()[:100],
                                    confidence=(
                                        1.0
                                        if line.strip().startswith(
                                            ("def ", "class ", "function ", "const ", "let ")
                                        )
                                        else 0.8
                                    ),
                                )
                            )
                            break  # Only one match per line

            except (UnicodeDecodeError, OSError):
                continue

    definitions.sort(key=lambda d: (-d.confidence, d.path, d.line))
    return definitions


@router.get("/{repo_id}/files/find-definition", response_model=SymbolSearchResult)
def find_definition(
    repo_id: str,
    symbol: str = Query(..., description="Symbol name to find (function, class, variable)"),
    current_file: str | None = Query(default=None, description="Current file path for context"),
    db: Session = Depends(get_db),
) -> SymbolSearchResult:
    """Find symbol definition (Go to Definition).

    Searches for function, class, and variable definitions.
    Also resolves Python imports to their source files.

    Returns the file path and line number of definitions.
    """
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))
    definitions: list[SymbolDefinition] = []

    # 1. If current_file is provided and is Python, check if symbol is an import
    if current_file and current_file.endswith(".py"):
        file_path = repo_path / current_file
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                imports = _parse_python_imports(content)

                for imp in imports:
                    if imp["name"] == symbol:
                        if imp["type"] == "from_import":
                            module_file = _resolve_python_module(
                                imp["module"], repo_path, current_file
                            )
                            if module_file:
                                module_content = module_file.read_text(encoding="utf-8")
                                for line_num, line in enumerate(module_content.split("\n"), 1):
                                    if re.match(
                                        rf"^(def|class)\s+{re.escape(symbol)}\s*[\(:]", line
                                    ):
                                        definitions.append(
                                            SymbolDefinition(
                                                symbol=symbol,
                                                path=str(module_file.relative_to(repo_path)),
                                                line=line_num,
                                                type=(
                                                    "function"
                                                    if line.strip().startswith("def")
                                                    else "class"
                                                ),
                                                preview=line.strip()[:100],
                                                confidence=1.0,
                                            )
                                        )
                                        break

                        elif imp["type"] == "import":
                            module_file = _resolve_python_module(
                                imp["module"], repo_path, current_file
                            )
                            if module_file:
                                definitions.append(
                                    SymbolDefinition(
                                        symbol=symbol,
                                        path=str(module_file.relative_to(repo_path)),
                                        line=1,
                                        type="import",
                                        preview=f"Module: {imp['module']}",
                                        confidence=1.0,
                                    )
                                )
            except Exception:
                pass

    if not definitions:
        definitions = _find_symbol_definitions(symbol, repo_path)

    if definitions:
        return SymbolSearchResult(
            found=True,
            definitions=definitions[:10],  # Limit to 10 results
            message=f"Found {len(definitions)} definition(s) for '{symbol}'",
        )

    return SymbolSearchResult(
        found=False,
        definitions=[],
        message=f"No definition found for '{symbol}'",
    )


@router.get("/{repo_id}/structure")
def get_structure_files(
    repo_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get all STRUCTURE.md files with their content.

    Returns a list of STRUCTURE.md files found in the repository,
    including their full content for display.
    """
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))

    structure_files: list[dict[str, Any]] = []
    for item in repo_path.rglob("STRUCTURE.md"):
        rel_path = item.relative_to(repo_path)
        # Skip hidden directories (check relative path, not absolute)
        if any(part.startswith(".") for part in rel_path.parts):
            continue

        rel_path_str = str(rel_path)
        try:
            content = item.read_text(encoding="utf-8")
            structure_files.append(
                {
                    "path": rel_path_str,
                    "directory": (
                        str(item.parent.relative_to(repo_path)) if item.parent != repo_path else ""
                    ),
                    "content": content,
                    "size": item.stat().st_size,
                }
            )
        except (UnicodeDecodeError, OSError):
            continue

    structure_files.sort(key=lambda f: (f["path"].count("/"), f["path"]))

    return {
        "repo_id": repo_id,
        "repo_name": repo.name,
        "total": len(structure_files),
        "files": structure_files,
    }


@router.get("/{repo_id}/files/content", response_model=FileContent)
def read_file(
    repo_id: str,
    path: str = Query(..., description="File path relative to repo root"),
    db: Session = Depends(get_db),
) -> FileContent:
    """Read file content.

    Only text files are supported. Binary files will return an error.
    """
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))
    file_path = repo_path / path

    # Security check
    try:
        file_path = file_path.resolve()
        repo_path_resolved = repo_path.resolve()
        if not str(file_path).startswith(str(repo_path_resolved)):
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
        raise HTTPException(
            status_code=400, detail=f"File too large (max {MAX_FILE_SIZE // 1024}KB)"
        )

    try:
        content = file_path.read_text(encoding="utf-8")
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
    data: FileWriteRequest = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Write file content.

    Updates an existing file or creates a new one.
    Optionally commits the change with the provided message.
    """
    from ...db.models import Repository

    repo = get_or_404(db, Repository, repo_id)

    repo_path = Path(cast(str, repo.local_path))
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
            detail=f"File extension not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Check content size
    if len(data.content.encode("utf-8")) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400, detail=f"Content too large (max {MAX_FILE_SIZE // 1024}KB)"
        )

    is_new = not file_path.exists()
    file_path.write_text(data.content, encoding="utf-8")

    committed = False
    if data.commit_message:
        import subprocess

        try:
            subprocess.run(
                ["git", "add", str(file_path)],
                cwd=str(repo_path),
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", data.commit_message],
                cwd=str(repo_path),
                check=True,
                capture_output=True,
            )
            committed = True
        except subprocess.CalledProcessError:
            pass

    return {
        "status": "created" if is_new else "updated",
        "path": path,
        "size": len(data.content.encode("utf-8")),
        "committed": committed,
    }
