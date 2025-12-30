"""
CLI runner utilities for TurboWrap orchestrators.

Provides:
- CLIRunner: Unified facade for Claude and Gemini CLI
- Re-exports ClaudeCLI and GeminiCLI from llm package
"""

from datetime import datetime
from pathlib import Path

# Re-export ClaudeCLI from llm package
from turbowrap.llm.claude_cli import ClaudeCLI, ClaudeCLIResult, ModelUsage

# Re-export GeminiCLI from llm package
from turbowrap.llm.gemini import (
    GEMINI_MODEL_MAP,
    GeminiCLI,
    GeminiCLIResult,
    GeminiModelType,
)


class CLIRunner:
    """
    Unified CLI runner facade for Claude and Gemini.

    Provides a consistent interface for running either CLI with
    common configuration and error handling.

    Usage:
        runner = CLIRunner(repo_path, s3_prefix="fix")

        # Run Claude for fixing
        result = await runner.run_claude(prompt, thinking_budget=16000)

        # Run Gemini for review
        result = await runner.run_gemini(prompt)

        # Get CLI instances for custom configuration
        claude = runner.get_claude_cli(model="haiku")
        gemini = runner.get_gemini_cli(model="flash")
    """

    def __init__(
        self,
        working_dir: Path,
        s3_prefix: str = "cli",
        claude_model: str | None = None,
        gemini_model: str | None = None,
        claude_timeout: int = 900,
        gemini_timeout: int = 300,
    ):
        """
        Initialize CLI runner.

        Args:
            working_dir: Working directory for CLI processes
            s3_prefix: S3 prefix for logging
            claude_model: Claude model override
            gemini_model: Gemini model override
            claude_timeout: Timeout for Claude CLI
            gemini_timeout: Timeout for Gemini CLI
        """
        self.working_dir = working_dir
        self.s3_prefix = s3_prefix
        self.claude_model = claude_model
        self.gemini_model = gemini_model
        self.claude_timeout = claude_timeout
        self.gemini_timeout = gemini_timeout

    def get_claude_cli(
        self,
        model: str | None = None,
        timeout: int | None = None,
        agent_md_path: Path | None = None,
    ) -> ClaudeCLI:
        """
        Create a ClaudeCLI instance.

        Args:
            model: Override model (uses runner default if not provided)
            timeout: Override timeout (uses runner default if not provided)
            agent_md_path: Optional agent instructions file

        Returns:
            Configured ClaudeCLI instance
        """
        return ClaudeCLI(
            working_dir=self.working_dir,
            model=model or self.claude_model or "opus",
            timeout=timeout or self.claude_timeout,
            s3_prefix=self.s3_prefix,
            agent_md_path=agent_md_path,
        )

    def get_gemini_cli(
        self,
        model: str | None = None,
        timeout: int | None = None,
    ) -> GeminiCLI:
        """
        Create a GeminiCLI instance.

        Args:
            model: Override model (uses runner default if not provided)
            timeout: Override timeout (uses runner default if not provided)

        Returns:
            Configured GeminiCLI instance
        """
        return GeminiCLI(
            working_dir=self.working_dir,
            model=model or self.gemini_model or "pro",
            timeout=timeout or self.gemini_timeout,
        )

    async def run_claude(
        self,
        prompt: str,
        operation_type: str,
        repo_name: str,
        context_id: str | None = None,
        thinking_budget: int | None = None,
    ) -> ClaudeCLIResult:
        """
        Run Claude CLI with prompt.

        Args:
            prompt: The prompt to send
            operation_type: Operation type ("fix", "review", etc.) - REQUIRED
            repo_name: Repository name for tracking - REQUIRED
            context_id: Optional ID for S3 logging
            thinking_budget: Override thinking budget

        Returns:
            ClaudeCLIResult with output and metadata
        """
        cli = self.get_claude_cli()
        return await cli.run(
            prompt=prompt,
            operation_type=operation_type,
            repo_name=repo_name,
            context_id=context_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            thinking_budget=thinking_budget,
        )

    async def run_gemini(
        self,
        prompt: str,
        operation_type: str,
        repo_name: str,
        context_id: str | None = None,
    ) -> GeminiCLIResult:
        """
        Run Gemini CLI with prompt.

        Args:
            prompt: The prompt to send
            operation_type: Operation type ("review", "git_merge", etc.) - REQUIRED
            repo_name: Repository name for tracking - REQUIRED
            context_id: Optional ID for S3 logging

        Returns:
            GeminiCLIResult with output
        """
        cli = self.get_gemini_cli()
        return await cli.run(
            prompt=prompt,
            operation_type=operation_type,
            repo_name=repo_name,
            context_id=context_id,
        )


# Re-exports for convenience
__all__ = [
    "ClaudeCLI",
    "ClaudeCLIResult",
    "ModelUsage",
    "GeminiCLI",
    "GeminiCLIResult",
    "GeminiModelType",
    "CLIRunner",
    "GEMINI_MODEL_MAP",
]
