"""
Challenger loop implementation for the dual-reviewer system.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from turbowrap.config import get_settings
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.models.challenger import ChallengerFeedback, ChallengerStatus
from turbowrap.review.models.report import ConvergenceStatus, IterationHistory, ChallengerInsight
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.reviewers.claude_reviewer import ClaudeReviewer
from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger


logger = logging.getLogger(__name__)


@dataclass
class ChallengerLoopResult:
    """Result of the challenger loop."""

    final_review: ReviewOutput
    iterations: int
    final_satisfaction: float
    convergence: ConvergenceStatus
    iteration_history: list[IterationHistory] = field(default_factory=list)
    insights: list[ChallengerInsight] = field(default_factory=list)
    challenger_feedbacks: list[ChallengerFeedback] = field(default_factory=list)


class ChallengerLoop:
    """
    Implements the challenger loop pattern.

    The loop continues until:
    1. Satisfaction threshold is met
    2. Max iterations reached
    3. Stagnation detected (no improvement)
    """

    def __init__(
        self,
        reviewer: Optional[ClaudeReviewer] = None,
        challenger: Optional[GeminiChallenger] = None,
        satisfaction_threshold: Optional[float] = None,
        max_iterations: Optional[int] = None,
        min_improvement_threshold: Optional[float] = None,
        stagnation_window: Optional[int] = None,
        forced_acceptance_threshold: Optional[float] = None,
    ):
        """
        Initialize the challenger loop.

        Args:
            reviewer: Claude reviewer instance
            challenger: Gemini challenger instance
            satisfaction_threshold: Required satisfaction score (0-100)
            max_iterations: Maximum number of iterations
            min_improvement_threshold: Minimum improvement per iteration
            stagnation_window: Number of iterations to detect stagnation
            forced_acceptance_threshold: Accept if above this after max iterations
        """
        self.reviewer = reviewer
        self.challenger = challenger

        # Default values
        self.satisfaction_threshold = satisfaction_threshold or 99.0
        self.max_iterations = max_iterations or 5
        self.min_improvement_threshold = min_improvement_threshold or 2.0
        self.stagnation_window = stagnation_window or 3
        self.forced_acceptance_threshold = forced_acceptance_threshold or 85.0

    async def run(
        self,
        context: ReviewContext,
        reviewer_name: str = "reviewer_be",
    ) -> ChallengerLoopResult:
        """
        Run the challenger loop.

        Args:
            context: Review context with files to review
            reviewer_name: Name of the reviewer agent

        Returns:
            ChallengerLoopResult with final review and metadata
        """
        settings = get_settings()

        # Initialize reviewer and challenger if not provided
        if self.reviewer is None:
            self.reviewer = ClaudeReviewer(name=reviewer_name)

        if self.challenger is None:
            self.challenger = GeminiChallenger()

        # Load agent prompt if available
        try:
            context.agent_prompt = self.reviewer.load_agent_prompt(
                settings.agents_dir
            )
        except FileNotFoundError:
            logger.warning(f"Agent file not found for {reviewer_name}")

        iteration = 0
        current_review: Optional[ReviewOutput] = None
        challenger_feedback: Optional[ChallengerFeedback] = None
        satisfaction_score = 0.0

        iteration_history: list[IterationHistory] = []
        challenger_feedbacks: list[ChallengerFeedback] = []
        insights: list[ChallengerInsight] = []

        logger.info(
            f"Starting challenger loop with threshold={self.satisfaction_threshold}%, "
            f"max_iterations={self.max_iterations}"
        )

        while iteration < self.max_iterations:
            iteration += 1
            logger.info(f"=== Challenger Loop Iteration {iteration} ===")

            # Step 1: Reviewer performs/refines review
            if current_review is None:
                logger.info("Performing initial review...")
                current_review = await self.reviewer.review(context)
            else:
                logger.info("Refining review based on challenger feedback...")
                current_review = await self.reviewer.refine(
                    context,
                    current_review,
                    challenger_feedback,
                )

            # Step 2: Challenger evaluates
            logger.info("Challenger evaluating review...")
            challenger_feedback = await self.challenger.challenge(
                context,
                current_review,
                iteration,
            )
            challenger_feedbacks.append(challenger_feedback)

            satisfaction_score = challenger_feedback.satisfaction_score
            logger.info(
                f"Iteration {iteration}: satisfaction={satisfaction_score:.1f}% "
                f"(threshold={self.satisfaction_threshold}%)"
            )

            # Record iteration history
            issues_added = len(challenger_feedback.missed_issues)
            challenges_resolved = (
                len(current_review.refinement_notes[-1].get("addressed_challenges", 0))
                if current_review.refinement_notes
                else 0
            )

            iteration_history.append(IterationHistory(
                iteration=iteration,
                satisfaction_score=satisfaction_score,
                issues_added=issues_added,
                challenges_resolved=challenges_resolved,
            ))

            # Extract insights from significant issues found
            for missed in challenger_feedback.missed_issues:
                if missed.suggested_severity in ["CRITICAL", "HIGH"]:
                    insights.append(ChallengerInsight(
                        iteration=iteration,
                        description=f"{missed.type}: {missed.description}",
                        impact="high" if missed.suggested_severity == "CRITICAL" else "medium",
                    ))

            # Check convergence
            convergence = self._check_convergence(
                satisfaction_score,
                iteration_history,
            )

            if convergence != ConvergenceStatus.THRESHOLD_MET:
                if convergence == ConvergenceStatus.STAGNATED:
                    logger.warning("Stagnation detected, stopping loop")
                    break
            else:
                logger.info(f"Threshold met at iteration {iteration}!")
                break

        # Determine final convergence status
        final_convergence = self._determine_final_convergence(
            satisfaction_score,
            iteration,
            iteration_history,
        )

        logger.info(
            f"Challenger loop completed: iterations={iteration}, "
            f"satisfaction={satisfaction_score:.1f}%, "
            f"convergence={final_convergence.value}"
        )

        return ChallengerLoopResult(
            final_review=current_review,
            iterations=iteration,
            final_satisfaction=satisfaction_score,
            convergence=final_convergence,
            iteration_history=iteration_history,
            insights=insights,
            challenger_feedbacks=challenger_feedbacks,
        )

    def _check_convergence(
        self,
        current_score: float,
        history: list[IterationHistory],
    ) -> ConvergenceStatus:
        """Check if the loop should terminate."""
        # Check if threshold met
        if current_score >= self.satisfaction_threshold:
            return ConvergenceStatus.THRESHOLD_MET

        # Check for stagnation
        if len(history) >= self.stagnation_window:
            recent = history[-self.stagnation_window:]
            improvements = [
                recent[i + 1].satisfaction_score - recent[i].satisfaction_score
                for i in range(len(recent) - 1)
            ]

            if all(imp < self.min_improvement_threshold for imp in improvements):
                return ConvergenceStatus.STAGNATED

        return ConvergenceStatus.THRESHOLD_MET  # Continue

    def _determine_final_convergence(
        self,
        final_score: float,
        iterations: int,
        history: list[IterationHistory],
    ) -> ConvergenceStatus:
        """Determine the final convergence status."""
        if final_score >= self.satisfaction_threshold:
            return ConvergenceStatus.THRESHOLD_MET

        if iterations >= self.max_iterations:
            if final_score >= self.forced_acceptance_threshold:
                return ConvergenceStatus.FORCED_ACCEPTANCE
            return ConvergenceStatus.MAX_ITERATIONS_REACHED

        # Check stagnation
        if len(history) >= self.stagnation_window:
            recent = history[-self.stagnation_window:]
            improvements = [
                recent[i + 1].satisfaction_score - recent[i].satisfaction_score
                for i in range(len(recent) - 1)
            ]
            if all(imp < self.min_improvement_threshold for imp in improvements):
                return ConvergenceStatus.STAGNATED

        return ConvergenceStatus.THRESHOLD_MET


async def run_challenger_loop(
    context: ReviewContext,
    reviewer_name: str = "reviewer_be",
    satisfaction_threshold: Optional[float] = None,
    max_iterations: Optional[int] = None,
) -> ChallengerLoopResult:
    """
    Convenience function to run the challenger loop.

    Args:
        context: Review context
        reviewer_name: Reviewer agent name
        satisfaction_threshold: Override default threshold
        max_iterations: Override default max iterations

    Returns:
        ChallengerLoopResult
    """
    loop = ChallengerLoop(
        satisfaction_threshold=satisfaction_threshold,
        max_iterations=max_iterations,
    )
    return await loop.run(context, reviewer_name)
