"""
End-to-end tests for the review pipeline.

Run with: uv run pytest tests/review/test_pipeline_e2e.py -v

These tests verify the complete review pipeline from repository
detection through to final report generation, including:
1. Backend-only repository review
2. Frontend-only repository review
3. Fullstack repository with parallel reviewers
4. Progress callback handling
5. Checkpoint resume functionality
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from turbowrap.review.models.progress import ProgressEvent, ProgressEventType
from turbowrap.review.models.report import FinalReport, Recommendation, RepoType
from turbowrap.review.models.review import (
    Issue,
    IssueCategory,
    IssueSeverity,
    ReviewMode,
    ReviewOptions,
    ReviewOutput,
    ReviewRequest,
    ReviewRequestSource,
)
from turbowrap.review.orchestrator import Orchestrator
from turbowrap.review.parallel_triple_llm_runner import ParallelTripleLLMResult

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def backend_repo(tmp_path):
    """Create a temporary backend repository."""
    repo = tmp_path / "backend_repo"
    repo.mkdir()

    # Create Python files
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text(
        '''
"""Main application entry point."""
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}
'''
    )
    (repo / "src" / "models.py").write_text(
        '''
"""Database models."""
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True)
'''
    )
    (repo / "requirements.txt").write_text("fastapi\nsqlalchemy\n")

    # Create structure.xml
    llms_dir = repo / ".llms"
    llms_dir.mkdir()
    (llms_dir / "structure.xml").write_text(
        """<?xml version="1.0"?>
<repository type="BACKEND" name="backend_repo">
  <metadata>
    <languages>Python</languages>
    <framework>FastAPI</framework>
  </metadata>
  <structure>
    <folder name="src">
      <file name="main.py" purpose="FastAPI application entry point"/>
      <file name="models.py" purpose="SQLAlchemy database models"/>
    </folder>
  </structure>
</repository>
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
def frontend_repo(tmp_path):
    """Create a temporary frontend repository."""
    repo = tmp_path / "frontend_repo"
    repo.mkdir()

    # Create TypeScript/React files
    (repo / "src").mkdir()
    (repo / "src" / "App.tsx").write_text(
        """
import React from "react";

export const App: React.FC = () => {
  return <div>Hello World</div>;
};
"""
    )
    (repo / "src" / "index.tsx").write_text(
        """
import React from "react";
import ReactDOM from "react-dom";
import { App } from "./App";

ReactDOM.render(<App />, document.getElementById("root"));
"""
    )
    (repo / "package.json").write_text('{"name": "frontend", "dependencies": {"react": "^18.0.0"}}')

    # Create structure.xml
    llms_dir = repo / ".llms"
    llms_dir.mkdir()
    (llms_dir / "structure.xml").write_text(
        """<?xml version="1.0"?>
<repository type="FRONTEND" name="frontend_repo">
  <metadata>
    <languages>TypeScript</languages>
    <framework>React</framework>
  </metadata>
  <structure>
    <folder name="src">
      <file name="App.tsx" purpose="Main React application component"/>
      <file name="index.tsx" purpose="Application entry point"/>
    </folder>
  </structure>
</repository>
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
def fullstack_repo(tmp_path):
    """Create a temporary fullstack repository."""
    repo = tmp_path / "fullstack_repo"
    repo.mkdir()

    # Backend files
    (repo / "backend").mkdir()
    (repo / "backend" / "app.py").write_text(
        """
from flask import Flask
app = Flask(__name__)
"""
    )

    # Frontend files
    (repo / "frontend").mkdir()
    (repo / "frontend" / "App.tsx").write_text(
        """
import React from "react";
export const App = () => <div>App</div>;
"""
    )

    # Create structure.xml
    llms_dir = repo / ".llms"
    llms_dir.mkdir()
    (llms_dir / "structure.xml").write_text(
        """<?xml version="1.0"?>
<repository type="FULLSTACK" name="fullstack_repo">
  <metadata>
    <languages>Python, TypeScript</languages>
    <frameworks>Flask, React</frameworks>
  </metadata>
</repository>
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


def create_mock_parallel_result(issues: list[Issue] | None = None) -> ParallelTripleLLMResult:
    """Create a mock ParallelTripleLLMResult."""
    if issues is None:
        issues = []
    return ParallelTripleLLMResult(
        final_review=ReviewOutput(
            reviewer="parallel_merged",
            issues=issues,
            duration_seconds=30.5,
            model_usage=[],
        ),
        claude_issues_count=len(issues),
        gemini_issues_count=len(issues) // 2,
        grok_issues_count=len(issues) // 2,
        merged_issues_count=len(issues),
        overlap_count=0,
    )


@pytest.fixture
def mock_parallel_result():
    """Create a mock ParallelTripleLLMResult with sample issues."""
    return create_mock_parallel_result(
        issues=[
            Issue(
                id="TEST-HIGH-001",
                file="src/main.py",
                line=10,
                severity=IssueSeverity.HIGH,
                category=IssueCategory.SECURITY,
                title="Potential SQL injection",
                description="SQL injection vulnerability detected in query construction",
                suggested_fix="Use parameterized queries",
                flagged_by=["reviewer_be_quality"],
            ),
            Issue(
                id="TEST-MED-001",
                file="src/main.py",
                line=25,
                severity=IssueSeverity.MEDIUM,
                category=IssueCategory.ARCHITECTURE,
                title="Missing error handling",
                description="Function lacks proper error handling for edge cases",
                suggested_fix="Add try-except block",
                flagged_by=["reviewer_be_quality"],
            ),
        ]
    )


# =============================================================================
# Backend Repository Tests
# =============================================================================


@pytest.mark.functional
class TestBackendRepoReview:
    """Tests for backend repository review pipeline."""

    @pytest.mark.asyncio
    async def test_backend_repo_detects_correct_type(self, backend_repo):
        """Backend repo is correctly detected as BACKEND type."""
        orchestrator = Orchestrator()

        # Mock ParallelTripleLLMRunner to avoid actual LLM calls
        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=create_mock_parallel_result())

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.repository.type == RepoType.BACKEND

    @pytest.mark.asyncio
    async def test_backend_repo_full_review_generates_report(self, backend_repo, mock_parallel_result):
        """Backend repo full review generates a complete report."""
        orchestrator = Orchestrator()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=mock_parallel_result)

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                # Verify report structure
                assert isinstance(report, FinalReport)
                assert report.id.startswith("rev_")
                assert report.repository.type == RepoType.BACKEND
                assert report.summary is not None


