"""
Main orchestrator for TurboWrap code review system.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Awaitable

from turbowrap.config import get_settings
from turbowrap.review.models.review import (
    ReviewRequest,
    ReviewOutput,
    ReviewMode,
    Issue,
    IssueSeverity,
)
from turbowrap.review.models.report import (
    FinalReport,
    RepoType,
    Recommendation,
    ReviewerResult,
    RepositoryInfo,
    ReportSummary,
    SeveritySummary,
    ChallengerMetadata,
    NextStep,
)
from turbowrap.review.models.progress import (
    ProgressEvent,
    ProgressEventType,
    get_reviewer_display_name,
)
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.challenger_loop import ChallengerLoop, ChallengerLoopResult
from turbowrap.review.utils.repo_detector import RepoDetector, detect_repo_type
from turbowrap.review.utils.git_utils import GitUtils
from turbowrap.review.utils.file_utils import FileUtils


logger = logging.getLogger(__name__)

# Type alias for progress callback
ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]


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
        progress_callback: Optional[ProgressCallback] = None,
    ) -> FinalReport:
        """
        Perform a complete code review.

        Args:
            request: Review request with source and options
            progress_callback: Optional async callback for progress events

        Returns:
            FinalReport with all findings
        """
        start_time = datetime.utcnow()
        report_id = f"rev_{uuid.uuid4().hex[:12]}"

        logger.info(f"Starting review {report_id}")

        # Helper to emit events
        async def emit(event: ProgressEvent):
            if progress_callback:
                event.review_id = report_id
                await progress_callback(event)

        # Emit review started
        await emit(ProgressEvent(
            type=ProgressEventType.REVIEW_STARTED,
            review_id=report_id,
            message="Starting code review...",
        ))

        # Step 1: Prepare context
        context = await self._prepare_context(request)

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

        if request.options.challenger_enabled:
            # Run all reviewers in PARALLEL with progress callbacks
            async def run_reviewer_with_progress(reviewer_name: str):
                """Run a single reviewer with progress events."""
                display_name = get_reviewer_display_name(reviewer_name)

                await emit(ProgressEvent(
                    type=ProgressEventType.REVIEWER_STARTED,
                    reviewer_name=reviewer_name,
                    reviewer_display_name=display_name,
                    message=f"Starting {display_name}...",
                ))

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
                    ))

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

                    return (reviewer_name, "error", str(e))

            # Execute all reviewers in parallel
            tasks = [run_reviewer_with_progress(name) for name in reviewers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    continue

                reviewer_name, status, data = result

                if status == "success":
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

        # Step 6: Build final report
        report = self._build_report(
            report_id=report_id,
            request=request,
            context=context,
            repo_type=repo_type,
            reviewer_results=reviewer_results,
            issues=prioritized_issues,
            loop_results=loop_results,
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

        return report

    async def _prepare_context(self, request: ReviewRequest) -> ReviewContext:
        """Prepare the review context from the request."""
        context = ReviewContext(request=request)
        source = request.source
        mode = request.options.mode

        # Set repo_path first (needed for all modes)
        if source.directory:
            context.repo_path = Path(source.directory)
        elif source.pr_url or source.commit_sha or source.files:
            context.repo_path = Path(source.directory or Path.cwd())
        else:
            context.repo_path = Path.cwd()

        # Load STRUCTURE.md files first (used in all modes)
        self._load_structure_docs(context)

        # INITIAL mode: Only use STRUCTURE.md, no code files
        if mode == ReviewMode.INITIAL:
            logger.info("INITIAL mode: Reviewing architecture via STRUCTURE.md files only")
            if not context.structure_docs:
                logger.warning("No STRUCTURE.md files found! Initial review may be limited.")
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
            "coverage", ".tox", "htmlcov",
        }

        for path in directory.rglob("*"):
            if path.is_file():
                # Check if any parent is in exclude list
                if any(part in exclude_dirs for part in path.parts):
                    continue

                if FileUtils.is_text_file(path):
                    files.append(str(path.relative_to(directory)))

        return files[:100]  # Limit to 100 files

    def _load_structure_docs(self, context: ReviewContext) -> None:
        """
        Find and load all STRUCTURE.md files in the repository.

        These files contain important documentation about the codebase
        architecture and are loaded into context.structure_docs.
        """
        if not context.repo_path:
            return

        logger.info("Scanning for STRUCTURE.md files...")

        # Find all STRUCTURE.md files
        structure_files = list(context.repo_path.rglob("STRUCTURE.md"))

        # Also check for structure.md (lowercase)
        structure_files.extend(context.repo_path.rglob("structure.md"))

        # Filter out common excluded directories
        exclude_dirs = {
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
        }

        for structure_file in structure_files:
            # Skip if in excluded directory
            if any(part in exclude_dirs for part in structure_file.parts):
                continue

            try:
                relative_path = str(structure_file.relative_to(context.repo_path))
                content = structure_file.read_text(encoding="utf-8")
                context.structure_docs[relative_path] = content
                logger.info(f"  Loaded: {relative_path}")
            except Exception as e:
                logger.warning(f"  Failed to read {structure_file}: {e}")

        if context.structure_docs:
            logger.info(f"Found {len(context.structure_docs)} STRUCTURE.md file(s)")
        else:
            logger.info("No STRUCTURE.md files found")

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
            for path, content in structure_docs.items():
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
                        elif type_str == "frontend":
                            return RepoType.FRONTEND
                        elif type_str == "fullstack":
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

        if repo_type in [RepoType.BACKEND, RepoType.FULLSTACK]:
            reviewers.append("reviewer_be_architecture")
            reviewers.append("reviewer_be_quality")

        if repo_type in [RepoType.FRONTEND, RepoType.FULLSTACK]:
            reviewers.append("reviewer_fe_architecture")
            reviewers.append("reviewer_fe_quality")

        # ALWAYS launch analyst_func - business logic is critical
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
        from turbowrap.review.reviewers.claude_reviewer import ClaudeReviewer

        reviewer = ClaudeReviewer(name=reviewer_name)

        try:
            context.agent_prompt = reviewer.load_agent_prompt(
                self.settings.agents_dir
            )
        except FileNotFoundError:
            pass

        return await reviewer.review(context)

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

    def _build_report(
        self,
        report_id: str,
        request: ReviewRequest,
        context: ReviewContext,
        repo_type: RepoType,
        reviewer_results: list[ReviewerResult],
        issues: list[Issue],
        loop_results: list[ChallengerLoopResult],
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
        from turbowrap.review.models.report import ConvergenceStatus
        convergence = loop_results[0].convergence
        for result in loop_results[1:]:
            if result.convergence.value != "THRESHOLD_MET":
                convergence = result.convergence

        return ChallengerMetadata(
            enabled=True,
            total_iterations=total_iterations,
            final_satisfaction_score=avg_satisfaction,
            threshold=99.0,
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
