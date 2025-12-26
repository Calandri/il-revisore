"""GitHub repository browsing utilities."""

from typing import Any

from github import Github, GithubException
from pydantic import BaseModel

from .git_utils import parse_github_url


class FolderInfo(BaseModel):
    """Folder information from GitHub API."""

    name: str
    path: str
    type: str = "dir"
    has_children: bool = True


class FolderListResponse(BaseModel):
    """Response for folder listing."""

    folders: list[FolderInfo]
    current_path: str
    parent_path: str | None
    repo_name: str


def list_repo_folders(
    url: str,
    path: str = "",
    branch: str = "main",
    token: str | None = None,
) -> FolderListResponse:
    """List directories in a GitHub repository using GitHub API.

    Args:
        url: GitHub repository URL (https or git@).
        path: Subdirectory path to list (default: root).
        branch: Branch to browse (default: main).
        token: Optional GitHub token for private repos.

    Returns:
        FolderListResponse with list of folders.

    Raises:
        GithubException: If API call fails (401, 404, rate limit, etc.).
    """
    # Parse URL to get owner/repo
    repo_info = parse_github_url(url)

    # Initialize GitHub client
    github = Github(token) if token else Github()
    repo = github.get_repo(f"{repo_info.owner}/{repo_info.name}")

    # Get contents at path
    try:
        contents = repo.get_contents(path, ref=branch)
    except GithubException as e:
        if e.status == 404 and path:
            # Path not found, return empty list
            return FolderListResponse(
                folders=[],
                current_path=path,
                parent_path=_get_parent_path(path),
                repo_name=repo_info.full_name,
            )
        raise

    # Handle single file case (when path is a file, not directory)
    if not isinstance(contents, list):
        contents = [contents]

    # Filter to directories only
    folders: list[FolderInfo] = []
    for item in contents:
        if item.type == "dir":
            folders.append(
                FolderInfo(
                    name=item.name,
                    path=item.path,
                    type="dir",
                    has_children=True,  # Assume true, will be loaded on demand
                )
            )

    # Sort alphabetically
    folders.sort(key=lambda x: x.name.lower())

    return FolderListResponse(
        folders=folders,
        current_path=path,
        parent_path=_get_parent_path(path),
        repo_name=repo_info.full_name,
    )


def _get_parent_path(path: str) -> str | None:
    """Get parent directory path.

    Args:
        path: Current path.

    Returns:
        Parent path or None if at root.
    """
    if not path:
        return None

    parts = path.rstrip("/").split("/")
    if len(parts) <= 1:
        return ""  # Return empty string for root

    return "/".join(parts[:-1])
