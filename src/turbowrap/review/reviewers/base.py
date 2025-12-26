"""
Base reviewer interface and context.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import ReviewOutput, ReviewRequest, ReviewSummary

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from turbowrap.review.reviewers.utils.s3_logger import S3Logger


@dataclass
class ReviewContext:
    """Context passed to reviewers."""

    # Request info
    request: ReviewRequest

    # Files to review
    files: list[str] = field(default_factory=list)
    file_contents: dict[str, str] = field(default_factory=dict)

    # Git info
    diff: str | None = None
    base_branch: str | None = None
    current_branch: str | None = None
    commit_sha: str | None = None

    # Repository info
    repo_path: Path | None = None
    repo_name: str | None = None
    workspace_path: str | None = None  # Monorepo: subfolder to limit review scope

    # Agent system prompt (from markdown files)
    agent_prompt: str | None = None

    # Structure documentation (.llms/structure.xml)
    structure_docs: dict[str, str] = field(default_factory=dict)

    # Business context (extracted from structure.xml or provided)
    business_context: str | None = None

    # Previous review (for refinement)
    previous_review: ReviewOutput | None = None
    challenger_feedback: ChallengerFeedback | None = None

    # Metadata (e.g., review_id for S3 logging)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_files_summary(self) -> str:
        """Get a summary of files being reviewed."""
        if not self.files:
            return "No files to review"

        by_extension: dict[str, list[str]] = {}
        for f in self.files:
            ext = Path(f).suffix or "no extension"
            by_extension.setdefault(ext, []).append(f)

        lines = [f"Total files: {len(self.files)}"]
        for ext, files in sorted(by_extension.items()):
            lines.append(f"  {ext}: {len(files)} files")

        return "\n".join(lines)

    def get_structure_context(self) -> str:
        """
        Get structure documentation context.

        Handles both XML (.llms/structure.xml) and Markdown (STRUCTURE.md) formats.
        XML is wrapped in semantic tags for better LLM parsing.

        Returns:
            Formatted structure documentation
        """
        if not self.structure_docs:
            return ""

        # Check if we have XML format (single consolidated file)
        if "structure.xml" in self.structure_docs:
            xml_content = self.structure_docs["structure.xml"]
            return f"""## Repository Structure

