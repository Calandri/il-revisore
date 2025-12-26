"""
Functional tests for ChallengerLoop convergence conditions.

Run with: uv run pytest tests/review/test_challenger_convergence.py -v

These tests verify the challenger loop termination logic:
1. Convergence by satisfaction threshold
2. Convergence by stagnation detection
3. Forced acceptance after max iterations
4. Hard safety limit enforcement
5. Iteration history tracking
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from turbowrap.review.challenger_loop import ChallengerLoop
from turbowrap.review.models.challenger import ChallengerFeedback, MissedIssue
from turbowrap.review.models.report import ConvergenceStatus
from turbowrap.review.models.review import Issue, ReviewOutput
from turbowrap.review.reviewers.base import ReviewContext

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_review_context(tmp_path):
    """Create a mock review context."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    (repo_path / "main.py").write_text("def hello(): pass")

    return ReviewContext(
        repo_path=str(repo_path),
        files=["main.py"],
        mode="initial",
        diff_content=None,
        workspace_path=None,
        agent_prompt=None,
    )


@pytest.fixture
def mock_review_output():
    """Create a mock review output."""
    return ReviewOutput(
        issues=[
            Issue(
                file="main.py",
                line=1,
                severity="medium",
                category="quality",
                message="Missing docstring",
                suggestion="Add docstring",
            )
        ],
        refinement_notes=[],
        model_usage=None,
    )


def create_challenger_feedback(satisfaction: float, missed_count: int = 0) -> ChallengerFeedback:
    """Helper to create challenger feedback with given satisfaction."""
    missed_issues = [
        MissedIssue(
            type="security",
            description=f"Missed issue {i}",
            suggested_severity="MEDIUM",
            file_hint="main.py",
        )
        for i in range(missed_count)
    ]

    return ChallengerFeedback(
        satisfaction_score=satisfaction,
        missed_issues=missed_issues,
        challenges=[],
        general_feedback=f"Score: {satisfaction}%",
        model_usage=None,
    )


# =============================================================================
# Convergence by Satisfaction Threshold
# =============================================================================


@pytest.mark.functional
class TestConvergenceBySatisfactionThreshold:
    """Tests for convergence when satisfaction threshold is met."""

    @pytest.mark.asyncio
    async def test_immediate_convergence(self, mock_review_context, mock_review_output):
        """Loop terminates immediately when first iteration meets threshold."""
        # Mock reviewer to return review
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)

        # Mock challenger to return high satisfaction immediately
        mock_challenger = MagicMock()
        mock_challenger.challenge = AsyncMock(
            return_value=create_challenger_feedback(satisfaction=60.0)
        )

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=50.0,
            max_iterations=5,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert result.convergence == ConvergenceStatus.THRESHOLD_MET
        assert result.iterations == 1
        assert result.final_satisfaction == 60.0

    @pytest.mark.asyncio
    async def test_convergence_after_multiple_iterations(
        self, mock_review_context, mock_review_output
    ):
        """Loop converges after satisfaction gradually increases."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        # Satisfaction increases each iteration
        satisfaction_scores = [30.0, 40.0, 55.0]
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            score = satisfaction_scores[min(call_count, len(satisfaction_scores) - 1)]
            call_count += 1
            return create_challenger_feedback(satisfaction=score)

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=50.0,
            max_iterations=10,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert result.convergence == ConvergenceStatus.THRESHOLD_MET
        assert result.iterations == 3
        assert result.final_satisfaction == 55.0

    @pytest.mark.asyncio
    async def test_iteration_history_recorded(self, mock_review_context, mock_review_output):
        """Iteration history is recorded correctly."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        scores = [20.0, 35.0, 60.0]
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            score = scores[min(call_count, len(scores) - 1)]
            call_count += 1
            return create_challenger_feedback(satisfaction=score, missed_count=1)

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=50.0,
            max_iterations=10,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert len(result.iteration_history) == 3
        assert result.iteration_history[0].iteration == 1
        assert result.iteration_history[0].satisfaction_score == 20.0
        assert result.iteration_history[1].satisfaction_score == 35.0
        assert result.iteration_history[2].satisfaction_score == 60.0


