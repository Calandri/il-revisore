"""
Base class for CLI-based reviewers.

Provides common functionality shared by ClaudeCLIReviewer, GeminiCLIReviewer,
and GrokCLIReviewer, eliminating code duplication.
"""

from __future__ import annotations

import contextlib
import logging
import time
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext
from turbowrap.review.reviewers.constants import DEFAULT_CLI_TIMEOUT
from turbowrap.review.reviewers.utils import parse_review_output

logger = logging.getLogger(__name__)


class BaseCLIReviewer(BaseReviewer):
    """
    Abstract base class for CLI-based reviewers.

    Provides common functionality:
    - __init__ with name, model, timeout, settings
    - _get_output_file_path() for review JSON output
    - _cleanup_file() for safe file deletion
    - _build_review_prompt() for constructing review prompts
    - _build_refinement_prompt() for constructing refinement prompts
    - _parse_response() for parsing CLI output
    - review() and refine() methods with shared logic

    Subclasses must implement:
    - _get_cli() to return the appropriate CLI instance
    - _get_output_file_suffix() to return the file suffix (e.g., "_gemini", "_grok")
    - _run_cli_and_read_output() for CLI-specific execution logic
    """

    def __init__(
        self,
        name: str,
        model: str,
        timeout: int = DEFAULT_CLI_TIMEOUT,
    ):
        """
        Initialize CLI reviewer.

        Args:
            name: Reviewer identifier (reviewer_be_architecture, etc.)
            model: Model identifier for base class
            timeout: Timeout in seconds for CLI execution
        """
        super().__init__(name, model=model)

        self.settings = get_settings()
        self.timeout = timeout

    @abstractmethod
    def _get_cli(self, context: ReviewContext) -> Any:
        """
        Create CLI instance for this review context.

        Args:
            context: Review context with repo path

        Returns:
            CLI instance (ClaudeCLI, GeminiCLI, or GrokCLI)
        """
        pass

    def _get_output_file_suffix(self) -> str:
        """
        Get the suffix for output filename.

        Override in subclasses to add CLI-specific suffixes.
        Default returns empty string (for Claude).

        Returns:
            File suffix (e.g., "_gemini", "_grok", or "")
        """
        return ""

    def _get_output_file_path(self, context: ReviewContext) -> Path:
        """
        Get the output file path for review JSON.

        For monorepos, saves inside workspace subdirectory.

        Args:
            context: Review context with repo and workspace paths

        Returns:
            Path to the output file
        """
        suffix = self._get_output_file_suffix()
        output_filename = f".turbowrap_review_{self.name}{suffix}.json"
        if context.repo_path:
            if context.workspace_path:
                return context.repo_path / context.workspace_path / output_filename
            return context.repo_path / output_filename
        return Path(output_filename)

    def _cleanup_file(self, path: Path) -> None:
        """Safely delete a file, ignoring errors."""
        with contextlib.suppress(Exception):
            path.unlink()

    @abstractmethod
    async def _run_cli_and_read_output(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, str | None]:
        """
        Run CLI and read output from file (with stdout fallback).

        Args:
            prompt: The prompt to send to CLI
            context: Review context with repo path and metadata
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, error message or None)
        """
        pass

    async def review(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ReviewOutput:
        """
        Perform code review using CLI.

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
            return self._create_error_output(error or "No output from CLI")

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
            return self._create_error_output(error or "No output from CLI")

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
        """Build the review prompt for CLI."""
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
        """Build the refinement prompt for CLI."""
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
        """Parse CLI response into ReviewOutput using centralized parser."""
        return parse_review_output(response_text, self.name, len(file_list))

    # _create_error_output() is inherited from BaseReviewer
