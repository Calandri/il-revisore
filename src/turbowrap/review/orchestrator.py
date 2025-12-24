"""
Main orchestrator for TurboWrap code review system.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from turbowrap.config import get_settings
from turbowrap.review.models.review import (
    ReviewRequest,
    ReviewOutput,
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
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.challenger_loop import ChallengerLoop, ChallengerLoopResult
from turbowrap.review.utils.repo_detector import RepoDetector, detect_repo_type
from turbowrap.review.utils.git_utils import GitUtils
from turbowrap.review.utils.file_utils import FileUtils


logger = logging.getLogger(__name__)


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

    async def review(self, request: ReviewRequest) -> FinalReport:
        """
        Perform a complete code review.

        Args:
            request: Review request with source and options

        Returns:
            FinalReport with all findings
        """
        start_time = datetime.utcnow()
        report_id = f"rev_{uuid.uuid4().hex[:12]}"

        logger.info(f"Starting review {report_id}")

        # Step 1: Prepare context
        context = await self._prepare_context(request)

        # Step 2: Detect repository type
        repo_type = self._detect_repo_type(context.files)
        logger.info(f"Detected repository type: {repo_type.value}")

        # Step 3: Determine which reviewers to run
        reviewers = self._get_reviewers(repo_type, request.options.include_functional)
        logger.info(f"Running reviewers: {reviewers}")

        # Step 4: Run challenger loops for each reviewer
        reviewer_results: list[ReviewerResult] = []
        all_issues: list[Issue] = []
        loop_results: list[ChallengerLoopResult] = []

        if request.options.challenger_enabled:
            # Run with challenger pattern
            for reviewer_name in reviewers:
                try:
                    result = await self._run_challenger_loop(context, reviewer_name)
                    loop_results.append(result)

                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="completed",
                        issues_found=len(result.final_review.issues),
                        duration_seconds=result.final_review.duration_seconds,
                        iterations=result.iterations,
                        final_satisfaction=result.final_satisfaction,
                    ))

                    all_issues.extend(result.final_review.issues)

                except Exception as e:
                    logger.error(f"Reviewer {reviewer_name} failed: {e}")
                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="error",
                        error=str(e),
                    ))
        else:
            # Run without challenger pattern (simple mode)
            for reviewer_name in reviewers:
                try:
                    result = await self._run_simple_review(context, reviewer_name)

                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="completed",
                        issues_found=len(result.issues),
                        duration_seconds=result.duration_seconds,
                        iterations=1,
                    ))

                    all_issues.extend(result.issues)

                except Exception as e:
                    logger.error(f"Reviewer {reviewer_name} failed: {e}")
                    reviewer_results.append(ReviewerResult(
                        name=reviewer_name,
                        status="error",
                        error=str(e),
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

        return report

    async def _prepare_context(self, request: ReviewRequest) -> ReviewContext:
        """Prepare the review context from the request."""
        context = ReviewContext(request=request)

        source = request.source

        # Handle different source types
        if source.pr_url:
            context = await self._prepare_pr_context(source.pr_url, context)

        elif source.commit_sha:
            # Get changed files from commit
            git = GitUtils(source.directory or Path.cwd())
            context.files = git.get_changed_files(head_ref=source.commit_sha)
            context.diff = git.get_diff(head_ref=source.commit_sha)
            context.commit_sha = source.commit_sha
            context.repo_path = Path(source.directory or Path.cwd())

        elif source.files:
            context.files = source.files
            context.repo_path = Path(source.directory or Path.cwd())

        elif source.directory:
            # Scan directory for files
            context.repo_path = Path(source.directory)
            context.files = self._scan_directory(context.repo_path)

        # Load file contents
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

    def _detect_repo_type(self, files: list[str]) -> RepoType:
        """Detect repository type from files."""
        return self.repo_detector.detect(files)

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
