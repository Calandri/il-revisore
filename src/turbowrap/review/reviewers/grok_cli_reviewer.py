"""
Grok CLI-based reviewer implementation.

Uses Grok CLI subprocess for code review, allowing the model to autonomously
explore the codebase via its own file reading capabilities.

Mirrors the GeminiCLIReviewer pattern but with Grok CLI execution.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from turbowrap.llm.grok import DEFAULT_GROK_MODEL, GrokCLI
from turbowrap.review.reviewers.base import ReviewContext
from turbowrap.review.reviewers.base_cli_reviewer import BaseCLIReviewer
from turbowrap.review.reviewers.constants import DEFAULT_CLI_TIMEOUT

logger = logging.getLogger(__name__)


class GrokCLIReviewer(BaseCLIReviewer):
    """
    Code reviewer using Grok CLI.

    Mirrors GeminiCLIReviewer pattern:
    1. Loads the specialist MD file (e.g., reviewer_be_architecture.md)
    2. Passes a list of files to analyze
    3. Runs Grok CLI with cwd=repo_path
    4. Grok CLI reads files autonomously
    """

    def __init__(
        self,
        name: str = "reviewer_be",
        timeout: int = DEFAULT_CLI_TIMEOUT,
        cli_path: str = "grok",
        model: str | None = None,
    ):
        """
        Initialize Grok CLI reviewer.

        Args:
            name: Reviewer identifier (reviewer_be_architecture, etc.)
            timeout: Timeout in seconds for CLI execution
            cli_path: Path to Grok CLI executable
            model: Model to use (defaults to grok-4-1-fast-reasoning)
        """
        super().__init__(name, model=model or DEFAULT_GROK_MODEL, timeout=timeout)
        self.cli_path = cli_path
        self.grok_model = model or DEFAULT_GROK_MODEL

    def _get_cli(self, context: ReviewContext) -> GrokCLI:
        """Create GrokCLI instance for this review context."""
        return GrokCLI(
            working_dir=context.repo_path,
            model=self.grok_model,
            s3_prefix=f"reviews/{self.name}",
        )

    def _get_output_file_suffix(self) -> str:
        """Return Grok-specific file suffix."""
        return "_grok"

    async def _run_cli(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Run Grok CLI using centralized GrokCLI class (with operation tracking).

        Args:
            prompt: The prompt to send to Grok CLI
            context: Review context with repo path
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, error message or None)
        """
        try:
            cli = self._get_cli(context)
            repo_name = context.repo_path.name if context.repo_path else "unknown"
            review_id = (
                context.metadata.get("review_id", "unknown") if context.metadata else "unknown"
            )

            result = await cli.run(
                prompt,
                operation_type="review",
                repo_name=repo_name,
                context_id=f"{review_id}_{self.name}",
                save_prompt=True,
                save_output=True,
                on_chunk=on_chunk,
                track_operation=True,
                user_name="system",
                operation_details={
                    "reviewer": self.name,
                    "workspace_path": context.workspace_path,
                },
            )

            if not result.success:
                return None, result.error or "GrokCLI failed"

            return result.output, None

        except FileNotFoundError:
            logger.error(f"[GROK CLI] Not found at: {self.cli_path}")
            return (
                None,
                f"CLI not found at: {self.cli_path}. Install: npm install -g @vibe-kit/grok-cli",
            )
        except Exception as e:
            logger.exception(f"[GROK CLI] Exception: {e}")
            return None, f"CLI exception: {e}"

    async def _run_cli_and_read_output(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Run Grok CLI and read output (with file and stdout JSON extraction).

        Strategy:
        1. Ask Grok to write JSON to file (most reliable)
        2. If file doesn't exist or is invalid, fallback to extracting from stdout

        Args:
            prompt: The prompt to send to Grok CLI
            context: Review context with repo path
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, error message or None)
        """
        # Output file path (Grok should write here)
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
                    logger.info(f"[GROK CLI] Read JSON from file: {len(output)} chars")
                else:
                    logger.warning(
                        f"[GROK CLI] File content is not valid JSON: {file_content[:100]}"
                    )
            except Exception as e:
                logger.warning(f"[GROK CLI] Failed to read output file: {e}")
            finally:
                self._cleanup_file(output_file)

        # Strategy 1b: Search recursively if file not found (monorepo workaround)
        if output is None and context.repo_path:
            try:
                found_files = list(context.repo_path.rglob(output_filename))
                if found_files:
                    found_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    found_file = found_files[0]
                    logger.warning(f"[GROK CLI] File not at expected path, found at: {found_file}")
                    file_content = found_file.read_text(encoding="utf-8").strip()
                    if file_content.startswith("{") and file_content.endswith("}"):
                        output = file_content
                        logger.info(f"[GROK CLI] Read JSON from fallback path: {len(output)} chars")
                    for f in found_files:
                        self._cleanup_file(f)
            except Exception as e:
                logger.warning(f"[GROK CLI] Recursive file search failed: {e}")

        # Strategy 2: Fallback to extracting JSON from stdout
        if output is None and raw_output and "{" in raw_output:
            first_brace = raw_output.find("{")
            last_brace = raw_output.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                output = raw_output[first_brace : last_brace + 1]
                logger.info(f"[GROK CLI] Fallback: extracted JSON from stdout: {len(output)} chars")

        if output is None:
            output_preview = raw_output[:300] if raw_output else "None"
            logger.error(f"[GROK CLI] No valid JSON found. CLI result: {output_preview}")
            return None, f"No valid JSON in output: {output_preview}"

        return output, None

    # review(), refine(), _build_review_prompt(), _build_refinement_prompt(),
    # _parse_response() are inherited from BaseCLIReviewer
    # _create_error_output() is inherited from BaseReviewer
