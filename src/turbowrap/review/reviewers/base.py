"""
Base reviewer interface and context.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from turbowrap.review.models.review import ReviewOutput, ReviewRequest
from turbowrap.review.models.challenger import ChallengerFeedback


@dataclass
class ReviewContext:
    """Context passed to reviewers."""

    # Request info
    request: ReviewRequest

    # Files to review
    files: list[str] = field(default_factory=list)
    file_contents: dict[str, str] = field(default_factory=dict)

    # Git info
    diff: Optional[str] = None
    base_branch: Optional[str] = None
    current_branch: Optional[str] = None
    commit_sha: Optional[str] = None

    # Repository info
    repo_path: Optional[Path] = None
    repo_name: Optional[str] = None

    # Agent system prompt (from markdown files)
    agent_prompt: Optional[str] = None

    # Structure documentation (STRUCTURE.md files found in repo)
    structure_docs: dict[str, str] = field(default_factory=dict)

    # Previous review (for refinement)
    previous_review: Optional[ReviewOutput] = None
    challenger_feedback: Optional[ChallengerFeedback] = None

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

        Returns:
            Formatted STRUCTURE.md contents
        """
        if not self.structure_docs:
            return ""

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

    def _timed_execution(self, func):
        """Decorator to time execution."""
        async def wrapper(*args, **kwargs):
            start = time.time()
            result = await func(*args, **kwargs)
            duration = time.time() - start
            if hasattr(result, 'duration_seconds'):
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
