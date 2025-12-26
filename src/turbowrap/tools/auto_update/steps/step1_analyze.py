"""Step 1: Analyze codebase functionalities."""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from turbowrap.llm import GeminiClient

from ..models import Functionality, Step1Checkpoint, StepStatus
from ..storage.s3_checkpoint import S3CheckpointManager
from .base import BaseStep

logger = logging.getLogger(__name__)


class AnalyzeFunctionalitiesStep(BaseStep[Step1Checkpoint]):
    """Step 1: Analyze the codebase to extract existing functionalities.

    Uses Gemini to semantically analyze the codebase and identify
    major functionalities, their categories, and dependencies.
    """

    step_name = "step1_analyze"
    step_number = 1
    checkpoint_class = Step1Checkpoint

    def __init__(
        self,
        checkpoint_manager: S3CheckpointManager,
        repo_path: Path,
        gemini_client: GeminiClient | None = None,
    ):
        """Initialize step.

        Args:
            checkpoint_manager: S3 checkpoint manager.
            repo_path: Path to repository.
            gemini_client: Optional Gemini client (created if not provided).
        """
        super().__init__(checkpoint_manager, repo_path)
        self.gemini_client = gemini_client

    def _get_gemini_client(self) -> GeminiClient:
        """Get or create Gemini client."""
        if self.gemini_client is None:
            self.gemini_client = GeminiClient(model=self.settings.analysis_model)
        return self.gemini_client

    def _get_commit_sha(self) -> str | None:
        """Get current git commit SHA."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()[:40]
        except Exception:
            pass
        return None

    def _build_codebase_context(self) -> str:
        """Build context string from codebase structure.

        Returns:
            Markdown-formatted context about the codebase.
        """
        context_parts = []

        # Get directory structure
        src_path = self.repo_path / "src"
        if not src_path.exists():
            src_path = self.repo_path

        context_parts.append("## Project Structure\n")

        # List top-level directories
        for item in sorted(src_path.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                context_parts.append(f"- {item.name}/")

                # List subdirectories
                for subitem in sorted(item.iterdir()):
                    if subitem.is_dir() and not subitem.name.startswith("_"):
                        context_parts.append(f"  - {subitem.name}/")

        context_parts.append("")

        # Read key files for context
        key_files = [
            "README.md",
            "pyproject.toml",
            "package.json",
            "STRUCTURE.md",
        ]

        for filename in key_files:
            filepath = self.repo_path / filename
            if filepath.exists():
                try:
                    content = filepath.read_text()[:3000]
                    context_parts.append(f"## {filename}\n```\n{content}\n```\n")
                except Exception:
                    pass

        return "\n".join(context_parts)

    async def execute(
        self,
        previous_checkpoint: Step1Checkpoint | None = None,
        **kwargs: Any,
    ) -> Step1Checkpoint:
        """Execute Step 1: Analyze codebase functionalities.

        Args:
            previous_checkpoint: Previous checkpoint if resuming.
            **kwargs: Additional keyword arguments (unused).

        Returns:
            Step1Checkpoint with extracted functionalities.
        """
        # Skip if already completed
        if self.should_skip(previous_checkpoint):
            logger.info(f"{self.step_name} already completed, skipping")
            return previous_checkpoint  # type: ignore[return-value]

        checkpoint = Step1Checkpoint(
            step=self.step_name,
            status=StepStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
            repo_path=str(self.repo_path),
            commit_sha=self._get_commit_sha(),
        )

        try:
            logger.info(f"Analyzing codebase at {self.repo_path}")

            # Build codebase context
            context = self._build_codebase_context()

            # Extract functionalities using Gemini
            functionalities = await self._extract_functionalities(context)

            checkpoint.functionalities = functionalities
            checkpoint.status = StepStatus.COMPLETED
            checkpoint.completed_at = datetime.utcnow()

            logger.info(f"Extracted {len(functionalities)} functionalities")

        except Exception as e:
            logger.error(f"Step 1 failed: {e}")
            checkpoint.status = StepStatus.FAILED
            checkpoint.error = str(e)
            raise

        return checkpoint

    async def _extract_functionalities(self, context: str) -> list[Functionality]:
        """Use Gemini to extract functionalities from codebase.

        Args:
            context: Codebase context string.

        Returns:
            List of extracted functionalities.
        """
        gemini = self._get_gemini_client()

        prompt = f"""Analyze this software project and identify all major functionalities.

{context}

For each functionality, provide:
- **id**: Unique ID in kebab-case (e.g., "code-review-challenger")
- **name**: Descriptive name (e.g., "Code Review with Challenger Loop")
- **description**: 2-3 sentences explaining what it does
- **category**: One of: review, fix, linear, cli, api, core, tools, utils
- **files**: List of main files/modules involved (relative paths)
- **dependencies**: IDs of other functionalities it depends on
- **maturity**: One of: stable, beta, experimental

Focus on high-level features, not individual functions.
Group related capabilities into single functionalities.

Respond ONLY with valid JSON in this format:
{{
  "functionalities": [
    {{
      "id": "code-review-challenger",
      "name": "Code Review with Challenger Loop",
      "description": "Performs code review using Claude with Gemini challenger for validation. Implements iterative refinement until quality threshold is met.",
      "category": "review",
      "files": ["review/orchestrator.py", "review/challenger_loop.py"],
      "dependencies": ["llm-claude", "llm-gemini"],
      "maturity": "stable"
    }}
  ]
}}
"""

        result = gemini.generate(prompt)

        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = result
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                json_str = result.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())
            functionalities = []

            for item in data.get("functionalities", []):
                try:
                    func = Functionality(
                        id=item.get("id", "unknown"),
                        name=item.get("name", "Unknown"),
                        description=item.get("description", ""),
                        category=item.get("category", "core"),
                        files=item.get("files", []),
                        dependencies=item.get("dependencies", []),
                        maturity=item.get("maturity", "stable"),
                    )
                    functionalities.append(func)
                except Exception as e:
                    logger.warning(f"Failed to parse functionality: {e}")

            return functionalities

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            logger.debug(f"Response was: {result[:500]}")
            return []
