"""
Functional tests for issue deduplication and prioritization.

Run with: uv run pytest tests/review/test_issue_prioritization.py -v

These tests verify:
1. Issue deduplication (merging duplicates from multiple reviewers)
2. Severity ordering (critical > high > medium > low)
3. Priority score calculation (severity + category + reviewer count)
4. Overall score calculation (10.0 - severity deductions)
5. Recommendation logic (approve/request changes based on severity counts)
6. Full processing pipeline
"""

import pytest

from turbowrap.orchestration.report_utils import (
    SEVERITY_DEDUCTIONS,
    build_next_steps,
    calculate_overall_score,
    calculate_priority_score,
    calculate_recommendation,
    count_by_severity,
    deduplicate_issues,
    get_severity_rank,
    prioritize_issues,
    process_issues,
)
from turbowrap.review.models.report import Recommendation, SeveritySummary
from turbowrap.review.models.review import Issue, IssueCategory, IssueSeverity

# =============================================================================
# Test Fixtures
# =============================================================================


def _make_issue(
    file: str,
    line: int,
    severity: IssueSeverity,
    category: IssueCategory,
    title: str,
    description: str | None = None,
    suggestion: str | None = None,
    flagged_by: list[str] | None = None,
    issue_id: str | None = None,
) -> Issue:
    """Factory function to create Issue with required fields."""
    # Auto-generate ID if not provided
    if issue_id is None:
        severity_code = severity.value[:4].upper()
        issue_id = f"TEST-{severity_code}-{file.replace('/', '-')}-L{line}"

    return Issue(
        id=issue_id,
        file=file,
        line=line,
        severity=severity,
        category=category,
        title=title,
        description=description or title,
        suggested_fix=suggestion,
        flagged_by=flagged_by or [],
    )


@pytest.fixture
def sample_issues():
    """Create a set of sample issues for testing."""
    return [
        _make_issue(
            file="src/main.py",
            line=10,
            severity=IssueSeverity.CRITICAL,
            category=IssueCategory.SECURITY,
            title="SQL injection vulnerability",
            suggestion="Use parameterized queries",
            flagged_by=["reviewer_be_quality"],
        ),
        _make_issue(
            file="src/main.py",
            line=25,
            severity=IssueSeverity.HIGH,
            category=IssueCategory.ARCHITECTURE,
            title="Function too long",
            suggestion="Extract into smaller functions",
            flagged_by=["reviewer_be_architecture"],
        ),
        _make_issue(
            file="src/utils.py",
            line=5,
            severity=IssueSeverity.MEDIUM,
            category=IssueCategory.DOCUMENTATION,
            title="Missing docstring",
            suggestion="Add docstring",
            flagged_by=["reviewer_be_quality"],
        ),
        _make_issue(
            file="src/utils.py",
            line=15,
            severity=IssueSeverity.LOW,
            category=IssueCategory.STYLE,
            title="Line too long",
            suggestion="Break into multiple lines",
            flagged_by=["reviewer_be_quality"],
        ),
    ]


@pytest.fixture
def duplicate_issues():
    """Create issues that should be deduplicated."""
    return [
        _make_issue(
            file="src/main.py",
            line=10,
            severity=IssueSeverity.MEDIUM,
            category=IssueCategory.SECURITY,
            title="Missing null check",
            suggestion="Add null check",
            flagged_by=["reviewer_be_quality"],
            issue_id="TEST-SEC-001",
        ),
        _make_issue(
            file="src/main.py",
            line=10,
            severity=IssueSeverity.HIGH,  # Higher severity, should win
            category=IssueCategory.SECURITY,
            title="Potential null pointer",
            suggestion="Validate input",
            flagged_by=["reviewer_be_architecture"],
            issue_id="TEST-SEC-002",
        ),
        _make_issue(
            file="src/main.py",
            line=10,
            severity=IssueSeverity.LOW,
            category=IssueCategory.SECURITY,
            title="Check for null",
            suggestion="Add validation",
            flagged_by=["analyst_func"],
            issue_id="TEST-SEC-003",
        ),
    ]


# =============================================================================
# Deduplication Tests
# =============================================================================