# =============================================================================
# Convergence by Stagnation
# =============================================================================


@pytest.mark.functional
class TestConvergenceByStagnation:
    """Tests for convergence when stagnation is detected."""

    @pytest.mark.asyncio
    async def test_stagnation_detection(self, mock_review_context, mock_review_output):
        """Loop terminates when no improvement for stagnation_window iterations."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        # Satisfaction stays flat - no improvement
        scores = [40.0, 40.5, 40.5, 40.5]  # Less than min_improvement_threshold
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            score = scores[min(call_count, len(scores) - 1)]
            call_count += 1
            return create_challenger_feedback(satisfaction=score)

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=80.0,  # High threshold, won't be met
            max_iterations=10,
            min_improvement_threshold=2.0,  # Require at least 2% improvement
            stagnation_window=3,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert result.convergence == ConvergenceStatus.STAGNATED
        assert result.iterations <= 5  # Should stop before max

    @pytest.mark.asyncio
    async def test_no_stagnation_with_improvement(self, mock_review_context, mock_review_output):
        """Loop continues when there is improvement."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        # Continuous improvement until threshold
        scores = [20.0, 30.0, 40.0, 55.0]
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            score = scores[min(call_count, len(scores) - 1)]
            call_count += 1
            return create_challenger_feedback(satisfaction=score)

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=50.0,
            max_iterations=10,
            min_improvement_threshold=2.0,
            stagnation_window=3,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert result.convergence == ConvergenceStatus.THRESHOLD_MET
        assert result.iterations == 4


# =============================================================================
# Max Iterations and Forced Acceptance
# =============================================================================


@pytest.mark.functional
class TestMaxIterationsAndForcedAcceptance:
    """Tests for max iterations and forced acceptance behavior."""

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, mock_review_context, mock_review_output):
        """Loop stops at max iterations with low score."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        # Score increases but never meets threshold
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Increase by 5% each iteration, starting at 10%
            return create_challenger_feedback(satisfaction=10.0 + (call_count * 5))

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=80.0,  # Very high threshold
            max_iterations=3,
            forced_acceptance_threshold=40.0,  # Below our scores
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert result.iterations == 3
        # Final score would be 25% (10 + 3*5 = 25), below forced acceptance
        assert result.convergence == ConvergenceStatus.MAX_ITERATIONS_REACHED

    @pytest.mark.asyncio
    async def test_forced_acceptance_after_max_iterations(
        self, mock_review_context, mock_review_output
    ):
        """Loop accepts if score > forced_acceptance_threshold after max iterations."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        # Score reaches 45% at max iterations
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return create_challenger_feedback(satisfaction=35.0 + (call_count * 5))

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=80.0,  # Very high, won't be met
            max_iterations=2,
            forced_acceptance_threshold=40.0,  # 45% > 40%, should force accept
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert result.iterations == 2
        assert result.final_satisfaction == 45.0  # 35 + 2*5
        assert result.convergence == ConvergenceStatus.FORCED_ACCEPTANCE


# =============================================================================
# Hard Safety Limit
# =============================================================================


