"""
Models for review requests and outputs.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    """Issue severity levels."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IssueCategory(str, Enum):
    """Issue category types."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    STYLE = "style"
    LOGIC = "logic"
    UX = "ux"
    TESTING = "testing"
    DOCUMENTATION = "documentation"


class Issue(BaseModel):
    """A single issue found during review."""

    id: str = Field(..., description="Unique issue identifier (e.g., BE-CRIT-001)")
    severity: IssueSeverity
    category: IssueCategory
    rule: str | None = Field(None, description="Linting rule code (e.g., B608)")
    file: str = Field(..., description="File path where issue was found")
    line: int | None = Field(None, description="Line number")
    end_line: int | None = Field(None, description="End line for multi-line issues")
    title: str = Field(..., description="Brief issue title")
    description: str = Field(..., description="Detailed description of the issue")
    current_code: str | None = Field(None, description="Current problematic code")
    suggested_fix: str | None = Field(None, description="Suggested code fix")
    references: list[str] = Field(default_factory=list, description="Reference URLs")
    flagged_by: list[str] = Field(
        default_factory=list, description="Reviewers that flagged this issue"
    )
    # Workload estimation for fix orchestrator batching
    estimated_effort: int | None = Field(
        None, ge=1, le=5, description="Estimated fix effort: 1=trivial, 5=major refactor"
    )
    estimated_files_count: int | None = Field(
        None, ge=1, description="Estimated number of files to modify for the fix"
    )


class ChecklistResult(BaseModel):
    """Result of a checklist category."""

    passed: int = Field(0, description="Number of passed checks")
    failed: int = Field(0, description="Number of failed checks")
    skipped: int = Field(0, description="Number of skipped checks")

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped


class ReviewMetrics(BaseModel):
    """Code metrics from the review."""

    complexity_avg: float | None = Field(
        None, description="Average cyclomatic complexity"
    )
    complexity_max: int | None = Field(None, description="Maximum complexity")
    test_coverage: float | None = Field(None, description="Test coverage percentage")
    type_coverage: float | None = Field(None, description="Type annotation coverage")
    lines_reviewed: int | None = Field(None, description="Total lines reviewed")
    functions_reviewed: int | None = Field(
        None, description="Total functions reviewed"
    )


class ReviewSummary(BaseModel):
    """Summary of review results."""

    files_reviewed: int = Field(0, description="Number of files reviewed")
    critical_issues: int = Field(0, description="Count of critical issues")
    high_issues: int = Field(0, description="Count of high severity issues")
    medium_issues: int = Field(0, description="Count of medium severity issues")
    low_issues: int = Field(0, description="Count of low severity issues")
    score: float = Field(
        10.0, ge=0.0, le=10.0, description="Overall score out of 10"
    )

    @property
    def total_issues(self) -> int:
        return (
            self.critical_issues
            + self.high_issues
            + self.medium_issues
            + self.low_issues
        )


class ModelUsageInfo(BaseModel):
    """Model usage information from CLI."""

    model: str = Field(..., description="Model name used")
    input_tokens: int = Field(0, description="Input tokens used")
    output_tokens: int = Field(0, description="Output tokens generated")
    cache_read_tokens: int = Field(0, description="Tokens read from cache")
    cache_creation_tokens: int = Field(0, description="Tokens written to cache")
    cost_usd: float = Field(0.0, description="Cost in USD")


class ReviewOutput(BaseModel):
    """Complete output from a reviewer."""

    reviewer: str = Field(
        ..., description="Reviewer identifier (reviewer_be, reviewer_fe, analyst_func)"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_seconds: float = Field(0.0, description="Time taken for review")
    iteration: int = Field(1, description="Challenger loop iteration number")
    summary: ReviewSummary = Field(default_factory=ReviewSummary)
    issues: list[Issue] = Field(default_factory=list)
    checklists: dict[str, ChecklistResult] = Field(
        default_factory=dict, description="Checklist results by category"
    )
    metrics: ReviewMetrics = Field(default_factory=ReviewMetrics)
    refinement_notes: list[dict] = Field(
        default_factory=list, description="Notes from challenger refinements"
    )
    model_usage: list[ModelUsageInfo] = Field(
        default_factory=list, description="Models used and their token usage"
    )

    def get_issue(self, issue_id: str) -> Issue | None:
        """Get an issue by ID."""
        for issue in self.issues:
            if issue.id == issue_id:
                return issue
        return None


class ReviewRequestSource(BaseModel):
    """Source specification for the review."""

    pr_url: str | None = Field(None, description="GitHub PR URL")
    commit_sha: str | None = Field(None, description="Specific commit SHA")
    files: list[str] = Field(default_factory=list, description="Specific file paths")
    directory: str | None = Field(None, description="Directory to review")


class ReviewRequirements(BaseModel):
    """Optional requirements for functional analysis."""

    description: str | None = Field(
        None, description="What the changes should do"
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list, description="List of acceptance criteria"
    )
    ticket_url: str | None = Field(None, description="Linear/Jira ticket URL")


class ReviewMode(str, Enum):
    """Review mode types."""

    INITIAL = "initial"  # Full repo review using only STRUCTURE.md files
    DIFF = "diff"  # Review only changed files (PR, commit, or specified files)


class ReviewOptions(BaseModel):
    """Review configuration options."""

    mode: ReviewMode = Field(
        ReviewMode.DIFF,
        description="Review mode: initial (STRUCTURE.md only) or diff (changed files)"
    )
    include_functional: bool = Field(
        True, description="Include functional analyst"
    )
    severity_threshold: IssueSeverity = Field(
        IssueSeverity.LOW, description="Minimum severity to report"
    )
    output_format: str = Field(
        "both", description="Output format: markdown, json, both"
    )
    challenger_enabled: bool = Field(
        True, description="Enable challenger loop"
    )
    satisfaction_threshold: int = Field(
        50, ge=0, le=100, description="Challenger satisfaction threshold"
    )


class ReviewRequest(BaseModel):
    """Complete review request input."""

    type: str = Field(
        ..., description="Request type: pr, commit, files, directory"
    )
    source: ReviewRequestSource
    requirements: ReviewRequirements | None = None
    options: ReviewOptions = Field(default_factory=ReviewOptions)
