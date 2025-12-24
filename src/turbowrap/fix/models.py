"""Pydantic models for the Fix Issue system."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FixStatus(str, Enum):
    """Status of a fix operation."""

    PENDING = "pending"
    VALIDATING = "validating"
    ANALYZING = "analyzing"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    GENERATING = "generating"
    APPLYING = "applying"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FixEventType(str, Enum):
    """Types of fix progress events."""

    # Session lifecycle
    FIX_SESSION_STARTED = "fix_session_started"
    FIX_SESSION_COMPLETED = "fix_session_completed"
    FIX_SESSION_ERROR = "fix_session_error"

    # Issue-level events
    FIX_ISSUE_STARTED = "fix_issue_started"
    FIX_ISSUE_VALIDATING = "fix_issue_validating"
    FIX_ISSUE_ANALYZING = "fix_issue_analyzing"
    FIX_CLARIFICATION_NEEDED = "fix_clarification_needed"
    FIX_CLARIFICATION_RECEIVED = "fix_clarification_received"
    FIX_ISSUE_GENERATING = "fix_issue_generating"
    FIX_ISSUE_STREAMING = "fix_issue_streaming"
    FIX_ISSUE_APPLYING = "fix_issue_applying"
    FIX_ISSUE_APPLIED = "fix_issue_applied"
    FIX_ISSUE_COMMITTING = "fix_issue_committing"
    FIX_ISSUE_COMMITTED = "fix_issue_committed"
    FIX_ISSUE_COMPLETED = "fix_issue_completed"
    FIX_ISSUE_ERROR = "fix_issue_error"
    FIX_ISSUE_SKIPPED = "fix_issue_skipped"


class FixRequest(BaseModel):
    """Request to fix one or more issues."""

    repository_id: str = Field(..., description="Repository ID")
    task_id: str = Field(..., description="Task ID that found the issues")
    issue_ids: list[str] = Field(..., min_length=1, description="Issue IDs to fix (in order)")


class ClarificationQuestion(BaseModel):
    """Question requiring user clarification."""

    id: str = Field(..., description="Question ID")
    issue_id: str = Field(..., description="Related issue ID")
    question: str = Field(..., description="Question text")
    context: Optional[str] = Field(default=None, description="Additional context")
    options: Optional[list[str]] = Field(default=None, description="Suggested options")


class ClarificationAnswer(BaseModel):
    """User's answer to a clarification question."""

    question_id: str = Field(..., description="Question ID")
    answer: str = Field(..., description="User's answer")


class FixContext(BaseModel):
    """Context for fixing an issue."""

    issue_id: str = Field(..., description="Issue ID")
    issue_code: str = Field(..., description="Issue code (e.g., BE-CRIT-001)")
    file_path: str = Field(..., description="File to fix")
    line: Optional[int] = Field(default=None, description="Line number")
    end_line: Optional[int] = Field(default=None, description="End line number")

    title: str = Field(..., description="Issue title")
    description: str = Field(..., description="Issue description")
    current_code: Optional[str] = Field(default=None, description="Current problematic code")
    suggested_fix: Optional[str] = Field(default=None, description="Suggested fix from review")
    category: str = Field(..., description="Issue category")
    severity: str = Field(..., description="Issue severity")

    # Full file content for context
    file_content: Optional[str] = Field(default=None, description="Full file content")

    # User clarifications
    clarifications: list[ClarificationAnswer] = Field(
        default_factory=list, description="User clarifications"
    )


class IssueFixResult(BaseModel):
    """Result of fixing a single issue."""

    issue_id: str = Field(..., description="Issue ID")
    issue_code: str = Field(..., description="Issue code")
    status: FixStatus = Field(..., description="Fix status")

    commit_sha: Optional[str] = Field(default=None, description="Commit SHA if committed")
    commit_message: Optional[str] = Field(default=None, description="Commit message")

    changes_made: Optional[str] = Field(default=None, description="Description of changes")
    error: Optional[str] = Field(default=None, description="Error message if failed")

    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)


class FixSessionResult(BaseModel):
    """Result of a complete fix session."""

    session_id: str = Field(..., description="Session ID")
    repository_id: str = Field(..., description="Repository ID")
    task_id: str = Field(..., description="Task ID")

    branch_name: str = Field(..., description="Git branch used for fixes")
    status: FixStatus = Field(..., description="Overall session status")

    issues_requested: int = Field(..., description="Number of issues requested")
    issues_fixed: int = Field(default=0, description="Number successfully fixed")
    issues_failed: int = Field(default=0, description="Number that failed")
    issues_skipped: int = Field(default=0, description="Number skipped")

    results: list[IssueFixResult] = Field(default_factory=list)

    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    error: Optional[str] = Field(default=None, description="Session-level error")


class FixProgressEvent(BaseModel):
    """Progress event for fix operations."""

    type: FixEventType = Field(..., description="Event type")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Session info
    session_id: Optional[str] = Field(default=None)
    branch_name: Optional[str] = Field(default=None)

    # Issue info
    issue_id: Optional[str] = Field(default=None)
    issue_code: Optional[str] = Field(default=None)
    issue_index: Optional[int] = Field(default=None, description="1-based index")
    total_issues: Optional[int] = Field(default=None)

    # Progress info
    message: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None, description="Streaming content")

    # Clarification
    clarification: Optional[ClarificationQuestion] = Field(default=None)

    # Commit info
    commit_sha: Optional[str] = Field(default=None)
    commit_message: Optional[str] = Field(default=None)

    # Error
    error: Optional[str] = Field(default=None)

    # Summary (for completed events)
    issues_fixed: Optional[int] = Field(default=None)
    issues_failed: Optional[int] = Field(default=None)

    def to_sse(self) -> dict:
        """Convert to SSE format."""
        return {
            "event": self.type.value,
            "data": self.model_dump_json(exclude_none=True),
        }
