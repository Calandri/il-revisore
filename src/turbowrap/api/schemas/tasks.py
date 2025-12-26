"""Task schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

TaskType = Literal["review", "develop", "lint_fix", "fix"]
TaskStatusType = Literal["pending", "running", "completed", "failed", "cancelled"]


class TaskCreate(BaseModel):
    """Request to create a task."""

    repository_id: str = Field(
        ...,
        min_length=1,
        description="Repository UUID",
    )
    type: TaskType = Field(
        ...,
        description="Task type",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Task-specific configuration",
    )
    priority: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Task priority (0=lowest, 10=highest)",
    )

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        """Validate config based on task type."""
        task_type = info.data.get("type")
        if task_type == "develop" and "instruction" not in v:
            raise ValueError("'instruction' is required for develop tasks")
        return v


class TaskProgress(BaseModel):
    """Progress information for a running task."""

    percentage: int = Field(..., ge=0, le=100, description="Progress percentage (0-100)")
    message: str | None = Field(default=None, description="Current step description")
    elapsed_seconds: float | None = Field(default=None, description="Time elapsed since start")
    estimated_remaining_seconds: float | None = Field(
        default=None, description="Estimated time remaining"
    )


class TaskResponse(BaseModel):
    """Task response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Task UUID")
    repository_id: str = Field(..., description="Associated repository UUID")
    type: TaskType = Field(..., description="Task type")
    status: TaskStatusType = Field(..., description="Current status")
    priority: int = Field(..., ge=0, description="Task priority")
    config: dict[str, Any] | None = Field(default=None, description="Task configuration")
    result: dict[str, Any] | None = Field(default=None, description="Task result data")
    error: str | None = Field(default=None, description="Error message if failed")
    progress: int = Field(default=0, ge=0, le=100, description="Progress percentage")
    progress_message: str | None = Field(default=None, description="Current step")
    started_at: datetime | None = Field(default=None, description="Execution start time")
    completed_at: datetime | None = Field(default=None, description="Execution end time")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @property
    def duration_seconds(self) -> float | None:
        """Calculate task duration if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def elapsed_seconds(self) -> float | None:
        """Calculate elapsed time for running tasks."""
        if self.started_at:
            if self.completed_at:
                return (self.completed_at - self.started_at).total_seconds()
            from datetime import datetime

            return (datetime.utcnow() - self.started_at).total_seconds()
        return None

    def get_progress(self) -> TaskProgress:
        """Get structured progress information."""
        elapsed = self.elapsed_seconds
        estimated_remaining = None

        if elapsed and self.progress > 0 and self.progress < 100:
            # Estimate remaining time based on current progress
            time_per_percent = elapsed / self.progress
            remaining_percent = 100 - self.progress
            estimated_remaining = time_per_percent * remaining_percent

        return TaskProgress(
            percentage=self.progress,
            message=self.progress_message,
            elapsed_seconds=elapsed,
            estimated_remaining_seconds=estimated_remaining,
        )


class TaskSummary(BaseModel):
    """Brief task summary for queue display."""

    id: str = Field(..., description="Task UUID")
    type: TaskType = Field(..., description="Task type")
    status: TaskStatusType = Field(..., description="Current status")
    priority: int = Field(..., description="Task priority")
    created_at: datetime = Field(..., description="Creation timestamp")


class TaskQueueStatus(BaseModel):
    """Task queue status."""

    pending: int = Field(..., ge=0, description="Pending task count")
    processing: int = Field(..., ge=0, description="Running task count")
    pending_tasks: list[TaskSummary] = Field(default_factory=list, description="Pending tasks")
    processing_tasks: list[TaskSummary] = Field(default_factory=list, description="Running tasks")
