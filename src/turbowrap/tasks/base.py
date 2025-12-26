"""Base task interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session


class TaskConfig(BaseModel):
    """Base configuration for tasks."""

    model_config = ConfigDict(extra="allow")

    repository_id: str = Field(..., min_length=1, description="Repository UUID")
    max_workers: int = Field(default=3, ge=1, le=10, description="Max parallel workers")


class ReviewTaskConfig(TaskConfig):
    """Configuration for review tasks."""

    batch_size: int = Field(default=3, ge=1, le=10, description="Files per batch")
    max_file_size: int = Field(default=6000, ge=100, description="Max file content chars")
    include_patterns: list[str] = Field(
        default_factory=list, description="File patterns to include"
    )
    exclude_patterns: list[str] = Field(
        default_factory=list, description="File patterns to exclude"
    )


class DevelopTaskConfig(TaskConfig):
    """Configuration for develop tasks."""

    instruction: str = Field(..., min_length=1, description="Development instruction")
    files: list[str] = Field(default_factory=list, description="Target files")
    auto_commit: bool = Field(default=False, description="Auto-commit changes")


class TaskContext(BaseModel):
    """Context for task execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Session = Field(..., description="Database session")
    repo_path: Path = Field(..., description="Repository local path")
    config: dict[str, Any] = Field(default_factory=dict, description="Task configuration")

    @field_validator("repo_path")
    @classmethod
    def validate_repo_path(cls, v: Path) -> Path:
        """Ensure repo path exists."""
        if not v.exists():
            raise ValueError(f"Repository path does not exist: {v}")
        return v


class TaskResult(BaseModel):
    """Result from task execution."""

    model_config = ConfigDict(frozen=True)

    status: Literal["completed", "failed"] = Field(..., description="Execution status")
    data: dict[str, Any] = Field(default_factory=dict, description="Result data")
    error: str | None = Field(default=None, description="Error message if failed")
    duration_seconds: float = Field(default=0, ge=0, description="Execution duration")
    started_at: datetime | None = Field(default=None, description="Start timestamp")
    completed_at: datetime | None = Field(default=None, description="Completion timestamp")

    @property
    def is_success(self) -> bool:
        """Check if task completed successfully."""
        return self.status == "completed"


class BaseTask(ABC):
    """Abstract base class for tasks."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Task name identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable task description."""
        ...

    @property
    def config_class(self) -> type[TaskConfig]:
        """Configuration class for this task."""
        return TaskConfig

    @abstractmethod
    def execute(self, context: TaskContext) -> TaskResult:
        """Execute the task.

        Args:
            context: Task execution context.

        Returns:
            TaskResult with execution results.
        """
        ...

    def validate_config(self, config: dict[str, Any]) -> TaskConfig:
        """Validate and parse task configuration.

        Args:
            config: Configuration dictionary.

        Returns:
            Validated TaskConfig instance.

        Raises:
            ValidationError: If config is invalid.
        """
        return self.config_class.model_validate(config)
