"""Repository management."""

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..db.models import Repository
from ..utils.git_utils import (
    clone_repo,
    pull_repo,
    get_repo_status,
    parse_github_url,
    get_local_path,
)
from ..utils.file_utils import (
    discover_files,
    detect_repo_type,
    load_file_content,
)
from ..exceptions import RepositoryError


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

    def clone(self, url: str, branch: str = "main") -> Repository:
        """Clone a new repository.

        Args:
            url: GitHub repository URL.
            branch: Branch to clone.

        Returns:
            Created Repository record.
        """
        # Parse URL
        repo_info = parse_github_url(url)

        # Check if already exists
        existing = self.db.query(Repository).filter(
            Repository.url == repo_info.url
        ).first()

        if existing:
            return self.sync(existing.id)

        # Clone to local
        local_path = clone_repo(repo_info.url, branch)

        # Detect repo type and calculate tokens
        be_files, fe_files = discover_files(local_path)
        repo_type = detect_repo_type(len(be_files), len(fe_files))

        # Calculate token stats for all files
        be_stats = _calculate_token_totals(local_path, be_files)
        fe_stats = _calculate_token_totals(local_path, fe_files)

        # Create DB record with detailed stats
        repo = Repository(
            name=repo_info.full_name,
            url=repo_info.url,
            local_path=str(local_path),
            default_branch=branch,
            status="active",
            repo_type=repo_type,
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

    def sync(self, repo_id: str) -> Repository:
        """Sync (pull) an existing repository.

        Args:
            repo_id: Repository ID.

        Returns:
            Updated Repository record.
        """
        repo = self.db.query(Repository).filter(Repository.id == repo_id).first()

        if not repo:
            raise RepositoryError(f"Repository not found: {repo_id}")

        repo.status = "syncing"
        self.db.commit()

        try:
            local_path = Path(repo.local_path)
            pull_repo(local_path)

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

    def list(self, status: str | None = None) -> list[Repository]:
        """List all repositories.

        Args:
            status: Optional status filter.

        Returns:
            List of Repository records.
        """
        query = self.db.query(Repository)

        if status:
            query = query.filter(Repository.status == status)

        return query.order_by(Repository.updated_at.desc()).all()

    def delete(self, repo_id: str, delete_local: bool = True) -> None:
        """Delete a repository.

        Args:
            repo_id: Repository ID.
            delete_local: Also delete local files.
        """
        repo = self.get(repo_id)

        if not repo:
            raise RepositoryError(f"Repository not found: {repo_id}")

        if delete_local:
            local_path = Path(repo.local_path)
            if local_path.exists():
                import shutil
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
            "files": repo.metadata_,
        }
