"""Repository schemas."""

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LinkTypeEnum(str, Enum):
    """Link type for API requests/responses."""

    FRONTEND_FOR = "frontend_for"
    BACKEND_FOR = "backend_for"
    SHARED_LIB = "shared_lib"
    MICROSERVICE = "microservice"
    MONOREPO_MODULE = "monorepo_module"
    RELATED = "related"


class RepoCreate(BaseModel):
    """Request to clone a repository."""

    url: str = Field(
        ...,
        min_length=10,
        description="GitHub repository URL",
        json_schema_extra={"examples": ["https://github.com/owner/repo"]},
    )
    branch: str = Field(
        default="main",
        min_length=1,
        max_length=100,
        description="Branch to clone",
    )
    token: str | None = Field(
        default=None,
        min_length=1,
        description="GitHub token for private repositories (overrides env GITHUB_TOKEN)",
    )
    workspace_path: str | None = Field(
        default=None,
        max_length=512,
        description="Monorepo workspace path (e.g., 'packages/frontend'). "
        "If set, fix/lint operations are scoped to this folder.",
    )

    @field_validator("url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        """Validate GitHub URL format."""
        pattern = r"^https?://github\.com/[\w.-]+/[\w.-]+/?$"
        if not re.match(pattern, v):
            raise ValueError("Must be a valid GitHub URL (https://github.com/owner/repo)")
        return v.rstrip("/")


def _sanitize_local_path(path: str) -> str:
    """Sanitize local path to hide sensitive directory names.

    Replaces the home directory portion with a generic placeholder
    to avoid exposing usernames or system structure in API responses.
    """
    import os

    home = os.path.expanduser("~")
    if path.startswith(home):
        return path.replace(home, "~", 1)
    return path


class RepoResponse(BaseModel):
    """Repository response."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(..., description="Repository UUID")
    name: str = Field(..., description="Repository name (owner/repo)")
    url: str = Field(..., description="GitHub URL")
    local_path: str = Field(..., description="Local filesystem path (sanitized)")
    default_branch: str = Field(..., description="Default branch name")
    status: Literal["active", "syncing", "error"] = Field(..., description="Repository status")
    repo_type: Literal["backend", "frontend", "fullstack", "unknown"] | None = Field(
        default=None, description="Detected repository type"
    )
    project_name: str | None = Field(
        default=None, description="Project name to group related repositories"
    )
    workspace_path: str | None = Field(
        default=None, description="Monorepo workspace path (e.g., 'packages/frontend')"
    )
    last_synced_at: datetime | None = Field(default=None, description="Last sync timestamp")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional metadata")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    # Disk usage fields (computed from metadata)
    disk_size_bytes: int | None = Field(default=None, description="Disk space used in bytes")
    estimated_cost_usd: float | None = Field(
        default=None, description="Estimated monthly AWS S3 storage cost in USD"
    )

    @field_validator("local_path", mode="before")
    @classmethod
    def sanitize_path(cls, v: str) -> str:
        """Sanitize local_path to hide sensitive directories."""
        return _sanitize_local_path(v) if v else v

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, v: Any) -> dict[str, Any] | None:
        """Convert metadata from SQLAlchemy model."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        # Try to get actual metadata from SQLAlchemy object
        if hasattr(v, "metadata_"):
            return getattr(v, "metadata_", None)
        # Handle SQLAlchemy MetaData collision - return None
        return None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "RepoResponse":
        """Override to handle SQLAlchemy metadata_ attribute."""
        # If it's a SQLAlchemy model, extract metadata_ manually
        if hasattr(obj, "metadata_") and not hasattr(obj, "metadata"):
            metadata = obj.metadata_ or {}
            # Extract disk size from metadata
            disk_size = metadata.get("disk_size_bytes")
            # Calculate AWS S3 cost: $0.023/GB/month
            estimated_cost = None
            if disk_size is not None:
                estimated_cost = round((disk_size / (1024**3)) * 0.023, 4)
            # Create a dict with the data
            data = {
                "id": obj.id,
                "name": obj.name,
                "url": obj.url,
                "local_path": obj.local_path,  # Will be sanitized by validator
                "default_branch": obj.default_branch,
                "status": obj.status,
                "repo_type": obj.repo_type,
                "project_name": getattr(obj, "project_name", None),
                "workspace_path": getattr(obj, "workspace_path", None),
                "last_synced_at": obj.last_synced_at,
                "metadata": obj.metadata_,  # Map metadata_ to metadata
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
                "disk_size_bytes": disk_size,
                "estimated_cost_usd": estimated_cost,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


class GitStatus(BaseModel):
    """Git repository status."""

    branch: str = Field(..., description="Current branch")
    is_clean: bool = Field(..., description="True if no uncommitted changes")
    modified: list[str] = Field(default_factory=list, description="Modified files")
    untracked: list[str] = Field(default_factory=list, description="Untracked files")


class FileStats(BaseModel):
    """Repository file statistics."""

    be_files: int = Field(default=0, ge=0, description="Backend file count")
    fe_files: int = Field(default=0, ge=0, description="Frontend file count")


class RepoStatus(BaseModel):
    """Detailed repository status."""

    id: str = Field(..., description="Repository UUID")
    name: str = Field(..., description="Repository name")
    status: Literal["active", "syncing", "error"] = Field(..., description="Current status")
    repo_type: Literal["backend", "frontend", "fullstack", "unknown"] | None = Field(
        default=None, description="Detected type"
    )
    last_synced_at: datetime | None = Field(default=None, description="Last sync")
    git: GitStatus = Field(..., description="Git status")
    files: FileStats | None = Field(default=None, description="File statistics")


# --- Link Schemas ---


class LinkCreate(BaseModel):
    """Request to create a repository link."""

    target_repo_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="Target repository UUID to link to",
    )
    link_type: LinkTypeEnum = Field(
        ...,
        description="Type of relationship between repositories",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional additional metadata for the link",
    )


class LinkResponse(BaseModel):
    """Repository link response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Link UUID")
    source_repo_id: str = Field(..., description="Source repository UUID")
    target_repo_id: str = Field(..., description="Target repository UUID")
    link_type: LinkTypeEnum = Field(..., description="Type of link")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional link metadata",
    )
    created_at: datetime = Field(..., description="Creation timestamp")

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, v: Any) -> dict[str, Any] | None:
        """Handle SQLAlchemy metadata_ attribute."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if hasattr(v, "metadata_"):
            return getattr(v, "metadata_", None)
        return None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "LinkResponse":
        """Override to handle SQLAlchemy metadata_ attribute."""
        if hasattr(obj, "metadata_") and not hasattr(obj, "metadata"):
            data = {
                "id": obj.id,
                "source_repo_id": obj.source_repo_id,
                "target_repo_id": obj.target_repo_id,
                "link_type": obj.link_type,
                "metadata": obj.metadata_,
                "created_at": obj.created_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


class LinkedRepoSummary(BaseModel):
    """Summary of a linked repository."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Repository UUID")
    name: str = Field(..., description="Repository name (owner/repo)")
    repo_type: str | None = Field(default=None, description="Detected repository type")
    link_id: str = Field(..., description="The link ID")
    link_type: LinkTypeEnum = Field(..., description="Type of link")
    direction: Literal["outgoing", "incoming"] = Field(
        ..., description="Link direction relative to queried repo"
    )


