"""
Claude CLI-based repository evaluator.

Produces comprehensive quality scores (0-100) for 6 dimensions.
Runs after all reviewers complete, with full context.

Uses the centralized ClaudeCLI utility for Claude CLI subprocess execution.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from turbowrap.config import get_settings
from turbowrap.llm.claude_cli import ClaudeCLI
from turbowrap.review.models.evaluation import RepositoryEvaluation
from turbowrap.review.models.report import RepositoryInfo, ReviewerResult
from turbowrap.review.models.review import Issue
from turbowrap.review.reviewers.utils import parse_json_safe

logger = logging.getLogger(__name__)

# Timeouts
EVALUATOR_TIMEOUT = 180  # 3 minutes for evaluation

# Agent file path
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
EVALUATOR_AGENT = AGENTS_DIR / "evaluator.md"


class ClaudeEvaluator:
    """
    Repository evaluator using Claude CLI.

    Produces 6 quality metrics (0-100) based on:
    - Repository structure (STRUCTURE.md)
    - Issues found by reviewers
    - File contents
    - Repository metadata

    Uses the centralized ClaudeCLI utility for Claude CLI execution.
    """

    def __init__(
        self,
        timeout: int = EVALUATOR_TIMEOUT,
    ):
        """
        Initialize Claude evaluator.

        Args:
            timeout: Timeout in seconds for CLI execution
        """
        self.settings = get_settings()
        self.timeout = timeout

    def _get_claude_cli(self, repo_path: Path | None = None) -> ClaudeCLI:
        """Create ClaudeCLI instance for evaluation."""
        return ClaudeCLI(
            agent_md_path=EVALUATOR_AGENT if EVALUATOR_AGENT.exists() else None,
            working_dir=repo_path,
            model="opus",  # Use Opus for comprehensive evaluation
            timeout=self.timeout,
            s3_prefix="evaluations",
        )

    @staticmethod
    def _get_enum_value(obj: object, attr: str) -> str:
        """
        Get string value from an enum-like attribute.

        Handles both proper Enum objects and string values.

        Args:
            obj: Object containing the attribute
            attr: Attribute name

        Returns:
            String value of the attribute
        """
        value = getattr(obj, attr, None)
        if value is None:
            return "UNKNOWN"
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    async def evaluate(
        self,
        structure_docs: dict[str, str],
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
        repo_path: Path | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        review_id: str | None = None,
    ) -> RepositoryEvaluation | None:
        """
        Evaluate repository and produce quality scores.

        Args:
            structure_docs: STRUCTURE.md contents by path
            issues: All deduplicated issues from reviewers
            reviewer_results: Results from each reviewer
            repo_info: Repository metadata
            repo_path: Path to repository (for Claude CLI cwd)
            on_chunk: Optional callback for streaming output
            review_id: Review ID for S3 logging

        Returns:
            RepositoryEvaluation with 6 scores, or None if evaluation failed
        """
        prompt = self._build_prompt(structure_docs, issues, reviewer_results, repo_info)

        # Use centralized ClaudeCLI utility
        cli = self._get_claude_cli(repo_path)
        context_id = review_id or f"eval_{repo_info.name}"

        result = await cli.run(
            prompt,
            context_id=context_id,
            save_prompt=True,
            save_output=True,
            on_chunk=on_chunk,
        )

        if not result.success:
            logger.error(f"Evaluator CLI failed: {result.error}")
            return None

        return self._parse_response(result.output)

    def _build_prompt(
        self,
        structure_docs: dict[str, str],
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
    ) -> str:
        """Build the evaluation prompt with all context.

        Note: Agent prompt is loaded by ClaudeCLI via agent_md_path.
        """
        sections = []

        # Repository info (agent prompt is loaded by ClaudeCLI)
        sections.append("# Repository Context\n")
        sections.append(f"- **Name**: {repo_info.name or 'Unknown'}\n")
        sections.append(f"- **Type**: {repo_info.type.value}\n")
        sections.append(f"- **Branch**: {repo_info.branch or 'Unknown'}\n")

        # Structure docs
        if structure_docs:
            sections.append("\n## Repository Structure\n")
            for path, content in structure_docs.items():
                # Truncate long structure docs
                truncated = content[:5000] if len(content) > 5000 else content
                sections.append(f"### {path}\n```\n{truncated}\n```\n")

        # Reviewer results summary
        sections.append("\n## Reviewer Results\n")
        for result in reviewer_results:
            status_emoji = "✅" if result.status == "completed" else "❌"
            sections.append(
                f"- **{result.name}**: {status_emoji} {result.issues_found} issues, "
                f"satisfaction: {result.final_satisfaction or 'N/A'}\n"
            )

        # Issues summary by severity
        sections.append("\n## Issues Found\n")
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for issue in issues:
            severity = self._get_enum_value(issue, "severity")
            if severity in severity_counts:
                severity_counts[severity] += 1

        sections.append(f"- **CRITICAL**: {severity_counts['CRITICAL']}\n")
        sections.append(f"- **HIGH**: {severity_counts['HIGH']}\n")
        sections.append(f"- **MEDIUM**: {severity_counts['MEDIUM']}\n")
        sections.append(f"- **LOW**: {severity_counts['LOW']}\n")
        sections.append(f"- **Total**: {len(issues)}\n")

        # Issue details (limit to first 30 to avoid token explosion)
        if issues:
            sections.append("\n### Issue Details\n")
            for issue in issues[:30]:
                severity = self._get_enum_value(issue, "severity")
                category = self._get_enum_value(issue, "category")
                sections.append(f"- **[{severity}]** `{issue.file}`: {issue.title} ({category})\n")
            if len(issues) > 30:
                sections.append(f"... and {len(issues) - 30} more issues\n")

        sections.append("\n---\n")
        sections.append("\n**Now evaluate this repository and output JSON.**\n")

        return "".join(sections)

    def _parse_response(self, response_text: str) -> RepositoryEvaluation | None:
        """Parse Claude's JSON response into RepositoryEvaluation."""
        try:
            # Use centralized JSON parser
            data = parse_json_safe(response_text)

            # Calculate overall if not provided
            overall = data.get("overall_score")
            if overall is None:
                overall = RepositoryEvaluation.calculate_overall(
                    functionality=data.get("functionality", 50),
                    code_quality=data.get("code_quality", 50),
                    comment_quality=data.get("comment_quality", 50),
                    architecture_quality=data.get("architecture_quality", 50),
                    effectiveness=data.get("effectiveness", 50),
                    code_duplication=data.get("code_duplication", 50),
                )

            return RepositoryEvaluation(
                functionality=data.get("functionality", 50),
                code_quality=data.get("code_quality", 50),
                comment_quality=data.get("comment_quality", 50),
                architecture_quality=data.get("architecture_quality", 50),
                effectiveness=data.get("effectiveness", 50),
                code_duplication=data.get("code_duplication", 50),
                overall_score=overall,
                summary=data.get("summary", "Evaluation completed."),
                strengths=data.get("strengths", []),
                weaknesses=data.get("weaknesses", []),
                evaluated_at=datetime.utcnow(),
                evaluator_model=self.settings.agents.claude_model,
            )

        except Exception as e:
            logger.error(f"Evaluator parse error: {e}")
            logger.error(f"Raw response: {response_text[:1000]}")
            return None
