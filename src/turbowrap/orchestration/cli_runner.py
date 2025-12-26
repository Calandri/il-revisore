"""
CLI runner utilities for TurboWrap orchestrators.

Provides:
- GeminiCLI: Gemini CLI runner for review/evaluation tasks
- CLIRunner: Unified facade for Claude and Gemini CLI
- Re-exports ClaudeCLI from utils for convenience
"""

import asyncio
import codecs
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from turbowrap.config import get_settings
from turbowrap.utils.aws_secrets import get_google_api_key

# Re-export ClaudeCLI for convenience
from turbowrap.utils.claude_cli import ClaudeCLI, ClaudeCLIResult, ModelUsage

logger = logging.getLogger(__name__)

# Gemini model aliases
GeminiModelType = Literal["flash", "pro", "ultra"]
GEMINI_MODEL_MAP = {
    "flash": "gemini-2.0-flash-exp",
    "pro": "gemini-1.5-pro-002",
    "ultra": "gemini-ultra",
}

# Default timeouts
DEFAULT_GEMINI_TIMEOUT = 120


@dataclass
class GeminiCLIResult:
    """Result from Gemini CLI execution."""

    success: bool
    output: str
    raw_output: str | None = None
    duration_ms: int = 0
    model: str = ""
    error: str | None = None


class GeminiCLI:
    """
    Gemini CLI runner for review/evaluation tasks.

    Usage:
        cli = GeminiCLI(working_dir=repo_path)
        result = await cli.run("Evaluate this code change...")

        # With streaming
        async def on_chunk(text: str):
            print(text, end="")
        result = await cli.run("Review...", on_chunk=on_chunk)
    """

    def __init__(
        self,
        working_dir: Path | None = None,
        model: str | GeminiModelType | None = None,
        timeout: int = DEFAULT_GEMINI_TIMEOUT,
        yolo_mode: bool = True,
    ):
        """
        Initialize Gemini CLI runner.

        Args:
            working_dir: Working directory for CLI process
            model: Model name or type ("flash", "pro")
            timeout: Timeout in seconds
            yolo_mode: Enable --yolo flag (auto-approve tool calls)
        """
        self.settings = get_settings()
        self.working_dir = working_dir
        self.timeout = timeout
        self.yolo_mode = yolo_mode

        # Resolve model name
        if model is None:
            self.model = self.settings.agents.gemini_pro_model
        elif model in GEMINI_MODEL_MAP:
            self.model = GEMINI_MODEL_MAP[model]
        else:
            self.model = model

    async def run(
        self,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> GeminiCLIResult:
        """
        Execute Gemini CLI and return result.

        Args:
            prompt: The prompt to send
            on_chunk: Optional callback for streaming output

        Returns:
            GeminiCLIResult with output
        """
        import time

        start_time = time.time()

        try:
            # Build environment with API key
            env = os.environ.copy()
            api_key = get_google_api_key()
            if api_key:
                env["GEMINI_API_KEY"] = api_key

            # Build command
            args = ["gemini", "-m", self.model]
            if self.yolo_mode:
                args.append("--yolo")
            args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            logger.info(f"[GEMINI CLI] Starting with model: {self.model}")
            logger.info(f"[GEMINI CLI] Prompt length: {len(prompt)} chars")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # Stream stdout with incremental UTF-8 decoder
            output_chunks: list[str] = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

            async def read_stream() -> None:
                assert process.stdout is not None
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        # Flush remaining bytes
                        decoded = decoder.decode(b"", final=True)
                        if decoded:
                            output_chunks.append(decoded)
                            if on_chunk:
                                await on_chunk(decoded)
                        break
                    # Incremental decode - handles partial multi-byte chars
                    decoded = decoder.decode(chunk)
                    if decoded:
                        output_chunks.append(decoded)
                        if on_chunk:
                            await on_chunk(decoded)

            try:
                await asyncio.wait_for(read_stream(), timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.error(f"[GEMINI CLI] Timeout after {self.timeout}s")
                process.kill()
                return GeminiCLIResult(
                    success=False,
                    output="",
                    error=f"Timeout after {self.timeout}s",
                    model=self.model,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            await process.wait()

            duration_ms = int((time.time() - start_time) * 1000)
            output = "".join(output_chunks)

            if process.returncode != 0:
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = f"Exit code {process.returncode}: {stderr.decode()[:500]}"
                logger.error(f"[GEMINI CLI] Failed: {error_msg}")
                return GeminiCLIResult(
                    success=False,
                    output=output,
                    raw_output=output,
                    error=error_msg,
                    duration_ms=duration_ms,
                    model=self.model,
                )

            logger.info(f"[GEMINI CLI] Completed in {duration_ms}ms")
            return GeminiCLIResult(
                success=True,
                output=output,
                raw_output=output,
                duration_ms=duration_ms,
                model=self.model,
            )

        except FileNotFoundError:
            return GeminiCLIResult(
                success=False,
                output="",
                error="Gemini CLI not found",
                model=self.model,
            )
        except Exception as e:
            logger.exception(f"[GEMINI CLI] Error: {e}")
            return GeminiCLIResult(
                success=False,
                output="",
                error=str(e),
                model=self.model,
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
        gemini_timeout: int = 120,
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
        context_id: str | None = None,
        thinking_budget: int | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_stderr: Callable[[str], Awaitable[None]] | None = None,
    ) -> ClaudeCLIResult:
        """
        Run Claude CLI with prompt.

        Args:
            prompt: The prompt to send
            context_id: Optional ID for S3 logging
            thinking_budget: Override thinking budget
            on_chunk: Callback for streaming output
            on_stderr: Callback for stderr

        Returns:
            ClaudeCLIResult with output and metadata
        """
        cli = self.get_claude_cli()
        return await cli.run(
            prompt=prompt,
            context_id=context_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            thinking_budget=thinking_budget,
            on_chunk=on_chunk,
            on_stderr=on_stderr,
        )

    async def run_gemini(
        self,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> GeminiCLIResult:
        """
        Run Gemini CLI with prompt.

        Args:
            prompt: The prompt to send
            on_chunk: Callback for streaming output

        Returns:
            GeminiCLIResult with output
        """
        cli = self.get_gemini_cli()
        return await cli.run(prompt=prompt, on_chunk=on_chunk)


# Re-exports for convenience
__all__ = [
    "ClaudeCLI",
    "ClaudeCLIResult",
    "ModelUsage",
    "GeminiCLI",
    "GeminiCLIResult",
    "CLIRunner",
    "GEMINI_MODEL_MAP",
]
