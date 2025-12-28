"""
Models for final report generation.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from turbowrap.review.models.evaluation import RepositoryEvaluation
from turbowrap.review.models.review import ChecklistResult, Issue, ReviewMetrics


class RepoType(str, Enum):
    """Repository type classification."""

    BACKEND = "BACKEND"
    FRONTEND = "FRONTEND"
    FULLSTACK = "FULLSTACK"
    UNKNOWN = "UNKNOWN"


class Recommendation(str, Enum):
    """Final review recommendation."""

    APPROVE = "APPROVE"
    APPROVE_WITH_CHANGES = "APPROVE_WITH_CHANGES"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    NEEDS_DISCUSSION = "NEEDS_DISCUSSION"


class ConvergenceStatus(str, Enum):
    """Challenger loop convergence status."""

    IN_PROGRESS = "IN_PROGRESS"  # Loop should continue
    THRESHOLD_MET = "THRESHOLD_MET"
    MAX_ITERATIONS_REACHED = "MAX_ITERATIONS_REACHED"
    STAGNATED = "STAGNATED"
    FORCED_ACCEPTANCE = "FORCED_ACCEPTANCE"


class ReviewerResult(BaseModel):
    """Result from a single reviewer."""

    name: str = Field(..., description="Reviewer name")
    status: str = Field(..., description="completed, skipped, timeout, error")
    issues_found: int = Field(0, description="Number of issues found")
    duration_seconds: float = Field(0.0)
    iterations: int = Field(1, description="Challenger iterations needed")
    final_satisfaction: float | None = Field(
        None, description="Final challenger satisfaction score"
    )
    error: str | None = Field(None, description="Error message if failed")
    reason: str | None = Field(None, description="Reason if skipped")
    cost_usd: float = Field(0.0, description="Total cost in USD for this reviewer")


class IterationHistory(BaseModel):
    """History of a single challenger iteration."""

    iteration: int
    satisfaction_score: float
    issues_added: int = 0
    challenges_resolved: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChallengerInsight(BaseModel):
    """Notable insight from challenger."""

    iteration: int
    description: str
    impact: str = Field(..., description="high, medium, low")


class SeveritySummary(BaseModel):
    """Issue count by severity."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0

    @property
    def total(self) -> int:
        return self.critical + self.high + self.medium + self.low


class ReportSummary(BaseModel):
    """Executive summary of the report."""

    repo_type: RepoType = RepoType.UNKNOWN
    files_reviewed: int = 0
    total_issues: int = 0
    by_severity: SeveritySummary = Field(default_factory=SeveritySummary)
    overall_score: float = Field(10.0, ge=0.0, le=10.0)
    recommendation: Recommendation = Recommendation.APPROVE


class ChallengerMetadata(BaseModel):
    """Metadata about the challenger process."""

    enabled: bool = True
    total_iterations: int = 1
    final_satisfaction_score: float = 100.0
    threshold: float = 50.0
    convergence: ConvergenceStatus = ConvergenceStatus.THRESHOLD_MET
    iteration_history: list[IterationHistory] = Field(default_factory=list)
    insights: list[ChallengerInsight] = Field(default_factory=list)


class NextStep(BaseModel):
    """A recommended next step."""

    priority: int = Field(..., ge=1, le=10)
    action: str
    issues: list[str] = Field(default_factory=list, description="Related issue IDs")


class RepositoryInfo(BaseModel):
    """Information about the reviewed repository."""

    type: RepoType
    name: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None


class FinalReport(BaseModel):
    """Complete final review report."""

    id: str = Field(..., description="Unique report identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = Field("1.0.0", description="Report schema version")

    repository: RepositoryInfo
    summary: ReportSummary = Field(default_factory=lambda: ReportSummary())

    reviewers: list[ReviewerResult] = Field(
        default_factory=list, description="Results from each reviewer"
    )

    challenger: ChallengerMetadata = Field(
        default_factory=ChallengerMetadata,
        description="Challenger loop metadata",
    )

    issues: list[Issue] = Field(default_factory=list, description="All deduplicated issues")

    checklists: dict[str, ChecklistResult] = Field(
        default_factory=dict, description="Aggregated checklist results"
    )

    metrics: ReviewMetrics = Field(
        default_factory=lambda: ReviewMetrics(), description="Aggregated metrics"
    )

    next_steps: list[NextStep] = Field(default_factory=list, description="Prioritized action items")

    evaluation: RepositoryEvaluation | None = Field(
        None, description="Final repository evaluation scores (0-100)"
    )

    def calculate_recommendation(self) -> Recommendation:
        """Calculate recommendation based on issues."""
        if self.summary.by_severity.critical > 0:
            return Recommendation.REQUEST_CHANGES
        if self.summary.by_severity.high > 3:
            return Recommendation.REQUEST_CHANGES
        if self.summary.by_severity.high > 0:
            return Recommendation.APPROVE_WITH_CHANGES
        return Recommendation.APPROVE

    def to_markdown(self) -> str:
        """Generate markdown report."""
        from turbowrap.review.report_generator import ReportGenerator

        return ReportGenerator.to_markdown(self)

    def to_json(self) -> str:
        """Generate JSON report."""
        return self.model_dump_json(indent=2)
