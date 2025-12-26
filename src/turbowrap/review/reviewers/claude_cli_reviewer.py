"""
Claude CLI-based reviewer implementation.

Uses Claude CLI subprocess instead of SDK, allowing the model to autonomously
explore the codebase via its own file reading capabilities.

Uses the centralized ClaudeCLI utility for Claude CLI subprocess execution.
"""

import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import ModelUsageInfo, ReviewOutput
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext
from turbowrap.review.reviewers.utils import parse_review_output
from turbowrap.utils.claude_cli import ClaudeCLI, ModelUsage

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

    Uses the centralized ClaudeCLI utility for Claude CLI execution.
    """

    def __init__(
        self,
        name: str = "reviewer_be",
        timeout: int = CLAUDE_CLI_TIMEOUT,
    ):
        """
        Initialize Claude CLI reviewer.

        Args:
            name: Reviewer identifier (reviewer_be_architecture, etc.)
            timeout: Timeout in seconds for CLI execution
        """
        super().__init__(name, model="claude-cli")

        self.settings = get_settings()
        self.timeout = timeout

    def _get_claude_cli(self, context: ReviewContext) -> ClaudeCLI:
        """Create ClaudeCLI instance for this review context."""
        return ClaudeCLI(
            working_dir=context.repo_path,
            model="opus",  # Use Opus for comprehensive reviews
            timeout=self.timeout,
            s3_prefix=f"reviews/{self.name}",
        )

    def _get_output_file_path(self, context: ReviewContext) -> Path:
        """
        Get the output file path for review JSON.

        For monorepos, saves inside workspace subdirectory.

        Args:
            context: Review context with repo and workspace paths

        Returns:
            Path to the output file
        """
        output_filename = f".turbowrap_review_{self.name}.json"
        if context.repo_path:
            if context.workspace_path:
                return context.repo_path / context.workspace_path / output_filename
            return context.repo_path / output_filename
        return Path(output_filename)

    def _cleanup_file(self, path: Path) -> None:
        """Safely delete a file, ignoring errors."""
        with contextlib.suppress(Exception):
            path.unlink()

    def _convert_model_usage(self, usage_list: list[ModelUsage]) -> list[ModelUsageInfo]:
        """Convert ClaudeCLI ModelUsage to review ModelUsageInfo."""
        return [
            ModelUsageInfo(
                model=u.model,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_creation_tokens=u.cache_creation_tokens,
                cost_usd=u.cost_usd,
            )
            for u in usage_list
        ]

    async def _run_cli_and_read_output(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[ModelUsageInfo], str | None]:
        """
        Run Claude CLI and read output from file (with stdout fallback).

        Uses the centralized ClaudeCLI utility for execution and S3 logging.

        Strategy:
        1. Ask Claude to write JSON to file (most reliable)
        2. If file doesn't exist or is invalid, fallback to extracting from stdout

        Args:
            prompt: The prompt to send to Claude CLI
            context: Review context with repo path and metadata
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, model usage list, error message or None)
        """
        # Output file path (Claude should write here)
        output_file = self._get_output_file_path(context)
        output_filename = output_file.name

        # Delete old output file if exists
        if output_file.exists():
            self._cleanup_file(output_file)

        # Get review_id for S3 logging
        review_id = context.metadata.get("review_id", "unknown") if context.metadata else "unknown"

        # Run Claude CLI with centralized utility
        cli = self._get_claude_cli(context)
        result = await cli.run(
            prompt,
            context_id=f"{review_id}_{self.name}",
            save_prompt=True,
            save_output=True,
            save_thinking=True,
            on_chunk=on_chunk,
        )

        # Check if CLI failed
        if not result.success:
            return None, [], result.error or "Claude CLI failed to execute"

        # Convert model usage
        model_usage = self._convert_model_usage(result.model_usage)

        # Strategy 1: Read from file at expected path (Claude should have written it)
        output = None
        if output_file.exists():
            try:
                file_content = output_file.read_text(encoding="utf-8").strip()
                # Validate it looks like JSON object
                if file_content.startswith("{") and file_content.endswith("}"):
                    output = file_content
                    logger.info(f"[CLAUDE CLI] Read JSON from file: {len(output)} chars")
                else:
                    logger.warning(
                        f"[CLAUDE CLI] File content is not valid JSON: {file_content[:100]}"
                    )
            except Exception as e:
                logger.warning(f"[CLAUDE CLI] Failed to read output file: {e}")
            finally:
                # Clean up output file
                self._cleanup_file(output_file)

        # Strategy 1b: Search recursively if file not found at expected path (monorepo workaround)
        if output is None and context.repo_path:
            try:
                found_files = list(context.repo_path.rglob(output_filename))
                if found_files:
                    # Use the most recently modified file
                    found_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    found_file = found_files[0]
                    logger.warning(
                        f"[CLAUDE CLI] File not at expected path, found at: {found_file}"
                    )
                    file_content = found_file.read_text(encoding="utf-8").strip()
                    if file_content.startswith("{") and file_content.endswith("}"):
                        output = file_content
                        logger.info(
                            f"[CLAUDE CLI] Read JSON from fallback path: {len(output)} chars"
                        )
                    # Clean up all found files
                    for f in found_files:
                        self._cleanup_file(f)
            except Exception as e:
                logger.warning(f"[CLAUDE CLI] Recursive file search failed: {e}")

        # Strategy 2: Fallback to extracting from stdout
        if output is None and result.output and "{" in result.output:
            first_brace = result.output.find("{")
            last_brace = result.output.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                output = result.output[first_brace : last_brace + 1]
                logger.info(
                    f"[CLAUDE CLI] Fallback: extracted JSON from stdout: {len(output)} chars"
                )

        if output is None:
            logger.error(f"[CLAUDE CLI] No valid JSON found. CLI result: {result.output[:300]}")
            return (
                None,
                model_usage,
                f"Claude CLI did not produce valid JSON. Output: {result.output[:300]}",
            )

        return output, model_usage, None

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

        # Run CLI and read output from file
        output, model_usage, error = await self._run_cli_and_read_output(prompt, context, on_chunk)

        if error or output is None:
            return self._create_error_output(error or "No output from Claude CLI")

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

        # Run CLI and read output from file
        output, model_usage, error = await self._run_cli_and_read_output(prompt, context, on_chunk)

        if error or output is None:
            return self._create_error_output(error or "No output from Claude CLI")

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

        # Include business context if available
        if context.business_context:
            sections.append("## Business Context\n")
            sections.append(context.business_context)
            sections.append("\n\n---\n")

        # File list to analyze
        sections.append("## Files to Analyze\n")
        sections.append("Read and analyze the following files:\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        # Add workspace constraint for monorepos
        workspace_constraint = ""
        if context.workspace_path:
            workspace_constraint = f"""
