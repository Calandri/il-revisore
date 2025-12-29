"""
Response parsers for LLM outputs.

Centralized parsing logic for:
- ReviewOutput (from reviewer responses)
- ChallengerFeedback (from challenger responses)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from turbowrap.review.models.challenger import (
    Challenge,
    ChallengerFeedback,
    ChallengerStatus,
    DimensionScores,
    MissedIssue,
)
from turbowrap.review.models.review import (
    ChecklistResult,
    Issue,
    IssueCategory,
    IssueSeverity,
    ReviewMetrics,
    ReviewOutput,
    ReviewSummary,
)
from turbowrap.review.reviewers.utils.json_extraction import parse_json_safe

logger = logging.getLogger(__name__)


# Category normalization map for common aliases
CATEGORY_ALIASES: dict[str, str] = {
    # Logic-related
    "business_logic": "logic",
    "business": "logic",
    "functional": "logic",
    "error_handling": "logic",
    "data_integrity": "logic",
    "reliability": "logic",
    "validation": "logic",
    # Security-related
    "access_control": "security",
    "authentication": "security",
    "authorization": "security",
    # Performance-related
    "scalability": "performance",
    "efficiency": "performance",
    "optimization": "performance",
    # Architecture-related
    "maintainability": "architecture",
    "design": "architecture",
    "structure": "architecture",
    # Style-related
    "code_quality": "style",
    "quality": "style",
    "readability": "style",
}


def parse_review_output(
    response_text: str,
    reviewer_name: str,
    files_reviewed: int = 0,
) -> ReviewOutput:
    """
    Parse LLM response into ReviewOutput.

    Handles:
    - Score normalization (0-100 -> 0-10)
    - Category alias normalization
    - Field name variations
    - Parse errors (returns minimal output)

    Args:
        response_text: Raw LLM response
        reviewer_name: Name of the reviewer
        files_reviewed: Fallback file count

    Returns:
        ReviewOutput (may be minimal on parse error)
    """
    try:
        data = parse_json_safe(response_text)

        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")

        # Parse summary
        summary_data = data.get("summary", {})
        if not isinstance(summary_data, dict):
            logger.warning(
                f"[PARSE] Invalid summary type: {type(summary_data).__name__}, using defaults"
            )
            summary_data = {}

        # Normalize score: LLMs sometimes return 0-100 instead of 0-10
        raw_score = summary_data.get("score", 10.0)
        if raw_score > 10:
            logger.warning(f"[PARSE] Score {raw_score} > 10, normalizing to 0-10 scale")
            raw_score = raw_score / 10.0
        normalized_score = max(0.0, min(10.0, raw_score))

        # Handle field name variations (LLMs sometimes use shorter names)
        summary = ReviewSummary(
            files_reviewed=summary_data.get("files_reviewed", files_reviewed),
            critical_issues=summary_data.get("critical_issues", summary_data.get("critical", 0)),
            high_issues=summary_data.get("high_issues", summary_data.get("high", 0)),
            medium_issues=summary_data.get("medium_issues", summary_data.get("medium", 0)),
            low_issues=summary_data.get("low_issues", summary_data.get("low", 0)),
            score=normalized_score,
        )

        # Parse issues
        issues = []
        for issue_data in data.get("issues", []):
            try:
                # Normalize category
                raw_category = issue_data.get("category", "style").lower()
                normalized_category = CATEGORY_ALIASES.get(raw_category, raw_category)

                issue = Issue(
                    id=issue_data.get("id", f"{reviewer_name.upper()}-ISSUE"),
                    severity=IssueSeverity(issue_data.get("severity", "MEDIUM")),
                    category=IssueCategory(normalized_category),
                    rule=issue_data.get("rule"),
                    file=issue_data.get("file", "unknown"),
                    line=issue_data.get("line"),
                    title=issue_data.get("title", "Issue"),
                    description=issue_data.get("description", ""),
                    current_code=issue_data.get("current_code"),
                    suggested_fix=issue_data.get("suggested_fix"),
                    references=issue_data.get("references", []),
                    flagged_by=[reviewer_name],
                    # Effort estimation (handle field name variations)
                    estimated_effort=issue_data.get("estimated_effort", issue_data.get("effort")),
                    estimated_files_count=issue_data.get(
                        "estimated_files_count", issue_data.get("estimated_files_to_fix")
                    ),
                )
                issues.append(issue)
            except Exception as e:
                logger.warning(
                    f"[PARSE] Skipping invalid issue: {e} - data: {issue_data.get('id', 'unknown')}"
                )
                continue

        # Parse checklists
        checklists = {}
        for category, checks in data.get("checklists", {}).items():
            if not isinstance(checks, dict):
                logger.warning(
                    f"[PARSE] Skipping invalid checklist '{category}': "
                    f"expected dict, got {type(checks).__name__}"
                )
                continue
            checklists[category] = ChecklistResult(
                passed=checks.get("passed", 0),
                failed=checks.get("failed", 0),
                skipped=checks.get("skipped", 0),
            )

        # Parse metrics
        metrics_data = data.get("metrics", {})
        metrics = ReviewMetrics(
            complexity_avg=metrics_data.get("complexity_avg"),
            test_coverage=metrics_data.get("test_coverage"),
            type_coverage=metrics_data.get("type_coverage"),
        )

        return ReviewOutput(
            reviewer=reviewer_name,
            summary=summary,
            issues=issues,
            checklists=checklists,
            metrics=metrics,
        )

    except Exception as e:
        logger.error(f"[PARSE] Review parse error: {e}")
        return ReviewOutput(
            reviewer=reviewer_name,
            summary=ReviewSummary(files_reviewed=files_reviewed, score=0.0),
            issues=[],  # No fake error issues - let the error be handled properly
        )


def convert_dict_to_review_output(
    data: dict[str, Any],
    reviewer_name: str,
    files_reviewed: int = 0,
    flagged_by: list[str] | None = None,
) -> ReviewOutput | None:
    """
    Convert a pre-parsed dict into ReviewOutput.

    Use this when you've already extracted JSON (e.g., from multi-JSON output).
    For raw LLM response text, use parse_review_output() instead.

    Args:
        data: Pre-parsed dict with review data
        reviewer_name: Name of the reviewer
        files_reviewed: Fallback file count
        flagged_by: Optional list of sources (e.g., ["claude", "reviewer_be_arch"])

    Returns:
        ReviewOutput or None on error
    """
    try:
        if not isinstance(data, dict):
            logger.warning(f"[CONVERT] Expected dict, got {type(data).__name__}")
            return None

        # Parse summary
        summary_data = data.get("summary", {})
        if not isinstance(summary_data, dict):
            summary_data = {}

        # Normalize score
        raw_score = summary_data.get("score", 5.0)
        if raw_score > 10:
            raw_score = raw_score / 10.0
        normalized_score = max(0.0, min(10.0, raw_score))

        summary = ReviewSummary(
            files_reviewed=summary_data.get("files_reviewed", files_reviewed),
            critical_issues=summary_data.get("critical_issues", summary_data.get("critical", 0)),
            high_issues=summary_data.get("high_issues", summary_data.get("high", 0)),
            medium_issues=summary_data.get("medium_issues", summary_data.get("medium", 0)),
            low_issues=summary_data.get("low_issues", summary_data.get("low", 0)),
            score=normalized_score,
        )

        # Parse issues
        issues = []
        issue_flagged_by = flagged_by or [reviewer_name]

        for issue_data in data.get("issues", []):
            try:
                # Normalize category
                raw_category = issue_data.get("category", "logic").lower()
                normalized_category = CATEGORY_ALIASES.get(raw_category, raw_category)

                # Validate category enum
                try:
                    category = IssueCategory(normalized_category)
                except ValueError:
                    category = IssueCategory.LOGIC

                # Normalize severity
                severity_str = issue_data.get("severity", "medium").lower()
                try:
                    severity = IssueSeverity(severity_str)
                except ValueError:
                    severity = IssueSeverity.MEDIUM

                issue = Issue(
                    id=issue_data.get(
                        "id", issue_data.get("code", f"{reviewer_name.upper()}-ISSUE")
                    ),
                    severity=severity,
                    category=category,
                    rule=issue_data.get("rule"),
                    file=issue_data.get("file", "unknown"),
                    line=issue_data.get("line"),
                    title=issue_data.get("title", "Issue"),
                    description=issue_data.get("description", ""),
                    current_code=issue_data.get("current_code"),
                    suggested_fix=issue_data.get("suggested_fix"),
                    references=issue_data.get("references", []),
                    flagged_by=list(issue_flagged_by),  # Copy to avoid mutation
                    estimated_effort=issue_data.get("estimated_effort", issue_data.get("effort")),
                    estimated_files_count=issue_data.get(
                        "estimated_files_count", issue_data.get("estimated_files_to_fix")
                    ),
                )
                issues.append(issue)
            except Exception as e:
                logger.debug(f"[CONVERT] Skipping invalid issue: {e}")
                continue

        return ReviewOutput(
            reviewer=reviewer_name,
            summary=summary,
            issues=issues,
        )

    except Exception as e:
        logger.warning(f"[CONVERT] Dict conversion error: {e}")
        return None


def parse_challenger_feedback(
    response_text: str,
    iteration: int,
    threshold: float,
) -> ChallengerFeedback:
    """
    Parse LLM response into ChallengerFeedback.

    Args:
        response_text: Raw LLM response
        iteration: Current iteration number
        threshold: Satisfaction threshold

    Returns:
        ChallengerFeedback
    """
    try:
        data = parse_json_safe(response_text)

        # Parse dimension scores
        dim_data = data.get("dimension_scores", {})
        dimension_scores = DimensionScores(
            completeness=dim_data.get("completeness", 50),
            accuracy=dim_data.get("accuracy", 50),
            depth=dim_data.get("depth", 50),
            actionability=dim_data.get("actionability", 50),
        )

        # Parse missed issues
        missed_issues = [
            MissedIssue(
                type=mi.get("type", "unknown"),
                description=mi.get("description", ""),
                file=mi.get("file", "unknown"),
                lines=mi.get("lines"),
                why_important=mi.get("why_important", ""),
                suggested_severity=mi.get("suggested_severity"),
            )
            for mi in data.get("missed_issues", [])
        ]

        # Parse challenges
        challenges = [
            Challenge(
                issue_id=ch.get("issue_id", "unknown"),
                challenge_type=ch.get("challenge_type", "needs_context"),
                challenge=ch.get("challenge", ""),
                reasoning=ch.get("reasoning", ""),
                suggested_change=ch.get("suggested_change"),
            )
            for ch in data.get("challenges", [])
        ]

        # Determine status
        score = data.get("satisfaction_score", dimension_scores.weighted_score)
        status_str = data.get("status", "")

        status: ChallengerStatus | None = None
        if status_str:
            try:
                status = ChallengerStatus(status_str)
            except ValueError:
                status = None

        if status is None:
            status = _score_to_status(score, threshold)

        return ChallengerFeedback(
            iteration=iteration,
            timestamp=datetime.utcnow(),
            satisfaction_score=score,
            threshold=threshold,
            status=status,
            dimension_scores=dimension_scores,
            missed_issues=missed_issues,
            challenges=challenges,
            improvements_needed=data.get("improvements_needed", []),
            positive_feedback=data.get("positive_feedback", []),
        )

    except Exception as e:
        logger.error(f"[PARSE] Challenger parse error: {e}")
        return ChallengerFeedback(
            iteration=iteration,
            satisfaction_score=50,
            threshold=threshold,
            status=ChallengerStatus.NEEDS_REFINEMENT,
            dimension_scores=DimensionScores(
                completeness=50,
                accuracy=50,
                depth=50,
                actionability=50,
            ),
            improvements_needed=[f"Parse error: {str(e)[:200]}"],
        )


def _score_to_status(score: float, threshold: float) -> ChallengerStatus:
    """Convert satisfaction score to status."""
    if score >= threshold:
        return ChallengerStatus.APPROVED
    if score >= 70:
        return ChallengerStatus.NEEDS_REFINEMENT
    return ChallengerStatus.MAJOR_ISSUES
