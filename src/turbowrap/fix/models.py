"""Pydantic models for the Fix Issue system."""

from datetime import datetime
from enum import Enum

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

    # Challenger events
    FIX_CHALLENGER_EVALUATING = "fix_challenger_evaluating"
    FIX_CHALLENGER_RESULT = "fix_challenger_result"
    FIX_CHALLENGER_APPROVED = "fix_challenger_approved"
    FIX_CHALLENGER_REJECTED = "fix_challenger_rejected"
    FIX_REGENERATING = "fix_regenerating"

    # Billing/API errors
    FIX_BILLING_ERROR = "fix_billing_error"


class FixChallengerStatus(str, Enum):
    """Status from fix challenger evaluation."""

    APPROVED = "APPROVED"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    REJECTED = "REJECTED"


class FixQualityScores(BaseModel):
    """Quality scores for fix evaluation."""

    correctness: float = Field(
        ..., ge=0, le=100, description="Does the fix actually solve the issue?"
    )
    safety: float = Field(
        ..., ge=0, le=100, description="Does the fix avoid introducing new bugs/vulnerabilities?"
    )
    minimality: float = Field(
        ..., ge=0, le=100, description="Is the fix minimal and focused (not over-engineered)?"
    )
    style_consistency: float = Field(
        ..., ge=0, le=100, description="Does the fix maintain code style consistency?"
    )

    @property
    def weighted_score(self) -> float:
        """Calculate weighted satisfaction score."""
        weights = {
            "correctness": 0.40,
            "safety": 0.30,
            "minimality": 0.15,
            "style_consistency": 0.15,
        }
        return (
            self.correctness * weights["correctness"]
            + self.safety * weights["safety"]
            + self.minimality * weights["minimality"]
            + self.style_consistency * weights["style_consistency"]
        )


class FixIssue(BaseModel):
    """An issue found in the proposed fix."""

    type: str = Field(..., description="Issue type: bug, vulnerability, style, logic")
    description: str = Field(..., description="Description of the problem")
    line: int | None = Field(default=None, description="Line number in the fix")
    severity: str = Field(default="MEDIUM", description="Severity: CRITICAL, HIGH, MEDIUM, LOW")
    suggestion: str | None = Field(default=None, description="How to fix this issue")


class FixChallengerFeedback(BaseModel):
    """Feedback from the fix challenger."""

    iteration: int = Field(..., description="Challenger iteration number")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    satisfaction_score: float = Field(
        ..., ge=0, le=100, description="Overall satisfaction with the fix"
    )
    threshold: float = Field(..., description="Required threshold to pass")
    status: FixChallengerStatus

    quality_scores: FixQualityScores
    issues_found: list[FixIssue] = Field(
        default_factory=list, description="Issues found in the proposed fix"
    )
    improvements_needed: list[str] = Field(default_factory=list, description="Improvements needed")
    positive_feedback: list[str] = Field(default_factory=list, description="What was done well")

    # Thinking output (if available)
    thinking_content: str | None = Field(
        default=None, description="Thinking process from Gemini (if thinking mode enabled)"
    )

    @property
    def passed(self) -> bool:
        """Check if the fix passes the threshold."""
        return self.satisfaction_score >= self.threshold

    def to_refinement_prompt(self) -> str:
        """Generate a prompt for the fixer to improve the fix."""
        sections = []

        if self.issues_found:
            sections.append("## Issues Found in Your Fix\n")
            for i, issue in enumerate(self.issues_found, 1):
                sections.append(
                    f"{i}. **{issue.type.upper()}** ({issue.severity})"
                    f"{f' at line {issue.line}' if issue.line else ''}\n"
                    f"   - {issue.description}\n"
                )
                if issue.suggestion:
                    sections.append(f"   - Suggestion: {issue.suggestion}\n")

        if self.improvements_needed:
            sections.append("\n## Improvements Needed\n")
            for improvement in self.improvements_needed:
                sections.append(f"- {improvement}\n")

        sections.append("\n## Scores\n")
        sections.append(f"- Correctness: {self.quality_scores.correctness:.0f}/100\n")
        sections.append(f"- Safety: {self.quality_scores.safety:.0f}/100\n")
        sections.append(f"- Minimality: {self.quality_scores.minimality:.0f}/100\n")
        sections.append(f"- Style: {self.quality_scores.style_consistency:.0f}/100\n")

        return "".join(sections)


