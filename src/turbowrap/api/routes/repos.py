"""Repository routes."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from github import GithubException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.repo_manager import RepoManager
from ...exceptions import RepositoryError
from ...utils.git_utils import get_repo_status as get_git_status
from ...utils.github_browse import FolderListResponse, list_repo_folders
from ..deps import get_db
from ..schemas.repos import (
    LinkCreate,
    LinkedRepoSummary,
    LinkResponse,
    RepoCreate,
    RepoResponse,
    RepoStatus,
)

router = APIRouter(prefix="/repos", tags=["repositories"])


# --- File Management Schemas ---

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


# Required for self-referencing model
TreeNode.model_rebuild()


class FileDiff(BaseModel):
    """Diff for a single file."""
    path: str
    diff: str
    status: str  # 'modified', 'untracked', 'staged'
    additions: int = 0
    deletions: int = 0


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
):
    """List all repositories, optionally filtered by status or project."""
    manager = RepoManager(db)
    return manager.list(status=status, project_name=project)


@router.get("/github/folders", response_model=FolderListResponse)
def list_github_folders(
    url: str = Query(..., description="GitHub repository URL"),
    path: str = Query(default="", description="Subdirectory path to browse"),
    branch: str = Query(default="main", description="Branch to browse"),
    db: Session = Depends(get_db),
):
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
    token = token_setting.value if token_setting else None

    try:
        return list_repo_folders(url, path, branch, token)
    except GithubException as e:
        if e.status == 401:
            raise HTTPException(
                status_code=401,
                detail="Token GitHub richiesto per repository private. Configuralo nelle Impostazioni.",
            )
        elif e.status == 404:
            raise HTTPException(
                status_code=404,
                detail="Repository o percorso non trovato. Verifica l'URL e il branch.",
            )
        elif e.status == 403:
            raise HTTPException(
                status_code=403,
                detail="Limite API GitHub raggiunto. Riprova tra qualche minuto.",
            )
        raise HTTPException(status_code=500, detail=f"Errore GitHub API: {e}")
    except RepositoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    """List all unique project names with their repository counts."""
    from sqlalchemy import func

    from ...db.models import Repository

    results = (
        db.query(
            Repository.project_name,
            func.count(Repository.id).label("repo_count")
        )
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
        "projects": [
            {"name": name, "repo_count": count}
            for name, count in results
        ],
        "unassigned_count": unassigned,
    }


@router.post("", response_model=RepoResponse)
def clone_repo(
    data: RepoCreate,
    db: Session = Depends(get_db),
):
    """Clone a new repository.

    For private repos, provide a GitHub token via:
    - `token` field in request body, OR
    - `GITHUB_TOKEN` environment variable

    For monorepos, provide `workspace_path` to scope operations to a subfolder.
    The same repo URL can be cloned multiple times with different workspace paths.
    """
    manager = RepoManager(db)
    try:
        return manager.clone(
            data.url,
            data.branch,
            data.token,
            workspace_path=data.workspace_path,
        )
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
):
    """Get repository details."""
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.patch("/{repo_id}", response_model=RepoResponse)
def update_repo(
    repo_id: str,
    data: RepoUpdate,
    db: Session = Depends(get_db),
):
    """Update repository metadata (project_name, repo_type)."""
    from ...db.models import Repository

    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if data.project_name is not None:
        repo.project_name = data.project_name if data.project_name else None
    if data.repo_type is not None:
        repo.repo_type = data.repo_type if data.repo_type else None

    db.commit()
    db.refresh(repo)
    return repo


@router.post("/{repo_id}/sync", response_model=RepoResponse)
def sync_repo(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """Sync (pull) repository."""
    manager = RepoManager(db)
    try:
        return manager.sync(repo_id)
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
        return manager.get_status(repo_id)
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
        return manager.get_linked_repos(
            repo_id=repo_id,
            link_type=link_type,
            direction=direction,
        )
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
            rel_path = item.relative_to(repo_path)
            # Skip hidden and .git directories (check relative path, not absolute)
            if any(part.startswith('.') for part in rel_path.parts):
                continue

            rel_path = str(rel_path)
            files.append(FileInfo(
                name=item.name,
                path=rel_path,
                type="file",
                size=item.stat().st_size,
                extension=item.suffix,
            ))

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
        for i, part in enumerate(parts[:-1]):
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

        # Add file node
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

    # Sort children: directories first, then alphabetically
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
):
    """Get hierarchical file tree with git status.

    Returns a nested tree structure suitable for VS Code-like file explorer.
    Directories come first, sorted alphabetically.
    """
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    ext_list = [ext.strip() for ext in extensions.split(',')]

    # Get flat file list
    files = []
    for ext in ext_list:
        if not ext.startswith('.'):
            ext = '.' + ext
        for item in repo_path.rglob(f'*{ext}'):
            rel_path = item.relative_to(repo_path)
            # Skip hidden and .git directories
            if any(part.startswith('.') for part in rel_path.parts):
                continue

            rel_path_str = str(rel_path)
            files.append(FileInfo(
                name=item.name,
                path=rel_path_str,
                type="file",
                size=item.stat().st_size,
                extension=item.suffix,
            ))

    # Get git status if requested
    modified_files: set[str] = set()
    untracked_files: set[str] = set()

    if include_git_status:
        try:
            git_status = get_git_status(repo_path)
            modified_files = set(git_status.modified)
            untracked_files = set(git_status.untracked)
        except Exception:
            # If git status fails, just continue without it
            pass

    return _build_tree_from_files(files, modified_files, untracked_files)


@router.get("/{repo_id}/files/diff", response_model=FileDiff)
def get_file_diff(
    repo_id: str,
    path: str = Query(..., description="File path relative to repo root"),
    staged: bool = Query(default=False, description="Get staged diff instead of working tree diff"),
    db: Session = Depends(get_db),
):
    """Get git diff for a specific file.

    Returns the diff content for uncommitted changes.
    For untracked files, returns the full file content as additions.
    """
    import subprocess

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

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Get git status to determine file status
    try:
        git_status = get_git_status(repo_path)
        is_modified = path in git_status.modified
        is_untracked = path in git_status.untracked
    except Exception:
        is_modified = False
        is_untracked = False

    # Determine status
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
            content = file_path.read_text(encoding='utf-8')
            lines = content.split('\n')
            diff_content = '\n'.join(f'+{line}' for line in lines)
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

            # Count additions/deletions
            for line in diff_content.split('\n'):
                if line.startswith('+') and not line.startswith('+++'):
                    additions += 1
                elif line.startswith('-') and not line.startswith('---'):
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


@router.get("/{repo_id}/structure")
def get_structure_files(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """Get all STRUCTURE.md files with their content.

    Returns a list of STRUCTURE.md files found in the repository,
    including their full content for display.
    """
    manager = RepoManager(db)
    repo = manager.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)

    structure_files = []
    for item in repo_path.rglob('STRUCTURE.md'):
        rel_path = item.relative_to(repo_path)
        # Skip hidden directories (check relative path, not absolute)
        if any(part.startswith('.') for part in rel_path.parts):
            continue

        rel_path = str(rel_path)
        try:
            content = item.read_text(encoding='utf-8')
            structure_files.append({
                "path": rel_path,
                "directory": str(item.parent.relative_to(repo_path)) if item.parent != repo_path else "",
                "content": content,
                "size": item.stat().st_size,
            })
        except (UnicodeDecodeError, OSError):
            continue

    # Sort by path depth (root first) then alphabetically
    structure_files.sort(key=lambda f: (f["path"].count('/'), f["path"]))

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
        except subprocess.CalledProcessError:
            # File written but commit failed
            pass

    return {
        "status": "created" if is_new else "updated",
        "path": path,
        "size": len(data.content.encode('utf-8')),
        "committed": committed,
    }
