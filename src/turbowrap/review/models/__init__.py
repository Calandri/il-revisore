"""
Pydantic models for TurboWrap review JSON schemas.
"""

from turbowrap.review.models.review import (
    ReviewRequest,
    ReviewOutput,
    Issue,
    IssueSeverity,
    IssueCategory,
    ChecklistResult,
    ReviewMetrics,
    ReviewSummary,
    ReviewRequestSource,
    ReviewRequirements,
    ReviewOptions,
)
from turbowrap.review.models.challenger import (
    ChallengerFeedback,
    ChallengerStatus,
    DimensionScores,
    MissedIssue,
    Challenge,
)
from turbowrap.review.models.report import (
    FinalReport,
    RepoType,
    Recommendation,
    ReviewerResult,
    IterationHistory,
    ConvergenceStatus,
    ChallengerInsight,
    SeveritySummary,
    ReportSummary,
    ChallengerMetadata,
    NextStep,
    RepositoryInfo,
)

__all__ = [
    # Review models
    "ReviewRequest",
    "ReviewOutput",
    "Issue",
    "IssueSeverity",
    "IssueCategory",
    "ChecklistResult",
    "ReviewMetrics",
    "ReviewSummary",
    "ReviewRequestSource",
    "ReviewRequirements",
    "ReviewOptions",
    # Challenger models
    "ChallengerFeedback",
    "ChallengerStatus",
    "DimensionScores",
    "MissedIssue",
    "Challenge",
    # Report models
    "FinalReport",
    "RepoType",
    "Recommendation",
    "ReviewerResult",
    "IterationHistory",
    "ConvergenceStatus",
    "ChallengerInsight",
    "SeveritySummary",
    "ReportSummary",
    "ChallengerMetadata",
    "NextStep",
    "RepositoryInfo",
]
