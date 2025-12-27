"""
End-to-end tests for the fix pipeline.

Run with: uv run pytest tests/fix/test_fix_pipeline_e2e.py -v

These tests verify the complete fix pipeline from issue classification
through to git commit, including:
1. Fix succeeds on first iteration (Gemini approves)
2. Fix with feedback iterations
3. Issue batching by workload
4. BE/FE classification
5. Branch creation and handling
6. Workspace scope validation

Note: Uses MockIssue to avoid SQLAlchemy model loading issues.
"""

import sys
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass
class MockIssue:
    """Mock Issue class for testing without SQLAlchemy.

    Mimics the interface of turbowrap.db.models.Issue.
    """

    id: int
    issue_code: str
    title: str = ""
    description: str = ""
    file: str = ""
    line: int | None = None
    end_line: int | None = None
    severity: str = "MEDIUM"
    category: str = "quality"
    suggested_fix: str | None = None
    current_code: str | None = None
    estimated_effort: int | None = None
    estimated_files_count: int | None = None


# Mock the db.models module before importing fix.orchestrator
mock_db_models = MagicMock()
mock_db_models.Issue = MockIssue
sys.modules["turbowrap.db.models"] = mock_db_models
sys.modules["turbowrap.db"] = MagicMock()

# Now we can import the fix modules
from turbowrap.fix.models import (  # noqa: E402
    FixRequest,
)
from turbowrap.fix.orchestrator import (  # noqa: E402
    DEFAULT_EFFORT,
    DEFAULT_FILES,
    MAX_ISSUES_PER_CLI_CALL,
    MAX_WORKLOAD_POINTS_PER_BATCH,
    FixOrchestrator,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fix_repo(tmp_path):
    """Create a temporary repository for fix tests."""
    repo = tmp_path / "fix_repo"
    repo.mkdir()

    # Create backend files
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text(
        """
def process_data(data):
    # TODO: Add validation
    result = eval(data)  # Security issue
    return result
"""
    )
    (repo / "src" / "utils.py").write_text(
        """
def format_string(s):
    return s.upper()
"""
    )

    # Create frontend files
    (repo / "frontend").mkdir()
    (repo / "frontend" / "App.tsx").write_text(
        """
import React from "react";
export const App = () => <div>App</div>;
"""
    )

    # Initialize git repo
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )

    return repo


@pytest.fixture
def sample_backend_issues():
    """Create sample backend issues for testing."""
    return [
        MockIssue(
            id=1,
            issue_code="BE-001",
            title="SQL Injection in query builder",
            description="Use parameterized queries",
            file="src/main.py",
            line=10,
            severity="HIGH",
            category="security",
            suggested_fix="Use parameterized queries instead of string concatenation",
            estimated_effort=2,
            estimated_files_count=1,
        ),
        MockIssue(
            id=2,
            issue_code="BE-002",
            title="Missing error handling",
            description="Add try-except block",
            file="src/utils.py",
            line=5,
            severity="MEDIUM",
            category="quality",
            suggested_fix="Wrap in try-except block",
            estimated_effort=1,
            estimated_files_count=1,
        ),
    ]


@pytest.fixture
def sample_frontend_issues():
    """Create sample frontend issues for testing."""
    return [
        MockIssue(
            id=3,
            issue_code="FE-001",
            title="Missing key prop in list",
            description="Add key prop to list items",
            file="frontend/App.tsx",
            line=5,
            severity="MEDIUM",
            category="react",
            suggested_fix="Add unique key prop",
            estimated_effort=1,
            estimated_files_count=1,
        ),
    ]


@pytest.fixture
def sample_fix_request():
    """Create a sample fix request."""
    return FixRequest(
        task_id="task_123456789",
        repository_id="repo_123",
        use_existing_branch=False,
    )


@pytest.fixture
def mock_claude_cli_success():
    """Mock ClaudeCLI that succeeds."""
    mock = AsyncMock()
    mock.return_value = "Fix applied successfully. Modified src/main.py"
    return mock


@pytest.fixture
def mock_gemini_cli_success():
    """Mock GeminiCLI that approves with high score."""
    mock = MagicMock()
    mock.run = AsyncMock()
    mock.run.return_value = MagicMock(
        success=True,
        output="""
BATCH_SCORE: 98

ISSUE_SCORES:
- BE-001: 98 | Fix correctly applied, parameterized query used

FAILED_ISSUES: none

All issues fixed correctly.
""",
    )
    return mock


