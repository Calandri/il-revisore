"""
Challenger loop implementation for the dual-reviewer system.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.report import ChallengerInsight, ConvergenceStatus, IterationHistory
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.reviewers.claude_cli_reviewer import ClaudeCLIReviewer
from turbowrap.review.reviewers.gemini_cli_challenger import GeminiCLIChallenger

logger = logging.getLogger(__name__)

# Callback types
IterationCallback = Callable[
    [int, float, int], Awaitable[None]
]  # iteration, satisfaction, issues_count
ContentCallback = Callable[[str], Awaitable[None]]  # streaming content


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

    # Hard safety limit - prevents infinite loops regardless of config
    ABSOLUTE_MAX_ITERATIONS = 10

    def __init__(
        self,
        reviewer: ClaudeCLIReviewer | None = None,
        challenger: GeminiCLIChallenger | None = None,
        satisfaction_threshold: float | None = None,
        max_iterations: int | None = None,
        min_improvement_threshold: float | None = None,
        stagnation_window: int | None = None,
        forced_acceptance_threshold: float | None = None,
    ):
        """
        Initialize the challenger loop.

        Args:
            reviewer: Claude CLI reviewer instance
            challenger: Gemini CLI challenger instance
            satisfaction_threshold: Required satisfaction score (0-100)
            max_iterations: Maximum number of iterations (capped at 10)
            min_improvement_threshold: Minimum improvement per iteration
            stagnation_window: Number of iterations to detect stagnation
            forced_acceptance_threshold: Accept if above this after max iterations
        """
        self.reviewer = reviewer
        self.challenger = challenger

        # Get defaults from config
        settings = get_settings()
        challenger_config = settings.challenger

        self.satisfaction_threshold = (
            satisfaction_threshold or challenger_config.satisfaction_threshold
        )

        # Apply hard safety cap to max_iterations
        requested_max = max_iterations or challenger_config.max_iterations
        self.max_iterations = min(requested_max, self.ABSOLUTE_MAX_ITERATIONS)

        if requested_max > self.ABSOLUTE_MAX_ITERATIONS:
            logger.warning(
                f"max_iterations={requested_max} exceeds safety limit. "
                f"Capped at {self.ABSOLUTE_MAX_ITERATIONS}."
            )

        self.min_improvement_threshold = (
            min_improvement_threshold or challenger_config.min_improvement_threshold
        )
        self.stagnation_window = stagnation_window or challenger_config.stagnation_window
        self.forced_acceptance_threshold = (
            forced_acceptance_threshold or challenger_config.forced_acceptance_threshold
        )

    async def run(
        self,
        context: ReviewContext,
        reviewer_name: str = "reviewer_be",
        on_iteration_callback: IterationCallback | None = None,
        on_content_callback: ContentCallback | None = None,
    ) -> ChallengerLoopResult:
        """
        Run the challenger loop.

        Args:
            context: Review context with files to review
            reviewer_name: Name of the reviewer agent
            on_iteration_callback: Called after each iteration with
                (iteration, satisfaction, issues_count)
            on_content_callback: Called with streaming content chunks

        Returns:
            ChallengerLoopResult with final review and metadata
        """
        settings = get_settings()

        # Initialize reviewer and challenger if not provided
        if self.reviewer is None:
            self.reviewer = ClaudeCLIReviewer(name=reviewer_name)

        if self.challenger is None:
            self.challenger = GeminiCLIChallenger()

        # Load agent prompt (must exist)
        context.agent_prompt = self.reviewer.load_agent_prompt(settings.agents_dir)

        iteration = 0
        current_review: ReviewOutput | None = None
        challenger_feedback: ChallengerFeedback | None = None
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

            # Safety check: absolute hard stop regardless of config
            if iteration > self.ABSOLUTE_MAX_ITERATIONS:
                logger.error(
                    f"SAFETY STOP: Iteration {iteration} exceeds absolute limit "
                    f"({self.ABSOLUTE_MAX_ITERATIONS}). Breaking loop."
                )
                break

            logger.info(f"[LOOP] ========== Iteration {iteration}/{self.max_iterations} ==========")
            logger.info(f"[LOOP] Reviewer: {self.reviewer.name}")

            # Step 1: Reviewer performs/refines review
            # CLI reviewers receive file list (not contents) and explore autonomously
            file_list = context.files
            # For monorepo: ensure only workspace files are included (safety filter)
            if context.workspace_path:
                file_list = [f for f in file_list if f.startswith(f"{context.workspace_path}/")]
            logger.info(f"[LOOP] Files to review: {len(file_list)}")

            if current_review is None:
                logger.info("[LOOP] >> Starting INITIAL review with Claude CLI...")
                current_review = await self.reviewer.review(context, file_list, on_content_callback)
                logger.info(
                    f"[LOOP] << Initial review complete: {len(current_review.issues)} issues found"
                )
            else:
                logger.info("[LOOP] >> Starting REFINEMENT with Claude CLI...")
                # challenger_feedback should never be None when refining
                # (it's set after first iteration)
                assert (
                    challenger_feedback is not None
                ), "challenger_feedback should be set after first iteration"
                current_review = await self.reviewer.refine(
                    context,
                    current_review,
                    challenger_feedback,
                    file_list,
                    on_content_callback,
                )
                logger.info(f"[LOOP] << Refinement complete: {len(current_review.issues)} issues")

            # Step 2: Challenger evaluates
            # CLI challenger receives review + file list and can read files to verify
            logger.info("[LOOP] >> Starting CHALLENGE with Gemini CLI...")
            challenger_feedback = await self.challenger.challenge(
                current_review,
                file_list,
                context.repo_path,
                iteration,
                on_content_callback,
            )
            challenger_feedbacks.append(challenger_feedback)

            satisfaction_score = challenger_feedback.satisfaction_score
            logger.info(
                f"[LOOP] << Challenge complete: satisfaction={satisfaction_score:.1f}% "
                f"(threshold={self.satisfaction_threshold}%)"
            )
            logger.info(
                f"[LOOP] Missed issues: {len(challenger_feedback.missed_issues)}, "
                f"Challenges: {len(challenger_feedback.challenges)}"
            )

            # Record iteration history
            issues_added = len(challenger_feedback.missed_issues)
            # addressed_challenges is already an int (count of challenges)
            challenges_resolved = (
                current_review.refinement_notes[-1].get("addressed_challenges", 0)
                if current_review.refinement_notes
                else 0
            )

            iteration_history.append(
                IterationHistory(
                    iteration=iteration,
                    satisfaction_score=satisfaction_score,
                    issues_added=issues_added,
                    challenges_resolved=challenges_resolved,
                )
            )

            # Call iteration callback if provided
            if on_iteration_callback:
                await on_iteration_callback(
                    iteration,
                    satisfaction_score,
                    len(current_review.issues) if current_review else 0,
                )

            # Extract insights from significant issues found
            for missed in challenger_feedback.missed_issues:
                if missed.suggested_severity in ["CRITICAL", "HIGH"]:
                    insights.append(
                        ChallengerInsight(
                            iteration=iteration,
                            description=f"{missed.type}: {missed.description}",
                            impact="high" if missed.suggested_severity == "CRITICAL" else "medium",
                        )
                    )

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

        logger.info("[LOOP] ========== LOOP COMPLETED ==========")
        logger.info(
            f"[LOOP] Final: iterations={iteration}, "
            f"satisfaction={satisfaction_score:.1f}%, "
            f"convergence={final_convergence.value}, "
            f"issues={len(current_review.issues) if current_review else 0}"
        )

        # At this point, current_review should never be None (at least one iteration ran)
        assert (
            current_review is not None
        ), "current_review should be set after at least one iteration"

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
            recent = history[-self.stagnation_window :]
            improvements = [
                recent[i + 1].satisfaction_score - recent[i].satisfaction_score
                for i in range(len(recent) - 1)
            ]

            if all(imp < self.min_improvement_threshold for imp in improvements):
                return ConvergenceStatus.STAGNATED

        return ConvergenceStatus.IN_PROGRESS  # Loop should continue

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
            recent = history[-self.stagnation_window :]
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
    satisfaction_threshold: float | None = None,
    max_iterations: int | None = None,
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
