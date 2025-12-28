"""
Grok CLI-based reviewer implementation.

Uses Grok CLI subprocess for code review, allowing the model to autonomously
explore the codebase via its own file reading capabilities.

Mirrors the GeminiCLIReviewer pattern but with Grok CLI execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from turbowrap.config import get_settings
from turbowrap.llm.grok import DEFAULT_GROK_MODEL
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext
from turbowrap.review.reviewers.utils import parse_review_output
from turbowrap.utils.aws_secrets import get_grok_api_key

logger = logging.getLogger(__name__)

# Timeouts
GROK_CLI_TIMEOUT = 300  # 5 minutes per review


class GrokCLIReviewer(BaseReviewer):
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
        timeout: int = GROK_CLI_TIMEOUT,
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
        super().__init__(name, model=model or DEFAULT_GROK_MODEL)

        self.settings = get_settings()
        self.timeout = timeout
        self.cli_path = cli_path
        self.grok_model = model or DEFAULT_GROK_MODEL

    def _get_output_file_path(self, context: ReviewContext) -> Path:
        """
        Get the output file path for review JSON.

        For monorepos, saves inside workspace subdirectory.

        Args:
            context: Review context with repo and workspace paths

        Returns:
            Path to the output file
        """
        output_filename = f".turbowrap_review_{self.name}_grok.json"
        if context.repo_path:
            if context.workspace_path:
                return context.repo_path / context.workspace_path / output_filename
            return context.repo_path / output_filename
        return Path(output_filename)

    def _cleanup_file(self, path: Path) -> None:
        """Safely delete a file, ignoring errors."""
        with contextlib.suppress(Exception):
            path.unlink()

    async def _run_cli(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Run Grok CLI and capture output.

        Args:
            prompt: The prompt to send to Grok CLI
            context: Review context with repo path
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, error message or None)
        """
        cwd = str(context.repo_path) if context.repo_path else None

        try:
            # Build environment with API key
            env = os.environ.copy()
            api_key = os.environ.get("GROK_API_KEY") or get_grok_api_key()
            if api_key:
                env["GROK_API_KEY"] = api_key

            # Build CLI arguments - use -p for headless mode with prompt
            args = [
                self.cli_path,
                "-m",
                self.grok_model,
                "--max-tool-rounds",
                "400",
                "-p",
                prompt,
            ]

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # Guard against None stdout
            if process.stdout is None:
                logger.error("[GROK CLI] stdout is not available")
                return None, "stdout not available"

            # Read stdout with streaming and JSONL parsing
            output_chunks: list[str] = []
            line_buffer = ""

            try:
                async with asyncio.timeout(self.timeout):  # type: ignore[attr-defined]
                    while True:
                        chunk = await process.stdout.read(4096)
                        if not chunk:
                            break

                        line_buffer += chunk.decode("utf-8", errors="replace")

                        # Parse JSONL lines
                        while "\n" in line_buffer:
                            line, line_buffer = line_buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue

                            try:
                                data: dict[str, Any] = json.loads(line)
                                role = data.get("role", "")
                                content = data.get("content", "")

                                if role == "assistant" and content:
                                    output_chunks.append(content)
                                    if on_chunk:
                                        await on_chunk(content)

                            except json.JSONDecodeError:
                                # Not JSON - raw output
                                output_chunks.append(line)
                                if on_chunk:
                                    await on_chunk(line + "\n")

            except asyncio.TimeoutError:
                logger.error(f"[GROK CLI] Timeout after {self.timeout}s")
                process.kill()
                return None, f"Timeout after {self.timeout}s"

            await process.wait()

            if process.returncode != 0:
                if process.stderr is not None:
                    stderr = await process.stderr.read()
                    error_msg = stderr.decode()[:500]
                    logger.error(f"[GROK CLI] Failed: {error_msg}")
                    return None, f"CLI failed: {error_msg}"
                logger.error("[GROK CLI] Failed with no stderr")
                return None, "CLI failed with no stderr"

            raw_output = "\n".join(output_chunks)
            return raw_output, None

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

    async def review(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ReviewOutput:
        """
        Perform code review using Grok CLI.

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

        # Run CLI and read output
        output, error = await self._run_cli_and_read_output(prompt, context, on_chunk)

        if error or output is None:
            return self._create_error_output(error or "No output from Grok CLI")

        # Parse the response
        review_output = self._parse_response(output, files_to_review)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()

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

        Note: In triple-LLM mode this is typically not used, but kept for compatibility.

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

        # Run CLI and read output
        output, error = await self._run_cli_and_read_output(prompt, context, on_chunk)

        if error or output is None:
            return self._create_error_output(error or "No output from Grok CLI")

        # Parse the response
        review_output = self._parse_response(output, files_to_review)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()
        review_output.iteration = previous_review.iteration + 1

        return review_output

    def _build_review_prompt(
        self,
        context: ReviewContext,
        file_list: list[str],
    ) -> str:
        """Build the review prompt for Grok CLI."""
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
            explore_instruction = (
                f"**Explore within workspace only** - you can read other files in "
                f"`{context.workspace_path}/` (imports, dependencies, tests) "
                f"but NOT outside it"
            )
        else:
            explore_instruction = (
                "**Explore freely** - you can read other files "
                "(imports, dependencies, tests) if needed"
            )

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
        """Build the refinement prompt for Grok CLI."""
        sections = []

        # Include specialist prompt
        if context.agent_prompt:
            sections.append(context.agent_prompt)
            sections.append("\n---\n")

        sections.append("# Review Refinement Request\n")

        # Include previous review
        sections.append("## Previous Review\n")
        sections.append(f"```json\n{previous_review.model_dump_json(indent=2)}\n```\n")

        sections.append("\n## Challenger Feedback\n")
        sections.append(feedback.to_refinement_prompt())

        sections.append("\n## Files to Re-analyze\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        # Output file - use ABSOLUTE path
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
        """Parse Grok's response into ReviewOutput using centralized parser."""
        return parse_review_output(response_text, self.name, len(file_list))

    # _create_error_output() is inherited from BaseReviewer
