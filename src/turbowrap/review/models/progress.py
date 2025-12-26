"""Progress events for streaming review updates."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProgressEventType(str, Enum):
    """Types of progress events."""

    # Review lifecycle
    REVIEW_STARTED = "review_started"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_ERROR = "review_error"

    # Structure generation (auto-generate STRUCTURE.md)
    STRUCTURE_GENERATION_STARTED = "structure_generation_started"
    STRUCTURE_GENERATION_PROGRESS = "structure_generation_progress"
    STRUCTURE_GENERATION_COMPLETED = "structure_generation_completed"

    # Reviewer events
    REVIEWER_STARTED = "reviewer_started"
    REVIEWER_ITERATION = "reviewer_iteration"
    REVIEWER_STREAMING = "reviewer_streaming"  # Token streaming
    REVIEWER_COMPLETED = "reviewer_completed"
    REVIEWER_ERROR = "reviewer_error"

    # Challenger events
    CHALLENGER_STARTED = "challenger_started"
    CHALLENGER_COMPLETED = "challenger_completed"

    # Log events (for UI toast notifications)
    REVIEW_LOG = "review_log"


class ProgressEvent(BaseModel):
    """Progress event for streaming updates."""

    type: ProgressEventType = Field(..., description="Event type")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Review-level info
    review_id: str | None = Field(default=None, description="Review ID")

    # Reviewer-level info
    reviewer_name: str | None = Field(default=None, description="Reviewer name")
    reviewer_display_name: str | None = Field(default=None, description="Human-readable name")
    model: str | None = Field(
        default=None, description="Model used (e.g., claude-opus-4-5, gemini-flash)"
    )

    # Iteration info
    iteration: int | None = Field(default=None, description="Current iteration")
    max_iterations: int | None = Field(default=None, description="Max iterations")
    satisfaction_score: float | None = Field(default=None, description="Current satisfaction %")

    # Streaming content
    content: str | None = Field(default=None, description="Streaming content chunk")

    # Status info
    message: str | None = Field(default=None, description="Human-readable status message")
    issues_found: int | None = Field(default=None, description="Issues found so far")

    # Error info
    error: str | None = Field(default=None, description="Error message if failed")

    # Log level (for REVIEW_LOG events)
    log_level: str | None = Field(default=None, description="Log level: INFO, WARNING, ERROR")

    # Model usage info (from CLI)
    model_usage: list[dict[str, Any]] | None = Field(
        default=None, description="Models used and their token/cost info"
    )

    def to_sse(self) -> dict:
        """Convert to SSE format."""
        return {
            "event": self.type.value,
            "data": self.model_dump_json(exclude_none=True),
        }


class ReviewerState(BaseModel):
    """State of a single reviewer."""

    name: str = Field(..., description="Reviewer name")
    display_name: str = Field(..., description="Human-readable name")
    status: Literal["pending", "running", "completed", "error"] = Field(default="pending")

    iteration: int = Field(default=0)
    max_iterations: int = Field(default=5)
    satisfaction_score: float = Field(default=0.0)

    issues_found: int = Field(default=0)
    current_content: str = Field(default="", description="Current streaming content")

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    error: str | None = Field(default=None)


class ReviewProgress(BaseModel):
    """Overall review progress with all reviewers."""

    review_id: str = Field(..., description="Review ID")
    status: Literal["pending", "running", "completed", "error"] = Field(default="pending")

    reviewers: dict[str, ReviewerState] = Field(default_factory=dict)

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    total_issues: int = Field(default=0)

    def get_active_reviewers(self) -> list[ReviewerState]:
        """Get reviewers currently running."""
        return [r for r in self.reviewers.values() if r.status == "running"]

    def get_completed_reviewers(self) -> list[ReviewerState]:
        """Get completed reviewers."""
        return [r for r in self.reviewers.values() if r.status == "completed"]


# Display names for reviewers
REVIEWER_DISPLAY_NAMES = {
    "reviewer_be_architecture": "Backend Architecture",
    "reviewer_be_quality": "Backend Quality",
    "reviewer_fe_architecture": "Frontend Architecture",
    "reviewer_fe_quality": "Frontend Quality",
    "analyst_func": "Functional Analyst",
}


def get_reviewer_display_name(name: str) -> str:
    """Get human-readable display name for a reviewer."""
    return REVIEWER_DISPLAY_NAMES.get(name, name.replace("_", " ").title())
