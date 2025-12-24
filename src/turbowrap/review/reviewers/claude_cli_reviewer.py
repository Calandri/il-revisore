"""
Claude CLI-based reviewer implementation.

Uses Claude CLI subprocess instead of SDK, allowing the model to autonomously
explore the codebase via its own file reading capabilities.
"""

import asyncio
import codecs
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import (
    ChecklistResult,
    Issue,
    IssueCategory,
    IssueSeverity,
    ModelUsageInfo,
    ReviewMetrics,
    ReviewOutput,
    ReviewSummary,
)
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext
from turbowrap.utils.aws_secrets import get_anthropic_api_key

logger = logging.getLogger(__name__)

# Timeouts
CLAUDE_CLI_TIMEOUT = 300  # 5 minutes per review


class ClaudeCLIReviewer(BaseReviewer):
    """
    Code reviewer using Claude CLI.

    Instead of passing file contents in the prompt, this reviewer:
    1. Loads the specialist MD file (e.g., reviewer_be_architecture.md)
    2. Passes a list of files to analyze
    3. Runs Claude CLI with cwd=repo_path
    4. Claude CLI reads files autonomously and can explore beyond the initial list
    """

    def __init__(
        self,
        name: str = "reviewer_be",
        cli_path: str = "claude",
        timeout: int = CLAUDE_CLI_TIMEOUT,
    ):
        """
        Initialize Claude CLI reviewer.

        Args:
            name: Reviewer identifier (reviewer_be_architecture, etc.)
            cli_path: Path to Claude CLI executable
            timeout: Timeout in seconds for CLI execution
        """
        super().__init__(name, model="claude-cli")

        self.settings = get_settings()
        self.cli_path = cli_path
        self.timeout = timeout

    async def review(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ReviewOutput:
        """
        Perform code review using Claude CLI.

        Args:
            context: Review context with repo path and metadata
            file_list: Optional list of files to analyze (uses context.files if not provided)
            on_chunk: Optional callback for streaming output chunks

        Returns:
            ReviewOutput with findings
        """
        start_time = time.time()

        # Use provided file list or fall back to context
        files_to_review = file_list or context.files

        # Build the review prompt
        prompt = self._build_review_prompt(context, files_to_review)

        # Run Claude CLI with streaming
        output, model_usage = await self._run_claude_cli(prompt, context.repo_path, on_chunk)

        if output is None:
            return self._create_error_output("Claude CLI failed to execute")

        # Parse the response
        review_output = self._parse_response(output, files_to_review)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()
        review_output.model_usage = model_usage

        return review_output

    async def refine(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
        file_list: list[str] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ReviewOutput:
        """
        Refine review based on challenger feedback.

        Args:
            context: Original review context
            previous_review: Previous review output
            feedback: Challenger feedback to address
            file_list: Optional list of files
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Refined ReviewOutput
        """
        start_time = time.time()

        files_to_review = file_list or context.files

        # Build refinement prompt
        prompt = self._build_refinement_prompt(context, previous_review, feedback, files_to_review)

        # Run Claude CLI with streaming
        output, model_usage = await self._run_claude_cli(prompt, context.repo_path, on_chunk)

        if output is None:
            return self._create_error_output("Claude CLI refinement failed")

        # Parse the response
        review_output = self._parse_response(output, files_to_review)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()
        review_output.iteration = previous_review.iteration + 1
        review_output.model_usage = model_usage

        return review_output

    def _build_review_prompt(
        self,
        context: ReviewContext,
        file_list: list[str],
    ) -> str:
        """Build the review prompt for Claude CLI."""
        sections = []

        # Include specialist prompt if available
        if context.agent_prompt:
            sections.append(context.agent_prompt)
            sections.append("\n---\n")

        # Include structure docs for architectural context
        if context.structure_docs:
            sections.append("## Repository Structure Documentation\n")
            for path, content in context.structure_docs.items():
                sections.append(f"### {path}\n{content}\n")
            sections.append("\n---\n")

        # File list to analyze
        sections.append("## Files to Analyze\n")
        sections.append("Read and analyze the following files:\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        sections.append("""
## Important Instructions

1. **Read the files** listed above using your file reading capabilities
2. **Explore freely** - you can read other files (imports, dependencies, tests) if needed
3. **Apply your expertise** from the system prompt above
4. **Output ONLY valid JSON** matching the schema below

## Output Schema

```json
{
  "summary": {
    "files_reviewed": <int>,
    "critical_issues": <int>,
    "high_issues": <int>,
    "medium_issues": <int>,
    "low_issues": <int>,
    "score": <float 0-10>
  },
  "issues": [
    {
      "id": "<REVIEWER-SEVERITY-NNN>",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "security|performance|architecture|style|logic|ux|testing|documentation",
      "file": "<file path>",
      "line": <line number or null>,
      "title": "<brief title>",
      "description": "<detailed description>",
      "suggested_fix": "<how to fix - code or explanation>"
    }
  ],
  "checklists": {
    "security": { "passed": <int>, "failed": <int>, "skipped": <int> },
    "performance": { "passed": <int>, "failed": <int>, "skipped": <int> },
    "architecture": { "passed": <int>, "failed": <int>, "skipped": <int> }
  }
}
```

Output ONLY the JSON, no markdown code blocks, no explanations.
""")

        return "".join(sections)

    def _build_refinement_prompt(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
        file_list: list[str],
    ) -> str:
        """Build the refinement prompt for Claude CLI."""
        sections = []

        # Include specialist prompt
        if context.agent_prompt:
            sections.append(context.agent_prompt)
            sections.append("\n---\n")

        sections.append("# Review Refinement Request\n")

        sections.append("## Previous Review\n")
        sections.append(f"```json\n{previous_review.model_dump_json(indent=2)}\n```\n")

        sections.append("\n## Challenger Feedback\n")
        sections.append(feedback.to_refinement_prompt())

        sections.append("\n## Files to Re-analyze\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        sections.append("""
## Refinement Instructions

1. **Read the files** again to verify the feedback
2. Address ALL missed issues identified by the challenger
3. Re-evaluate challenged issues and adjust if warranted
4. Incorporate suggested improvements
5. Maintain valid issues from the previous review

Output the complete refined review as JSON (same schema as before).
""")

        return "".join(sections)

    async def _run_claude_cli(
        self,
        prompt: str,
        repo_path: Path | None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[ModelUsageInfo]]:
        """
        Run Claude CLI with the prompt, streaming output.

        Args:
            prompt: The full prompt to send
            repo_path: Working directory for the CLI
            on_chunk: Optional callback for streaming chunks

        Returns:
            Tuple of (CLI output or None if failed, list of model usage info)
        """
        cwd = str(repo_path) if repo_path else None

        try:
            # Build environment with API key from AWS Secrets Manager
            env = os.environ.copy()
            api_key = get_anthropic_api_key()
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
                logger.info("ANTHROPIC_API_KEY loaded from AWS Secrets Manager")
            else:
                logger.warning("ANTHROPIC_API_KEY not found in AWS - using environment")

            # Use model from settings
            model = self.settings.agents.claude_model

            logger.info(f"Running Claude CLI for {self.name} in {cwd} with model={model}")

            # Build CLI arguments with stream-json for real-time streaming
            args = [
                self.cli_path,
                "--print",
                "--dangerously-skip-permissions",
                "--model",
                model,
                "--output-format",
                "stream-json",
                "--verbose",  # Required for stream-json
            ]

            # Add extended thinking settings if enabled
            if self.settings.thinking.enabled:
                thinking_settings = {"alwaysThinkingEnabled": True}
                args.extend(["--settings", json.dumps(thinking_settings)])
                logger.info("Extended thinking enabled for Claude CLI")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # Write prompt to stdin
            prompt_bytes = prompt.encode()
            logger.info(f"Sending prompt to Claude CLI: {len(prompt_bytes)} bytes")
            try:
                process.stdin.write(prompt_bytes)
                await process.stdin.drain()
                process.stdin.close()
            except BrokenPipeError:
                # Claude CLI crashed before accepting input - check stderr
                stderr = await process.stderr.read()
                logger.error(f"Claude CLI crashed on stdin: {stderr.decode()[:500]}")
                return None, []

            # Read stdout in streaming mode with incremental UTF-8 decoder
            # This handles multi-byte UTF-8 characters split across chunk boundaries
            output_chunks = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        chunk = await process.stdout.read(1024)
                        if not chunk:
                            # Flush remaining bytes
                            decoded = decoder.decode(b"", final=True)
                            if decoded:
                                output_chunks.append(decoded)
                                if on_chunk:
                                    await on_chunk(decoded)
                            break
                        # Incremental decode - handles partial multi-byte chars
                        decoded = decoder.decode(chunk)
                        if decoded:
                            output_chunks.append(decoded)
                            # Emit chunk for streaming
                            if on_chunk:
                                await on_chunk(decoded)
                            logger.debug(f"Claude CLI chunk: {len(decoded)} chars")
            except asyncio.TimeoutError:
                logger.error(f"Claude CLI timed out after {self.timeout}s")
                process.kill()
                return None, []

            await process.wait()

            if process.returncode != 0:
                stderr = await process.stderr.read()
                logger.error(f"Claude CLI failed: {stderr.decode()}")
                return None, []

            raw_output = "".join(output_chunks)
            model_usage_list: list[ModelUsageInfo] = []
            output = ""

            # Log raw output for debugging
            logger.info(f"Claude CLI raw output length: {len(raw_output)}")
            if len(raw_output) < 2000:
                logger.debug(f"Claude CLI raw output: {raw_output}")

            # Parse stream-json output (NDJSON - one JSON per line)
            # Look for the "result" type line which contains final output and costs
            for line in raw_output.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    event_type = event.get("type")
                    logger.debug(f"Stream event type: {event_type}")

                    if event_type == "result":
                        # Final result with content and model usage
                        output = event.get("result", "")

                        # Extract model usage
                        model_usage = event.get("modelUsage", {})
                        if model_usage:
                            models_used = list(model_usage.keys())
                            logger.info(f"Claude CLI models used: {models_used}")
                            for model_name, usage in model_usage.items():
                                info = ModelUsageInfo(
                                    model=model_name,
                                    input_tokens=usage.get("inputTokens", 0),
                                    output_tokens=usage.get("outputTokens", 0),
                                    cache_read_tokens=usage.get("cacheReadInputTokens", 0),
                                    cache_creation_tokens=usage.get("cacheCreationInputTokens", 0),
                                    cost_usd=usage.get("costUSD", 0.0),
                                )
                                model_usage_list.append(info)
                                logger.info(
                                    f"  {model_name}: in={info.input_tokens}, "
                                    f"out={info.output_tokens}, cost=${info.cost_usd:.4f}"
                                )

                        # Log total cost
                        total_cost = event.get("total_cost_usd", 0)
                        logger.info(f"Total cost: ${total_cost:.4f}")

                except json.JSONDecodeError:
                    # Skip non-JSON lines
                    continue

            # Fallback if no result found
            if not output:
                logger.warning("No result found in stream-json output, using raw")
                logger.warning(f"Raw output first 500 chars: {raw_output[:500]}")
                output = raw_output

            logger.info(f"Claude CLI completed, output length: {len(output)}")
            logger.info(f"Output first 200 chars: {output[:200] if output else 'EMPTY'}")
            return output, model_usage_list

        except FileNotFoundError:
            logger.error(f"Claude CLI not found at: {self.cli_path}")
            return None, []
        except Exception as e:
            logger.exception(f"Claude CLI error: {e}")
            return None, []

    def _parse_response(
        self,
        response_text: str,
        file_list: list[str],
    ) -> ReviewOutput:
        """Parse Claude's response into ReviewOutput."""
        try:
            # Try to extract JSON from response
            json_text = response_text.strip()

            # Handle markdown code blocks
            if json_text.startswith("```"):
                lines = json_text.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```"):
                        in_block = not in_block
                        continue
                    if in_block:
                        json_lines.append(line)
                json_text = "\n".join(json_lines)

            data = json.loads(json_text)

            # Build ReviewOutput from parsed data
            summary_data = data.get("summary", {})
            summary = ReviewSummary(
                files_reviewed=summary_data.get("files_reviewed", len(file_list)),
                critical_issues=summary_data.get("critical_issues", 0),
                high_issues=summary_data.get("high_issues", 0),
                medium_issues=summary_data.get("medium_issues", 0),
                low_issues=summary_data.get("low_issues", 0),
                score=summary_data.get("score", 10.0),
            )

            # Parse issues
            issues = []
            for issue_data in data.get("issues", []):
                try:
                    issue = Issue(
                        id=issue_data.get("id", f"{self.name.upper()}-ISSUE"),
                        severity=IssueSeverity(issue_data.get("severity", "MEDIUM")),
                        category=IssueCategory(issue_data.get("category", "style")),
                        rule=issue_data.get("rule"),
                        file=issue_data.get("file", "unknown"),
                        line=issue_data.get("line"),
                        title=issue_data.get("title", "Issue"),
                        description=issue_data.get("description", ""),
                        current_code=issue_data.get("current_code"),
                        suggested_fix=issue_data.get("suggested_fix"),
                        references=issue_data.get("references", []),
                        flagged_by=[self.name],
                    )
                    issues.append(issue)
                except Exception:
                    continue

            # Parse checklists
            checklists = {}
            for category, checks in data.get("checklists", {}).items():
                checklists[category] = ChecklistResult(
                    passed=checks.get("passed", 0),
                    failed=checks.get("failed", 0),
                    skipped=checks.get("skipped", 0),
                )

            # Parse metrics
            metrics_data = data.get("metrics", {})
            metrics = ReviewMetrics(
                complexity_avg=metrics_data.get("complexity_avg"),
                test_coverage=metrics_data.get("test_coverage"),
                type_coverage=metrics_data.get("type_coverage"),
            )

            return ReviewOutput(
                reviewer=self.name,
                summary=summary,
                issues=issues,
                checklists=checklists,
                metrics=metrics,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            return self._create_error_output(
                f"JSON parse error: {str(e)}\n\nRaw output:\n{response_text[:1000]}"
            )

    def _create_error_output(self, error_message: str) -> ReviewOutput:
        """Create an error ReviewOutput."""
        return ReviewOutput(
            reviewer=self.name,
            summary=ReviewSummary(
                files_reviewed=0,
                score=0.0,
            ),
            issues=[
                Issue(
                    id=f"{self.name.upper()}-ERROR",
                    severity=IssueSeverity.HIGH,
                    category=IssueCategory.DOCUMENTATION,
                    file="review_output",
                    title="Review failed",
                    description=error_message,
                )
            ],
        )
