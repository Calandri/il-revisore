"""Repository schemas."""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator


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

    @field_validator("url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        """Validate GitHub URL format."""
        pattern = r"^https?://github\.com/[\w.-]+/[\w.-]+/?$"
        if not re.match(pattern, v):
            raise ValueError("Must be a valid GitHub URL (https://github.com/owner/repo)")
        return v.rstrip("/")


class RepoResponse(BaseModel):
    """Repository response."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(..., description="Repository UUID")
    name: str = Field(..., description="Repository name (owner/repo)")
    url: str = Field(..., description="GitHub URL")
    local_path: str = Field(..., description="Local filesystem path")
    default_branch: str = Field(..., description="Default branch name")
    status: Literal["active", "syncing", "error"] = Field(..., description="Repository status")
    repo_type: Literal["backend", "frontend", "fullstack", "unknown"] | None = Field(
        default=None, description="Detected repository type"
    )
    last_synced_at: datetime | None = Field(default=None, description="Last sync timestamp")
    metadata_: dict[str, Any] | None = Field(
        default=None,
        alias="metadata",
        serialization_alias="metadata",
        description="Additional metadata"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


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
