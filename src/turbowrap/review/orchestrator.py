"""
Main orchestrator for TurboWrap code review system.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from turbowrap.config import get_settings
from turbowrap.llm import GeminiClient

# Import shared orchestration utilities
from turbowrap.orchestration import (
    build_next_steps,
    calculate_overall_score,
    calculate_recommendation,
    count_by_severity,
    deduplicate_issues,
    prioritize_issues,
)
from turbowrap.review.dual_llm_runner import TripleLLMResult, TripleLLMRunner
from turbowrap.review.models.evaluation import RepositoryEvaluation
from turbowrap.review.models.progress import (
    ProgressEvent,
    ProgressEventType,
    get_reviewer_display_name,
)
from turbowrap.review.models.report import (
    ChallengerMetadata,
    FinalReport,
    ReportSummary,
    RepositoryInfo,
    RepoType,
    ReviewerResult,
)
from turbowrap.review.models.review import Issue, ReviewMode, ReviewRequest
from turbowrap.review.parallel_triple_llm_runner import ParallelTripleLLMRunner
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.reviewers.claude_evaluator import ClaudeEvaluator
from turbowrap.review.utils.repo_detector import RepoDetector
from turbowrap.tools.structure_generator import StructureGenerator
from turbowrap.utils.file_utils import is_text_file, read_file
from turbowrap.utils.git_utils import GitUtils

logger = logging.getLogger(__name__)

CheckpointData = dict[str, dict[str, Any]]

ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]

CheckpointCallback = Callable[
    [str, str, list[Issue], float, int, list[dict[str, Any]], datetime],
    Awaitable[None],
]


class Orchestrator:
    """
    Master orchestrator for the TurboWrap code review system.

    Coordinates:
    1. Repository type detection
    2. Reviewer selection and execution
    3. Challenger loop for each reviewer
    4. Report aggregation and generation
    """

    def __init__(self) -> None:
        """Initialize the orchestrator."""
        self.settings = get_settings()
        self.repo_detector = RepoDetector()

    async def review(
        self,
        request: ReviewRequest,
        progress_callback: ProgressCallback | None = None,
        completed_checkpoints: CheckpointData | None = None,
        checkpoint_callback: CheckpointCallback | None = None,
        parent_session_id: str | None = None,
    ) -> FinalReport:
        """Perform a complete code review.

        Args:
            request: Review request with source and options
            progress_callback: Optional async callback for progress events
            completed_checkpoints: Dict of already completed reviewers (for resume).
                Keys are reviewer names, values are checkpoint dicts with:
                - issues_data: list of issue dicts
                - final_satisfaction: float
                - iterations: int
            checkpoint_callback: Optional callback to save checkpoint after each reviewer
            parent_session_id: Optional parent session ID for operation tracking

        Returns:
            FinalReport with all findings
        """
        datetime.utcnow()
        report_id = f"rev_{uuid.uuid4().hex[:12]}"

        logger.info(f"Starting review {report_id}")

        async def emit(event: ProgressEvent) -> None:
            if progress_callback:
                event.review_id = report_id
                await progress_callback(event)

        async def emit_log(level: str, message: str) -> None:
            """Emit a log event for UI toast notifications."""
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEW_LOG,
                    message=message,
                    log_level=level,
                )
            )

        await emit(
            ProgressEvent(
                type=ProgressEventType.REVIEW_STARTED,
                review_id=report_id,
                message="Starting code review...",
            )
        )

        context = await self._prepare_context(request, emit, report_id, parent_session_id)

        repo_type = self._detect_repo_type(context.files, context.structure_docs)
        logger.info(f"Detected repository type: {repo_type.value}")

        reviewers = self._get_reviewers(repo_type, request.options.include_functional)
        logger.info(f"Running reviewers: {reviewers}")
        reviewer_results: list[ReviewerResult] = []
        all_issues: list[Issue] = []

        # Parallel Triple-LLM mode: 3 CLI processes instead of 15
        # Each LLM (Claude, Gemini, Grok) runs IN PARALLEL
        # This shares cache within each LLM session, reducing costs by ~80%

        started_at = datetime.utcnow()

        # Emit start events for the 3 LLM streams
        await emit(
            ProgressEvent(
                type=ProgressEventType.REVIEWER_STARTED,
                reviewer_name="parallel_claude",
                reviewer_display_name="Claude (All Specialists)",
                message="Starting Claude parallel review...",
            )
        )
        await emit(
            ProgressEvent(
                type=ProgressEventType.REVIEWER_STARTED,
                reviewer_name="parallel_gemini",
                reviewer_display_name="Gemini (All Specialists)",
                message="Starting Gemini parallel review...",
            )
        )
        await emit(
            ProgressEvent(
                type=ProgressEventType.REVIEWER_STARTED,
                reviewer_name="parallel_grok",
                reviewer_display_name="Grok (All Specialists)",
                message="Starting Grok parallel review...",
            )
        )

        # Streaming callbacks for each LLM
        async def on_claude_chunk(chunk: str) -> None:
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_STREAMING,
                    reviewer_name="parallel_claude",
                    reviewer_display_name="Claude (All Specialists)",
                    content=chunk,
                )
            )

        async def on_gemini_chunk(chunk: str) -> None:
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_STREAMING,
                    reviewer_name="parallel_gemini",
                    reviewer_display_name="Gemini (All Specialists)",
                    content=chunk,
                )
            )

        async def on_grok_chunk(chunk: str) -> None:
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_STREAMING,
                    reviewer_name="parallel_grok",
                    reviewer_display_name="Grok (All Specialists)",
                    content=chunk,
                )
            )

        try:
            # Run the parallel triple-LLM review (3 CLIs in parallel)
            runner = ParallelTripleLLMRunner(specialists=reviewers)
            par_result = await runner.run(
                context=context,
                file_list=context.files,
                on_claude_chunk=on_claude_chunk,
                on_gemini_chunk=on_gemini_chunk,
                on_grok_chunk=on_grok_chunk,
            )

            # Emit completion events for each LLM
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_COMPLETED,
                    reviewer_name="parallel_claude",
                    reviewer_display_name="Claude (All Specialists)",
                    issues_found=par_result.claude_issues_count,
                    message=f"Claude: {par_result.claude_issues_count} issues",
                )
            )
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_COMPLETED,
                    reviewer_name="parallel_gemini",
                    reviewer_display_name="Gemini (All Specialists)",
                    issues_found=par_result.gemini_issues_count,
                    message=f"Gemini: {par_result.gemini_issues_count} issues",
                )
            )
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_COMPLETED,
                    reviewer_name="parallel_grok",
                    reviewer_display_name="Grok (All Specialists)",
                    issues_found=par_result.grok_issues_count,
                    message=f"Grok: {par_result.grok_issues_count} issues",
                )
            )

            # Log summary
            await emit_log(
                "INFO",
                f"✓ Parallel review: {par_result.merged_issues_count} issues "
                f"(C:{par_result.claude_issues_count} G:{par_result.gemini_issues_count} "
                f"X:{par_result.grok_issues_count}, overlap={par_result.overlap_count})",
            )

            # Build reviewer_results for each specialist from merged data
            for reviewer_name in reviewers:
                # Count issues for this specialist across all LLMs
                specialist_issues = 0
                if reviewer_name in par_result.claude_reviews:
                    specialist_issues += len(par_result.claude_reviews[reviewer_name].issues)
                if reviewer_name in par_result.gemini_reviews:
                    specialist_issues += len(par_result.gemini_reviews[reviewer_name].issues)
                if reviewer_name in par_result.grok_reviews:
                    specialist_issues += len(par_result.grok_reviews[reviewer_name].issues)

                # Count how many LLMs successfully reviewed this specialist
                llms_ok = sum(
                    [
                        reviewer_name in par_result.claude_reviews,
                        reviewer_name in par_result.gemini_reviews,
                        reviewer_name in par_result.grok_reviews,
                    ]
                )

                # Calculate total cost for this specialist across all LLMs
                specialist_cost = 0.0
                if reviewer_name in par_result.claude_reviews:
                    specialist_cost += sum(
                        m.cost_usd for m in par_result.claude_reviews[reviewer_name].model_usage
                    )
                if reviewer_name in par_result.gemini_reviews:
                    specialist_cost += sum(
                        m.cost_usd for m in par_result.gemini_reviews[reviewer_name].model_usage
                    )
                if reviewer_name in par_result.grok_reviews:
                    specialist_cost += sum(
                        m.cost_usd for m in par_result.grok_reviews[reviewer_name].model_usage
                    )

                reviewer_results.append(
                    ReviewerResult(
                        name=reviewer_name,
                        status="completed" if llms_ok > 0 else "error",
                        issues_found=specialist_issues,
                        duration_seconds=par_result.total_duration_seconds / len(reviewers),
                        iterations=1,
                        final_satisfaction=llms_ok * 33.33,
                        cost_usd=specialist_cost,
                    )
                )

            # Add all merged issues
            all_issues.extend(par_result.final_review.issues)

            # Checkpoint callback for recovery
            if checkpoint_callback:
                for reviewer_name in reviewers:
                    # Get issues for this specialist
                    spec_issues: list[Issue] = []
                    if reviewer_name in par_result.claude_reviews:
                        spec_issues.extend(par_result.claude_reviews[reviewer_name].issues)
                    if reviewer_name in par_result.gemini_reviews:
                        spec_issues.extend(par_result.gemini_reviews[reviewer_name].issues)
                    if reviewer_name in par_result.grok_reviews:
                        spec_issues.extend(par_result.grok_reviews[reviewer_name].issues)

                    await checkpoint_callback(
                        reviewer_name,
                        "completed",
                        spec_issues,
                        100.0,
                        1,
                        [],
                        started_at,
                    )

        except Exception as e:
            logger.exception(f"Parallel triple-LLM review failed: {e}")

            # Emit error for all LLM streams
            llm_names = ["parallel_claude", "parallel_gemini", "parallel_grok"]
            for llm_name in llm_names:
                display = f"{llm_name.split('_')[1].title()} (All Specialists)"
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.REVIEWER_ERROR,
                        reviewer_name=llm_name,
                        reviewer_display_name=display,
                        error=str(e),
                        message=f"{llm_name} failed: {str(e)[:50]}",
                    )
                )

            await emit_log("ERROR", f"✗ Parallel review failed: {str(e)[:60]}")

            # Mark all reviewers as failed
            for reviewer_name in reviewers:
                reviewer_results.append(
                    ReviewerResult(
                        name=reviewer_name,
                        status="error",
                        error=str(e),
                    )
                )

                if checkpoint_callback:
                    await checkpoint_callback(
                        reviewer_name,
                        "failed",
                        [],
                        0.0,
                        0,
                        [],
                        started_at,
                    )

        # Step 5: Deduplicate and prioritize issues
        deduplicated_issues = deduplicate_issues(all_issues)
        prioritized_issues = prioritize_issues(deduplicated_issues)

        # Step 5.5: Run final evaluator (Claude Opus)
        repo_info = RepositoryInfo(
            type=repo_type,
            name=context.repo_name,
            branch=context.current_branch,
            commit_sha=context.commit_sha,
        )

        await emit(
            ProgressEvent(
                type=ProgressEventType.REVIEWER_STARTED,
                reviewer_name="evaluator",
                reviewer_display_name="Repository Evaluator",
                message="Running final evaluation...",
            )
        )

        evaluation, eval_error = await self._run_evaluator(
            context=context,
            issues=prioritized_issues,
            reviewer_results=reviewer_results,
            repo_info=repo_info,
            emit=emit,
            review_id=report_id,
        )

        if evaluation:
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_COMPLETED,
                    reviewer_name="evaluator",
                    reviewer_display_name="Repository Evaluator",
                    message=f"Evaluation complete: {evaluation.overall_score}/100",
                )
            )
            await emit_log("INFO", f"✓ Evaluation: {evaluation.overall_score}/100")
        else:
            error_msg = eval_error or "Unknown error"
            await emit(
                ProgressEvent(
                    type=ProgressEventType.REVIEWER_ERROR,
                    reviewer_name="evaluator",
                    reviewer_display_name="Repository Evaluator",
                    error=error_msg,
                    message=f"Evaluation failed: {error_msg[:100]}",
                )
            )
            await emit_log("ERROR", f"✗ Evaluation: {error_msg[:80]}")

        # Step 6: Build final report
        report = self._build_report(
            report_id=report_id,
            request=request,
            context=context,
            repo_type=repo_type,
            reviewer_results=reviewer_results,
            issues=prioritized_issues,
            evaluation=evaluation,
        )

        logger.info(
            f"Review {report_id} completed: "
            f"{report.summary.total_issues} issues, "
            f"score={report.summary.overall_score:.1f}, "
            f"recommendation={report.summary.recommendation.value}"
        )

        await emit(
            ProgressEvent(
                type=ProgressEventType.REVIEW_COMPLETED,
                review_id=report_id,
                issues_found=report.summary.total_issues,
                message=(
                    f"Review completed with {report.summary.total_issues} issues "
                    f"(score: {report.summary.overall_score:.1f})"
                ),
            )
        )

        await emit_log(
            "INFO",
            (
                f"🎉 Review completata: {report.summary.total_issues} issues, "
                f"score {report.summary.overall_score:.1f}/10"
            ),
        )

        return report

    async def _prepare_context(
        self,
        request: ReviewRequest,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
        report_id: str | None = None,
        parent_session_id: str | None = None,
    ) -> ReviewContext:
        """Prepare the review context from the request.

        Args:
            request: Review request
            emit: Optional callback for progress events
            report_id: Review ID for logging
            parent_session_id: Optional parent session ID for operation tracking

        Returns:
            ReviewContext with loaded files/structure docs
        """
        context = ReviewContext(request=request)
        if report_id:
            context.metadata["review_id"] = report_id
        source = request.source
        mode = request.options.mode

        if source.directory:
            context.repo_path = Path(source.directory)
        elif source.pr_url or source.commit_sha or source.files:
            context.repo_path = Path(source.directory or Path.cwd())
        else:
            context.repo_path = Path.cwd()

        if source.workspace_path:
            context.workspace_path = source.workspace_path
            logger.info(f"Monorepo mode: limiting review to workspace '{source.workspace_path}'")

        # Delete existing structure.xml if regenerate_structure is True
        if request.options.regenerate_structure:
            if context.workspace_path:
                xml_path = context.repo_path / context.workspace_path / ".llms" / "structure.xml"
            else:
                xml_path = context.repo_path / ".llms" / "structure.xml"
            if xml_path.exists():
                xml_path.unlink()
                logger.info(f"Deleted existing {xml_path} (regenerate_structure=True)")

        self._load_structure_docs(context)

        if not context.structure_docs:
            logger.info("No .llms/structure.xml found - auto-generating with Gemini Flash...")
            await self._auto_generate_structure(context, emit, parent_session_id)
            self._load_structure_docs(context)

            if not context.structure_docs:
                logger.warning("Structure generation completed but .llms/structure.xml not found!")

        if mode == ReviewMode.INITIAL:
            logger.info("INITIAL mode: Reviewing architecture via .llms/structure.xml only")
            if context.workspace_path:
                scan_base = context.repo_path / context.workspace_path
                if scan_base.exists():
                    workspace_files = self._scan_directory(scan_base)
                    context.files = [f"{context.workspace_path}/{f}" for f in workspace_files]
                else:
                    logger.warning(f"Workspace path does not exist: {scan_base}")
                    context.files = self._scan_directory(context.repo_path)
            else:
                context.files = self._scan_directory(context.repo_path)

        else:
            logger.info("DIFF mode: Reviewing changed files")

            if source.pr_url:
                context = await self._prepare_pr_context(source.pr_url, context)

            elif source.commit_sha:
                git = GitUtils(context.repo_path)
                context.files = git.get_changed_files(head_ref=source.commit_sha)
                context.diff = git.get_diff(head_ref=source.commit_sha)
                context.commit_sha = source.commit_sha

            elif source.files:
                context.files = source.files

            elif source.directory:
                # Fallback: scan directory (limited)
                assert context.repo_path is not None
                if context.workspace_path:
                    scan_base = context.repo_path / context.workspace_path
                    if not scan_base.exists():
                        logger.warning(f"Workspace path does not exist: {scan_base}")
                        context.files = self._scan_directory(context.repo_path)
                    else:
                        workspace_files = self._scan_directory(scan_base)
                        context.files = [f"{context.workspace_path}/{f}" for f in workspace_files]
                else:
                    context.files = self._scan_directory(context.repo_path)

            await self._load_file_contents(context)

        try:
            git = GitUtils(context.repo_path)
            if git.is_git_repo():
                context.current_branch = git.get_current_branch()
                context.repo_name = git.get_repo_name()
                if not context.commit_sha:
                    context.commit_sha = git.get_current_commit().sha
        except Exception:
            pass

        return context

    async def _prepare_pr_context(
        self,
        pr_url: str,
        context: ReviewContext,
    ) -> ReviewContext:
        """Prepare context from a GitHub PR URL."""
        pr_info = GitUtils.parse_pr_url(pr_url)
        if not pr_info:
            raise ValueError(f"Invalid PR URL: {pr_url}")

        context.repo_path = Path.cwd()
        context.repo_name = f"{pr_info.owner}/{pr_info.repo}"

        git = GitUtils(context.repo_path)
        context.files = git.get_changed_files()
        context.diff = git.get_diff()
        context.current_branch = git.get_current_branch()

        return context

    def _scan_directory(self, directory: Path) -> list[str]:
        """Scan directory for reviewable files."""
        files = []
        exclude_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            ".mypy_cache",
            ".pytest_cache",
            "dist",
            "build",
            ".next",
            "coverage",
            ".tox",
            "htmlcov",
            ".reviews",
            ".llms",  # Structure docs directory
        }
        exclude_patterns = {".turbowrap_review_"}

        for path in directory.rglob("*"):
            if path.is_file():
                rel_path = path.relative_to(directory)
                # Check if any parent is in exclude list (use relative path, not absolute)
                if any(part in exclude_dirs for part in rel_path.parts):
                    continue
                if any(pattern in path.name for pattern in exclude_patterns):
                    continue

                if is_text_file(path):
                    files.append(str(rel_path))

        return files[:100]  # Limit to 100 files

    def _load_structure_docs(self, context: ReviewContext) -> None:
        """
        Load repository structure documentation for LLM context.

        Only uses .llms/structure.xml (consolidated XML format, optimized for LLM).
        No fallback to STRUCTURE.md.

        For monorepo: loads from workspace/.llms/structure.xml if workspace_path is set.
        """
        if not context.repo_path:
            return

        if context.workspace_path:
            xml_path = context.repo_path / context.workspace_path / ".llms" / "structure.xml"
        else:
            xml_path = context.repo_path / ".llms" / "structure.xml"

        if xml_path.exists():
            try:
                content = xml_path.read_text(encoding="utf-8")
                context.structure_docs["structure.xml"] = content
                logger.info(
                    f"Loaded {xml_path.relative_to(context.repo_path)} "
                    f"({xml_path.stat().st_size:,} bytes)"
                )
            except Exception as e:
                logger.warning(f"Failed to read {xml_path}: {e}")
        else:
            logger.info(
                f"No {xml_path.relative_to(context.repo_path)} found - structure docs not available"
            )

    async def _auto_generate_structure(
        self,
        context: ReviewContext,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
        parent_session_id: str | None = None,
    ) -> None:
        """
        Auto-generate structure documentation using Gemini Flash.

        Generates only .llms/structure.xml (optimized for LLM).
        Called when no structure docs exist.

        Args:
            context: Review context with repo_path set
            emit: Optional callback for progress events
            parent_session_id: Optional parent session ID for operation tracking
        """
        if not context.repo_path:
            logger.error("Cannot generate structure: no repo_path set")
            return

        if context.workspace_path:
            context.repo_path / context.workspace_path
            display_name = context.workspace_path
        else:
            display_name = context.repo_path.name

        if emit:
            await emit(
                ProgressEvent(
                    type=ProgressEventType.STRUCTURE_GENERATION_STARTED,
                    message=f"Generating structure documentation for {display_name}...",
                )
            )

        # Register operation for tracking in live-tasks (import deferred to avoid circular)
        from turbowrap.api.services.operation_tracker import OperationType, get_tracker

        tracker = get_tracker()
        operation_id = f"structure_{uuid.uuid4().hex[:12]}"
        repo_name = context.repo_path.name if context.repo_path else "unknown"

        tracker.register(
            op_type=OperationType.REVIEW,
            operation_id=operation_id,
            repo_name=repo_name,
            user="system",
            details={
                "agent": "flash_analyzer",
                "model": "gemini-3-flash-preview",
                "parent_session_id": parent_session_id,
                "workspace_path": context.workspace_path,
                "task": "structure_generation",
            },
        )

        try:
            # GeminiClient is REQUIRED for structure generation
            logger.info("[ORCHESTRATOR] Creating GeminiClient...")
            gemini_client = GeminiClient()
            logger.info("[ORCHESTRATOR] GeminiClient OK")

            logger.info(
                f"[ORCHESTRATOR] StructureGenerator: repo={context.repo_path}, "
                f"workspace={context.workspace_path}"
            )
            assert context.repo_path is not None
            generator = StructureGenerator(
                context.repo_path,
                workspace_path=context.workspace_path,
                gemini_client=gemini_client,
            )
            logger.info(f"[ORCHESTRATOR] scan_root={generator.scan_root}")

            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.STRUCTURE_GENERATION_PROGRESS,
                        message="Analyzing repository structure with Gemini Flash...",
                    )
                )

            loop = asyncio.get_running_loop()
            start_time = time.time()
            generated_files = await loop.run_in_executor(
                None, lambda: generator.generate(verbose=True, formats=["xml"])
            )
            duration = time.time() - start_time

            if not generated_files:
                raise RuntimeError(
                    f"StructureGenerator returned empty list! scan_root={generator.scan_root}"
                )

            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.STRUCTURE_GENERATION_COMPLETED,
                        message=f"Generated {len(generated_files)} structure file(s)",
                    )
                )

            # Convert Path objects to strings for JSON serialization
            generated_files_str = [str(f) for f in generated_files]

            logger.info(
                f"[ORCHESTRATOR] SUCCESS: Generated {len(generated_files)} "
                f"structure files: {generated_files_str}"
            )

            # Complete operation tracking
            tracker.complete(
                operation_id,
                result={
                    "files_generated": len(generated_files),
                    "files": generated_files_str,
                    "duration_seconds": duration,
                },
            )

        except Exception as e:
            import traceback

            logger.error("[ORCHESTRATOR] !!!! STRUCTURE.XML GENERATION FAILED !!!!")
            logger.error(f"[ORCHESTRATOR] Error: {e}")
            logger.error(f"[ORCHESTRATOR] Traceback:\n{traceback.format_exc()}")

            # Fail operation tracking
            tracker.fail(operation_id, str(e))

            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.REVIEW_ERROR,
                        error=f"CRITICAL: Structure generation failed: {str(e)}",
                        message="Structure generation FAILED - check logs!",
                    )
                )
            raise

    async def _load_file_contents(self, context: ReviewContext) -> None:
        """Load content of files in context."""
        for file_path in context.files:
            try:
                full_path = context.repo_path / file_path if context.repo_path else Path(file_path)
                if full_path.exists() and is_text_file(full_path):
                    content = read_file(full_path)
                    if len(content) < 50000:
                        context.file_contents[file_path] = content
            except Exception as e:
                logger.warning(f"Failed to read {file_path}: {e}")

    def _detect_repo_type(
        self,
        files: list[str],
        structure_docs: dict[str, str] | None = None,
    ) -> RepoType:
        """
        Detect repository type from structure.xml or file patterns.

        Priority:
        1. Parse `type` attribute from structure.xml (most reliable)
        2. Fallback to file pattern detection

        Args:
            files: List of file paths to analyze
            structure_docs: structure.xml contents

        Returns:
            RepoType enum value
        """
        import re

        # Priority 1: Parse type from structure.xml (authoritative source)
        if structure_docs:
            for path, content in structure_docs.items():
                # XML format: <repository ... type="backend" ...>
                if "structure.xml" in path or content.strip().startswith("<?xml"):
                    match = re.search(
                        r'<repository[^>]+type=["\'](\w+)["\']',
                        content,
                        re.IGNORECASE,
                    )
                    if match:
                        type_str = match.group(1).lower()
                        logger.info(f"Detected repo type from structure.xml: {type_str}")
                        if type_str == "backend":
                            return RepoType.BACKEND
                        if type_str == "frontend":
                            return RepoType.FRONTEND
                        if type_str == "fullstack":
                            return RepoType.FULLSTACK

                # Legacy: STRUCTURE.md format
                elif "## Metadata" in content and "Repository Type" in content:
                    match = re.search(
                        r"\*\*Repository Type\*\*:\s*`?(\w+)`?",
                        content,
                        re.IGNORECASE,
                    )
                    if match:
                        type_str = match.group(1).lower()
                        logger.info(f"Detected repo type from STRUCTURE.md: {type_str}")
                        if type_str == "backend":
                            return RepoType.BACKEND
                        if type_str == "frontend":
                            return RepoType.FRONTEND
                        if type_str == "fullstack":
                            return RepoType.FULLSTACK

        # Priority 2: File pattern detection (fallback)
        if files:
            detected = self.repo_detector.detect(files)
            logger.info(f"Detected repo type from file patterns: {detected.value}")
            return detected

        logger.warning(
            "No repo type found in structure docs. "
            "Run structure generator to create structure.xml."
        )
        return RepoType.UNKNOWN

    def _get_reviewers(self, repo_type: RepoType, include_functional: bool) -> list[str]:
        """Get list of reviewers to run based on repo type.

        Returns up to 5 specialized reviewers:
        - reviewer_be_architecture: Backend architecture (SOLID, layers, coupling)
        - reviewer_be_quality: Backend quality (linting, security, performance)
        - reviewer_fe_architecture: Frontend architecture (React patterns, state)
        - reviewer_fe_quality: Frontend quality (type safety, performance)
        - analyst_func: Functional analysis (business logic, requirements)
        """
        reviewers = []

        if repo_type in [RepoType.BACKEND, RepoType.FULLSTACK, RepoType.UNKNOWN]:
            reviewers.append("reviewer_be_architecture")
            reviewers.append("reviewer_be_quality")

        if repo_type in [RepoType.FRONTEND, RepoType.FULLSTACK]:
            reviewers.append("reviewer_fe_architecture")
            reviewers.append("reviewer_fe_quality")

        if include_functional:
            reviewers.append("analyst_func")

        return reviewers

    async def _run_triple_llm_review(
        self,
        context: ReviewContext,
        reviewer_name: str,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
    ) -> TripleLLMResult:
        """
        Run triple-LLM review (Claude + Gemini + Grok in parallel).

        Uses TripleLLMRunner to execute all three LLMs and merge results.

        Args:
            context: Review context with repo path and metadata
            reviewer_name: Name of the reviewer (e.g., reviewer_be_architecture)
            emit: Optional callback for progress events

        Returns:
            TripleLLMResult with merged issues and per-LLM stats
        """
        from turbowrap.review.reviewers.claude_cli_reviewer import ClaudeCLIReviewer
        from turbowrap.review.reviewers.gemini_cli_reviewer import GeminiCLIReviewer
        from turbowrap.review.reviewers.grok_cli_reviewer import GrokCLIReviewer

        claude_reviewer = ClaudeCLIReviewer(name=reviewer_name)
        gemini_reviewer = GeminiCLIReviewer(name=reviewer_name)
        grok_reviewer = GrokCLIReviewer(name=reviewer_name)

        # Load agent prompt (must exist)
        context.agent_prompt = claude_reviewer.load_agent_prompt(self.settings.agents_dir)

        # NOTE: Use base reviewer_name so content goes to the right card
        display_name = get_reviewer_display_name(reviewer_name)

        async def on_claude_chunk(chunk: str) -> None:
            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.REVIEWER_STREAMING,
                        reviewer_name=reviewer_name,
                        reviewer_display_name=display_name,
                        content=chunk,
                    )
                )

        async def on_gemini_chunk(chunk: str) -> None:
            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.REVIEWER_STREAMING,
                        reviewer_name=reviewer_name,
                        reviewer_display_name=display_name,
                        content=chunk,
                    )
                )

        async def on_grok_chunk(chunk: str) -> None:
            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.REVIEWER_STREAMING,
                        reviewer_name=reviewer_name,
                        reviewer_display_name=display_name,
                        content=chunk,
                    )
                )

        runner = TripleLLMRunner(
            claude_reviewer=claude_reviewer,
            gemini_reviewer=gemini_reviewer,
            grok_reviewer=grok_reviewer,
        )

        return await runner.run(
            context=context,
            file_list=context.files,
            on_claude_chunk=on_claude_chunk,
            on_gemini_chunk=on_gemini_chunk,
            on_grok_chunk=on_grok_chunk,
        )

    # NOTE: _deduplicate_issues, _severity_rank, _prioritize_issues moved to

    async def _run_evaluator(
        self,
        context: ReviewContext,
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
        review_id: str | None = None,
    ) -> tuple[RepositoryEvaluation | None, str | None]:
        """
        Run the final repository evaluator.

        Args:
            context: Review context with structure docs
            issues: All deduplicated/prioritized issues
            reviewer_results: Results from each reviewer
            repo_info: Repository metadata
            emit: Optional callback for progress events
            review_id: Review ID for S3 logging

        Returns:
            Tuple of (RepositoryEvaluation or None, error message or None)
        """
        try:
            evaluator = ClaudeEvaluator()

            async def on_chunk(chunk: str) -> None:
                if emit:
                    await emit(
                        ProgressEvent(
                            type=ProgressEventType.REVIEWER_STREAMING,
                            reviewer_name="evaluator",
                            reviewer_display_name="Repository Evaluator",
                            content=chunk,
                        )
                    )

            evaluation = await evaluator.evaluate(
                structure_docs=context.structure_docs,
                issues=issues,
                reviewer_results=reviewer_results,
                repo_info=repo_info,
                repo_path=context.repo_path,
                on_chunk=on_chunk,
                review_id=review_id,
            )

            if evaluation:
                logger.info(
                    f"Evaluation complete: overall={evaluation.overall_score}, "
                    f"arch={evaluation.architecture_quality}, "
                    f"code={evaluation.code_quality}"
                )
                return evaluation, None

            return None, "Evaluator returned empty response"

        except Exception as e:
            logger.exception(f"Evaluator failed: {e}")
            return None, str(e)

    def _build_report(
        self,
        report_id: str,
        request: ReviewRequest,
        context: ReviewContext,
        repo_type: RepoType,
        reviewer_results: list[ReviewerResult],
        issues: list[Issue],
        evaluation: RepositoryEvaluation | None = None,
    ) -> FinalReport:
        """Build the final report."""
        severity_counts = count_by_severity(issues)

        score = calculate_overall_score(issues)

        recommendation = calculate_recommendation(severity_counts)

        # ChallengerLoop deprecated - always disabled
        challenger_metadata = ChallengerMetadata(enabled=False)

        # Build next steps (using shared utility)
        next_steps = build_next_steps(issues)

        repo_info = RepositoryInfo(
            type=repo_type,
            name=context.repo_name,
            branch=context.current_branch,
            commit_sha=context.commit_sha,
        )

        summary = ReportSummary(
            repo_type=repo_type,
            files_reviewed=len(context.files),
            total_issues=len(issues),
            by_severity=severity_counts,
            overall_score=score,
            recommendation=recommendation,
        )

        return FinalReport(
            id=report_id,
            timestamp=datetime.utcnow(),
            version="1.0.0",
            repository=repo_info,
            summary=summary,
            reviewers=reviewer_results,
            challenger=challenger_metadata,
            issues=issues,
            next_steps=next_steps,
            evaluation=evaluation,
        )

    # NOTE: _build_next_steps moved to turbowrap.orchestration.report_utils

    async def _refresh_stale_structures(
        self,
        context: ReviewContext,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
    ) -> None:
        """
        Check and regenerate stale STRUCTURE.md files.

        A STRUCTURE.md is stale if:
        1. Any code file in its directory has been modified after the "Generated At" timestamp
        2. Git shows the directory has commits newer than the STRUCTURE.md

        Args:
            context: Review context with repo_path set
            emit: Optional callback for progress events
        """
        import re

        if not context.repo_path or not context.repo_path.exists():
            return

        if context.workspace_path:
            search_base = context.repo_path / context.workspace_path
            if not search_base.exists():
                logger.warning(f"Workspace path does not exist for stale check: {search_base}")
                return
        else:
            search_base = context.repo_path

        stale_dirs: list[Path] = []

        for structure_file in search_base.rglob("STRUCTURE.md"):
            rel_path = structure_file.relative_to(context.repo_path)
            if any(
                part.startswith(".")
                or part in {"node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
                for part in rel_path.parts
            ):
                continue

            try:
                content = structure_file.read_text()
            except Exception:
                continue

            # Extract timestamp from STRUCTURE.md footer
            match = re.search(r"\|\s*ts:(\d+)", content)
            if not match:
                structure_mtime = structure_file.stat().st_mtime
                file_age_hours = (time.time() - structure_mtime) / 3600
                if file_age_hours > 24:
                    stale_dirs.append(structure_file.parent)
                continue

            generated_at = int(match.group(1))
            parent_dir = structure_file.parent

            # Check if any code file was modified after the generation timestamp
            is_stale = False
            for code_file in parent_dir.iterdir():
                if not code_file.is_file():
                    continue

                suffix = code_file.suffix.lower()
                if suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                    continue

                file_mtime = int(code_file.stat().st_mtime)
                if file_mtime > generated_at + 10:
                    is_stale = True
                    logger.info(
                        f"STRUCTURE.md stale: {code_file.name} modified after generation "
                        f"(file: {file_mtime}, gen: {generated_at})"
                    )
                    break

            if is_stale:
                try:
                    rel_path = parent_dir.relative_to(context.repo_path)
                    stale_dirs.append(rel_path if str(rel_path) != "." else Path("."))
                except ValueError:
                    stale_dirs.append(Path("."))

        if not stale_dirs:
            logger.info("All STRUCTURE.md files are up to date")
            return

        logger.info(f"Found {len(stale_dirs)} stale STRUCTURE.md files to regenerate")

        if emit:
            await emit(
                ProgressEvent(
                    type=ProgressEventType.STRUCTURE_GENERATION_STARTED,
                    message=f"Regenerating {len(stale_dirs)} stale STRUCTURE.md files...",
                )
            )

        try:
            assert context.repo_path is not None
            generator = StructureGenerator(
                context.repo_path,
                gemini_client=None,  # Quick mode without Gemini for refresh
            )

            loop = asyncio.get_event_loop()
            regenerated = await loop.run_in_executor(
                None, lambda: generator.regenerate_stale(verbose=True)
            )

            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.STRUCTURE_GENERATION_COMPLETED,
                        message=f"Regenerated {len(regenerated)} STRUCTURE.md files",
                    )
                )

            logger.info(f"Regenerated {len(regenerated)} STRUCTURE.md files")

        except Exception as e:
            logger.error(f"Failed to regenerate STRUCTURE.md files: {e}")
            if emit:
                await emit(
                    ProgressEvent(
                        type=ProgressEventType.REVIEW_ERROR,
                        error=f"Structure refresh failed: {str(e)}",
                    )
                )