class FixRequest(BaseModel):
    """Request to fix one or more issues."""

    repository_id: str = Field(..., description="Repository ID")
    task_id: str = Field(..., description="Task ID that found the issues")
    issue_ids: list[str] = Field(..., min_length=1, description="Issue IDs to fix (in order)")

    # Branch handling - allows continuing on existing branch instead of creating new one
    use_existing_branch: bool = Field(
        default=False, description="If True, use existing branch instead of creating new one from main"
    )
    existing_branch_name: str | None = Field(
        default=None, description="Name of existing branch to use (required if use_existing_branch=True)"
    )


class ClarificationQuestion(BaseModel):
    """Question requiring user clarification."""

    id: str = Field(..., description="Question ID")
    issue_id: str = Field(..., description="Related issue ID")
    question: str = Field(..., description="Question text")
    context: str | None = Field(default=None, description="Additional context")
    options: list[str] | None = Field(default=None, description="Suggested options")


class ClarificationAnswer(BaseModel):
    """User's answer to a clarification question."""

    question_id: str = Field(..., description="Question ID")
    answer: str = Field(..., description="User's answer")


class FixContext(BaseModel):
    """Context for fixing an issue."""

    issue_id: str = Field(..., description="Issue ID")
    issue_code: str = Field(..., description="Issue code (e.g., BE-CRIT-001)")
    file_path: str = Field(..., description="File to fix")
    line: int | None = Field(default=None, description="Line number")
    end_line: int | None = Field(default=None, description="End line number")

    title: str = Field(..., description="Issue title")
    description: str = Field(..., description="Issue description")
    current_code: str | None = Field(default=None, description="Current problematic code")
    suggested_fix: str | None = Field(default=None, description="Suggested fix from review")
    category: str = Field(..., description="Issue category")
    severity: str = Field(..., description="Issue severity")

    # Full file content for context
    file_content: str | None = Field(default=None, description="Full file content")

    # User clarifications
    clarifications: list[ClarificationAnswer] = Field(
        default_factory=list, description="User clarifications"
    )


class IssueFixResult(BaseModel):
    """Result of fixing a single issue."""

    issue_id: str = Field(..., description="Issue ID")
    issue_code: str = Field(..., description="Issue code")
    status: FixStatus = Field(..., description="Fix status")

    commit_sha: str | None = Field(default=None, description="Commit SHA if committed")
    commit_message: str | None = Field(default=None, description="Commit message")

    changes_made: str | None = Field(default=None, description="Description of changes")
    error: str | None = Field(default=None, description="Error message if failed")

    # Fix result fields (for DB storage)
    fix_code: str | None = Field(default=None, description="Snippet of fixed code (max 500 chars for display)")
    fix_explanation: str | None = Field(default=None, description="PR-style explanation of the fix")
    fix_files_modified: list[str] = Field(default_factory=list, description="List of modified files")

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


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

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    error: str | None = Field(default=None, description="Session-level error")


class FixProgressEvent(BaseModel):
    """Progress event for fix operations."""

    type: FixEventType = Field(..., description="Event type")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Session info
    session_id: str | None = Field(default=None)
    branch_name: str | None = Field(default=None)

    # Issue info
    issue_id: str | None = Field(default=None)
    issue_code: str | None = Field(default=None)
    issue_index: int | None = Field(default=None, description="1-based index")
    total_issues: int | None = Field(default=None)

    # Progress info
    message: str | None = Field(default=None)
    content: str | None = Field(default=None, description="Streaming content")

    # Clarification
    clarification: ClarificationQuestion | None = Field(default=None)

    # Commit info
    commit_sha: str | None = Field(default=None)
    commit_message: str | None = Field(default=None)

    # Error
    error: str | None = Field(default=None)

    # Summary (for completed events)
    issues_fixed: int | None = Field(default=None)
    issues_failed: int | None = Field(default=None)

    def to_sse(self) -> dict[str, str]:
        """Convert to SSE format."""
        return {
            "event": self.type.value,
            "data": self.model_dump_json(exclude_none=True),
        }
