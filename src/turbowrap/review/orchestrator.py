"""
Main orchestrator for TurboWrap code review system.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from turbowrap.config import get_settings
from turbowrap.llm import GeminiClient
from turbowrap.review.challenger_loop import ChallengerLoop, ChallengerLoopResult
from turbowrap.review.models.evaluation import RepositoryEvaluation
from turbowrap.review.models.progress import (
    ProgressEvent,
    ProgressEventType,
    get_reviewer_display_name,
)
from turbowrap.review.models.report import (
    ChallengerMetadata,
    FinalReport,
    NextStep,
    Recommendation,
    ReportSummary,
    RepositoryInfo,
    RepoType,
    ReviewerResult,
    SeveritySummary,
)
from turbowrap.review.models.review import (
    Issue,
    IssueSeverity,
    ReviewMode,
    ReviewOutput,
    ReviewRequest,
)

# Type alias for checkpoint data (reviewer_name -> checkpoint dict)
CheckpointData = dict[str, dict]
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.reviewers.claude_evaluator import ClaudeEvaluator
from turbowrap.review.utils.file_utils import FileUtils
from turbowrap.review.utils.git_utils import GitUtils
from turbowrap.review.utils.repo_detector import RepoDetector
from turbowrap.tools.structure_generator import StructureGenerator

logger = logging.getLogger(__name__)

# Type alias for progress callback
ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]

# Type alias for checkpoint callback
# Args: reviewer_name, status, issues, satisfaction, iterations, model_usage, started_at
CheckpointCallback = Callable[
    [str, str, list, float, int, list[dict], datetime],
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

    def __init__(self):
        """
        Initialize the orchestrator.
        """
        self.settings = get_settings()
        self.repo_detector = RepoDetector()

    async def review(
        self,
        request: ReviewRequest,
        progress_callback: ProgressCallback | None = None,
        completed_checkpoints: CheckpointData | None = None,
        checkpoint_callback: CheckpointCallback | None = None,
    ) -> FinalReport:
        """
        Perform a complete code review.

        Args:
            request: Review request with source and options
            progress_callback: Optional async callback for progress events
            completed_checkpoints: Dict of already completed reviewers (for resume).
                Keys are reviewer names, values are checkpoint dicts with:
                - issues_data: list of issue dicts
                - final_satisfaction: float
                - iterations: int
            checkpoint_callback: Optional callback to save checkpoint after each reviewer

        Returns:
            FinalReport with all findings
        """
        datetime.utcnow()
        report_id = f"rev_{uuid.uuid4().hex[:12]}"

        logger.info(f"Starting review {report_id}")

        # Helper to emit events
        async def emit(event: ProgressEvent):
            if progress_callback:
                event.review_id = report_id
                await progress_callback(event)

        # Helper to emit toast log notifications
        async def emit_log(level: str, message: str):
            """Emit a log event for UI toast notifications."""
            await emit(ProgressEvent(
                type=ProgressEventType.REVIEW_LOG,
                message=message,
                log_level=level,
            ))

        # Emit review started
        await emit(ProgressEvent(
            type=ProgressEventType.REVIEW_STARTED,
            review_id=report_id,
            message="Starting code review...",
        ))

        # Step 1: Prepare context (may auto-generate STRUCTURE.md)
        context = await self._prepare_context(request, emit, report_id)

        # Step 2: Detect repository type
        repo_type = self._detect_repo_type(context.files, context.structure_docs)
        logger.info(f"Detected repository type: {repo_type.value}")

        # Step 3: Determine which reviewers to run
        reviewers = self._get_reviewers(repo_type, request.options.include_functional)
        logger.info(f"Running reviewers: {reviewers}")

        # Step 4: Run challenger loops for each reviewer IN PARALLEL
        reviewer_results: list[ReviewerResult] = []
        all_issues: list[Issue] = []
        loop_results: list[ChallengerLoopResult] = []

        # Checkpoint data for resume (default to empty)
        checkpoints = completed_checkpoints or {}

        if request.options.challenger_enabled:
            # Run all reviewers in PARALLEL with progress callbacks
            async def run_reviewer_with_progress(reviewer_name: str):
                """Run a single reviewer with progress events."""
                display_name = get_reviewer_display_name(reviewer_name)

                # CHECK FOR CHECKPOINT: Skip if already completed
                if reviewer_name in checkpoints:
                    checkpoint = checkpoints[reviewer_name]
                    issues_count = len(checkpoint.get("issues_data", []))
                    satisfaction = checkpoint.get("final_satisfaction", 0.0)
                    iterations = checkpoint.get("iterations", 1)

                    logger.info(f"Skipping {reviewer_name} - restored from checkpoint")

                    await emit(ProgressEvent(
                        type=ProgressEventType.REVIEWER_COMPLETED,
                        reviewer_name=reviewer_name,
                        reviewer_display_name=display_name,
                        iteration=iterations,
                        satisfaction_score=satisfaction,
                        issues_found=issues_count,
                        message=f"⚡ {display_name} restored from checkpoint ({issues_count} issues)",
                    ))

                    await emit_log(
                        "INFO",
                        f"⚡ {display_name}: restored from checkpoint ({issues_count} issues)"
                    )

                    return (reviewer_name, "checkpoint", checkpoint)

                await emit(ProgressEvent(
                    type=ProgressEventType.REVIEWER_STARTED,
                    reviewer_name=reviewer_name,
                    reviewer_display_name=display_name,
                    message=f"Starting {display_name}...",
                ))

                started_at = datetime.utcnow()

                try:
                    result = await self._run_challenger_loop_with_progress(
                        context,
                        reviewer_name,
                        emit,
                    )

                    await emit(ProgressEvent(
                        type=ProgressEventType.REVIEWER_COMPLETED,
                        reviewer_name=reviewer_name,
                        reviewer_display_name=display_name,
                        iteration=result.iterations,
                        satisfaction_score=result.final_satisfaction,
                        issues_found=len(result.final_review.issues),
                        message=f"{display_name} completed with {len(result.final_review.issues)} issues",
                        model_usage=[m.model_dump() for m in result.final_review.model_usage],
                    ))

                    # Toast notification for completed reviewer
                    await emit_log(
                        "INFO",
                        f"✓ {display_name}: {result.final_satisfaction:.0f}% ({result.iterations} iter, {len(result.final_review.issues)} issues)"
                    )

                    # SAVE CHECKPOINT on success
                    if checkpoint_callback:
                        await checkpoint_callback(
                            reviewer_name,
                            "completed",
                            result.final_review.issues,
                            result.final_satisfaction,
                            result.iterations,
                            [m.model_dump() for m in result.final_review.model_usage],
                            started_at,
                        )

                    return (reviewer_name, "success", result)

                except Exception as e:
                    logger.error(f"Reviewer {reviewer_name} failed: {e}")

                    await emit(ProgressEvent(
                        type=ProgressEventType.REVIEWER_ERROR,
                        reviewer_name=reviewer_name,
                        reviewer_display_name=display_name,
                        error=str(e),
                        message=f"{display_name} failed: {str(e)[:50]}",
                    ))

                    # Toast notification for failed reviewer
                    await emit_log("ERROR", f"✗ {display_name}: {str(e)[:60]}")

                    # SAVE FAILED CHECKPOINT (so we know to retry this one)
                    if checkpoint_callback:
                        await checkpoint_callback(
                            reviewer_name,
                            "failed",
                            [],  # No issues on failure
                            0.0,
                            0,
                            [],
                            started_at,
                        )

                    return (reviewer_name, "error", str(e))

            # Execute all reviewers in parallel
            tasks = [run_reviewer_with_progress(name) for name in reviewers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    continue

                reviewer_name, status, data = result

                if status == "checkpoint":
                    # Restore from checkpoint
                    checkpoint = data
                    issues_data = checkpoint.get("issues_data", [])
                    # Convert issue dicts back to Issue objects
                    restored_issues = [
                        Issue.model_validate(issue_dict) for issue_dict in issues_data
                    ]
                    all_issues.extend(restored_issues)

                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="completed",  # From user perspective, it's completed
                        issues_found=len(restored_issues),
                        iterations=checkpoint.get("iterations", 1),
                        final_satisfaction=checkpoint.get("final_satisfaction", 0.0),
                    ))

                elif status == "success":
                    loop_result = data
                    loop_results.append(loop_result)

                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="completed",
                        issues_found=len(loop_result.final_review.issues),
                        duration_seconds=loop_result.final_review.duration_seconds,
                        iterations=loop_result.iterations,
                        final_satisfaction=loop_result.final_satisfaction,
                    ))

                    all_issues.extend(loop_result.final_review.issues)
                else:
                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="error",
                        error=data,
                    ))

        else:
            # Run without challenger pattern (simple mode) - still parallel
            async def run_simple_with_progress(reviewer_name: str):
                display_name = get_reviewer_display_name(reviewer_name)

                await emit(ProgressEvent(
                    type=ProgressEventType.REVIEWER_STARTED,
                    reviewer_name=reviewer_name,
                    reviewer_display_name=display_name,
                ))

                try:
                    result = await self._run_simple_review(context, reviewer_name)

                    await emit(ProgressEvent(
                        type=ProgressEventType.REVIEWER_COMPLETED,
                        reviewer_name=reviewer_name,
                        reviewer_display_name=display_name,
                        issues_found=len(result.issues),
                        model_usage=[m.model_dump() for m in result.model_usage],
                    ))

                    return (reviewer_name, "success", result)

                except Exception as e:
                    await emit(ProgressEvent(
                        type=ProgressEventType.REVIEWER_ERROR,
                        reviewer_name=reviewer_name,
                        error=str(e),
                    ))
                    return (reviewer_name, "error", str(e))

            tasks = [run_simple_with_progress(name) for name in reviewers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    continue

                reviewer_name, status, data = result

                if status == "success":
                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="completed",
                        issues_found=len(data.issues),
                        duration_seconds=data.duration_seconds,
                        iterations=1,
                    ))
                    all_issues.extend(data.issues)
                else:
                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="error",
                        error=data,
                    ))

        # Step 5: Deduplicate and prioritize issues
        deduplicated_issues = self._deduplicate_issues(all_issues)
        prioritized_issues = self._prioritize_issues(deduplicated_issues)

        # Step 5.5: Run final evaluator (Claude Opus)
        repo_info = RepositoryInfo(
            type=repo_type,
            name=context.repo_name,
            branch=context.current_branch,
            commit_sha=context.commit_sha,
        )

        await emit(ProgressEvent(
            type=ProgressEventType.REVIEWER_STARTED,
            reviewer_name="evaluator",
            reviewer_display_name="Repository Evaluator",
            message="Running final evaluation...",
        ))

        evaluation = await self._run_evaluator(
            context=context,
            issues=prioritized_issues,
            reviewer_results=reviewer_results,
            repo_info=repo_info,
            emit=emit,
            review_id=report_id,
        )

        if evaluation:
            await emit(ProgressEvent(
                type=ProgressEventType.REVIEWER_COMPLETED,
                reviewer_name="evaluator",
                reviewer_display_name="Repository Evaluator",
                message=f"Evaluation complete: {evaluation.overall_score}/100",
            ))
            await emit_log("INFO", f"✓ Evaluation: {evaluation.overall_score}/100")
        else:
            await emit(ProgressEvent(
                type=ProgressEventType.REVIEWER_ERROR,
                reviewer_name="evaluator",
                reviewer_display_name="Repository Evaluator",
                error="Evaluation failed",
            ))
            await emit_log("WARNING", "⚠ Evaluation skipped")

        # Step 6: Build final report
        report = self._build_report(
            report_id=report_id,
            request=request,
            context=context,
            repo_type=repo_type,
            reviewer_results=reviewer_results,
            issues=prioritized_issues,
            loop_results=loop_results,
            evaluation=evaluation,
        )

        logger.info(
            f"Review {report_id} completed: "
            f"{report.summary.total_issues} issues, "
            f"score={report.summary.overall_score:.1f}, "
            f"recommendation={report.summary.recommendation.value}"
        )

        # Emit review completed
        await emit(ProgressEvent(
            type=ProgressEventType.REVIEW_COMPLETED,
            review_id=report_id,
            issues_found=report.summary.total_issues,
            message=f"Review completed with {report.summary.total_issues} issues (score: {report.summary.overall_score:.1f})",
        ))

        # Final toast notification
        await emit_log(
            "INFO",
            f"🎉 Review completata: {report.summary.total_issues} issues, score {report.summary.overall_score:.1f}/10"
        )

        # Save report to output directory
        await self._save_report(report, context.repo_path)

        return report

    async def _prepare_context(
        self,
        request: ReviewRequest,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
        report_id: str | None = None,
    ) -> ReviewContext:
        """Prepare the review context from the request.

        Args:
            request: Review request
            emit: Optional callback for progress events
            report_id: Review ID for logging

        Returns:
            ReviewContext with loaded files/structure docs
        """
        context = ReviewContext(request=request)
        if report_id:
            context.metadata["review_id"] = report_id
        source = request.source
        mode = request.options.mode

        # Set repo_path first (needed for all modes)
        if source.directory:
            context.repo_path = Path(source.directory)
        elif source.pr_url or source.commit_sha or source.files:
            context.repo_path = Path(source.directory or Path.cwd())
        else:
            context.repo_path = Path.cwd()

        # Set workspace_path for monorepo scope limiting
        if source.workspace_path:
            context.workspace_path = source.workspace_path
            logger.info(f"Monorepo mode: limiting review to workspace '{source.workspace_path}'")

        # Load .llms/structure.xml (used in all modes for context)
        self._load_structure_docs(context)

        # AUTO-GENERATE .llms/structure.xml if missing (for all modes)
        if not context.structure_docs:
            logger.info("No .llms/structure.xml found - auto-generating with Gemini Flash...")
            await self._auto_generate_structure(context, emit)
            # Reload after generation
            self._load_structure_docs(context)

            if not context.structure_docs:
                logger.warning("Structure generation completed but .llms/structure.xml not found!")

        # INITIAL mode: Use structure docs + file list (no file contents)
        if mode == ReviewMode.INITIAL:
            logger.info("INITIAL mode: Reviewing architecture via .llms/structure.xml only")
            # Scan files for reference (challenger needs file list)
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
            # No file contents loaded - reviewers use only structure docs

        # DIFF mode: Load only changed/specified files
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
                # Use workspace subfolder if set (monorepo support)
                if context.workspace_path:
                    scan_base = context.repo_path / context.workspace_path
                    if not scan_base.exists():
                        logger.warning(f"Workspace path does not exist: {scan_base}")
                        context.files = self._scan_directory(context.repo_path)
                    else:
                        # Scan workspace and prefix paths so they're relative to repo root
                        workspace_files = self._scan_directory(scan_base)
                        context.files = [
                            f"{context.workspace_path}/{f}" for f in workspace_files
                        ]
                else:
                    context.files = self._scan_directory(context.repo_path)

            # Load file contents for diff mode
            await self._load_file_contents(context)

        # Get git info
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

        # Assume we're in the repo directory
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
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
            "coverage", ".tox", "htmlcov", ".reviews",
        }
        # Exclude previous review output files
        exclude_patterns = {".turbowrap_review"}

        for path in directory.rglob("*"):
            if path.is_file():
                rel_path = path.relative_to(directory)
                # Check if any parent is in exclude list (use relative path, not absolute)
                if any(part in exclude_dirs for part in rel_path.parts):
                    continue
                # Skip review output files
                if any(pattern in path.name for pattern in exclude_patterns):
                    continue

                if FileUtils.is_text_file(path):
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

        # For monorepo: load from workspace/.llms/structure.xml
        if context.workspace_path:
            xml_path = context.repo_path / context.workspace_path / ".llms" / "structure.xml"
        else:
            xml_path = context.repo_path / ".llms" / "structure.xml"

        if xml_path.exists():
            try:
                content = xml_path.read_text(encoding="utf-8")
                context.structure_docs["structure.xml"] = content
                logger.info(f"Loaded {xml_path.relative_to(context.repo_path)} ({xml_path.stat().st_size:,} bytes)")
            except Exception as e:
                logger.warning(f"Failed to read {xml_path}: {e}")
        else:
            logger.info(f"No {xml_path.relative_to(context.repo_path)} found - structure docs not available")

    async def _auto_generate_structure(
        self,
        context: ReviewContext,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
    ) -> None:
        """
        Auto-generate structure documentation using Gemini Flash.

        Generates only .llms/structure.xml (optimized for LLM).
        Called when no structure docs exist.

        Args:
            context: Review context with repo_path set
            emit: Optional callback for progress events
        """
        if not context.repo_path:
            logger.error("Cannot generate structure: no repo_path set")
            return

        # For monorepo: generate structure.xml only for the workspace
        if context.workspace_path:
            target_dir = context.repo_path / context.workspace_path
            display_name = context.workspace_path
        else:
            target_dir = context.repo_path
            display_name = context.repo_path.name

        # Emit start event
        if emit:
            await emit(ProgressEvent(
                type=ProgressEventType.STRUCTURE_GENERATION_STARTED,
                message=f"Generating structure documentation for {display_name}...",
            ))

        try:
            # Create generator with GeminiClient for semantic analysis
            # Pass workspace_path for monorepo support
            generator = StructureGenerator(
                str(context.repo_path),
                workspace_path=context.workspace_path,
                gemini_client=GeminiClient(),
            )

            # Emit progress update
            if emit:
                await emit(ProgressEvent(
                    type=ProgressEventType.STRUCTURE_GENERATION_PROGRESS,
                    message="Analyzing repository structure with Gemini Flash...",
                ))

            # Run generation (sync method, run in executor)
            # Only generate XML format (.llms/structure.xml)
            loop = asyncio.get_event_loop()
            generated_files = await loop.run_in_executor(
                None,
                lambda: generator.generate(verbose=True, formats=["xml"])
            )

            # Emit completion
            if emit:
                await emit(ProgressEvent(
                    type=ProgressEventType.STRUCTURE_GENERATION_COMPLETED,
                    message=f"Generated {len(generated_files)} structure file(s)",
                ))

            logger.info(f"Auto-generated {len(generated_files)} structure files")

        except Exception as e:
            logger.error(f"Failed to auto-generate structure: {e}")
            if emit:
                await emit(ProgressEvent(
                    type=ProgressEventType.REVIEW_ERROR,
                    error=f"Structure generation failed: {str(e)}",
                    message="Failed to generate structure docs - proceeding without them",
                ))

    async def _load_file_contents(self, context: ReviewContext) -> None:
        """Load content of files in context."""
        for file_path in context.files:
            try:
                full_path = context.repo_path / file_path if context.repo_path else Path(file_path)
                if full_path.exists() and FileUtils.is_text_file(full_path):
                    content = FileUtils.read_file(full_path)
                    # Limit file size
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
        Detect repository type from files or STRUCTURE.md.

        For INITIAL mode (no files), parses repo type from root STRUCTURE.md.
        For DIFF mode, uses file extensions.

        Args:
            files: List of file paths to analyze
            structure_docs: STRUCTURE.md contents for fallback detection

        Returns:
            RepoType enum value
        """
        # If we have files, use file-based detection
        if files:
            return self.repo_detector.detect(files)

        # In INITIAL mode, try to extract from STRUCTURE.md
        if structure_docs:
            # Look for root STRUCTURE.md (the one with Metadata section)
            for _path, content in structure_docs.items():
                if "## Metadata" in content and "Repository Type" in content:
                    # Parse repo type from: **Repository Type**: `BACKEND`
                    import re
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

            logger.warning(
                "No repo type found in STRUCTURE.md. "
                "Run `python -m turbowrap.tools.structure_generator` to generate updated docs."
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
            # For UNKNOWN, assume backend as default since most repos have backend code
            reviewers.append("reviewer_be_architecture")
            reviewers.append("reviewer_be_quality")

        if repo_type in [RepoType.FRONTEND, RepoType.FULLSTACK]:
            reviewers.append("reviewer_fe_architecture")
            reviewers.append("reviewer_fe_quality")

        # ALWAYS launch analyst_func - business logic is critical
        if include_functional:
            reviewers.append("analyst_func")

        return reviewers

    async def _run_challenger_loop(
        self,
        context: ReviewContext,
        reviewer_name: str,
    ) -> ChallengerLoopResult:
        """Run the challenger loop for a reviewer."""
        loop = ChallengerLoop()
        return await loop.run(context, reviewer_name)

    async def _run_challenger_loop_with_progress(
        self,
        context: ReviewContext,
        reviewer_name: str,
        emit: Callable[[ProgressEvent], Awaitable[None]],
    ) -> ChallengerLoopResult:
        """Run the challenger loop with progress updates."""
        display_name = get_reviewer_display_name(reviewer_name)

        # Create iteration callback
        async def on_iteration(iteration: int, satisfaction: float, issues_count: int):
            await emit(ProgressEvent(
                type=ProgressEventType.REVIEWER_ITERATION,
                reviewer_name=reviewer_name,
                reviewer_display_name=display_name,
                iteration=iteration,
                max_iterations=5,
                satisfaction_score=satisfaction,
                issues_found=issues_count,
                message=f"Iteration {iteration}: {satisfaction:.1f}% satisfaction",
            ))

        # Create streaming callback for token-by-token updates
        async def on_content(content: str):
            await emit(ProgressEvent(
                type=ProgressEventType.REVIEWER_STREAMING,
                reviewer_name=reviewer_name,
                reviewer_display_name=display_name,
                content=content,
            ))

        loop = ChallengerLoop()
        return await loop.run(
            context,
            reviewer_name,
            on_iteration_callback=on_iteration,
            on_content_callback=on_content,
        )

    async def _run_simple_review(
        self,
        context: ReviewContext,
        reviewer_name: str,
    ) -> ReviewOutput:
        """Run a simple review without challenger pattern."""
        from turbowrap.review.reviewers.claude_cli_reviewer import ClaudeCLIReviewer

        reviewer = ClaudeCLIReviewer(name=reviewer_name)

        with contextlib.suppress(FileNotFoundError):
            context.agent_prompt = reviewer.load_agent_prompt(
                self.settings.agents_dir
            )

        # CLI reviewer receives file list and explores autonomously
        return await reviewer.review(context, context.files)

    def _deduplicate_issues(self, issues: list[Issue]) -> list[Issue]:
        """Deduplicate issues from multiple reviewers."""
        unique: dict[tuple, Issue] = {}

        for issue in issues:
            key = (issue.file, issue.line, issue.category)

            if key in unique:
                existing = unique[key]
                # Keep highest severity
                if self._severity_rank(issue.severity) > self._severity_rank(existing.severity):
                    existing.severity = issue.severity
                # Merge flagged_by
                for reviewer in issue.flagged_by:
                    if reviewer not in existing.flagged_by:
                        existing.flagged_by.append(reviewer)
            else:
                unique[key] = issue

        return list(unique.values())

    def _severity_rank(self, severity: IssueSeverity) -> int:
        """Get numeric rank for severity."""
        ranks = {
            IssueSeverity.CRITICAL: 4,
            IssueSeverity.HIGH: 3,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 1,
        }
        return ranks.get(severity, 0)

    def _prioritize_issues(self, issues: list[Issue]) -> list[Issue]:
        """Sort issues by priority score."""
        def priority_score(issue: Issue) -> float:
            severity_scores = {
                IssueSeverity.CRITICAL: 100,
                IssueSeverity.HIGH: 75,
                IssueSeverity.MEDIUM: 50,
                IssueSeverity.LOW: 25,
            }
            category_multipliers = {
                "security": 1.5,
                "logic": 1.3,
                "performance": 1.1,
                "architecture": 1.0,
                "ux": 0.9,
                "style": 0.8,
                "testing": 0.9,
                "documentation": 0.7,
            }

            base = severity_scores.get(issue.severity, 50)
            multiplier = category_multipliers.get(issue.category.value, 1.0)
            reviewer_bonus = len(issue.flagged_by) * 5

            return min(100, base * multiplier + reviewer_bonus)

        return sorted(issues, key=priority_score, reverse=True)

    async def _run_evaluator(
        self,
        context: ReviewContext,
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
        emit: Callable[[ProgressEvent], Awaitable[None]] | None = None,
        review_id: str | None = None,
    ) -> RepositoryEvaluation | None:
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
            RepositoryEvaluation with 6 scores, or None if failed
        """
        try:
            evaluator = ClaudeEvaluator()

            # Create streaming callback
            async def on_chunk(chunk: str) -> None:
                if emit:
                    await emit(ProgressEvent(
                        type=ProgressEventType.REVIEWER_STREAMING,
                        reviewer_name="evaluator",
                        reviewer_display_name="Repository Evaluator",
                        content=chunk,
                    ))

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

            return evaluation

        except Exception as e:
            logger.error(f"Evaluator failed: {e}")
            return None

    def _build_report(
        self,
        report_id: str,
        request: ReviewRequest,
        context: ReviewContext,
        repo_type: RepoType,
        reviewer_results: list[ReviewerResult],
        issues: list[Issue],
        loop_results: list[ChallengerLoopResult],
        evaluation: RepositoryEvaluation | None = None,
    ) -> FinalReport:
        """Build the final report."""
        # Count by severity
        severity_counts = SeveritySummary(
            critical=sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL),
            high=sum(1 for i in issues if i.severity == IssueSeverity.HIGH),
            medium=sum(1 for i in issues if i.severity == IssueSeverity.MEDIUM),
            low=sum(1 for i in issues if i.severity == IssueSeverity.LOW),
        )

        # Calculate score
        score = self._calculate_score(issues)

        # Determine recommendation
        recommendation = self._calculate_recommendation(severity_counts)

        # Build challenger metadata
        challenger_metadata = self._build_challenger_metadata(loop_results)

        # Build next steps
        next_steps = self._build_next_steps(issues)

        # Repository info
        repo_info = RepositoryInfo(
            type=repo_type,
            name=context.repo_name,
            branch=context.current_branch,
            commit_sha=context.commit_sha,
        )

        # Summary
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
            repository=repo_info,
            summary=summary,
            reviewers=reviewer_results,
            challenger=challenger_metadata,
            issues=issues,
            next_steps=next_steps,
            evaluation=evaluation,
        )

    def _calculate_score(self, issues: list[Issue]) -> float:
        """Calculate overall score based on issues."""
        if not issues:
            return 10.0

        # Deductions per severity
        deductions = {
            IssueSeverity.CRITICAL: 2.0,
            IssueSeverity.HIGH: 1.0,
            IssueSeverity.MEDIUM: 0.3,
            IssueSeverity.LOW: 0.1,
        }

        total_deduction = sum(
            deductions.get(issue.severity, 0.1) for issue in issues
        )

        return max(0.0, round(10.0 - total_deduction, 1))

    def _calculate_recommendation(self, severity: SeveritySummary) -> Recommendation:
        """Calculate recommendation based on severity counts."""
        if severity.critical >= 1:
            return Recommendation.REQUEST_CHANGES
        if severity.high > 3:
            return Recommendation.REQUEST_CHANGES
        if severity.high > 0:
            return Recommendation.APPROVE_WITH_CHANGES
        return Recommendation.APPROVE

    def _build_challenger_metadata(
        self,
        loop_results: list[ChallengerLoopResult],
    ) -> ChallengerMetadata:
        """Build challenger metadata from loop results."""
        if not loop_results:
            return ChallengerMetadata(enabled=False)

        # Aggregate from all loops
        total_iterations = sum(r.iterations for r in loop_results)
        avg_satisfaction = sum(r.final_satisfaction for r in loop_results) / len(loop_results)

        # Combine iteration history
        all_history = []
        all_insights = []
        for result in loop_results:
            all_history.extend(result.iteration_history)
            all_insights.extend(result.insights)

        # Use worst convergence status
        convergence = loop_results[0].convergence
        for result in loop_results[1:]:
            if result.convergence.value != "THRESHOLD_MET":
                convergence = result.convergence

        return ChallengerMetadata(
            enabled=True,
            total_iterations=total_iterations,
            final_satisfaction_score=avg_satisfaction,
            threshold=50.0,
            convergence=convergence,
            iteration_history=all_history,
            insights=all_insights,
        )

    def _build_next_steps(self, issues: list[Issue]) -> list[NextStep]:
        """Build prioritized next steps."""
        steps = []

        critical_issues = [i for i in issues if i.severity == IssueSeverity.CRITICAL]
        if critical_issues:
            steps.append(NextStep(
                priority=1,
                action=f"Fix {len(critical_issues)} critical security/logic issues",
                issues=[i.id for i in critical_issues],
            ))

        high_issues = [i for i in issues if i.severity == IssueSeverity.HIGH]
        if high_issues:
            steps.append(NextStep(
                priority=2,
                action=f"Address {len(high_issues)} high priority issues",
                issues=[i.id for i in high_issues],
            ))

        medium_issues = [i for i in issues if i.severity == IssueSeverity.MEDIUM]
        if medium_issues:
            steps.append(NextStep(
                priority=3,
                action=f"Consider {len(medium_issues)} medium priority suggestions",
                issues=[i.id for i in medium_issues[:5]],  # Limit
            ))

        return steps

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

        # Determine search base: workspace subfolder or full repo
        if context.workspace_path:
            search_base = context.repo_path / context.workspace_path
            if not search_base.exists():
                logger.warning(f"Workspace path does not exist for stale check: {search_base}")
                return
        else:
            search_base = context.repo_path

        stale_dirs: list[Path] = []

        # Find all STRUCTURE.md files within search base
        for structure_file in search_base.rglob("STRUCTURE.md"):
            rel_path = structure_file.relative_to(context.repo_path)
            # Skip ignored directories (use relative path, not absolute)
            if any(part.startswith(".") or part in {
                "node_modules", "__pycache__", ".venv", "venv", "dist", "build"
            } for part in rel_path.parts):
                continue

            try:
                content = structure_file.read_text()
            except Exception:
                continue

            # Extract timestamp from STRUCTURE.md footer
            # New format: *Generated by TurboWrap - 2025-12-24 16:20 | ts:1735055800*
            # Old format: *Generated by TurboWrap - 2025-12-24 16:20* (no ts, use file mtime)
            match = re.search(r"\|\s*ts:(\d+)", content)
            if not match:
                # No timestamp in content - use file modification time as fallback
                # Consider stale if file is older than 24 hours (legacy files)
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

                # Compare file mtime with generation timestamp (10s tolerance)
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

        # Emit progress event
        if emit:
            await emit(ProgressEvent(
                type=ProgressEventType.STRUCTURE_GENERATION_STARTED,
                message=f"Regenerating {len(stale_dirs)} stale STRUCTURE.md files...",
            ))

        # Use StructureGenerator to regenerate
        try:
            generator = StructureGenerator(
                str(context.repo_path),
                gemini_client=None,  # Quick mode without Gemini for refresh
            )

            # Run regeneration in executor (sync method)
            loop = asyncio.get_event_loop()
            regenerated = await loop.run_in_executor(
                None,
                lambda: generator.regenerate_stale(verbose=True)
            )

            if emit:
                await emit(ProgressEvent(
                    type=ProgressEventType.STRUCTURE_GENERATION_COMPLETED,
                    message=f"Regenerated {len(regenerated)} STRUCTURE.md files",
                ))

            logger.info(f"Regenerated {len(regenerated)} STRUCTURE.md files")

        except Exception as e:
            logger.error(f"Failed to regenerate STRUCTURE.md files: {e}")
            if emit:
                await emit(ProgressEvent(
                    type=ProgressEventType.REVIEW_ERROR,
                    error=f"Structure refresh failed: {str(e)}",
                ))

    async def _save_report(self, report: FinalReport, repo_path: Path) -> None:
        """
        Save the final report to the output directory with atomic writes.

        Uses a two-phase commit pattern:
        1. Write all files to temp locations
        2. Move all temp files to final locations atomically
        3. Rollback on any failure

        This ensures no partial writes if the process fails mid-save.
        """
        import shutil
        import tempfile

        output_dir = repo_path / ".reviews"
        temp_files: list[tuple[Path, Path]] = []  # (temp_path, final_path)

        try:
            # Phase 1: Create output directory
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate timestamp for filename
            timestamp = report.timestamp.strftime("%Y%m%d_%H%M%S")
            base_name = f"review_{timestamp}_{report.id}"

            # Prepare content once (avoid regenerating)
            json_content = report.model_dump_json(indent=2)
            md_content = report.to_markdown()

            # Define all target files
            targets = [
                (output_dir / f"{base_name}.json", json_content),
                (output_dir / f"{base_name}.md", md_content),
                (output_dir / "latest.json", json_content),
                (output_dir / "latest.md", md_content),
            ]

            # Phase 2: Write to temp files first
            for final_path, content in targets:
                # Create temp file in same directory (for atomic rename)
                fd, temp_path_str = tempfile.mkstemp(
                    dir=output_dir,
                    prefix=f".tmp_{final_path.stem}_",
                    suffix=final_path.suffix,
                )
                temp_path = Path(temp_path_str)
                temp_files.append((temp_path, final_path))

                try:
                    # Write content
                    with open(fd, 'w', encoding='utf-8') as f:
                        f.write(content)
                except Exception:
                    # Close fd if write fails
                    import os
                    os.close(fd)
                    raise

            # Phase 3: Atomic move all temp files to final locations
            for temp_path, final_path in temp_files:
                # Remove existing file first (for latest files)
                final_path.unlink(missing_ok=True)
                # Atomic rename (same filesystem)
                shutil.move(str(temp_path), str(final_path))

            logger.info(f"Reports saved atomically to {output_dir}")

        except Exception as e:
            # Rollback: clean up any temp files
            for temp_path, _ in temp_files:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass  # Best effort cleanup
            logger.error(f"Failed to save report (rolled back): {e}")
            raise  # Re-raise to signal failure to caller