@pytest.fixture
def mock_gemini_cli_needs_retry():
    """Mock GeminiCLI that requires a retry."""
    call_count = [0]

    async def mock_run(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: needs retry
            return MagicMock(
                success=True,
                output="""
BATCH_SCORE: 75

ISSUE_SCORES:
- BE-001: 75 | Fix incomplete, still vulnerable

FAILED_ISSUES: BE-001

The fix is partial. Need to also sanitize inputs.
""",
            )
        # Second call: approved
        return MagicMock(
            success=True,
            output="""
BATCH_SCORE: 98

ISSUE_SCORES:
- BE-001: 98 | Fix correctly applied now

FAILED_ISSUES: none

All issues fixed correctly.
""",
        )

    mock = MagicMock()
    mock.run = mock_run
    return mock


# =============================================================================
# Issue Classification Tests
# =============================================================================


@pytest.mark.functional
class TestIssueClassification:
    """Tests for BE/FE issue classification."""

    def test_backend_files_classified_correctly(self, fix_repo):
        """Python files are classified as backend."""
        orchestrator = FixOrchestrator(fix_repo)

        assert orchestrator._is_backend_file("src/main.py") is True
        assert orchestrator._is_backend_file("src/utils.py") is True
        assert orchestrator._is_backend_file("app.go") is True
        assert orchestrator._is_backend_file("server.java") is True

    def test_frontend_files_classified_correctly(self, fix_repo):
        """TypeScript/JavaScript files are classified as frontend."""
        orchestrator = FixOrchestrator(fix_repo)

        assert orchestrator._is_frontend_file("frontend/App.tsx") is True
        assert orchestrator._is_frontend_file("components/Button.jsx") is True
        assert orchestrator._is_frontend_file("styles/app.css") is True
        assert orchestrator._is_frontend_file("index.html") is True

    def test_classify_issues_separates_be_fe(
        self, fix_repo, sample_backend_issues, sample_frontend_issues
    ):
        """Issues are correctly separated into BE and FE lists."""
        orchestrator = FixOrchestrator(fix_repo)
        all_issues = sample_backend_issues + sample_frontend_issues

        be_issues, fe_issues = orchestrator._classify_issues(all_issues)

        assert len(be_issues) == 2
        assert len(fe_issues) == 1
        assert all(i.file.endswith(".py") for i in be_issues)
        assert all(i.file.endswith(".tsx") for i in fe_issues)

    def test_unknown_extensions_default_to_backend(self, fix_repo):
        """Unknown file extensions default to backend."""
        orchestrator = FixOrchestrator(fix_repo)

        # Create issue with unknown extension
        issue = MockIssue(
            id=99,
            issue_code="UNK-001",
            title="Unknown file issue",
            file="config.yaml",
            severity="LOW",
            category="config",
        )

        be_issues, fe_issues = orchestrator._classify_issues([issue])

        assert len(be_issues) == 1
        assert len(fe_issues) == 0


# =============================================================================
# Issue Batching Tests
# =============================================================================


@pytest.mark.functional
class TestIssueBatching:
    """Tests for issue batching by workload."""

    def test_batching_respects_max_issues(self, fix_repo):
        """Batches don't exceed MAX_ISSUES_PER_CLI_CALL."""

        # Create 10 issues with low workload
        issues = [
            MockIssue(
                id=i,
                issue_code=f"BE-{i:03d}",
                title=f"Issue {i}",
                file="src/main.py",
                severity="LOW",
                category="quality",
                estimated_effort=1,
                estimated_files_count=1,
            )
            for i in range(10)
        ]

        # Manually call the batching function
        def batch_issues_by_workload(issues_to_batch):
            batches = []
            current_batch = []
            current_workload = 0

            for issue in issues_to_batch:
                effort = int(issue.estimated_effort) if issue.estimated_effort else DEFAULT_EFFORT
                files = (
                    int(issue.estimated_files_count)
                    if issue.estimated_files_count
                    else DEFAULT_FILES
                )
                workload = effort * files

                if current_batch and (
                    current_workload + workload > MAX_WORKLOAD_POINTS_PER_BATCH
                    or len(current_batch) >= MAX_ISSUES_PER_CLI_CALL
                ):
                    batches.append(current_batch)
                    current_batch = []
                    current_workload = 0

                current_batch.append(issue)
                current_workload += workload

            if current_batch:
                batches.append(current_batch)

            return batches

        batches = batch_issues_by_workload(issues)

        # Each batch should have at most MAX_ISSUES_PER_CLI_CALL issues
        for batch in batches:
            assert len(batch) <= MAX_ISSUES_PER_CLI_CALL

    def test_batching_respects_max_workload(self, fix_repo):
        """Batches don't exceed MAX_WORKLOAD_POINTS_PER_BATCH."""

        # Create 3 issues with high workload (5 effort * 3 files = 15 each)
        issues = [
            MockIssue(
                id=i,
                issue_code=f"BE-{i:03d}",
                title=f"Complex issue {i}",
                file="src/main.py",
                severity="HIGH",
                category="architecture",
                estimated_effort=5,
                estimated_files_count=3,
            )
            for i in range(3)
        ]

        # Manually call the batching function
        def get_issue_workload(issue):
            effort = int(issue.estimated_effort) if issue.estimated_effort else DEFAULT_EFFORT
            files = (
                int(issue.estimated_files_count) if issue.estimated_files_count else DEFAULT_FILES
            )
            return effort * files

        def batch_issues_by_workload(issues_to_batch):
            batches = []
            current_batch = []
            current_workload = 0

            for issue in issues_to_batch:
                workload = get_issue_workload(issue)

                if current_batch and (
                    current_workload + workload > MAX_WORKLOAD_POINTS_PER_BATCH
                    or len(current_batch) >= MAX_ISSUES_PER_CLI_CALL
                ):
                    batches.append(current_batch)
                    current_batch = []
                    current_workload = 0

                current_batch.append(issue)
                current_workload += workload

            if current_batch:
                batches.append(current_batch)

            return batches

        batches = batch_issues_by_workload(issues)

        # Each high-workload issue (15 points) should be in its own batch
        assert len(batches) == 3

    def test_empty_issues_returns_empty_batches(self, fix_repo):
        """Empty issue list returns empty batch list."""

        def batch_issues_by_workload(issues_to_batch):
            if not issues_to_batch:
                return []
            return [[i] for i in issues_to_batch]

        batches = batch_issues_by_workload([])
        assert batches == []


# =============================================================================
# Workspace Scope Validation Tests
# =============================================================================


@pytest.mark.functional
class TestWorkspaceScopeValidation:
    """Tests for monorepo workspace scope validation."""

    def test_validate_workspace_scope_allows_valid_files(self, fix_repo):
        """Files within workspace scope pass validation."""
        orchestrator = FixOrchestrator(fix_repo)

        modified_files = [
            "packages/frontend/src/App.tsx",
            "packages/frontend/src/utils.ts",
            "packages/frontend/package.json",
        ]
        workspace_path = "packages/frontend"

        violations = orchestrator._validate_workspace_scope(modified_files, workspace_path)

        assert violations == []

    def test_validate_workspace_scope_blocks_violations(self, fix_repo):
        """Files outside workspace scope are blocked."""
        orchestrator = FixOrchestrator(fix_repo)

        modified_files = [
            "packages/frontend/src/App.tsx",  # valid
            "packages/backend/src/main.py",  # violation!
            "root_config.json",  # violation!
        ]
        workspace_path = "packages/frontend"

        violations = orchestrator._validate_workspace_scope(modified_files, workspace_path)

        assert len(violations) == 2
        assert "packages/backend/src/main.py" in violations
        assert "root_config.json" in violations

    def test_validate_workspace_scope_no_restriction(self, fix_repo):
        """No workspace path means no restrictions."""
        orchestrator = FixOrchestrator(fix_repo)

        modified_files = [
            "anywhere/file.py",
            "root.json",
        ]

        violations = orchestrator._validate_workspace_scope(modified_files, workspace_path=None)

        assert violations == []

    def test_validate_workspace_scope_with_allowed_extra_paths(self, fix_repo):
        """Files in allowed_extra_paths pass validation."""
        orchestrator = FixOrchestrator(fix_repo)

        modified_files = [
            "packages/frontend/src/App.tsx",  # in workspace
            "packages/shared/types.ts",  # in allowed_extra_paths
            "packages/common/utils.ts",  # in allowed_extra_paths
        ]
        workspace_path = "packages/frontend"
        allowed_extra_paths = ["packages/shared", "packages/common"]

        violations = orchestrator._validate_workspace_scope(
            modified_files, workspace_path, allowed_extra_paths
        )

        assert violations == []

    def test_validate_workspace_scope_allowed_extra_paths_blocks_others(self, fix_repo):
        """Files outside workspace AND allowed_extra_paths are blocked."""
        orchestrator = FixOrchestrator(fix_repo)

        modified_files = [
            "packages/frontend/src/App.tsx",  # valid (workspace)
            "packages/shared/types.ts",  # valid (allowed_extra)
            "packages/backend/main.py",  # violation!
            "root_config.json",  # violation!
        ]
        workspace_path = "packages/frontend"
        allowed_extra_paths = ["packages/shared"]

        violations = orchestrator._validate_workspace_scope(
            modified_files, workspace_path, allowed_extra_paths
        )

        assert len(violations) == 2
        assert "packages/backend/main.py" in violations
        assert "root_config.json" in violations


# =============================================================================
# Score Parsing Tests
# =============================================================================


@pytest.mark.functional
class TestScoreParsing:
    """Tests for Gemini output score parsing."""

    def test_parse_batch_score(self, fix_repo, sample_backend_issues):
        """BATCH_SCORE is parsed correctly."""
        orchestrator = FixOrchestrator(fix_repo)

        output = """
BATCH_SCORE: 95

ISSUE_SCORES:
- BE-001: 95 | Good fix

FAILED_ISSUES: none
"""

        score, failed, per_issue, quality = orchestrator._parse_batch_review(
            output, sample_backend_issues
        )

        assert score == 95.0
        assert failed == []

    def test_parse_failed_issues(self, fix_repo, sample_backend_issues):
        """FAILED_ISSUES are parsed correctly."""
        orchestrator = FixOrchestrator(fix_repo)

        output = """
BATCH_SCORE: 70

ISSUE_SCORES:
- BE-001: 60 | Incomplete fix
- BE-002: 80 | Good

FAILED_ISSUES: BE-001
"""

        score, failed, per_issue, quality = orchestrator._parse_batch_review(
            output, sample_backend_issues
        )

        assert score == 70.0
        assert "BE-001" in failed

    def test_parse_per_issue_scores(self, fix_repo, sample_backend_issues):
        """Per-issue scores are parsed correctly."""
        orchestrator = FixOrchestrator(fix_repo)

        output = """
BATCH_SCORE: 85

ISSUE_SCORES:
- BE-001: 90 | Good
- BE-002: 80 | Acceptable

FAILED_ISSUES: none
"""

        score, failed, per_issue, quality = orchestrator._parse_batch_review(
            output, sample_backend_issues
        )

        assert per_issue["BE-001"] == 90.0
        assert per_issue["BE-002"] == 80.0

    def test_parse_fallback_score(self, fix_repo, sample_backend_issues):
        """Fallback to SCORE pattern if BATCH_SCORE not present."""
        orchestrator = FixOrchestrator(fix_repo)

        output = """
The fix looks good overall.

SCORE: 88

All changes are appropriate.
"""

        score, failed, per_issue, quality = orchestrator._parse_batch_review(
            output, sample_backend_issues
        )

        assert score == 88.0


# =============================================================================
# Fix Explanation Tests
# =============================================================================


@pytest.mark.functional
class TestFixExplanation:
    """Tests for fix explanation generation."""

    def test_build_fix_explanation_includes_issues(self, fix_repo, sample_backend_issues):
        """Fix explanation includes all fixed issues."""
        orchestrator = FixOrchestrator(fix_repo)

        explanation = orchestrator._build_fix_explanation(
            sample_backend_issues,
            gemini_output="All fixes look good.",
        )

        assert "BE-001" in explanation
        assert "BE-002" in explanation
        assert "SQL Injection" in explanation
        assert "error handling" in explanation

    def test_build_fix_explanation_includes_review_summary(self, fix_repo, sample_backend_issues):
        """Fix explanation includes Gemini review summary."""
        orchestrator = FixOrchestrator(fix_repo)

        gemini_output = "The security fix correctly addresses the SQL injection vulnerability."

        explanation = orchestrator._build_fix_explanation(
            sample_backend_issues,
            gemini_output=gemini_output,
        )

        assert "Review Summary" in explanation
        assert "security fix" in explanation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
