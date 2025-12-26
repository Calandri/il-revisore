"""
Claude API-based repository evaluator.

Produces comprehensive quality scores (0-100) for 6 dimensions.
Runs after all reviewers complete, with full context.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from turbowrap.config import get_settings
from turbowrap.llm import ClaudeClient
from turbowrap.review.models.evaluation import RepositoryEvaluation
from turbowrap.review.models.report import RepositoryInfo, ReviewerResult
from turbowrap.review.models.review import Issue

logger = logging.getLogger(__name__)

# Timeouts
EVALUATOR_TIMEOUT = 180  # 3 minutes for evaluation

# Agent file path
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
EVALUATOR_AGENT = AGENTS_DIR / "evaluator.md"


class ClaudeEvaluator:
    """
    Repository evaluator using Claude API.

    Produces 6 quality metrics (0-100) based on:
    - Repository structure (STRUCTURE.md)
    - Issues found by reviewers
    - File contents
    - Repository metadata
    """

    def __init__(
        self,
        timeout: int = EVALUATOR_TIMEOUT,
    ):
        """
        Initialize Claude evaluator.

        Args:
            timeout: Timeout in seconds for API call
        """
        self.settings = get_settings()
        self.timeout = timeout
        self._agent_prompt: str | None = None
        self._client: ClaudeClient | None = None

    def _load_agent_prompt(self) -> str:
        """Load evaluator agent prompt from MD file."""
        if self._agent_prompt is not None:
            return self._agent_prompt

        if not EVALUATOR_AGENT.exists():
            logger.warning(f"Evaluator agent file not found: {EVALUATOR_AGENT}")
            return ""

        content = EVALUATOR_AGENT.read_text(encoding="utf-8")

        # Strip YAML frontmatter (--- ... ---)
        if content.startswith("---"):
            end_match = re.search(r"\n---\n", content[3:])
            if end_match:
                content = content[3 + end_match.end() :]

        self._agent_prompt = content.strip()
        return self._agent_prompt

    async def evaluate(
        self,
        structure_docs: dict[str, str],
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
        repo_path: Path | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
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

        Returns:
            RepositoryEvaluation with 6 scores, or None if evaluation failed
        """
        prompt = self._build_prompt(structure_docs, issues, reviewer_results, repo_info)

        output = await self._run_claude_api(prompt, on_chunk)

        if output is None:
            logger.error("Evaluator API returned None")
            return None

        return self._parse_response(output)

    def _build_prompt(
        self,
        structure_docs: dict[str, str],
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
    ) -> str:
        """Build the evaluation prompt with all context."""
        sections = []

        # Agent prompt
        agent_prompt = self._load_agent_prompt()
        if agent_prompt:
            sections.append(agent_prompt)
            sections.append("\n---\n")

        # Repository info
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
            severity = issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity)
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
            for _i, issue in enumerate(issues[:30]):
                severity = issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity)
                category = issue.category.value if hasattr(issue.category, 'value') else str(issue.category)
                sections.append(
                    f"- **[{severity}]** `{issue.file}`: {issue.title} "
                    f"({category})\n"
                )
            if len(issues) > 30:
                sections.append(f"... and {len(issues) - 30} more issues\n")

        sections.append("\n---\n")
        sections.append("\n**Now evaluate this repository and output JSON.**\n")

        return "".join(sections)

    def _get_client(self) -> ClaudeClient:
        """Get or create Claude API client."""
        if self._client is None:
            self._client = ClaudeClient(
                model=self.settings.agents.claude_model,
                max_tokens=8192,
                timeout=float(self.timeout),
            )
        return self._client

    async def _run_claude_api(
        self,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """
        Run Claude API with the prompt.

        Args:
            prompt: The full prompt to send
            on_chunk: Optional callback for streaming chunks

        Returns:
            API response or None if failed
        """
        try:
            client = self._get_client()

            # System prompt for evaluation
            system_prompt = (
                "You are a senior code quality evaluator. "
                "Analyze the repository and produce a JSON evaluation with scores 0-100. "
                "Be objective and provide constructive feedback."
            )

            # Use streaming if callback provided
            if on_chunk:
                output_chunks: list[str] = []
                async for chunk in client.agenerate_stream(prompt, system_prompt):
                    output_chunks.append(chunk)
                    await on_chunk(chunk)
                return "".join(output_chunks)
            else:
                # Non-streaming call
                return await client.agenerate(prompt, system_prompt)

        except Exception as e:
            logger.exception(f"Evaluator API error: {e}")
            return None

    def _parse_response(self, response_text: str) -> RepositoryEvaluation | None:
        """Parse Claude's JSON response into RepositoryEvaluation."""
        try:
            # Extract JSON from response
            json_text = self._extract_json(response_text)
            data = json.loads(json_text)

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

        except json.JSONDecodeError as e:
            logger.error(f"Evaluator JSON parse error: {e}")
            logger.error(f"Raw response: {response_text[:1000]}")
            return None
        except Exception as e:
            logger.error(f"Evaluator parse error: {e}")
            return None

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response text."""
        text = text.strip()

        # Look for markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()

        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end != -1:
                potential = text[start:end].strip()
                if potential.startswith("{"):
                    return potential

        # Find first { and last }
        first_brace = text.find("{")
        if first_brace != -1:
            last_brace = text.rfind("}")
            if last_brace > first_brace:
                return text[first_brace:last_brace + 1]

        return text
