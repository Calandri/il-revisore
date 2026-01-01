"""
Claude CLI-based reviewer implementation.

Uses Claude CLI subprocess instead of SDK, allowing the model to autonomously
explore the codebase via its own file reading capabilities.

Uses the turbowrap_llm package for Claude CLI execution with tracker integration.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from turbowrap_llm import ClaudeCLI

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import ModelUsageInfo, ReviewOutput
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.reviewers.base_cli_reviewer import BaseCLIReviewer
from turbowrap.review.reviewers.constants import DEFAULT_CLI_TIMEOUT
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)


class ClaudeCLIReviewer(BaseCLIReviewer):
    """
    Code reviewer using Claude CLI.

    Instead of passing file contents in the prompt, this reviewer:
    1. Loads the specialist MD file (e.g., reviewer_be_architecture.md)
    2. Passes a list of files to analyze
    3. Runs Claude CLI with cwd=repo_path
    4. Claude CLI reads files autonomously and can explore beyond the initial list

    Uses turbowrap_llm package with TurboWrapTrackerAdapter for operation tracking.
    """

    def __init__(
        self,
        name: str = "reviewer_be",
        timeout: int = DEFAULT_CLI_TIMEOUT,
    ):
        """
        Initialize Claude CLI reviewer.

        Args:
            name: Reviewer identifier (reviewer_be_architecture, etc.)
            timeout: Timeout in seconds for CLI execution
        """
        super().__init__(name, model="claude-cli", timeout=timeout)

    def _get_cli(self, context: ReviewContext) -> ClaudeCLI:
        """Create ClaudeCLI instance for this review context.

        Uses turbowrap_llm package with TurboWrapTrackerAdapter for operation tracking.
        """
        # Lazy import to avoid circular dependency
        from turbowrap.api.services.llm_adapters import TurboWrapTrackerAdapter
        from turbowrap.api.services.operation_tracker import OperationType, get_tracker

        settings = get_settings()

        # S3 artifact saver for prompts/outputs
        artifact_saver = S3ArtifactSaver(
            bucket=settings.thinking.s3_bucket,
            region=settings.thinking.s3_region,
            prefix=f"reviews/{self.name}",
        )

        # Get review metadata
        review_id = context.metadata.get("review_id", "unknown") if context.metadata else "unknown"
        repo_name = context.repo_path.name if context.repo_path else "unknown"

        # Create tracker adapter for operation visibility
        tracker = TurboWrapTrackerAdapter(
            tracker=get_tracker(),
            operation_type=OperationType.REVIEW,
            repo_name=repo_name,
            initial_details={
                "reviewer": self.name,
                "review_id": review_id,
                "workspace_path": context.workspace_path,
                "files_count": len(context.files) if context.files else 0,
            },
        )

        return ClaudeCLI(
            working_dir=context.repo_path,
            model="opus",  # Use Opus for comprehensive reviews
            thinking_enabled=True,
            artifact_saver=artifact_saver,
            tracker=tracker,
        )

    def _convert_model_usage(self, usage_list: list[Any]) -> list[ModelUsageInfo]:
        """Convert ClaudeCLI ModelUsage to review ModelUsageInfo."""
        return [
            ModelUsageInfo(
                model=getattr(u, "model", "unknown"),
                input_tokens=getattr(u, "input_tokens", 0),
                output_tokens=getattr(u, "output_tokens", 0),
                cache_read_tokens=getattr(u, "cache_read_tokens", 0),
                cache_creation_tokens=getattr(u, "cache_creation_tokens", 0),
                cost_usd=getattr(u, "cost_usd", 0.0),
            )
            for u in usage_list
        ]

    async def _run_cli_and_read_output_with_usage(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[ModelUsageInfo], str | None]:
        """
        Run Claude CLI and read output from file (with stdout fallback).

        Claude-specific implementation that also returns model usage information.

        Uses the turbowrap_llm package for execution with tracker integration.

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

        # Run Claude CLI with turbowrap_llm package
        # Tracker adapter handles all operation tracking automatically
        cli = self._get_cli(context)
        result = await cli.run(
            prompt=prompt,
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

    async def _run_cli_and_read_output(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Run CLI and read output (base class interface).

        This wraps the Claude-specific implementation to match base class signature.
        For full model usage, use _run_cli_and_read_output_with_usage directly.

        Args:
            prompt: The prompt to send to CLI
            context: Review context with repo path and metadata
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, error message or None)
        """
        output, _model_usage, error = await self._run_cli_and_read_output_with_usage(
            prompt, context, on_chunk
        )
        return output, error

    # Note: review() and refine() are overridden to capture model_usage from Claude CLI

    async def review(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ReviewOutput:
        """
        Perform code review using Claude CLI.

        Overrides base class to capture model usage information.

        Args:
            context: Review context with repo path and metadata
            file_list: Optional list of files to analyze (uses context.files if not provided)
            on_chunk: Optional callback for streaming output chunks

        Returns:
            ReviewOutput with findings and model usage
        """
        import time
        from datetime import datetime

        start_time = time.time()

        # Use provided file list or fall back to context
        files_to_review = file_list or context.files

        # Build the review prompt
        prompt = self._build_review_prompt(context, files_to_review)

        # Run CLI and read output from file (with model usage)
        output, model_usage, error = await self._run_cli_and_read_output_with_usage(
            prompt, context, on_chunk
        )

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

        Overrides base class to capture model usage information.

        Args:
            context: Original review context
            previous_review: Previous review output
            feedback: Challenger feedback to address
            file_list: Optional list of files
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Refined ReviewOutput with model usage
        """
        import time
        from datetime import datetime

        start_time = time.time()

        files_to_review = file_list or context.files

        # Build refinement prompt
        prompt = self._build_refinement_prompt(context, previous_review, feedback, files_to_review)

        # Run CLI and read output from file (with model usage)
        output, model_usage, error = await self._run_cli_and_read_output_with_usage(
            prompt, context, on_chunk
        )

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

    # _build_review_prompt, _build_refinement_prompt, _parse_response inherited from BaseCLIReviewer
    # _create_error_output() inherited from BaseReviewer