# --- External Link Schemas ---


class ExternalLinkTypeEnum(str, Enum):
    """External link types for repositories."""

    STAGING = "staging"
    PRODUCTION = "production"
    DOCS = "docs"
    API = "api"
    ADMIN = "admin"
    SWAGGER = "swagger"
    GRAPHQL = "graphql"
    MONITORING = "monitoring"
    LOGS = "logs"
    CI_CD = "ci_cd"
    OTHER = "other"


class ExternalLinkCreate(BaseModel):
    """Request to create an external link."""

    link_type: ExternalLinkTypeEnum = Field(
        ...,
        description="Type of external link (staging, production, docs, etc.)",
    )
    url: str = Field(
        ...,
        min_length=5,
        max_length=1024,
        description="External URL",
    )
    label: str | None = Field(
        default=None,
        max_length=100,
        description="Optional custom label for the link",
    )
    is_primary: bool = Field(
        default=False,
        description="Mark this link as primary for its type",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional additional metadata",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class ExternalLinkUpdate(BaseModel):
    """Request to update an external link."""

    link_type: ExternalLinkTypeEnum | None = Field(
        default=None,
        description="Type of external link",
    )
    url: str | None = Field(
        default=None,
        min_length=5,
        max_length=1024,
        description="External URL",
    )
    label: str | None = Field(
        default=None,
        max_length=100,
        description="Optional custom label",
    )
    is_primary: bool | None = Field(
        default=None,
        description="Mark as primary for its type",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional additional metadata",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        """Validate URL format if provided."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class ExternalLinkResponse(BaseModel):
    """External link response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Link UUID")
    repository_id: str = Field(..., description="Repository UUID")
    link_type: ExternalLinkTypeEnum = Field(..., description="Type of link")
    url: str = Field(..., description="External URL")
    label: str | None = Field(default=None, description="Custom label")
    is_primary: bool = Field(default=False, description="Primary link for type")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional metadata")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, v: Any) -> dict[str, Any] | None:
        """Handle SQLAlchemy metadata_ attribute."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if hasattr(v, "metadata_"):
            return getattr(v, "metadata_", None)
        return None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "ExternalLinkResponse":
        """Override to handle SQLAlchemy metadata_ attribute."""
        if hasattr(obj, "metadata_") and not hasattr(obj, "metadata"):
            data = {
                "id": obj.id,
                "repository_id": obj.repository_id,
                "link_type": obj.link_type,
                "url": obj.url,
                "label": obj.label,
                "is_primary": obj.is_primary,
                "metadata": obj.metadata_,
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)