<repository-structure>
{xml_content}
</repository-structure>
"""

        # Fallback: Markdown format (multiple STRUCTURE.md files)
        sections = ["## Repository Structure Documentation\n"]
        sections.append("The following STRUCTURE.md files describe the codebase architecture:\n")

        for path, content in sorted(self.structure_docs.items()):
            sections.append(f"### {path}\n")
            sections.append(f"{content}\n")
            sections.append("---\n")

        return "\n".join(sections)

    def get_code_context(self, max_chars: int = 100000) -> str:
        """
        Get concatenated code context for review.

        Includes structure documentation first, then file contents.

        Args:
            max_chars: Maximum characters to include

        Returns:
            Formatted code context
        """
        sections = []
        total_chars = 0

        # Include structure docs first (they don't count against max_chars)
        structure_context = self.get_structure_context()
        if structure_context:
            sections.append(structure_context)

        for file_path, content in self.file_contents.items():
            if total_chars + len(content) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 1000:
                    content = content[:remaining] + "\n... (truncated)"
                else:
                    sections.append(f"\n... ({len(self.file_contents) - len(sections)} more files)")
                    break

            sections.append(f"### {file_path}\n```\n{content}\n```\n")
            total_chars += len(content)

        return "\n".join(sections)


class BaseReviewer(ABC):
    """Base class for all reviewers."""

    def __init__(self, name: str, model: str):
        """
        Initialize reviewer.

        Args:
            name: Reviewer name/identifier
            model: Model identifier
        """
        self.name = name
        self.model = model

    @abstractmethod
    async def review(self, context: ReviewContext) -> ReviewOutput:
        """
        Perform code review.

        Args:
            context: Review context with files and metadata

        Returns:
            ReviewOutput with findings
        """
        pass

    @abstractmethod
    async def refine(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
    ) -> ReviewOutput:
        """
        Refine a previous review based on challenger feedback.

        Args:
            context: Original review context
            previous_review: Previous review output
            feedback: Challenger feedback to address

        Returns:
            Refined ReviewOutput
        """
        pass

    def _timed_execution(
        self, func: Callable[..., Coroutine[Any, Any, ReviewOutput]]
    ) -> Callable[..., Coroutine[Any, Any, ReviewOutput]]:
        """Decorator to time execution."""

        async def wrapper(*args: Any, **kwargs: Any) -> ReviewOutput:
            start = time.time()
            result = await func(*args, **kwargs)
            duration = time.time() - start
            if hasattr(result, "duration_seconds"):
                result.duration_seconds = duration
            return result

        return wrapper

    def load_agent_prompt(self, agents_dir: str | Path) -> str:
        """
        Load agent system prompt from markdown file.

        Args:
            agents_dir: Directory containing agent markdown files

        Returns:
            Agent prompt content
        """
        agents_dir = Path(agents_dir)
        agent_file = agents_dir / f"{self.name}.md"

        if not agent_file.exists():
            raise FileNotFoundError(f"Agent file not found: {agent_file}")

        content = agent_file.read_text()

        # Remove frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()

        return content

    def _create_error_output(self, error_message: str) -> ReviewOutput:
        """
        Create a ReviewOutput for error cases.

        Used when review execution fails. Does not create fake issues -
        the error is handled through normal error reporting channels.

        Args:
            error_message: Description of the error

        Returns:
            ReviewOutput with zero score and no issues
        """
        logger.error(f"[{self.name}] Review failed: {error_message}")
        return ReviewOutput(
            reviewer=self.name,
            summary=ReviewSummary(
                files_reviewed=0,
                score=0.0,
            ),
            issues=[],
        )


class S3LoggingMixin:
    """
    Mixin that provides S3 logging capabilities.

    Usage:
        class MyReviewer(BaseReviewer, S3LoggingMixin):
            async def review(self, context):
                # ... do review ...
                await self.log_review_to_s3(...)
    """

    _s3_logger: S3Logger | None = None

    @property
    def s3_logger(self) -> S3Logger:
        """Lazy-load S3 logger."""
        if self._s3_logger is None:
            from turbowrap.review.reviewers.utils.s3_logger import S3Logger

            self._s3_logger = S3Logger()
        return self._s3_logger

    async def log_thinking_to_s3(
        self,
        content: str,
        review_id: str,
        model: str,
        files_reviewed: int = 0,
    ) -> str | None:
        """Save thinking content to S3."""
        from turbowrap.review.reviewers.utils.s3_logger import S3ArtifactMetadata

        metadata = S3ArtifactMetadata(
            review_id=review_id,
            component=getattr(self, "name", "unknown"),
            model=model,
        )
        return await self.s3_logger.save_thinking(content, metadata, files_reviewed)

    async def log_review_to_s3(
        self,
        system_prompt: str,
        user_prompt: str,
        response: str,
        review_output: ReviewOutput,
        review_id: str,
        model: str,
    ) -> str | None:
        """Save complete review to S3."""
        from turbowrap.review.reviewers.utils.s3_logger import S3ArtifactMetadata

        metadata = S3ArtifactMetadata(
            review_id=review_id,
            component=getattr(self, "name", "unknown"),
            model=model,
        )
        return await self.s3_logger.save_review(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
            review_json=review_output.model_dump_json(indent=2),
            metadata=metadata,
            duration_seconds=review_output.duration_seconds,
            files_reviewed=review_output.summary.files_reviewed,
        )

    async def log_challenge_to_s3(
        self,
        prompt: str,
        response: str,
        feedback: ChallengerFeedback,
        review_id: str,
        model: str,
    ) -> str | None:
        """Save challenge feedback to S3."""
        from turbowrap.review.reviewers.utils.s3_logger import S3ArtifactMetadata

        metadata = S3ArtifactMetadata(
            review_id=review_id,
            component=getattr(self, "name", "unknown"),
            model=model,
        )
        return await self.s3_logger.save_challenge(
            prompt=prompt,
            response=response,
            feedback_json=feedback.model_dump_json(indent=2),
            metadata=metadata,
            iteration=feedback.iteration,
            satisfaction_score=feedback.satisfaction_score,
            status=feedback.status.value,
        )
