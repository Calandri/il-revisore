"""
Triple-LLM Review Runner.

Runs Claude, Gemini, and Grok reviews in parallel for the same task,
then merges the outputs using deduplication.

Replaces ChallengerLoop when challenger_enabled=False.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from turbowrap.orchestration.report_utils import deduplicate_issues
from turbowrap.review.models.review import Issue, ReviewOutput, ReviewSummary

if TYPE_CHECKING:
    from turbowrap.review.reviewers.base import ReviewContext
    from turbowrap.review.reviewers.claude_cli_reviewer import ClaudeCLIReviewer
    from turbowrap.review.reviewers.gemini_cli_reviewer import GeminiCLIReviewer
    from turbowrap.review.reviewers.grok_cli_reviewer import GrokCLIReviewer

logger = logging.getLogger(__name__)


@dataclass
class DualLLMResult:
    """Result of dual-LLM parallel review (legacy, kept for compatibility)."""

    # Merged review output
    final_review: ReviewOutput

    # Per-LLM stats
    claude_issues_count: int = 0
    gemini_issues_count: int = 0
    merged_issues_count: int = 0
    overlap_count: int = 0  # Issues found by both

    # Status (ok or error message)
    claude_status: str = "ok"
    gemini_status: str = "ok"

    # Duration
    claude_duration_seconds: float = 0.0
    gemini_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0

    # Raw outputs (for debugging/UI)
    claude_review: ReviewOutput | None = None
    gemini_review: ReviewOutput | None = None


@dataclass
class TripleLLMResult:
    """Result of triple-LLM parallel review."""

    # Merged review output
    final_review: ReviewOutput

    # Per-LLM stats
    claude_issues_count: int = 0
    gemini_issues_count: int = 0
    grok_issues_count: int = 0
    merged_issues_count: int = 0
    overlap_count: int = 0  # Issues found by 2+ LLMs
    triple_overlap_count: int = 0  # Issues found by all 3 LLMs

    # Status (ok or error message)
    claude_status: str = "ok"
    gemini_status: str = "ok"
    grok_status: str = "ok"

    # Duration
    claude_duration_seconds: float = 0.0
    gemini_duration_seconds: float = 0.0
    grok_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0

    # Raw outputs (for debugging/UI)
    claude_review: ReviewOutput | None = None
    gemini_review: ReviewOutput | None = None
    grok_review: ReviewOutput | None = None


class DualLLMRunner:
    """
    Runs Claude and Gemini reviews in parallel (legacy).

    Usage:
        runner = DualLLMRunner(
            claude_reviewer=ClaudeCLIReviewer(name="reviewer_be"),
            gemini_reviewer=GeminiCLIReviewer(name="reviewer_be"),
        )
        result = await runner.run(context, file_list)
    """

    def __init__(
        self,
        claude_reviewer: ClaudeCLIReviewer,
        gemini_reviewer: GeminiCLIReviewer,
    ):
        """
        Initialize dual-LLM runner.

        Args:
            claude_reviewer: Claude CLI reviewer instance
            gemini_reviewer: Gemini CLI reviewer instance
        """
        self.claude_reviewer = claude_reviewer
        self.gemini_reviewer = gemini_reviewer

    async def run(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_claude_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_gemini_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> DualLLMResult:
        """
        Run Claude and Gemini reviews in parallel.

        Args:
            context: Review context with repo path and metadata
            file_list: List of files to review
            on_claude_chunk: Optional callback for Claude streaming output
            on_gemini_chunk: Optional callback for Gemini streaming output

        Returns:
            DualLLMResult with merged issues and per-LLM stats
        """
        import time

        start_time = time.time()

        # Launch both reviews in parallel
        claude_task = asyncio.create_task(self._run_claude(context, file_list, on_claude_chunk))
        gemini_task = asyncio.create_task(self._run_gemini(context, file_list, on_gemini_chunk))

        # Wait for both with exception handling
        results = await asyncio.gather(claude_task, gemini_task, return_exceptions=True)

        claude_result, gemini_result = results

        # Process results
        claude_ok = not isinstance(claude_result, Exception)
        gemini_ok = not isinstance(gemini_result, Exception)

        claude_review: ReviewOutput | None = None
        gemini_review: ReviewOutput | None = None
        claude_issues: list[Issue] = []
        gemini_issues: list[Issue] = []

        if claude_ok and isinstance(claude_result, ReviewOutput):
            claude_review = claude_result
            claude_issues = claude_result.issues
            # Tag issues with source
            for issue in claude_issues:
                if "claude" not in issue.flagged_by:
                    issue.flagged_by.append("claude")

        if gemini_ok and isinstance(gemini_result, ReviewOutput):
            gemini_review = gemini_result
            gemini_issues = gemini_result.issues
            # Tag issues with source
            for issue in gemini_issues:
                if "gemini" not in issue.flagged_by:
                    issue.flagged_by.append("gemini")

        # Merge all issues
        all_issues = claude_issues + gemini_issues
        merged_issues = deduplicate_issues(all_issues)

        # Count overlaps (issues flagged by both)
        overlap_count = sum(
            1
            for issue in merged_issues
            if len(issue.flagged_by) > 1
            and "claude" in issue.flagged_by
            and "gemini" in issue.flagged_by
        )

        # Calculate merged summary
        merged_summary = self._merge_summaries(claude_review, gemini_review, merged_issues)

        # Create merged review output
        final_review = ReviewOutput(
            reviewer=self.claude_reviewer.name,  # Use reviewer name
            summary=merged_summary,
            issues=merged_issues,
            duration_seconds=time.time() - start_time,
        )

        # Determine statuses
        claude_status = "ok" if claude_ok else str(claude_result)
        gemini_status = "ok" if gemini_ok else str(gemini_result)

        # Log results
        logger.info(
            f"[DUAL-LLM] {self.claude_reviewer.name}: "
            f"Claude={len(claude_issues)} issues ({claude_status}), "
            f"Gemini={len(gemini_issues)} issues ({gemini_status}), "
            f"Merged={len(merged_issues)} issues (overlap={overlap_count})"
        )

        return DualLLMResult(
            final_review=final_review,
            claude_issues_count=len(claude_issues),
            gemini_issues_count=len(gemini_issues),
            merged_issues_count=len(merged_issues),
            overlap_count=overlap_count,
            claude_status=claude_status,
            gemini_status=gemini_status,
            claude_duration_seconds=claude_review.duration_seconds if claude_review else 0.0,
            gemini_duration_seconds=gemini_review.duration_seconds if gemini_review else 0.0,
            total_duration_seconds=time.time() - start_time,
            claude_review=claude_review,
            gemini_review=gemini_review,
        )

    async def _run_claude(
        self,
        context: ReviewContext,
        file_list: list[str] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> ReviewOutput:
        """Run Claude review with error handling."""
        try:
            return await self.claude_reviewer.review(
                context=context,
                file_list=file_list,
                on_chunk=on_chunk,
            )
        except Exception as e:
            logger.error(f"[DUAL-LLM] Claude review failed: {e}")
            raise

    async def _run_gemini(
        self,
        context: ReviewContext,
        file_list: list[str] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> ReviewOutput:
        """Run Gemini review with error handling."""
        try:
            return await self.gemini_reviewer.review(
                context=context,
                file_list=file_list,
                on_chunk=on_chunk,
            )
        except Exception as e:
            logger.error(f"[DUAL-LLM] Gemini review failed: {e}")
            raise

    def _merge_summaries(
        self,
        claude_review: ReviewOutput | None,
        gemini_review: ReviewOutput | None,
        merged_issues: list[Issue],
    ) -> ReviewSummary:
        """
        Merge summaries from Claude and Gemini reviews.

        Args:
            claude_review: Claude review output (may be None)
            gemini_review: Gemini review output (may be None)
            merged_issues: Merged issues list

        Returns:
            Merged ReviewSummary
        """
        from turbowrap.review.models.review import IssueSeverity

        # Count severities in merged issues
        critical = sum(1 for i in merged_issues if i.severity == IssueSeverity.CRITICAL)
        high = sum(1 for i in merged_issues if i.severity == IssueSeverity.HIGH)
        medium = sum(1 for i in merged_issues if i.severity == IssueSeverity.MEDIUM)
        low = sum(1 for i in merged_issues if i.severity == IssueSeverity.LOW)

        # Get files_reviewed from available reviews
        files_reviewed = 0
        if claude_review:
            files_reviewed = max(files_reviewed, claude_review.summary.files_reviewed)
        if gemini_review:
            files_reviewed = max(files_reviewed, gemini_review.summary.files_reviewed)

        # Average scores if both available, otherwise use the available one
        scores = []
        if claude_review:
            scores.append(claude_review.summary.score)
        if gemini_review:
            scores.append(gemini_review.summary.score)
        avg_score = sum(scores) / len(scores) if scores else 5.0

        return ReviewSummary(
            files_reviewed=files_reviewed,
            critical_issues=critical,
            high_issues=high,
            medium_issues=medium,
            low_issues=low,
            score=avg_score,
        )


class TripleLLMRunner:
    """
    Runs Claude, Gemini, and Grok reviews in parallel.

    Usage:
        runner = TripleLLMRunner(
            claude_reviewer=ClaudeCLIReviewer(name="reviewer_be"),
            gemini_reviewer=GeminiCLIReviewer(name="reviewer_be"),
            grok_reviewer=GrokCLIReviewer(name="reviewer_be"),
        )
        result = await runner.run(context, file_list)
    """

    def __init__(
        self,
        claude_reviewer: ClaudeCLIReviewer,
        gemini_reviewer: GeminiCLIReviewer,
        grok_reviewer: GrokCLIReviewer,
    ):
        """
        Initialize triple-LLM runner.

        Args:
            claude_reviewer: Claude CLI reviewer instance
            gemini_reviewer: Gemini CLI reviewer instance
            grok_reviewer: Grok CLI reviewer instance
        """
        self.claude_reviewer = claude_reviewer
        self.gemini_reviewer = gemini_reviewer
        self.grok_reviewer = grok_reviewer

    async def run(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_claude_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_gemini_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_grok_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> TripleLLMResult:
        """
        Run Claude, Gemini, and Grok reviews in parallel.

        Args:
            context: Review context with repo path and metadata
            file_list: List of files to review
            on_claude_chunk: Optional callback for Claude streaming output
            on_gemini_chunk: Optional callback for Gemini streaming output
            on_grok_chunk: Optional callback for Grok streaming output

        Returns:
            TripleLLMResult with merged issues and per-LLM stats
        """
        import time

        start_time = time.time()

        # Launch all three reviews in parallel
        claude_task = asyncio.create_task(self._run_claude(context, file_list, on_claude_chunk))
        gemini_task = asyncio.create_task(self._run_gemini(context, file_list, on_gemini_chunk))
        grok_task = asyncio.create_task(self._run_grok(context, file_list, on_grok_chunk))

        # Wait for all with exception handling
        results = await asyncio.gather(claude_task, gemini_task, grok_task, return_exceptions=True)

        claude_result, gemini_result, grok_result = results

        # Process results
        claude_ok = not isinstance(claude_result, Exception)
        gemini_ok = not isinstance(gemini_result, Exception)
        grok_ok = not isinstance(grok_result, Exception)

        claude_review: ReviewOutput | None = None
        gemini_review: ReviewOutput | None = None
        grok_review: ReviewOutput | None = None
        claude_issues: list[Issue] = []
        gemini_issues: list[Issue] = []
        grok_issues: list[Issue] = []

        if claude_ok and isinstance(claude_result, ReviewOutput):
            claude_review = claude_result
            claude_issues = claude_result.issues
            # Tag issues with source
            for issue in claude_issues:
                if "claude" not in issue.flagged_by:
                    issue.flagged_by.append("claude")

        if gemini_ok and isinstance(gemini_result, ReviewOutput):
            gemini_review = gemini_result
            gemini_issues = gemini_result.issues
            # Tag issues with source
            for issue in gemini_issues:
                if "gemini" not in issue.flagged_by:
                    issue.flagged_by.append("gemini")

        if grok_ok and isinstance(grok_result, ReviewOutput):
            grok_review = grok_result
            grok_issues = grok_result.issues
            # Tag issues with source
            for issue in grok_issues:
                if "grok" not in issue.flagged_by:
                    issue.flagged_by.append("grok")

        # Merge all issues
        all_issues = claude_issues + gemini_issues + grok_issues
        merged_issues = deduplicate_issues(all_issues)

        # Count overlaps
        overlap_count = sum(1 for issue in merged_issues if len(issue.flagged_by) > 1)
        triple_overlap_count = sum(
            1
            for issue in merged_issues
            if len(issue.flagged_by) >= 3
            and "claude" in issue.flagged_by
            and "gemini" in issue.flagged_by
            and "grok" in issue.flagged_by
        )

        # Calculate merged summary
        merged_summary = self._merge_summaries(
            claude_review, gemini_review, grok_review, merged_issues
        )

        # Create merged review output
        final_review = ReviewOutput(
            reviewer=self.claude_reviewer.name,  # Use reviewer name
            summary=merged_summary,
            issues=merged_issues,
            duration_seconds=time.time() - start_time,
        )

        # Determine statuses
        claude_status = "ok" if claude_ok else str(claude_result)
        gemini_status = "ok" if gemini_ok else str(gemini_result)
        grok_status = "ok" if grok_ok else str(grok_result)

        # Log results
        logger.info(
            f"[TRIPLE-LLM] {self.claude_reviewer.name}: "
            f"Claude={len(claude_issues)} ({claude_status}), "
            f"Gemini={len(gemini_issues)} ({gemini_status}), "
            f"Grok={len(grok_issues)} ({grok_status}), "
            f"Merged={len(merged_issues)} (overlap={overlap_count}, triple={triple_overlap_count})"
        )

        return TripleLLMResult(
            final_review=final_review,
            claude_issues_count=len(claude_issues),
            gemini_issues_count=len(gemini_issues),
            grok_issues_count=len(grok_issues),
            merged_issues_count=len(merged_issues),
            overlap_count=overlap_count,
            triple_overlap_count=triple_overlap_count,
            claude_status=claude_status,
            gemini_status=gemini_status,
            grok_status=grok_status,
            claude_duration_seconds=claude_review.duration_seconds if claude_review else 0.0,
            gemini_duration_seconds=gemini_review.duration_seconds if gemini_review else 0.0,
            grok_duration_seconds=grok_review.duration_seconds if grok_review else 0.0,
            total_duration_seconds=time.time() - start_time,
            claude_review=claude_review,
            gemini_review=gemini_review,
            grok_review=grok_review,
        )

    async def _run_claude(
        self,
        context: ReviewContext,
        file_list: list[str] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> ReviewOutput:
        """Run Claude review with error handling."""
        try:
            return await self.claude_reviewer.review(
                context=context,
                file_list=file_list,
                on_chunk=on_chunk,
            )
        except Exception as e:
            logger.error(f"[TRIPLE-LLM] Claude review failed: {e}")
            raise

    async def _run_gemini(
        self,
        context: ReviewContext,
        file_list: list[str] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> ReviewOutput:
        """Run Gemini review with error handling."""
        try:
            return await self.gemini_reviewer.review(
                context=context,
                file_list=file_list,
                on_chunk=on_chunk,
            )
        except Exception as e:
            logger.error(f"[TRIPLE-LLM] Gemini review failed: {e}")
            raise

    async def _run_grok(
        self,
        context: ReviewContext,
        file_list: list[str] | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> ReviewOutput:
        """Run Grok review with error handling."""
        try:
            return await self.grok_reviewer.review(
                context=context,
                file_list=file_list,
                on_chunk=on_chunk,
            )
        except Exception as e:
            logger.error(f"[TRIPLE-LLM] Grok review failed: {e}")
            raise

    def _merge_summaries(
        self,
        claude_review: ReviewOutput | None,
        gemini_review: ReviewOutput | None,
        grok_review: ReviewOutput | None,
        merged_issues: list[Issue],
    ) -> ReviewSummary:
        """
        Merge summaries from Claude, Gemini, and Grok reviews.

        Args:
            claude_review: Claude review output (may be None)
            gemini_review: Gemini review output (may be None)
            grok_review: Grok review output (may be None)
            merged_issues: Merged issues list

        Returns:
            Merged ReviewSummary
        """
        from turbowrap.review.models.review import IssueSeverity

        # Count severities in merged issues
        critical = sum(1 for i in merged_issues if i.severity == IssueSeverity.CRITICAL)
        high = sum(1 for i in merged_issues if i.severity == IssueSeverity.HIGH)
        medium = sum(1 for i in merged_issues if i.severity == IssueSeverity.MEDIUM)
        low = sum(1 for i in merged_issues if i.severity == IssueSeverity.LOW)

        # Get files_reviewed from available reviews
        files_reviewed = 0
        if claude_review:
            files_reviewed = max(files_reviewed, claude_review.summary.files_reviewed)
        if gemini_review:
            files_reviewed = max(files_reviewed, gemini_review.summary.files_reviewed)
        if grok_review:
            files_reviewed = max(files_reviewed, grok_review.summary.files_reviewed)

        # Average scores from all available reviews
        scores = []
        if claude_review:
            scores.append(claude_review.summary.score)
        if gemini_review:
            scores.append(gemini_review.summary.score)
        if grok_review:
            scores.append(grok_review.summary.score)
        avg_score = sum(scores) / len(scores) if scores else 5.0

        return ReviewSummary(
            files_reviewed=files_reviewed,
            critical_issues=critical,
            high_issues=high,
            medium_issues=medium,
            low_issues=low,
            score=avg_score,
        )