@pytest.mark.functional
class TestIssueDuplication:
    """Tests for issue deduplication logic."""

    def test_duplicate_issues_merged(self, duplicate_issues):
        """Duplicate issues from multiple reviewers are merged."""
        result = deduplicate_issues(duplicate_issues)

        # Should have only 1 issue (all 3 are on same file/line/category)
        assert len(result) == 1

    def test_highest_severity_kept(self, duplicate_issues):
        """When merging duplicates, highest severity is kept."""
        result = deduplicate_issues(duplicate_issues)

        # HIGH (from second issue) should win
        assert result[0].severity == IssueSeverity.HIGH

    def test_flagged_by_merged(self, duplicate_issues):
        """When merging, all flagged_by reviewers are kept."""
        result = deduplicate_issues(duplicate_issues)

        flagged_by = result[0].flagged_by
        assert len(flagged_by) == 3
        assert "reviewer_be_quality" in flagged_by
        assert "reviewer_be_architecture" in flagged_by
        assert "analyst_func" in flagged_by

    def test_no_duplicates_unchanged(self, sample_issues):
        """Issues with no duplicates pass through unchanged."""
        result = deduplicate_issues(sample_issues)

        assert len(result) == len(sample_issues)

    def test_different_lines_not_duplicates(self):
        """Issues on different lines are not duplicates."""
        issues = [
            _make_issue(
                file="src/main.py",
                line=10,
                severity=IssueSeverity.HIGH,
                category=IssueCategory.SECURITY,
                title="Issue 1",
            ),
            _make_issue(
                file="src/main.py",
                line=20,  # Different line
                severity=IssueSeverity.HIGH,
                category=IssueCategory.SECURITY,
                title="Issue 2",
            ),
        ]

        result = deduplicate_issues(issues)

        assert len(result) == 2

    def test_different_categories_not_duplicates(self):
        """Issues with different categories are not duplicates."""
        issues = [
            _make_issue(
                file="src/main.py",
                line=10,
                severity=IssueSeverity.HIGH,
                category=IssueCategory.SECURITY,
                title="Security issue",
            ),
            _make_issue(
                file="src/main.py",
                line=10,
                severity=IssueSeverity.HIGH,
                category=IssueCategory.PERFORMANCE,  # Different category
                title="Performance issue",
            ),
        ]

        result = deduplicate_issues(issues)

        assert len(result) == 2


# =============================================================================
# Severity Ordering Tests
# =============================================================================


@pytest.mark.functional
class TestSeverityOrdering:
    """Tests for severity-based ordering."""

    def test_severity_rank_ordering(self):
        """Severity ranks are ordered correctly."""
        assert get_severity_rank(IssueSeverity.CRITICAL) > get_severity_rank(IssueSeverity.HIGH)
        assert get_severity_rank(IssueSeverity.HIGH) > get_severity_rank(IssueSeverity.MEDIUM)
        assert get_severity_rank(IssueSeverity.MEDIUM) > get_severity_rank(IssueSeverity.LOW)

    def test_prioritize_by_severity(self):
        """Issues are prioritized by severity (highest first)."""
        issues = [
            _make_issue(
                file="a.py",
                line=1,
                severity=IssueSeverity.LOW,
                category=IssueCategory.DOCUMENTATION,
                title="Low",
            ),
            _make_issue(
                file="b.py",
                line=1,
                severity=IssueSeverity.CRITICAL,
                category=IssueCategory.DOCUMENTATION,
                title="Critical",
            ),
            _make_issue(
                file="c.py",
                line=1,
                severity=IssueSeverity.MEDIUM,
                category=IssueCategory.DOCUMENTATION,
                title="Medium",
            ),
        ]

        result = prioritize_issues(issues)

        assert result[0].severity == IssueSeverity.CRITICAL
        assert result[1].severity == IssueSeverity.MEDIUM
        assert result[2].severity == IssueSeverity.LOW


# =============================================================================
# Priority Score Calculation Tests
# =============================================================================