## IMPORTANT: Monorepo Workspace Scope

This is a **monorepo** review. You MUST only analyze files within the workspace:
- **Workspace path**: `{context.workspace_path}/`
- **DO NOT** read or analyze files outside this workspace
- **DO NOT** navigate to other apps/packages in the monorepo
- If you need to explore imports, only follow them if they're within `{context.workspace_path}/`

"""
            sections.append(workspace_constraint)

        # Output file for this reviewer - use ABSOLUTE path
        output_file = str(self._get_output_file_path(context))

        # Adjust exploration instruction based on workspace
        if context.workspace_path:
            explore_instruction = f"**Explore within workspace only** - you can read other files in `{context.workspace_path}/` (imports, dependencies, tests) but NOT outside it"
        else:
            explore_instruction = "**Explore freely** - you can read other files (imports, dependencies, tests) if needed"

        sections.append(
            f"""
## Important Instructions

1. **Read the files** listed above using your file reading capabilities
2. {explore_instruction}
3. **Apply your expertise** from the system prompt above
4. **Output Format**: Use the JSON schema defined in your system prompt above
5. **CRITICAL**: Save output to the ABSOLUTE path: `{output_file}`

After writing, confirm with: "Review saved to {output_file}"
"""
        )

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

        # Include previous review (complete with all issues)
        sections.append("## Previous Review\n")
        sections.append(f"```json\n{previous_review.model_dump_json(indent=2)}\n```\n")

        sections.append("\n## Challenger Feedback\n")
        sections.append(feedback.to_refinement_prompt())

        sections.append("\n## Files to Re-analyze\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        # Output file for this reviewer - use ABSOLUTE path
        output_file = str(self._get_output_file_path(context))

        sections.append(
            f"""
## Refinement Instructions

1. **Read the files** again to verify the feedback
2. Address ALL missed issues identified by the challenger
3. Re-evaluate challenged issues and adjust if warranted
4. Incorporate suggested improvements
5. Maintain valid issues from the previous review
6. **CRITICAL**: Always save output to the ABSOLUTE path specified below

## IMPORTANT: Save output to file

WRITE the complete refined JSON to this file: `{output_file}`

After writing, confirm with: "Review saved to {output_file}"
"""
        )

        return "".join(sections)

    def _parse_response(
        self,
        response_text: str,
        file_list: list[str],
    ) -> ReviewOutput:
        """Parse Claude's response into ReviewOutput using centralized parser."""
        return parse_review_output(response_text, self.name, len(file_list))

    # _create_error_output() is inherited from BaseReviewer
