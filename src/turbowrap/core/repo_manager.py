"""Repository management."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import LinkType, Repository, RepositoryLink, Setting
from ..exceptions import RepositoryError
from ..utils.file_utils import (
    detect_repo_type,
    discover_files,
    load_file_content,
)
from ..utils.git_utils import (
    clone_repo,
    get_repo_status,
    parse_github_url,
    pull_repo,
)


def _calculate_token_totals(repo_path: Path, files: list) -> dict:
    """Calculate total tokens for a list of files.

    Args:
        repo_path: Repository root path.
        files: List of FileInfo objects.

    Returns:
        Dictionary with count, total_chars, total_lines, total_tokens.
    """
    total_chars = 0
    total_lines = 0
    total_tokens = 0

    for file_info in files:
        # Load content to calculate tokens
        load_file_content(repo_path, file_info)
        total_chars += file_info.chars
        total_lines += file_info.lines
        total_tokens += file_info.tokens

    return {
        "count": len(files),
        "chars": total_chars,
        "lines": total_lines,
        "tokens": total_tokens,
    }


class RepoManager:
    """Manages repository operations."""

    def __init__(self, db: Session):
        """Initialize with database session."""
        self.db = db
        self._settings = get_settings()

    def _validate_path(self, path: Path, base_dir: Path | None = None) -> Path:
        """Validate a path for security issues.

        Checks for:
        - Path traversal attacks (../)
        - Symlinks pointing outside allowed directories
        - Absolute paths when relative expected

        Args:
            path: Path to validate.
            base_dir: If provided, ensures path stays within this directory.

        Returns:
            Resolved, validated Path.

        Raises:
            RepositoryError: If path is invalid or potentially malicious.
        """
        # Resolve to absolute path (follows symlinks)
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as e:
            raise RepositoryError(f"Invalid path: {path} - {e}")

        # Check for symlink escape if base_dir provided
        if base_dir:
            base_resolved = base_dir.resolve()

            # Check if resolved path is within base directory
            try:
                resolved.relative_to(base_resolved)
            except ValueError:
                raise RepositoryError(
                    f"Path traversal detected: {path} resolves outside {base_dir}"
                )

            # Additionally check if it's a symlink pointing outside
            if path.is_symlink():
                link_target = path.readlink()
                if link_target.is_absolute():
                    target_resolved = link_target.resolve()
                else:
                    target_resolved = (path.parent / link_target).resolve()

                try:
                    target_resolved.relative_to(base_resolved)
                except ValueError:
                    raise RepositoryError(
                        f"Symlink escape detected: {path} points to {target_resolved} "
                        f"outside {base_dir}"
                    )

        # Check for suspicious path components
        path_str = str(path)
        if ".." in path_str:
            # Additional check even after resolve() for logging/alerting
            raise RepositoryError(f"Path traversal attempt detected: {path}")

        return resolved

    def _get_token(self, request_token: str | None = None) -> str | None:
        """Get GitHub token from request, database, or config.

        Priority: request > database > environment.

        Args:
            request_token: Token passed in request (takes priority).

        Returns:
            Token or None.
        """
        # 1. Request token has highest priority
        if request_token:
            return request_token

        # 2. Check database
        db_setting = self.db.query(Setting).filter(Setting.key == "github_token").first()
        if db_setting and db_setting.value:
            return db_setting.value

        # 3. Fall back to environment variable
        return self._settings.agents.github_token

    def clone(
        self,
        url: str,
        branch: str = "main",
        token: str | None = None,
        workspace_path: str | None = None,
    ) -> Repository:
        """Clone a new repository.

        Args:
            url: GitHub repository URL.
            branch: Branch to clone.
            token: Optional GitHub token for private repos.
            workspace_path: Monorepo workspace path (e.g., 'packages/frontend').
                           Allows same URL to be cloned multiple times with different workspaces.

        Returns:
            Created Repository record.
        """
        # Parse URL
        repo_info = parse_github_url(url)

        # Check if already exists with same URL AND workspace_path
        # This allows multiple clones of same repo with different workspaces
        query = self.db.query(Repository).filter(Repository.url == repo_info.url)
        if workspace_path:
            query = query.filter(Repository.workspace_path == workspace_path)
        else:
            query = query.filter(Repository.workspace_path.is_(None))

        existing = query.first()

        if existing:
            return self.sync(existing.id, token)

        # Get effective token
        effective_token = self._get_token(token)

        # Clone to local
        local_path = clone_repo(repo_info.url, branch, effective_token)

        # Detect repo type and calculate tokens
        be_files, fe_files = discover_files(local_path)
        repo_type = detect_repo_type(len(be_files), len(fe_files))

        # Calculate token stats for all files
        be_stats = _calculate_token_totals(local_path, be_files)
        fe_stats = _calculate_token_totals(local_path, fe_files)

        # Create DB record with detailed stats
        # If workspace_path is set, append it to the name for display
        display_name = repo_info.full_name
        if workspace_path:
            display_name = f"{repo_info.full_name} [{workspace_path}]"

        repo = Repository(
            name=display_name,
            url=repo_info.url,
            local_path=str(local_path),
            default_branch=branch,
            status="active",
            repo_type=repo_type,
            workspace_path=workspace_path,
            last_synced_at=datetime.utcnow(),
            metadata_={
                "be_files": be_stats,
                "fe_files": fe_stats,
                "total_tokens": be_stats["tokens"] + fe_stats["tokens"],
                "total_files": be_stats["count"] + fe_stats["count"],
            },
        )

        self.db.add(repo)
        self.db.commit()
        self.db.refresh(repo)

        return repo

    def ensure_repo_exists(self, repo_id: str, token: str | None = None) -> Repository:
        """Ensure repository local path exists, re-clone if missing.

        This handles the case where local files were deleted (e.g., disk cleanup)
        but the database record still exists.

        Args:
            repo_id: Repository ID.
            token: Optional GitHub token for private repos.

        Returns:
            Repository with valid local path.

        Raises:
            RepositoryError: If repository not found in DB or re-clone fails.
        """
        repo = self.db.query(Repository).filter(Repository.id == repo_id).first()

        if not repo:
            raise RepositoryError(f"Repository not found: {repo_id}")

        local_path = Path(repo.local_path)

        # Check if local path exists
        if local_path.exists() and (local_path / ".git").exists():
            return repo  # All good

        # Local path missing - re-clone
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Repository local path missing, re-cloning: {repo.name} -> {local_path}")

        effective_token = self._get_token(token)

        try:
            # Re-clone to the same path
            clone_repo(repo.url, repo.default_branch or "main", effective_token, target_path=local_path)

            # Update sync timestamp
            repo.last_synced_at = datetime.utcnow()
            repo.status = "active"
            self.db.commit()
            self.db.refresh(repo)

            logger.info(f"Successfully re-cloned repository: {repo.name}")
            return repo

        except Exception as e:
            repo.status = "error"
            self.db.commit()
            raise RepositoryError(f"Failed to re-clone repository {repo.name}: {e}") from e

    def sync(self, repo_id: str, token: str | None = None) -> Repository:
        """Sync (pull) an existing repository.

        Args:
            repo_id: Repository ID.
            token: Optional GitHub token for private repos.

        Returns:
            Updated Repository record.

        Raises:
            RepositoryError: If repository not found or path validation fails.
        """
        repo = self.db.query(Repository).filter(Repository.id == repo_id).first()

        if not repo:
            raise RepositoryError(f"Repository not found: {repo_id}")

        # Ensure local path exists before syncing
        repo = self.ensure_repo_exists(repo_id, token)

        repo.status = "syncing"
        self.db.commit()

        try:
            local_path = Path(repo.local_path)

            # Validate path stays within repos directory
            self._validate_path(local_path, base_dir=self._settings.repos_dir)

            effective_token = self._get_token(token)
            pull_repo(local_path, effective_token)

            # Re-detect files and recalculate tokens
            be_files, fe_files = discover_files(local_path)
            be_stats = _calculate_token_totals(local_path, be_files)
            fe_stats = _calculate_token_totals(local_path, fe_files)

            repo.status = "active"
            repo.last_synced_at = datetime.utcnow()
            repo.metadata_ = {
                "be_files": be_stats,
                "fe_files": fe_stats,
                "total_tokens": be_stats["tokens"] + fe_stats["tokens"],
                "total_files": be_stats["count"] + fe_stats["count"],
            }
            self.db.commit()
            self.db.refresh(repo)

            return repo

        except Exception as e:
            repo.status = "error"
            self.db.commit()
            raise RepositoryError(f"Sync failed: {e}") from e

    def get(self, repo_id: str) -> Repository | None:
        """Get repository by ID."""
        return self.db.query(Repository).filter(Repository.id == repo_id).first()

    def get_by_name(self, name: str) -> Repository | None:
        """Get repository by name (owner/repo)."""
        return self.db.query(Repository).filter(Repository.name == name).first()

    def list(self, status: str | None = None, project_name: str | None = None) -> list[Repository]:
        """List all repositories.

        Args:
            status: Optional status filter.
            project_name: Optional project name filter.

        Returns:
            List of Repository records.
        """
        query = self.db.query(Repository)

        if status:
            query = query.filter(Repository.status == status)

        if project_name:
            query = query.filter(Repository.project_name == project_name)

        return query.order_by(Repository.updated_at.desc()).all()

    def delete(self, repo_id: str, delete_local: bool = True) -> None:
        """Delete a repository.

        Args:
            repo_id: Repository ID.
            delete_local: Also delete local files.

        Raises:
            RepositoryError: If repository not found or path validation fails.
        """
        import shutil

        repo = self.get(repo_id)

        if not repo:
            raise RepositoryError(f"Repository not found: {repo_id}")

        if delete_local:
            local_path = Path(repo.local_path)

            # CRITICAL: Validate path before deletion to prevent directory traversal attacks
            # This ensures we only delete within the repos directory
            self._validate_path(local_path, base_dir=self._settings.repos_dir)

            if local_path.exists():
                shutil.rmtree(local_path)

        self.db.delete(repo)
        self.db.commit()

    def get_status(self, repo_id: str) -> dict:
        """Get detailed repository status.

        Args:
            repo_id: Repository ID.

        Returns:
            Status dictionary.
        """
        repo = self.get(repo_id)

        if not repo:
            raise RepositoryError(f"Repository not found: {repo_id}")

        local_path = Path(repo.local_path)
        git_status = get_repo_status(local_path)

        # Parse file stats from metadata if available
        files_stats = None
        if repo.metadata_ and isinstance(repo.metadata_, dict):
            be_count = repo.metadata_.get("be_files")
            fe_count = repo.metadata_.get("fe_files")
            if isinstance(be_count, int) and isinstance(fe_count, int):
                files_stats = {"be_files": be_count, "fe_files": fe_count}

        return {
            "id": repo.id,
            "name": repo.name,
            "status": repo.status,
            "repo_type": repo.repo_type,
            "last_synced_at": repo.last_synced_at.isoformat() if repo.last_synced_at else None,
            "git": {
                "branch": git_status.branch,
                "is_clean": git_status.is_clean,
                "modified": git_status.modified,
                "untracked": git_status.untracked,
            },
            "files": files_stats,
        }

    # --- Repository Link Methods ---

    def link_repositories(
        self,
        source_id: str,
        target_id: str,
        link_type: str,
        metadata: dict | None = None,
    ) -> RepositoryLink:
        """Create a link between two repositories.

        Args:
            source_id: Source repository UUID.
            target_id: Target repository UUID.
            link_type: Type of link (from LinkType enum values).
            metadata: Optional additional metadata.

        Returns:
            Created RepositoryLink record.

        Raises:
            RepositoryError: If source or target not found, or link already exists.
        """
        # Validate repositories exist
        source = self.get(source_id)
        if not source:
            raise RepositoryError(f"Source repository not found: {source_id}")

        target = self.get(target_id)
        if not target:
            raise RepositoryError(f"Target repository not found: {target_id}")

        # Prevent self-linking
        if source_id == target_id:
            raise RepositoryError("Cannot link a repository to itself")

        # Validate link type
        try:
            LinkType(link_type)
        except ValueError:
            valid_types = [t.value for t in LinkType]
            raise RepositoryError(f"Invalid link type: {link_type}. Valid types: {valid_types}")

        # Check for existing link (same type)
        existing = (
            self.db.query(RepositoryLink)
            .filter(
                RepositoryLink.source_repo_id == source_id,
                RepositoryLink.target_repo_id == target_id,
                RepositoryLink.link_type == link_type,
            )
            .first()
        )

        if existing:
            raise RepositoryError(
                f"Link already exists: {source.name} --{link_type}--> {target.name}"
            )

        # Create link
        link = RepositoryLink(
            source_repo_id=source_id,
            target_repo_id=target_id,
            link_type=link_type,
            metadata_=metadata,
        )

        self.db.add(link)
        self.db.commit()
        self.db.refresh(link)

        return link

    def unlink_repositories(self, link_id: str) -> None:
        """Remove a repository link.

        Args:
            link_id: Link UUID to remove.

        Raises:
            RepositoryError: If link not found.
        """
        link = self.db.query(RepositoryLink).filter(RepositoryLink.id == link_id).first()

        if not link:
            raise RepositoryError(f"Link not found: {link_id}")

        self.db.delete(link)
        self.db.commit()

    def get_linked_repos(
        self,
        repo_id: str,
        link_type: str | None = None,
        direction: str | None = None,
    ) -> list[dict]:
        """Get all repositories linked to a repository.

        Args:
            repo_id: Repository UUID.
            link_type: Optional filter by link type.
            direction: Optional filter: 'outgoing', 'incoming', or None (both).

        Returns:
            List of dicts with repo info, link details, and direction.

        Raises:
            RepositoryError: If repository not found.
        """
        repo = self.get(repo_id)
        if not repo:
            raise RepositoryError(f"Repository not found: {repo_id}")

        linked_repos = []

        # Outgoing links (this repo is the source)
        if direction is None or direction == "outgoing":
            query = self.db.query(RepositoryLink).filter(RepositoryLink.source_repo_id == repo_id)
            if link_type:
                query = query.filter(RepositoryLink.link_type == link_type)

            for link in query.all():
                linked_repos.append(
                    {
                        "id": link.target_repo.id,
                        "name": link.target_repo.name,
                        "repo_type": link.target_repo.repo_type,
                        "link_id": link.id,
                        "link_type": link.link_type,
                        "direction": "outgoing",
                    }
                )

        # Incoming links (this repo is the target)
        if direction is None or direction == "incoming":
            query = self.db.query(RepositoryLink).filter(RepositoryLink.target_repo_id == repo_id)
            if link_type:
                query = query.filter(RepositoryLink.link_type == link_type)

            for link in query.all():
                linked_repos.append(
                    {
                        "id": link.source_repo.id,
                        "name": link.source_repo.name,
                        "repo_type": link.source_repo.repo_type,
                        "link_id": link.id,
                        "link_type": link.link_type,
                        "direction": "incoming",
                    }
                )

        return linked_repos

    def get_link(self, link_id: str) -> RepositoryLink | None:
        """Get a specific link by ID.

        Args:
            link_id: Link UUID.

        Returns:
            RepositoryLink or None if not found.
        """
        return self.db.query(RepositoryLink).filter(RepositoryLink.id == link_id).first()
