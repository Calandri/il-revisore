"""Progress events for streaming review updates."""

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProgressEventType(str, Enum):
    """Types of progress events."""

    # Review lifecycle
    REVIEW_STARTED = "review_started"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_ERROR = "review_error"

    # Reviewer events
    REVIEWER_STARTED = "reviewer_started"
    REVIEWER_ITERATION = "reviewer_iteration"
    REVIEWER_STREAMING = "reviewer_streaming"  # Token streaming
    REVIEWER_COMPLETED = "reviewer_completed"
    REVIEWER_ERROR = "reviewer_error"

    # Challenger events
    CHALLENGER_STARTED = "challenger_started"
    CHALLENGER_COMPLETED = "challenger_completed"


class ProgressEvent(BaseModel):
    """Progress event for streaming updates."""

    type: ProgressEventType = Field(..., description="Event type")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Review-level info
    review_id: Optional[str] = Field(default=None, description="Review ID")

    # Reviewer-level info
    reviewer_name: Optional[str] = Field(default=None, description="Reviewer name")
    reviewer_display_name: Optional[str] = Field(default=None, description="Human-readable name")

    # Iteration info
    iteration: Optional[int] = Field(default=None, description="Current iteration")
    max_iterations: Optional[int] = Field(default=None, description="Max iterations")
    satisfaction_score: Optional[float] = Field(default=None, description="Current satisfaction %")

    # Streaming content
    content: Optional[str] = Field(default=None, description="Streaming content chunk")

    # Status info
    message: Optional[str] = Field(default=None, description="Human-readable status message")
    issues_found: Optional[int] = Field(default=None, description="Issues found so far")

    # Error info
    error: Optional[str] = Field(default=None, description="Error message if failed")

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

    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    error: Optional[str] = Field(default=None)


class ReviewProgress(BaseModel):
    """Overall review progress with all reviewers."""

    review_id: str = Field(..., description="Review ID")
    status: Literal["pending", "running", "completed", "error"] = Field(default="pending")

    reviewers: dict[str, ReviewerState] = Field(default_factory=dict)

    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)

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
