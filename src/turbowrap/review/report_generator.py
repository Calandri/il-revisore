"""
Report generator for TurboWrap.
"""

from pathlib import Path

from turbowrap.review.models.report import (
    ConvergenceStatus,
    FinalReport,
    Recommendation,
)
from turbowrap.review.models.review import Issue, IssueSeverity


class ReportGenerator:
    """
    Generates formatted reports from FinalReport.
    """

    @staticmethod
    def to_markdown(report: FinalReport) -> str:
        """
        Generate a Markdown report.

        Args:
            report: The final report to format

        Returns:
            Formatted Markdown string
        """
        sections = []

        # Header
        sections.append("# TurboWrap - Code Review Report\n")

        # Executive Summary
        sections.append(ReportGenerator._generate_summary(report))

        # Review Quality (Challenger)
        if report.challenger.enabled:
            sections.append(ReportGenerator._generate_challenger_section(report))

        # Review Coverage
        sections.append(ReportGenerator._generate_coverage_section(report))

        # Issues by Severity
        if report.issues:
            sections.append(ReportGenerator._generate_issues_section(report))

        # Next Steps
        if report.next_steps:
            sections.append(ReportGenerator._generate_next_steps(report))

        # Footer
        sections.append(ReportGenerator._generate_footer(report))

        return "\n".join(sections)

    @staticmethod
    def _generate_summary(report: FinalReport) -> str:
        """Generate executive summary section."""
        summary = report.summary

        # Recommendation emoji
        rec_emoji = {
            Recommendation.APPROVE: ":white_check_mark:",
            Recommendation.APPROVE_WITH_CHANGES: ":warning:",
            Recommendation.REQUEST_CHANGES: ":x:",
            Recommendation.NEEDS_DISCUSSION: ":speech_balloon:",
        }

        lines = [
            "## Executive Summary\n",
            "| Metric | Value |",
            "|--------|-------|",
            f"| **Repository Type** | {summary.repo_type.value} |",
            f"| **Files Reviewed** | {summary.files_reviewed} |",
            f"| **Total Issues** | {summary.total_issues} |",
            f"| **Critical** | {summary.by_severity.critical} |",
            f"| **High** | {summary.by_severity.high} |",
            f"| **Medium** | {summary.by_severity.medium} |",
            f"| **Low** | {summary.by_severity.low} |",
            f"| **Overall Score** | {summary.overall_score:.1f} / 10 |",
            f"| **Recommendation** | {rec_emoji.get(summary.recommendation, '')} {summary.recommendation.value} |",
            "",
        ]

        return "\n".join(lines)

    @staticmethod
    def _generate_challenger_section(report: FinalReport) -> str:
        """Generate challenger/review quality section."""
        challenger = report.challenger

        # Convergence emoji
        conv_emoji = {
            ConvergenceStatus.THRESHOLD_MET: ":white_check_mark:",
            ConvergenceStatus.MAX_ITERATIONS_REACHED: ":warning:",
            ConvergenceStatus.STAGNATED: ":warning:",
            ConvergenceStatus.FORCED_ACCEPTANCE: ":yellow_circle:",
        }

        lines = [
            "## Review Quality\n",
            "| Metric | Value |",
            "|--------|-------|",
            f"| **Challenger Iterations** | {challenger.total_iterations} |",
            f"| **Final Satisfaction Score** | {challenger.final_satisfaction_score:.1f}% |",
            f"| **Threshold** | {challenger.threshold}% |",
            f"| **Convergence** | {conv_emoji.get(challenger.convergence, '')} {challenger.convergence.value.replace('_', ' ').title()} |",
            "",
        ]

        # Iteration history table
        if challenger.iteration_history:
            lines.append("### Iteration History\n")
            lines.append("| Iteration | Satisfaction | Issues Added | Challenges Resolved |")
            lines.append("|-----------|--------------|--------------|---------------------|")

            for hist in challenger.iteration_history:
                lines.append(
                    f"| {hist.iteration} | {hist.satisfaction_score:.1f}% | "
                    f"+{hist.issues_added} | {hist.challenges_resolved} |"
                )
            lines.append("")

        # Challenger insights
        if challenger.insights:
            lines.append("### Challenger Insights\n")
            lines.append("The challenger identified the following critical additions:\n")
            for insight in challenger.insights:
                lines.append(f"- {insight.description} (iteration {insight.iteration})")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_coverage_section(report: FinalReport) -> str:
        """Generate review coverage section."""
        lines = [
            "## Review Coverage\n",
            "| Reviewer | Status | Issues Found | Duration | Iterations |",
            "|----------|--------|--------------|----------|------------|",
        ]

        status_emoji = {
            "completed": ":white_check_mark:",
            "skipped": ":fast_forward:",
            "timeout": ":hourglass:",
            "error": ":x:",
        }

        for reviewer in report.reviewers:
            emoji = status_emoji.get(reviewer.status, "")
            issues = reviewer.issues_found if reviewer.status == "completed" else "-"
            duration = (
                f"{reviewer.duration_seconds:.1f}s"
                if reviewer.status == "completed"
                else "-"
            )
            iterations = (
                str(reviewer.iterations)
                if reviewer.status == "completed"
                else "-"
            )

            status_text = reviewer.status.title()
            if reviewer.reason:
                status_text += f" ({reviewer.reason})"
            if reviewer.error:
                status_text += f" ({reviewer.error[:30]}...)"

            lines.append(
                f"| {reviewer.name} | {emoji} {status_text} | {issues} | {duration} | {iterations} |"
            )

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _generate_issues_section(report: FinalReport) -> str:
        """Generate issues section grouped by severity."""
        lines = []

        # Group by severity
        severity_order = [
            IssueSeverity.CRITICAL,
            IssueSeverity.HIGH,
            IssueSeverity.MEDIUM,
            IssueSeverity.LOW,
        ]

        severity_emoji = {
            IssueSeverity.CRITICAL: ":red_circle:",
            IssueSeverity.HIGH: ":orange_circle:",
            IssueSeverity.MEDIUM: ":yellow_circle:",
            IssueSeverity.LOW: ":white_circle:",
        }

        severity_title = {
            IssueSeverity.CRITICAL: "Critical Issues (Must Fix)",
            IssueSeverity.HIGH: "High Priority Issues",
            IssueSeverity.MEDIUM: "Medium Priority Issues",
            IssueSeverity.LOW: "Low Priority Issues (Nice to Have)",
        }

        for severity in severity_order:
            issues = [i for i in report.issues if i.severity == severity]
            if not issues:
                continue

            lines.append(f"## {severity_title[severity]}\n")

            for issue in issues:
                lines.append(ReportGenerator._format_issue(issue, severity_emoji[severity]))
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_issue(issue: Issue, emoji: str) -> str:
        """Format a single issue."""
        lines = [
            f"### [{issue.id}] {issue.title}",
            f"- **Severity**: {emoji} {issue.severity.value}",
            f"- **Category**: {issue.category.value.title()}",
            f"- **File**: `{issue.file}"
            + (f":{issue.line}" if issue.line else "")
            + "`",
        ]

        if len(issue.flagged_by) > 1:
            lines.append(f"- **Flagged By**: {', '.join(issue.flagged_by)}")

        if issue.rule:
            lines.append(f"- **Rule**: `{issue.rule}`")

        lines.append(f"- **Description**: {issue.description}")

        if issue.current_code:
            lines.append("\n**Current Code**:")
            lines.append(f"```\n{issue.current_code}\n```")

        if issue.suggested_fix:
            lines.append("\n**Suggested Fix**:")
            lines.append(f"```\n{issue.suggested_fix}\n```")

        if issue.references:
            lines.append("\n**References**:")
            for ref in issue.references:
                lines.append(f"- {ref}")

        return "\n".join(lines)

    @staticmethod
    def _generate_next_steps(report: FinalReport) -> str:
        """Generate next steps section."""
        lines = ["## Next Steps\n"]

        for i, step in enumerate(report.next_steps, 1):
            priority_emoji = {1: ":one:", 2: ":two:", 3: ":three:"}.get(i, f"{i}.")
            lines.append(f"{priority_emoji} **{step.action}**")
            if step.issues:
                lines.append(f"   - Issues: {', '.join(step.issues[:5])}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_footer(report: FinalReport) -> str:
        """Generate report footer."""
        timestamp = report.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        completed_reviewers = [
            r.name for r in report.reviewers if r.status == "completed"
        ]

        lines = [
            "---\n",
            f"*Generated by TurboWrap on {timestamp}*",
        ]

        if completed_reviewers:
            lines.append(f"*Reviewers: {', '.join(completed_reviewers)}*")

        if report.challenger.enabled:
            lines.append(
                f"*Challenger: Gemini 3 CLI (threshold: {report.challenger.threshold}%)*"
            )

        return "\n".join(lines)

    @staticmethod
    def save_report(
        report: FinalReport,
        output_dir: str | Path,
        formats: list[str] = None,
    ) -> dict[str, Path]:
        """
        Save report to files.

        Args:
            report: The report to save
            output_dir: Directory to save reports
            formats: List of formats ("markdown", "json", or both)

        Returns:
            Dictionary mapping format to file path
        """
        if formats is None:
            formats = ["markdown", "json"]

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = report.timestamp.strftime("%Y%m%d_%H%M%S")
        base_name = f"review_{report.id}_{timestamp}"

        saved = {}

        if "markdown" in formats:
            md_path = output_dir / f"{base_name}.md"
            md_path.write_text(ReportGenerator.to_markdown(report))
            saved["markdown"] = md_path

        if "json" in formats:
            json_path = output_dir / f"{base_name}.json"
            json_path.write_text(report.model_dump_json(indent=2))
            saved["json"] = json_path

        return saved
