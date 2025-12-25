"""
Pydantic models for TurboWrap review JSON schemas.
"""

from turbowrap.review.models.challenger import (
    Challenge,
    ChallengerFeedback,
    ChallengerStatus,
    DimensionScores,
    MissedIssue,
)
from turbowrap.review.models.evaluation import RepositoryEvaluation
from turbowrap.review.models.report import (
    ChallengerInsight,
    ChallengerMetadata,
    ConvergenceStatus,
    FinalReport,
    IterationHistory,
    NextStep,
    Recommendation,
    ReportSummary,
    RepositoryInfo,
    RepoType,
    ReviewerResult,
    SeveritySummary,
)
from turbowrap.review.models.review import (
    ChecklistResult,
    Issue,
    IssueCategory,
    IssueSeverity,
    ReviewMetrics,
    ReviewOptions,
    ReviewOutput,
    ReviewRequest,
    ReviewRequestSource,
    ReviewRequirements,
    ReviewSummary,
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
    # Evaluation models
    "RepositoryEvaluation",
]
