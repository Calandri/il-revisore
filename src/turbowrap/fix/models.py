"""Pydantic models for the Fix Issue system."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ScopeValidationError(Exception):
    """Raised when modified files are outside the allowed workspace scope.

    This exception is raised during fix operations when Claude modifies files
    that are outside the configured workspace_path for a monorepo.
    The orchestrator will automatically revert all uncommitted changes when this occurs.
    """

    def __init__(self, files_outside_scope: list[str], workspace_path: str):
        self.files_outside_scope = files_outside_scope
        self.workspace_path = workspace_path
        message = (
            f"Fix modified files outside workspace scope '{workspace_path}': "
            f"{', '.join(files_outside_scope)}"
        )
        super().__init__(message)


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

    # Log events (for UI toast notifications)
    FIX_LOG = "fix_log"

    # Scope violation events (interactive prompt for user)
    FIX_SCOPE_VIOLATION_PROMPT = "fix_scope_violation_prompt"

    # Batch-level commit events (for atomic per-batch commits)
    FIX_BATCH_COMMITTED = "fix_batch_committed"
    FIX_BATCH_FAILED = "fix_batch_failed"


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
        default=False,
        description="If True, use existing branch instead of creating new one from main",
    )
    existing_branch_name: str | None = Field(
        default=None,
        description="Name of existing branch to use (required if use_existing_branch=True)",
    )

    # Monorepo workspace scope - limits fix operations to a subfolder
    workspace_path: str | None = Field(
        default=None,
        description="Relative path within repo to limit fixes (e.g., 'packages/frontend'). "
        "If set, fixes outside this path will be rejected and reverted.",
    )

    # Additional allowed paths for monorepo scope exceptions
    allowed_extra_paths: list[str] | None = Field(
        default=None,
        description="Additional paths allowed for modifications beyond workspace_path. "
        "Used for cross-package changes in monorepos.",
    )

    # User notes - additional context/instructions for the fixer
    user_notes: str | None = Field(
        default=None,
        description="Optional user notes with additional context or instructions for the fixer "
        "(e.g., 'Use the new API endpoint /api/v2/users')",
    )

    # Session from pre-fix clarification phase
    clarify_session_id: str | None = Field(
        default=None,
        description="Session ID from pre-fix clarification phase. "
        "If provided, the fixer will resume this session to preserve clarification context.",
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
    fix_code: str | None = Field(
        default=None, description="Snippet of fixed code (max 500 chars for display)"
    )
    fix_explanation: str | None = Field(default=None, description="PR-style explanation of the fix")
    fix_files_modified: list[str] = Field(
        default_factory=list, description="List of modified files"
    )

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    # False positive flag - issue doesn't exist in code
    false_positive: bool = Field(
        default=False, description="True if issue was a false positive (no fix needed)"
    )

    # Scores from evaluation
    fix_self_score: int | None = Field(
        default=None, description="Self-evaluation score from Claude (0-100)"
    )
    fix_gemini_score: int | None = Field(
        default=None, description="Gemini challenger score (0-100)"
    )


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

    # Batch info (for per-batch challenger events)
    issue_ids: list[str] | None = Field(
        default=None, description="Issue IDs in batch (for batch events)"
    )
    issue_codes: list[str] | None = Field(default=None, description="Issue codes in batch")

    # Progress info
    message: str | None = Field(default=None)
    content: str | None = Field(default=None, description="Streaming content")
    batch_type: str | None = Field(
        default=None, description="Batch type: BE, FE, or DB (for streaming events)"
    )

    # Clarification
    clarification: ClarificationQuestion | None = Field(default=None)

    # Commit info
    commit_sha: str | None = Field(default=None)
    commit_message: str | None = Field(default=None)

    # Error
    error: str | None = Field(default=None)

    # Log level (for FIX_LOG events)
    log_level: str | None = Field(default=None, description="Log level: INFO, WARNING, ERROR")

    # Summary (for completed events)
    issues_fixed: int | None = Field(default=None)
    issues_failed: int | None = Field(default=None)

    # Quality scores from Gemini review (for FIX_CHALLENGER_RESULT)
    quality_scores: dict[str, int] | None = Field(
        default=None, description="Quality dimension scores"
    )

    # Scope violation info (for FIX_SCOPE_VIOLATION_PROMPT)
    scope_violation_dirs: list[str] | None = Field(
        default=None, description="Directories modified outside workspace scope"
    )

    def to_sse(self) -> dict[str, str]:
        """Convert to SSE format."""
        return {
            "event": self.type.value,
            "data": self.model_dump_json(exclude_none=True),
        }


# =============================================================================
# Planning Phase Models (Clarify + Planner)
# =============================================================================


class IssueClarificationQuestion(BaseModel):
    """A clarification question for a specific issue."""

    id: str = Field(..., description="Question ID (format: {issue_code}-q{n})")
    question: str = Field(..., description="The question to ask the user")
    context: str | None = Field(default=None, description="Why this question is being asked")


class IssueQuestionsGroup(BaseModel):
    """Group of questions for a single issue."""

    issue_code: str = Field(..., description="Issue code (e.g., BE-001)")
    questions: list[IssueClarificationQuestion] = Field(
        default_factory=list, description="Questions for this issue"
    )


class ClarificationPhaseOutput(BaseModel):
    """Output from the clarification phase of the planner."""

    phase: str = Field(default="clarification", description="Current phase")
    has_questions: bool = Field(..., description="Whether there are questions to ask")
    questions_by_issue: list[IssueQuestionsGroup] = Field(
        default_factory=list, description="Questions grouped by issue"
    )
    issues_without_questions: list[str] = Field(
        default_factory=list, description="Issue codes that don't need clarification"
    )
    ready_to_plan: bool = Field(..., description="Whether ready to proceed to planning")


class IssueClarificationAnswered(BaseModel):
    """A clarification question with its answer."""

    question_id: str = Field(..., description="Question ID")
    question: str = Field(..., description="The original question")
    answer: str = Field(..., description="User's answer")
    context: str | None = Field(default=None, description="Original context")


class RelatedFile(BaseModel):
    """A file related to the issue context."""

    path: str = Field(..., description="File path")
    reason: str = Field(..., description="Why this file is relevant")


class IssueContextInfo(BaseModel):
    """Pre-analyzed context for an issue."""

    file_content_snippet: str | None = Field(
        default=None, description="Relevant code snippet from target file"
    )
    related_files: list[RelatedFile] = Field(
        default_factory=list, description="Files related to this issue"
    )
    existing_patterns: list[str] = Field(
        default_factory=list, description="Existing patterns found in codebase"
    )


class IssuePlan(BaseModel):
    """Step-by-step plan for fixing an issue."""

    approach: str = Field(..., description="Fix approach: patch | refactor | rewrite")
    steps: list[str] = Field(..., description="Numbered steps to fix the issue")
    estimated_lines_changed: int = Field(default=0, description="Estimated lines of code to change")
    risks: list[str] = Field(default_factory=list, description="Potential risks of this fix")
    verification: str | None = Field(default=None, description="How to verify the fix works")


class IssueTodo(BaseModel):
    """Complete TODO for a single issue (passed to fixer agent)."""

    issue_code: str = Field(..., description="Issue code (e.g., BE-001)")
    issue_id: str = Field(..., description="Issue UUID")
    file: str = Field(..., description="Target file path")
    line: int | None = Field(default=None, description="Target line number")
    title: str = Field(..., description="Issue title")

    clarifications: list[IssueClarificationAnswered] = Field(
        default_factory=list, description="Q&A specific to this issue"
    )
    context: IssueContextInfo = Field(
        default_factory=IssueContextInfo, description="Pre-analyzed context"
    )
    plan: IssuePlan | None = Field(default=None, description="Execution plan")


class IssueEntry(BaseModel):
    """Entry for a single issue in an execution step."""

    code: str = Field(..., description="Issue code")
    todo_file: str = Field(..., description="Path to issue TODO file")
    agent_type: str = Field(
        default="fixer-single",
        description="Agent type: fixer-single | fixer-refactor | fixer-complex",
    )


class ExecutionStep(BaseModel):
    """A step in the execution plan (all issues in a step run in parallel)."""

    step: int = Field(..., description="Step number (1-based)")
    issues: list[IssueEntry] = Field(..., description="Issues to fix in this step")
    reason: str | None = Field(default=None, description="Why these issues are grouped")


class MasterTodoSummary(BaseModel):
    """Summary of the master TODO."""

    total_issues: int = Field(..., description="Total number of issues")
    total_steps: int = Field(..., description="Total number of execution steps")


class MasterTodo(BaseModel):
    """Master TODO for the orchestrator (defines execution order)."""

    session_id: str = Field(..., description="Fix session ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    branch_name: str | None = Field(default=None, description="Git branch name")

    execution_steps: list[ExecutionStep] = Field(
        ..., description="Steps to execute (sequential between steps, parallel within)"
    )

    summary: MasterTodoSummary = Field(..., description="Summary statistics")

    @classmethod
    def from_issue_todos(
        cls,
        session_id: str,
        issue_todos: list[IssueTodo],
        execution_steps: list[ExecutionStep],
        branch_name: str | None = None,
    ) -> "MasterTodo":
        """Create MasterTodo from issue todos and execution plan."""
        return cls(
            session_id=session_id,
            branch_name=branch_name,
            execution_steps=execution_steps,
            summary=MasterTodoSummary(
                total_issues=len(issue_todos),
                total_steps=len(execution_steps),
            ),
        )


class PlanningPhaseOutput(BaseModel):
    """Output from the planning phase of the planner."""

    phase: str = Field(default="planning", description="Current phase")
    master_todo: MasterTodo = Field(..., description="Master TODO for orchestrator")
    issue_todos: list[IssueTodo] = Field(..., description="Individual issue TODOs")