# =============================================================================
# Frontend Repository Tests
# =============================================================================


@pytest.mark.functional
class TestFrontendRepoReview:
    """Tests for frontend repository review pipeline."""

    @pytest.mark.asyncio
    async def test_frontend_repo_detects_correct_type(self, frontend_repo):
        """Frontend repo is correctly detected as FRONTEND type."""
        orchestrator = Orchestrator()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=create_mock_parallel_result())

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(frontend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.repository.type == RepoType.FRONTEND


# =============================================================================
# Fullstack Repository Tests
# =============================================================================


@pytest.mark.functional
class TestFullstackRepoReview:
    """Tests for fullstack repository review pipeline."""

    @pytest.mark.asyncio
    async def test_fullstack_detects_correct_type(self, fullstack_repo):
        """Fullstack repo is correctly detected as FULLSTACK type."""
        orchestrator = Orchestrator()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=create_mock_parallel_result())

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(fullstack_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=True,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.repository.type == RepoType.FULLSTACK


# =============================================================================
# Progress Callback Tests
# =============================================================================


@pytest.mark.functional
class TestProgressCallbacks:
    """Tests for progress callback handling."""

    @pytest.mark.asyncio
    async def test_progress_events_emitted_in_order(self, backend_repo):
        """Progress events are emitted in correct order."""
        orchestrator = Orchestrator()

        events = []

        async def collect_events(event: ProgressEvent):
            events.append(event)

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=create_mock_parallel_result())

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request, progress_callback=collect_events)

                # Check event order
                event_types = [e.type for e in events]

                # Must start with REVIEW_STARTED
                assert event_types[0] == ProgressEventType.REVIEW_STARTED

                # Must have REVIEW_COMPLETED
                assert ProgressEventType.REVIEW_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_reviewer_events_emitted(self, backend_repo):
        """Reviewer started/completed events are emitted."""
        orchestrator = Orchestrator()

        events = []

        async def collect_events(event: ProgressEvent):
            events.append(event)

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=create_mock_parallel_result())

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request, progress_callback=collect_events)

                event_types = [e.type for e in events]

                # Must have reviewer events for parallel LLMs
                assert ProgressEventType.REVIEWER_STARTED in event_types
                assert ProgressEventType.REVIEWER_COMPLETED in event_types


# =============================================================================
# Score and Recommendation Tests
# =============================================================================


@pytest.mark.functional
class TestScoreAndRecommendation:
    """Tests for score calculation and recommendation logic."""

    @pytest.mark.asyncio
    async def test_no_issues_gives_perfect_score(self, backend_repo):
        """No issues results in perfect score and APPROVE recommendation."""
        orchestrator = Orchestrator()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=create_mock_parallel_result(issues=[]))

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.summary.overall_score == 10.0
                assert report.summary.recommendation == Recommendation.APPROVE

    @pytest.mark.asyncio
    async def test_critical_issue_triggers_request_changes(self, backend_repo):
        """Critical issue results in REQUEST_CHANGES recommendation."""
        orchestrator = Orchestrator()

        critical_issue = Issue(
            id="TEST-CRIT-001",
            file="src/main.py",
            line=10,
            severity=IssueSeverity.CRITICAL,
            category=IssueCategory.SECURITY,
            title="Critical vulnerability",
            description="Critical security vulnerability detected",
        )

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(
            return_value=create_mock_parallel_result(issues=[critical_issue])
        )

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.summary.recommendation == Recommendation.REQUEST_CHANGES


# =============================================================================
# Report Structure Tests
# =============================================================================


@pytest.mark.functional
class TestReportStructure:
    """Tests for report structure and contents."""

    @pytest.mark.asyncio
    async def test_report_contains_issues(self, backend_repo, mock_parallel_result):
        """Report contains issues from the review."""
        orchestrator = Orchestrator()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=mock_parallel_result)

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                # Should have the issues from mock
                assert len(report.issues) == 2
                assert report.summary.total_issues == 2

    @pytest.mark.asyncio
    async def test_report_has_valid_id(self, backend_repo):
        """Report has a valid ID format."""
        orchestrator = Orchestrator()

        mock_runner_instance = MagicMock()
        mock_runner_instance.run = AsyncMock(return_value=create_mock_parallel_result())

        with patch(
            "turbowrap.review.orchestrator.ParallelTripleLLMRunner",
            return_value=mock_runner_instance,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=(None, None)):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.id.startswith("rev_")
                assert len(report.id) > 10  # Has a timestamp/uuid suffix


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
