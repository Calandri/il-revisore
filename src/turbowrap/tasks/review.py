"""Review task implementation using the new orchestrator with challenger loop."""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..db.models import Task
from ..review.models.report import FinalReport
from ..review.models.review import (
    IssueSeverity,
    ReviewMode,
    ReviewOptions,
    ReviewRequest,
    ReviewRequestSource,
)
from ..review.orchestrator import Orchestrator
from .base import BaseTask, ReviewTaskConfig, TaskContext, TaskResult


class ReviewTask(BaseTask):
    """Code review task using 5 specialized reviewers with challenger loop.

    Reviewers:
    - reviewer_be_architecture: Backend architecture (SOLID, layers, coupling)
    - reviewer_be_quality: Backend quality (linting, security, performance)
    - reviewer_fe_architecture: Frontend architecture (React patterns, state)
    - reviewer_fe_quality: Frontend quality (type safety, performance)
    - analyst_func: Functional analysis (business logic, requirements)
    """

    @property
    def name(self) -> str:
        return "review"

    @property
    def description(self) -> str:
        return "Deep code review with 5 specialized AI reviewers and challenger loop"

    @property
    def config_class(self) -> type[ReviewTaskConfig]:
        return ReviewTaskConfig

    def execute(self, context: TaskContext) -> TaskResult:
        """Execute review task.

        Args:
            context: Task context with db session and repo path.

        Returns:
            TaskResult with review results.
        """
        started_at = datetime.utcnow()
        start_time = time.time()

        try:
            # Get or create task record
            task = self._get_or_create_task(context)

            # Update task status
            task.status = "running"  # type: ignore[assignment]
            task.started_at = started_at  # type: ignore[assignment]
            context.db.commit()

            # Build review request
            request = self._build_request(context)

            # Run orchestrator (async)
            orchestrator = Orchestrator()
            report = asyncio.run(orchestrator.review(request))

            # Update task with results
            completed_at = datetime.utcnow()
            duration = time.time() - start_time

            result_data = self._report_to_dict(report)
            task.status = "completed"  # type: ignore[assignment]
            task.completed_at = completed_at  # type: ignore[assignment]
            task.result = result_data  # type: ignore[assignment]

            context.db.commit()

            return TaskResult(
                status="completed",
                data=result_data,
                duration_seconds=duration,
                started_at=started_at,
                completed_at=completed_at,
            )

        except Exception as e:
            duration = time.time() - start_time
            completed_at = datetime.utcnow()

            # Update task if exists
            if "task" in locals():
                task.status = "failed"  # type: ignore[assignment]
                task.error = str(e)  # type: ignore[assignment]
                task.completed_at = completed_at  # type: ignore[assignment]
                context.db.commit()

            return TaskResult(
                status="failed",
                error=str(e),
                duration_seconds=duration,
                started_at=started_at,
                completed_at=completed_at,
            )

    def _build_request(self, context: TaskContext) -> ReviewRequest:
        """Build ReviewRequest from TaskContext."""
        config = context.config

        # Determine review type
        pr_url = config.get("pr_url")
        commit_sha = config.get("commit_sha")
        files = config.get("files", [])

        if pr_url:
            review_type = "pr"
            source = ReviewRequestSource(
                pr_url=pr_url,
                commit_sha=None,
                directory=None,
                workspace_path=None,
            )
        elif commit_sha:
            review_type = "commit"
            source = ReviewRequestSource(
                pr_url=None,
                commit_sha=commit_sha,
                directory=str(context.repo_path),
                workspace_path=None,
            )
        elif files:
            review_type = "files"
            source = ReviewRequestSource(
                pr_url=None,
                commit_sha=None,
                files=files,
                directory=str(context.repo_path),
                workspace_path=None,
            )
        else:
            review_type = "directory"
            source = ReviewRequestSource(
                pr_url=None,
                commit_sha=None,
                directory=str(context.repo_path),
                workspace_path=None,
            )

        # Get severity threshold from config, defaulting to LOW
        severity_threshold_str = config.get("severity_threshold")
        if severity_threshold_str is not None:
            severity_threshold = IssueSeverity(severity_threshold_str)
        else:
            severity_threshold = IssueSeverity.LOW

        # Build options
        options = ReviewOptions(
            mode=ReviewMode.DIFF,
            include_functional=config.get("include_functional", True),
            severity_threshold=severity_threshold,
            output_format=config.get("output_format", "both"),
        )

        return ReviewRequest(
            type=review_type,
            source=source,
            options=options,
        )

    def _report_to_dict(self, report: FinalReport) -> dict[str, Any]:
        """Convert FinalReport to dictionary for storage.

        Uses Pydantic's model_dump() for reliable serialization of nested objects,
        then extracts the fields we need for the task result.
        """
        # Use Pydantic serialization for safety with nested objects
        full_dump = report.model_dump(mode="json")

        # Extract and flatten the fields we need
        return {
            "id": report.id,
            "recommendation": report.summary.recommendation.value,
            "score": report.summary.overall_score,
            "total_issues": report.summary.by_severity.total,
            "critical_issues": report.summary.by_severity.critical,
            "high_issues": report.summary.by_severity.high,
            "medium_issues": report.summary.by_severity.medium,
            "low_issues": report.summary.by_severity.low,
            "reviewers": [
                {
                    "name": r.name,
                    "status": r.status,
                    "issues_found": r.issues_found,
                    "iterations": r.iterations,
                    "satisfaction_score": r.final_satisfaction,
                }
                for r in report.reviewers
            ],
            "challenger": {
                "enabled": report.challenger.enabled,
                "total_iterations": report.challenger.total_iterations,
                "average_satisfaction": report.challenger.final_satisfaction_score,
                "convergence_status": (
                    report.challenger.convergence.value if report.challenger.convergence else None
                ),
            },
            "issues": [
                {
                    "id": i.id,
                    "severity": i.severity.value,
                    "category": i.category.value,
                    "file": i.file,
                    "line": i.line,
                    "title": i.title,
                    "description": i.description,
                    "suggested_fix": i.suggested_fix,
                    "flagged_by": i.flagged_by,
                }
                for i in report.issues
            ],
            "next_steps": [
                {"priority": ns.priority, "action": ns.action, "issues": ns.issues}
                for ns in report.next_steps
            ],
            "timestamp": report.timestamp.isoformat(),
            # Include full serialized data for debugging/completeness
            "full_report": full_dump,
        }

    def _get_or_create_task(self, context: TaskContext) -> Task:
        """Get existing task or create new one."""
        task_id = context.config.get("task_id")

        if task_id:
            existing_task: Task | None = context.db.query(Task).filter(Task.id == task_id).first()
            if existing_task is not None:
                return existing_task

        # Create new task
        new_task = Task(
            repository_id=context.config.get("repository_id"),
            type=self.name,
            status="pending",
            config=context.config,
        )
        context.db.add(new_task)
        context.db.commit()
        context.db.refresh(new_task)

        return new_task

    def generate_report(self, result: TaskResult, output_dir: Path) -> Path:
        """Generate markdown report from results.

        Args:
            result: Task result.
            output_dir: Directory for output files.

        Returns:
            Path to generated report.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        data = result.data
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # Generate rich report
        lines = [
            "# Code Review Report",
            "",
            f"*Generated by TurboWrap: {timestamp}*",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            f"**Recommendation:** {data.get('recommendation', 'N/A')}",
            f"**Score:** {data.get('score', 'N/A')}/10",
            "",
            "### Issue Summary",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| Critical | {data.get('critical_issues', 0)} |",
            f"| High | {data.get('high_issues', 0)} |",
            f"| Medium | {data.get('medium_issues', 0)} |",
            f"| Low | {data.get('low_issues', 0)} |",
            f"| **Total** | **{data.get('total_issues', 0)}** |",
            "",
            "---",
            "",
        ]

        # Reviewers section
        if data.get("reviewers"):
            lines.extend(
                [
                    "## Reviewers",
                    "",
                ]
            )
            for reviewer in data["reviewers"]:
                lines.extend(
                    [
                        f"### {reviewer['name']}",
                        f"- Status: {reviewer['status']}",
                        f"- Issues found: {reviewer['issues_found']}",
                        f"- Iterations: {reviewer.get('iterations', 1)}",
                        f"- Satisfaction: {reviewer.get('satisfaction_score', 'N/A')}%",
                        "",
                    ]
                )

        # Challenger section
        challenger = data.get("challenger", {})
        if challenger.get("enabled"):
            lines.extend(
                [
                    "## Challenger Loop",
                    "",
                    f"- **Total iterations:** {challenger.get('total_iterations', 0)}",
                    f"- **Average satisfaction:** {challenger.get('average_satisfaction', 0):.1f}%",
                    f"- **Convergence:** {challenger.get('convergence_status', 'N/A')}",
                    "",
                    "---",
                    "",
                ]
            )

        # Issues section
        issues = data.get("issues", [])
        if issues:
            lines.extend(
                [
                    "## Issues",
                    "",
                ]
            )

            # Group by severity
            for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                severity_issues = [i for i in issues if i["severity"] == severity]
                if severity_issues:
                    lines.extend(
                        [
                            f"### {severity} ({len(severity_issues)})",
                            "",
                        ]
                    )
                    for issue in severity_issues:
                        lines.extend(
                            [
                                f"#### [{issue['id']}] {issue['title']}",
                                f"**File:** `{issue['file']}`"
                                + (f" (line {issue['line']})" if issue.get("line") else ""),
                                f"**Category:** {issue['category']}",
                                "",
                                issue["description"],
                                "",
                            ]
                        )
                        if issue.get("suggested_fix"):
                            lines.extend(
                                [
                                    "**Suggested fix:**",
                                    "```",
                                    issue["suggested_fix"],
                                    "```",
                                    "",
                                ]
                            )
                        if issue.get("flagged_by"):
                            lines.append(f"*Flagged by: {', '.join(issue['flagged_by'])}*")
                            lines.append("")

        # Next steps section
        next_steps = data.get("next_steps", [])
        if next_steps:
            lines.extend(
                [
                    "---",
                    "",
                    "## Next Steps",
                    "",
                ]
            )
            for step in next_steps:
                lines.append(f"{step['priority']}. {step['action']}")
            lines.append("")

        # Footer
        lines.extend(
            [
                "---",
                "",
                f"*Review completed in {result.duration_seconds:.2f} seconds*",
                "",
                "*Generated with TurboWrap - 5 Specialized Reviewers + Challenger Loop*",
            ]
        )

        output_file = output_dir / "REVIEW_REPORT.md"
        output_file.write_text("\n".join(lines), encoding="utf-8")

        return output_file