@pytest.mark.functional
class TestPriorityScoreCalculation:
    """Tests for priority score calculation."""

    def test_critical_has_highest_base_score(self):
        """Critical issues have highest base score."""
        critical = _make_issue(
            file="a.py",
            line=1,
            severity=IssueSeverity.CRITICAL,
            category=IssueCategory.DOCUMENTATION,
            title="Critical",
        )
        high = _make_issue(
            file="b.py",
            line=1,
            severity=IssueSeverity.HIGH,
            category=IssueCategory.DOCUMENTATION,
            title="High",
        )

        assert calculate_priority_score(critical) > calculate_priority_score(high)

    def test_security_category_multiplier(self):
        """Security issues get higher priority than same-severity quality issues."""
        security = _make_issue(
            file="a.py",
            line=1,
            severity=IssueSeverity.HIGH,
            category=IssueCategory.SECURITY,
            title="Security",
        )
        quality = _make_issue(
            file="b.py",
            line=1,
            severity=IssueSeverity.HIGH,
            category=IssueCategory.DOCUMENTATION,
            title="Quality",
        )

        assert calculate_priority_score(security) > calculate_priority_score(quality)

    def test_multiple_reviewers_bonus(self):
        """Issues flagged by multiple reviewers get bonus score."""
        single_reviewer = _make_issue(
            file="a.py",
            line=1,
            severity=IssueSeverity.HIGH,
            category=IssueCategory.DOCUMENTATION,
            title="Single",
            flagged_by=["reviewer1"],
        )
        multiple_reviewers = _make_issue(
            file="b.py",
            line=1,
            severity=IssueSeverity.HIGH,
            category=IssueCategory.DOCUMENTATION,
            title="Multiple",
            flagged_by=["reviewer1", "reviewer2", "reviewer3"],
        )

        single_score = calculate_priority_score(single_reviewer)
        multi_score = calculate_priority_score(multiple_reviewers)

        # 3 reviewers = 15 bonus (3 * 5), vs 1 reviewer = 5 bonus
        assert multi_score > single_score
        assert multi_score - single_score == 10  # (3-1) * 5

    def test_score_capped_at_100(self):
        """Priority score is capped at 100."""
        maxed = _make_issue(
            file="a.py",
            line=1,
            severity=IssueSeverity.CRITICAL,
            category=IssueCategory.SECURITY,
            title="Max",
            flagged_by=["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10"],
        )

        score = calculate_priority_score(maxed)

        assert score == 100


# =============================================================================
# Overall Score Calculation Tests
# =============================================================================


@pytest.mark.functional
class TestOverallScoreCalculation:
    """Tests for overall quality score calculation."""

    def test_no_issues_perfect_score(self):
        """No issues = perfect score of 10.0."""
        score = calculate_overall_score([])

        assert score == 10.0

    def test_critical_issue_deduction(self):
        """Critical issue deducts heavily from score."""
        issues = [
            _make_issue(
                file="a.py",
                line=1,
                severity=IssueSeverity.CRITICAL,
                category=IssueCategory.SECURITY,
                title="Critical",
            )
        ]

        score = calculate_overall_score(issues)

        expected = 10.0 - SEVERITY_DEDUCTIONS[IssueSeverity.CRITICAL]
        assert score == expected

    def test_multiple_issues_accumulate(self):
        """Multiple issues accumulate deductions."""
        issues = [
            _make_issue(
                file="a.py",
                line=1,
                severity=IssueSeverity.HIGH,
                category=IssueCategory.DOCUMENTATION,
                title="High 1",
            ),
            _make_issue(
                file="b.py",
                line=1,
                severity=IssueSeverity.HIGH,
                category=IssueCategory.DOCUMENTATION,
                title="High 2",
            ),
        ]

        score = calculate_overall_score(issues)

        expected = 10.0 - (2 * SEVERITY_DEDUCTIONS[IssueSeverity.HIGH])
        assert score == expected

    def test_score_minimum_zero(self):
        """Score cannot go below 0."""
        issues = [
            _make_issue(
                file=f"{i}.py",
                line=1,
                severity=IssueSeverity.CRITICAL,
                category=IssueCategory.SECURITY,
                title=f"Critical {i}",
            )
            for i in range(10)
        ]

        score = calculate_overall_score(issues)

        assert score == 0.0


# =============================================================================
# Recommendation Tests
# =============================================================================