@pytest.mark.functional
class TestHardSafetyLimit:
    """Tests for the hard safety limit of 10 iterations."""

    def test_hard_limit_caps_max_iterations(self):
        """max_iterations is capped at ABSOLUTE_MAX_ITERATIONS."""
        loop = ChallengerLoop(
            satisfaction_threshold=50.0,
            max_iterations=100,  # Way above limit
        )

        assert loop.max_iterations == ChallengerLoop.ABSOLUTE_MAX_ITERATIONS
        assert loop.max_iterations == 10

    def test_hard_limit_constant(self):
        """ABSOLUTE_MAX_ITERATIONS is set to 10."""
        assert ChallengerLoop.ABSOLUTE_MAX_ITERATIONS == 10

    @pytest.mark.asyncio
    async def test_never_exceeds_absolute_max(self, mock_review_context, mock_review_output):
        """Loop never exceeds absolute max iterations even with very high config."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        # Always return low satisfaction to force max iterations
        mock_challenger = MagicMock()
        mock_challenger.challenge = AsyncMock(
            return_value=create_challenger_feedback(satisfaction=10.0)
        )

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=90.0,
            max_iterations=50,  # Requested 50, but capped at 10
            min_improvement_threshold=0.0,  # Disable stagnation
            stagnation_window=100,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert result.iterations == 10  # Capped at hard limit
        assert result.iterations <= ChallengerLoop.ABSOLUTE_MAX_ITERATIONS


# =============================================================================
# Callback Behavior
# =============================================================================


@pytest.mark.functional
class TestCallbackBehavior:
    """Tests for iteration and content callbacks."""

    @pytest.mark.asyncio
    async def test_iteration_callback_called(self, mock_review_context, mock_review_output):
        """Iteration callback is called after each iteration."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        scores = [30.0, 60.0]
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            score = scores[min(call_count, len(scores) - 1)]
            call_count += 1
            return create_challenger_feedback(satisfaction=score)

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        callback_calls = []

        async def on_iteration(iteration, satisfaction, issues_count):
            callback_calls.append((iteration, satisfaction, issues_count))

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=50.0,
            max_iterations=5,
        )

        await loop.run(mock_review_context, "test_reviewer", on_iteration_callback=on_iteration)

        assert len(callback_calls) == 2
        assert callback_calls[0][0] == 1  # First iteration
        assert callback_calls[0][1] == 30.0  # First satisfaction
        assert callback_calls[1][0] == 2  # Second iteration
        assert callback_calls[1][1] == 60.0  # Second satisfaction


# =============================================================================
# Insights Collection
# =============================================================================


@pytest.mark.functional
class TestInsightsCollection:
    """Tests for challenger insights collection."""

    @pytest.mark.asyncio
    async def test_high_severity_issues_become_insights(
        self, mock_review_context, mock_review_output
    ):
        """High severity missed issues are recorded as insights."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)

        # Create feedback with CRITICAL missed issue
        feedback = ChallengerFeedback(
            satisfaction_score=60.0,
            missed_issues=[
                MissedIssue(
                    type="security",
                    description="SQL Injection vulnerability",
                    suggested_severity="CRITICAL",
                    file_hint="main.py",
                ),
                MissedIssue(
                    type="quality",
                    description="Missing docstring",
                    suggested_severity="LOW",  # Not high, shouldn't be insight
                    file_hint="main.py",
                ),
            ],
            challenges=[],
            general_feedback="Review needed",
            model_usage=None,
        )

        mock_challenger = MagicMock()
        mock_challenger.challenge = AsyncMock(return_value=feedback)

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=50.0,
            max_iterations=1,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        # Only CRITICAL/HIGH issues become insights
        assert len(result.insights) == 1
        assert "SQL Injection" in result.insights[0].description
        assert result.insights[0].impact == "high"


# =============================================================================
# Challenger Feedbacks Collection
# =============================================================================


@pytest.mark.functional
class TestChallengerFeedbacksCollection:
    """Tests for challenger feedbacks collection."""

    @pytest.mark.asyncio
    async def test_all_feedbacks_collected(self, mock_review_context, mock_review_output):
        """All challenger feedbacks are collected across iterations."""
        mock_reviewer = MagicMock()
        mock_reviewer.name = "test_reviewer"
        mock_reviewer.review = AsyncMock(return_value=mock_review_output)
        mock_reviewer.refine = AsyncMock(return_value=mock_review_output)

        scores = [20.0, 40.0, 60.0]
        call_count = 0

        async def mock_challenge(*args, **kwargs):
            nonlocal call_count
            score = scores[min(call_count, len(scores) - 1)]
            call_count += 1
            return create_challenger_feedback(satisfaction=score)

        mock_challenger = MagicMock()
        mock_challenger.challenge = mock_challenge

        loop = ChallengerLoop(
            reviewer=mock_reviewer,
            challenger=mock_challenger,
            satisfaction_threshold=50.0,
            max_iterations=10,
        )

        result = await loop.run(mock_review_context, "test_reviewer")

        assert len(result.challenger_feedbacks) == 3
        assert result.challenger_feedbacks[0].satisfaction_score == 20.0
        assert result.challenger_feedbacks[1].satisfaction_score == 40.0
        assert result.challenger_feedbacks[2].satisfaction_score == 60.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
