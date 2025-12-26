"""
Issue processing utilities for TurboWrap orchestrators.

Provides common functions for:
- Issue deduplication (merging same issues from multiple reviewers)
- Issue prioritization (sorting by severity and category)
- Score calculation (overall quality score)
- Recommendation determination (approve/request changes)
"""

from typing import Any

from turbowrap.review.models.report import NextStep, Recommendation, SeveritySummary
from turbowrap.review.models.review import Issue, IssueSeverity

# Severity ranking for comparisons
SEVERITY_RANKS = {
    IssueSeverity.CRITICAL: 4,
    IssueSeverity.HIGH: 3,
    IssueSeverity.MEDIUM: 2,
    IssueSeverity.LOW: 1,
}

# Score deductions per severity
SEVERITY_DEDUCTIONS = {
    IssueSeverity.CRITICAL: 2.0,
    IssueSeverity.HIGH: 1.0,
    IssueSeverity.MEDIUM: 0.3,
    IssueSeverity.LOW: 0.1,
}

# Category multipliers for prioritization
CATEGORY_MULTIPLIERS = {
    "security": 1.5,
    "logic": 1.3,
    "performance": 1.1,
    "architecture": 1.0,
    "ux": 0.9,
    "style": 0.8,
    "testing": 0.9,
    "documentation": 0.7,
}


def get_severity_rank(severity: IssueSeverity) -> int:
    """
    Get numeric rank for severity comparison.

    Args:
        severity: Issue severity enum

    Returns:
        Numeric rank (higher = more severe)
    """
    return SEVERITY_RANKS.get(severity, 0)


def deduplicate_issues(issues: list[Issue]) -> list[Issue]:
    """
    Deduplicate issues from multiple reviewers.

    Issues are considered duplicates if they have the same:
    - file
    - line
    - category

    When duplicates are found:
    - Keep the highest severity
    - Merge flagged_by lists

    Args:
        issues: List of issues (may contain duplicates)

    Returns:
        Deduplicated list of issues
    """
    unique: dict[tuple[str | None, int | None, Any], Issue] = {}

    for issue in issues:
        key = (issue.file, issue.line, issue.category)

        if key in unique:
            existing = unique[key]
            # Keep highest severity
            if get_severity_rank(issue.severity) > get_severity_rank(existing.severity):
                existing.severity = issue.severity
            # Merge flagged_by
            for reviewer in issue.flagged_by:
                if reviewer not in existing.flagged_by:
                    existing.flagged_by.append(reviewer)
        else:
            unique[key] = issue

    return list(unique.values())


def calculate_priority_score(issue: Issue) -> float:
    """
    Calculate priority score for an issue.

    Score is based on:
    - Severity (base score)
    - Category (multiplier)
    - Number of reviewers that flagged it (bonus)

    Args:
        issue: Issue to score

    Returns:
        Priority score (0-100)
    """
    severity_scores = {
        IssueSeverity.CRITICAL: 100,
        IssueSeverity.HIGH: 75,
        IssueSeverity.MEDIUM: 50,
        IssueSeverity.LOW: 25,
    }

    base = severity_scores.get(issue.severity, 50)
    multiplier = CATEGORY_MULTIPLIERS.get(issue.category.value, 1.0)
    reviewer_bonus = len(issue.flagged_by) * 5

    return min(100, base * multiplier + reviewer_bonus)


def prioritize_issues(issues: list[Issue]) -> list[Issue]:
    """
    Sort issues by priority score (highest first).

    Args:
        issues: List of issues to sort

    Returns:
        Sorted list of issues
    """
    return sorted(issues, key=calculate_priority_score, reverse=True)


def calculate_overall_score(issues: list[Issue]) -> float:
    """
    Calculate overall quality score based on issues.

    Starts at 10.0 (perfect) and deducts based on issue severity.

    Args:
        issues: List of issues found

    Returns:
        Score from 0.0 to 10.0
    """
    if not issues:
        return 10.0

    total_deduction = sum(SEVERITY_DEDUCTIONS.get(issue.severity, 0.1) for issue in issues)

    return max(0.0, round(10.0 - total_deduction, 1))


def count_by_severity(issues: list[Issue]) -> SeveritySummary:
    """
    Count issues by severity level.

    Args:
        issues: List of issues

    Returns:
        SeveritySummary with counts
    """
    return SeveritySummary(
        critical=sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL),
        high=sum(1 for i in issues if i.severity == IssueSeverity.HIGH),
        medium=sum(1 for i in issues if i.severity == IssueSeverity.MEDIUM),
        low=sum(1 for i in issues if i.severity == IssueSeverity.LOW),
    )


def calculate_recommendation(severity_counts: SeveritySummary) -> Recommendation:
    """
    Determine recommendation based on severity counts.

    Rules:
    - REQUEST_CHANGES if any critical or >3 high
    - APPROVE_WITH_CHANGES if any high
    - APPROVE otherwise

    Args:
        severity_counts: Summary of issue severities

    Returns:
        Recommendation enum value
    """
    if severity_counts.critical >= 1:
        return Recommendation.REQUEST_CHANGES
    if severity_counts.high > 3:
        return Recommendation.REQUEST_CHANGES
    if severity_counts.high > 0:
        return Recommendation.APPROVE_WITH_CHANGES
    return Recommendation.APPROVE


def build_next_steps(issues: list[Issue]) -> list[NextStep]:
    """
    Build prioritized list of next steps based on issues.

    Groups issues by severity and creates actionable steps.

    Args:
        issues: Prioritized list of issues

    Returns:
        List of NextStep actions
    """
    steps = []

    critical_issues = [i for i in issues if i.severity == IssueSeverity.CRITICAL]
    if critical_issues:
        steps.append(
            NextStep(
                priority=1,
                action=f"Fix {len(critical_issues)} critical security/logic issues",
                issues=[i.id for i in critical_issues],
            )
        )

    high_issues = [i for i in issues if i.severity == IssueSeverity.HIGH]
    if high_issues:
        steps.append(
            NextStep(
                priority=2,
                action=f"Address {len(high_issues)} high priority issues",
                issues=[i.id for i in high_issues],
            )
        )

    medium_issues = [i for i in issues if i.severity == IssueSeverity.MEDIUM]
    if medium_issues:
        steps.append(
            NextStep(
                priority=3,
                action=f"Consider {len(medium_issues)} medium priority suggestions",
                issues=[i.id for i in medium_issues[:5]],  # Limit to first 5
            )
        )

    return steps


def process_issues(
    issues: list[Issue],
) -> tuple[list[Issue], SeveritySummary, float, Recommendation, list[NextStep]]:
    """
    Full issue processing pipeline.

    Args:
        issues: Raw list of issues from reviewers

    Returns:
        Tuple of (deduplicated_issues, severity_counts, score, recommendation, next_steps)
    """
    deduplicated = deduplicate_issues(issues)
    prioritized = prioritize_issues(deduplicated)
    severity_counts = count_by_severity(prioritized)
    score = calculate_overall_score(prioritized)
    recommendation = calculate_recommendation(severity_counts)
    next_steps = build_next_steps(prioritized)

    return prioritized, severity_counts, score, recommendation, next_steps
