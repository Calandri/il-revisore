"""
Gemini CLI-based reviewer implementation.

Uses Gemini CLI subprocess for code review, allowing the model to autonomously
explore the codebase via its own file reading capabilities.

Uses turbowrap_llm package with TurboWrapTrackerAdapter for operation tracking.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from turbowrap_llm import GeminiCLI

from turbowrap.config import get_settings
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.reviewers.base_cli_reviewer import BaseCLIReviewer
from turbowrap.review.reviewers.constants import DEFAULT_CLI_TIMEOUT
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)


class GeminiCLIReviewer(BaseCLIReviewer):
    """
    Code reviewer using Gemini CLI.

    Mirrors ClaudeCLIReviewer pattern:
    1. Loads the specialist MD file (e.g., reviewer_be_architecture.md)
    2. Passes a list of files to analyze
    3. Runs Gemini CLI with cwd=repo_path
    4. Gemini CLI reads files autonomously

    Uses turbowrap_llm package with TurboWrapTrackerAdapter for operation tracking.
    """

    def __init__(
        self,
        name: str = "reviewer_be",
        timeout: int = DEFAULT_CLI_TIMEOUT,
    ):
        """
        Initialize Gemini CLI reviewer.

        Args:
            name: Reviewer identifier (reviewer_be_architecture, etc.)
            timeout: Timeout in seconds for CLI execution
        """
        super().__init__(name, model="gemini-cli", timeout=timeout)

    def _get_cli(self, context: ReviewContext) -> GeminiCLI:
        """Create GeminiCLI instance for this review context.

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

        return GeminiCLI(
            working_dir=context.repo_path,
            model="pro",  # Use Pro for comprehensive reviews
            artifact_saver=artifact_saver,
            tracker=tracker,
        )

    def _get_output_file_suffix(self) -> str:
        """Return Gemini-specific file suffix."""
        return "_gemini"

    async def _run_cli(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Run Gemini CLI using turbowrap_llm package (with operation tracking).

        Args:
            prompt: The prompt to send to Gemini CLI
            context: Review context with repo path
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, error message or None)
        """
        try:
            # Run Gemini CLI with turbowrap_llm package
            # Tracker adapter handles all operation tracking automatically
            cli = self._get_cli(context)
            result = await cli.run(
                prompt=prompt,
                on_chunk=on_chunk,
            )

            if not result.success:
                return None, result.error or "GeminiCLI failed"

            return result.output, None

        except FileNotFoundError:
            logger.error("[GEMINI CLI] Not found")
            return None, "Gemini CLI not found"
        except Exception as e:
            logger.exception(f"[GEMINI CLI] Exception: {e}")
            return None, f"CLI exception: {e}"

    async def _run_cli_and_read_output(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Run Gemini CLI and read output (with stdout JSON extraction fallback).

        Strategy:
        1. Ask Gemini to write JSON to file (most reliable)
        2. If file doesn't exist or is invalid, fallback to extracting from stdout

        Args:
            prompt: The prompt to send to Gemini CLI
            context: Review context with repo path
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, error message or None)
        """
        # Output file path (Gemini should write here)
        output_file = self._get_output_file_path(context)
        output_filename = output_file.name

        # Delete old output file if exists
        if output_file.exists():
            self._cleanup_file(output_file)

        # Run CLI
        raw_output, error = await self._run_cli(prompt, context, on_chunk)

        if error:
            return None, error

        # Strategy 1: Read from file at expected path
        output = None
        if output_file.exists():
            try:
                file_content = output_file.read_text(encoding="utf-8").strip()
                if file_content.startswith("{") and file_content.endswith("}"):
                    output = file_content
                    logger.info(f"[GEMINI CLI] Read JSON from file: {len(output)} chars")
                else:
                    logger.warning(
                        f"[GEMINI CLI] File content is not valid JSON: {file_content[:100]}"
                    )
            except Exception as e:
                logger.warning(f"[GEMINI CLI] Failed to read output file: {e}")
            finally:
                self._cleanup_file(output_file)

        # Strategy 1b: Search recursively if file not found (monorepo workaround)
        if output is None and context.repo_path:
            try:
                found_files = list(context.repo_path.rglob(output_filename))
                if found_files:
                    found_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    found_file = found_files[0]
                    logger.warning(
                        f"[GEMINI CLI] File not at expected path, found at: {found_file}"
                    )
                    file_content = found_file.read_text(encoding="utf-8").strip()
                    if file_content.startswith("{") and file_content.endswith("}"):
                        output = file_content
                        logger.info(
                            f"[GEMINI CLI] Read JSON from fallback path: {len(output)} chars"
                        )
                    for f in found_files:
                        self._cleanup_file(f)
            except Exception as e:
                logger.warning(f"[GEMINI CLI] Recursive file search failed: {e}")

        # Strategy 2: Fallback to extracting JSON from stdout
        if output is None and raw_output and "{" in raw_output:
            first_brace = raw_output.find("{")
            last_brace = raw_output.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                output = raw_output[first_brace : last_brace + 1]
                logger.info(
                    f"[GEMINI CLI] Fallback: extracted JSON from stdout: {len(output)} chars"
                )

        if output is None:
            output_preview = raw_output[:300] if raw_output else "None"
            logger.error(f"[GEMINI CLI] No valid JSON found. CLI result: {output_preview}")
            return None, f"No valid JSON in output: {output_preview}"

        return output, None

    # review(), refine(), _build_review_prompt(), _build_refinement_prompt(),
    # _parse_response() are inherited from BaseCLIReviewer
    # _create_error_output() is inherited from BaseReviewer
