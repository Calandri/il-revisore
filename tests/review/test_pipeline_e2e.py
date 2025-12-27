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
from unittest.mock import patch

import pytest

from turbowrap.review.challenger_loop import ChallengerLoopResult
from turbowrap.review.models.progress import ProgressEvent, ProgressEventType
from turbowrap.review.models.report import ConvergenceStatus, FinalReport, Recommendation, RepoType
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


@pytest.fixture
def mock_challenger_loop_result():
    """Create a mock ChallengerLoopResult."""
    return ChallengerLoopResult(
        final_review=ReviewOutput(
            reviewer="reviewer_be_quality",
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
            ],
            duration_seconds=30.5,
            model_usage=[],
        ),
        iterations=2,
        final_satisfaction=75.0,
        convergence=ConvergenceStatus.THRESHOLD_MET,
        iteration_history=[],
        insights=[],
        challenger_feedbacks=[],
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

        # Mock the challenger loop to avoid actual LLM calls
        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            # Also mock the evaluator
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.repository.type == RepoType.BACKEND

    @pytest.mark.asyncio
    async def test_backend_repo_selects_be_reviewers(self, backend_repo):
        """Backend repo selects backend reviewers only."""
        orchestrator = Orchestrator()

        reviewers_called = []

        async def mock_loop(context, reviewer_name, emit):
            reviewers_called.append(reviewer_name)
            return ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

        with patch.object(
            orchestrator, "_run_challenger_loop_with_progress", side_effect=mock_loop
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request)

                # Should have BE reviewers only
                assert "reviewer_be_architecture" in reviewers_called
                assert "reviewer_be_quality" in reviewers_called
                assert "reviewer_fe_architecture" not in reviewers_called
                assert "reviewer_fe_quality" not in reviewers_called

    @pytest.mark.asyncio
    async def test_backend_repo_full_review_generates_report(
        self, backend_repo, mock_challenger_loop_result
    ):
        """Backend repo full review generates a complete report."""
        orchestrator = Orchestrator()

        with patch.object(
            orchestrator,
            "_run_challenger_loop_with_progress",
            return_value=mock_challenger_loop_result,
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
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

        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(frontend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.repository.type == RepoType.FRONTEND

    @pytest.mark.asyncio
    async def test_frontend_repo_selects_fe_reviewers(self, frontend_repo):
        """Frontend repo selects frontend reviewers only."""
        orchestrator = Orchestrator()

        reviewers_called = []

        async def mock_loop(context, reviewer_name, emit):
            reviewers_called.append(reviewer_name)
            return ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

        with patch.object(
            orchestrator, "_run_challenger_loop_with_progress", side_effect=mock_loop
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(frontend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request)

                # Should have FE reviewers only
                assert "reviewer_fe_architecture" in reviewers_called
                assert "reviewer_fe_quality" in reviewers_called
                assert "reviewer_be_architecture" not in reviewers_called
                assert "reviewer_be_quality" not in reviewers_called


# =============================================================================
# Fullstack Repository Tests
# =============================================================================


@pytest.mark.functional
class TestFullstackRepoReview:
    """Tests for fullstack repository review pipeline."""

    @pytest.mark.asyncio
    async def test_fullstack_runs_all_reviewers(self, fullstack_repo):
        """Fullstack repo runs both BE and FE reviewers."""
        orchestrator = Orchestrator()

        reviewers_called = []

        async def mock_loop(context, reviewer_name, emit):
            reviewers_called.append(reviewer_name)
            return ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

        with patch.object(
            orchestrator, "_run_challenger_loop_with_progress", side_effect=mock_loop
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(fullstack_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=True,  # Include functional
                    ),
                )

                await orchestrator.review(request)

                # Should have all reviewers
                assert "reviewer_be_architecture" in reviewers_called
                assert "reviewer_be_quality" in reviewers_called
                assert "reviewer_fe_architecture" in reviewers_called
                assert "reviewer_fe_quality" in reviewers_called
                assert "analyst_func" in reviewers_called

    @pytest.mark.asyncio
    async def test_fullstack_reviewers_run_in_parallel(self, fullstack_repo):
        """Fullstack reviewers run concurrently, not sequentially."""
        orchestrator = Orchestrator()

        execution_times = {}
        start_time = asyncio.get_event_loop().time()

        async def mock_loop(context, reviewer_name, emit):
            # Record when each reviewer starts
            execution_times[reviewer_name] = asyncio.get_event_loop().time() - start_time
            # Simulate some work
            await asyncio.sleep(0.1)
            return ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

        with patch.object(
            orchestrator, "_run_challenger_loop_with_progress", side_effect=mock_loop
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(fullstack_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request)

                # All reviewers should start nearly simultaneously (within 0.05s)
                times = list(execution_times.values())
                max_start_diff = max(times) - min(times)
                assert max_start_diff < 0.05, f"Reviewers not parallel: {execution_times}"


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

        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request, progress_callback=collect_events)

                # Check event order
                event_types = [e.type for e in events]

                # Must start with REVIEW_STARTED
                assert event_types[0] == ProgressEventType.REVIEW_STARTED

                # Must have REVIEW_COMPLETED (may have log events after)
                assert ProgressEventType.REVIEW_COMPLETED in event_types

                # Must have reviewer events
                assert ProgressEventType.REVIEWER_STARTED in event_types
                assert ProgressEventType.REVIEWER_COMPLETED in event_types

                # REVIEW_COMPLETED should come after all reviewer events
                completed_idx = event_types.index(ProgressEventType.REVIEW_COMPLETED)
                last_reviewer_completed_idx = max(
                    i
                    for i, t in enumerate(event_types)
                    if t == ProgressEventType.REVIEWER_COMPLETED
                )
                assert completed_idx > last_reviewer_completed_idx

    @pytest.mark.asyncio
    async def test_all_reviewers_emit_started_completed(self, backend_repo):
        """Each reviewer emits STARTED and COMPLETED events."""
        orchestrator = Orchestrator()

        events = []

        async def collect_events(event: ProgressEvent):
            events.append(event)

        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request, progress_callback=collect_events)

                # Get reviewer names from events
                started_reviewers = {
                    e.reviewer_name for e in events if e.type == ProgressEventType.REVIEWER_STARTED
                }
                completed_reviewers = {
                    e.reviewer_name
                    for e in events
                    if e.type == ProgressEventType.REVIEWER_COMPLETED
                }

                # Remove evaluator from check (separate logic)
                started_reviewers.discard("evaluator")
                completed_reviewers.discard("evaluator")

                # Every started reviewer should complete
                assert started_reviewers == completed_reviewers


# =============================================================================
# Checkpoint Resume Tests
# =============================================================================


@pytest.mark.functional
class TestCheckpointResume:
    """Tests for checkpoint and resume functionality."""

    @pytest.mark.asyncio
    async def test_checkpoint_callback_called_per_reviewer(self, backend_repo):
        """Checkpoint callback is called after each reviewer completes."""
        orchestrator = Orchestrator()

        checkpoints_saved = []

        async def checkpoint_callback(
            reviewer_name, status, issues, satisfaction, iterations, model_usage, started_at
        ):
            checkpoints_saved.append(
                {
                    "reviewer": reviewer_name,
                    "status": status,
                    "issues_count": len(issues),
                    "satisfaction": satisfaction,
                }
            )

        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer",
                    issues=[
                        Issue(
                            id="TEST-LOW-001",
                            file="test.py",
                            line=1,
                            severity=IssueSeverity.LOW,
                            category=IssueCategory.DOCUMENTATION,
                            title="Test issue",
                            description="Test issue description",
                        )
                    ],
                    duration_seconds=1.0,
                    model_usage=[],
                ),
                iterations=1,
                final_satisfaction=80.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(
                    request,
                    checkpoint_callback=checkpoint_callback,
                )

                # Should have checkpoints for BE reviewers
                assert len(checkpoints_saved) >= 2  # At least arch + quality

                # All should be "completed"
                assert all(c["status"] == "completed" for c in checkpoints_saved)

    @pytest.mark.asyncio
    async def test_resume_skips_completed_reviewers(self, backend_repo):
        """Resuming with checkpoints skips already-completed reviewers."""
        orchestrator = Orchestrator()

        reviewers_called = []

        async def mock_loop(context, reviewer_name, emit):
            reviewers_called.append(reviewer_name)
            return ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

        # Prepare checkpoint for reviewer_be_architecture (already done)
        completed_checkpoints = {
            "reviewer_be_architecture": {
                "issues_data": [
                    {
                        "id": "TEST-LOW-RESTORED",
                        "file": "test.py",
                        "line": 1,
                        "severity": "LOW",
                        "category": "documentation",
                        "title": "Restored issue",
                        "description": "Restored issue description",
                    }
                ],
                "final_satisfaction": 90.0,
                "iterations": 2,
            }
        }

        with patch.object(
            orchestrator, "_run_challenger_loop_with_progress", side_effect=mock_loop
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(
                    request,
                    completed_checkpoints=completed_checkpoints,
                )

                # reviewer_be_architecture should NOT be called (restored from checkpoint)
                assert "reviewer_be_architecture" not in reviewers_called

                # reviewer_be_quality should still run
                assert "reviewer_be_quality" in reviewers_called


# =============================================================================
# Issue Handling Tests
# =============================================================================


@pytest.mark.functional
class TestIssueHandling:
    """Tests for issue deduplication and aggregation."""

    @pytest.mark.asyncio
    async def test_issues_from_multiple_reviewers_merged(self, backend_repo):
        """Issues from multiple reviewers are merged in final report."""
        orchestrator = Orchestrator()

        call_count = [0]

        async def mock_loop(context, reviewer_name, emit):
            call_count[0] += 1
            # Each reviewer returns different issues
            issue = Issue(
                id=f"TEST-MED-{call_count[0]:03d}",
                file=f"file_{reviewer_name}.py",
                line=call_count[0] * 10,
                severity=IssueSeverity.MEDIUM,
                category=IssueCategory.DOCUMENTATION,
                title=f"Issue from {reviewer_name}",
                description=f"Issue description from {reviewer_name}",
                flagged_by=[reviewer_name],
            )
            return ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer=reviewer_name,
                    issues=[issue],
                    duration_seconds=1.0,
                    model_usage=[],
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

        with patch.object(
            orchestrator, "_run_challenger_loop_with_progress", side_effect=mock_loop
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                # Should have issues from both BE reviewers
                assert report.summary.total_issues == 2

    @pytest.mark.asyncio
    async def test_duplicate_issues_deduplicated(self, backend_repo):
        """Duplicate issues from different reviewers are deduplicated."""
        orchestrator = Orchestrator()

        # Both reviewers return the same issue (same file/line/category)
        duplicate_issue = Issue(
            id="TEST-HIGH-DUP",
            file="src/main.py",
            line=10,
            severity=IssueSeverity.HIGH,
            category=IssueCategory.SECURITY,
            title="SQL injection vulnerability",
            description="SQL injection vulnerability detected",
        )

        async def mock_loop(context, reviewer_name, emit):
            issue_copy = duplicate_issue.model_copy()
            issue_copy.flagged_by = [reviewer_name]
            return ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer=reviewer_name,
                    issues=[issue_copy],
                    duration_seconds=1.0,
                    model_usage=[],
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

        with patch.object(
            orchestrator, "_run_challenger_loop_with_progress", side_effect=mock_loop
        ):
            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                # Should be deduplicated to 1 issue
                assert report.summary.total_issues == 1

                # The merged issue should have both reviewers in flagged_by
                assert len(report.issues[0].flagged_by) == 2


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

        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
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

        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer",
                    issues=[critical_issue],
                    duration_seconds=1.0,
                    model_usage=[],
                ),
                iterations=1,
                final_satisfaction=50.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                report = await orchestrator.review(request)

                assert report.summary.recommendation == Recommendation.REQUEST_CHANGES


# =============================================================================
# Report Saving Tests
# =============================================================================


@pytest.mark.functional
class TestReportSaving:
    """Tests for report file saving."""

    @pytest.mark.asyncio
    async def test_report_saved_to_reviews_directory(self, backend_repo):
        """Report is saved to .reviews directory."""
        orchestrator = Orchestrator()

        with patch.object(orchestrator, "_run_challenger_loop_with_progress") as mock_loop:
            mock_loop.return_value = ChallengerLoopResult(
                final_review=ReviewOutput(
                    reviewer="test_reviewer", issues=[], duration_seconds=1.0, model_usage=[]
                ),
                iterations=1,
                final_satisfaction=100.0,
                convergence=ConvergenceStatus.THRESHOLD_MET,
            )

            with patch.object(orchestrator, "_run_evaluator", return_value=None):
                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=str(backend_repo)),
                    options=ReviewOptions(
                        mode=ReviewMode.DIFF,
                        challenger_enabled=True,
                        include_functional=False,
                    ),
                )

                await orchestrator.review(request)

                # Check that .reviews directory was created
                reviews_dir = backend_repo / ".reviews"
                assert reviews_dir.exists()

                # Check for latest.json
                assert (reviews_dir / "latest.json").exists()

                # Check for latest.md
                assert (reviews_dir / "latest.md").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