@pytest.mark.functional
class TestRecommendationLogic:
    """Tests for recommendation determination."""

    def test_approve_with_no_issues(self):
        """No issues = APPROVE."""
        counts = SeveritySummary(critical=0, high=0, medium=0, low=0)

        recommendation = calculate_recommendation(counts)

        assert recommendation == Recommendation.APPROVE

    def test_approve_with_only_low_medium(self):
        """Only low/medium issues = APPROVE."""
        counts = SeveritySummary(critical=0, high=0, medium=5, low=10)

        recommendation = calculate_recommendation(counts)

        assert recommendation == Recommendation.APPROVE

    def test_approve_with_changes_for_high(self):
        """Any high issues (up to 3) = APPROVE_WITH_CHANGES."""
        counts = SeveritySummary(critical=0, high=2, medium=0, low=0)

        recommendation = calculate_recommendation(counts)

        assert recommendation == Recommendation.APPROVE_WITH_CHANGES

    def test_request_changes_for_critical(self):
        """Any critical issue = REQUEST_CHANGES."""
        counts = SeveritySummary(critical=1, high=0, medium=0, low=0)

        recommendation = calculate_recommendation(counts)

        assert recommendation == Recommendation.REQUEST_CHANGES

    def test_request_changes_for_many_high(self):
        """More than 3 high issues = REQUEST_CHANGES."""
        counts = SeveritySummary(critical=0, high=4, medium=0, low=0)

        recommendation = calculate_recommendation(counts)

        assert recommendation == Recommendation.REQUEST_CHANGES


# =============================================================================
# Next Steps Generation Tests
# =============================================================================


@pytest.mark.functional
class TestNextStepsGeneration:
    """Tests for next steps generation."""

    def test_critical_issues_priority_1(self, sample_issues):
        """Critical issues get priority 1 step."""
        steps = build_next_steps(sample_issues)

        priority_1 = [s for s in steps if s.priority == 1]
        assert len(priority_1) == 1
        assert "critical" in priority_1[0].action.lower()

    def test_high_issues_priority_2(self, sample_issues):
        """High issues get priority 2 step."""
        steps = build_next_steps(sample_issues)

        priority_2 = [s for s in steps if s.priority == 2]
        assert len(priority_2) == 1
        assert "high priority" in priority_2[0].action.lower()

    def test_no_steps_for_empty_issues(self):
        """No steps generated for empty issue list."""
        steps = build_next_steps([])

        assert len(steps) == 0


# =============================================================================
# Full Pipeline Tests
# =============================================================================


@pytest.mark.functional
class TestFullProcessingPipeline:
    """Tests for full issue processing pipeline."""

    def test_process_issues_returns_all_components(self, sample_issues):
        """process_issues returns all expected components."""
        issues, counts, score, recommendation, steps = process_issues(sample_issues)

        assert isinstance(issues, list)
        assert isinstance(counts, SeveritySummary)
        assert isinstance(score, float)
        assert isinstance(recommendation, Recommendation)
        assert isinstance(steps, list)

    def test_process_issues_deduplicates(self, duplicate_issues):
        """process_issues deduplicates input."""
        issues, *_ = process_issues(duplicate_issues)

        assert len(issues) == 1  # All 3 duplicates merged

    def test_process_issues_prioritizes(self, sample_issues):
        """process_issues returns prioritized issues."""
        issues, *_ = process_issues(sample_issues)

        # First issue should be highest priority (critical)
        assert issues[0].severity == IssueSeverity.CRITICAL

    def test_process_issues_counts_correctly(self, sample_issues):
        """process_issues counts severities correctly."""
        _, counts, *_ = process_issues(sample_issues)

        assert counts.critical == 1
        assert counts.high == 1
        assert counts.medium == 1
        assert counts.low == 1
        assert counts.total == 4


# =============================================================================
# Severity Summary Tests
# =============================================================================


@pytest.mark.functional
class TestSeveritySummary:
    """Tests for severity summary counting."""

    def test_count_by_severity(self, sample_issues):
        """count_by_severity returns correct counts."""
        counts = count_by_severity(sample_issues)

        assert counts.critical == 1
        assert counts.high == 1
        assert counts.medium == 1
        assert counts.low == 1

    def test_total_property(self, sample_issues):
        """SeveritySummary.total returns sum of all counts."""
        counts = count_by_severity(sample_issues)

        assert counts.total == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
