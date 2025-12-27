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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings
from turbowrap.utils.aws_secrets import get_google_api_key

# Re-export ClaudeCLI for convenience
from turbowrap.utils.claude_cli import ClaudeCLI, ClaudeCLIResult, ModelUsage

logger = logging.getLogger(__name__)

# Gemini model aliases
GeminiModelType = Literal["flash", "pro", "ultra"]
GEMINI_MODEL_MAP = {
    "flash": "gemini-3-flash-preview",
    "pro": "gemini-3-pro-preview",
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
    s3_prompt_url: str | None = None
    s3_output_url: str | None = None


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
        auto_accept: bool = True,
        s3_prefix: str = "gemini-cli",
    ):
        """
        Initialize Gemini CLI runner.

        Args:
            working_dir: Working directory for CLI process
            model: Model name or type ("flash", "pro")
            timeout: Timeout in seconds
            auto_accept: Enable --auto-accept flag (auto-approve tool calls)
            s3_prefix: S3 path prefix for logs
        """
        self.settings = get_settings()
        self.working_dir = working_dir
        self.timeout = timeout
        self.auto_accept = auto_accept
        self.s3_prefix = s3_prefix

        # Resolve model name
        if model is None:
            self.model = self.settings.agents.gemini_pro_model
        elif model in GEMINI_MODEL_MAP:
            self.model = GEMINI_MODEL_MAP[model]
        else:
            self.model = model

        # S3 config
        self.s3_bucket = self.settings.thinking.s3_bucket
        self.s3_region = self.settings.thinking.s3_region
        self._s3_client: Any = None

    @property
    def s3_client(self) -> Any:
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    async def _save_to_s3(
        self,
        content: str,
        artifact_type: str,
        context_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Save artifact to S3.

        Args:
            content: Content to save
            artifact_type: "prompt", "output", or "error"
            context_id: Identifier for grouping artifacts
            metadata: Additional metadata to include

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.s3_bucket:
            return None

        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"{self.s3_prefix}/{timestamp}/{context_id}_{artifact_type}.md"

            # Build markdown content
            md_content = f"""# Gemini CLI {artifact_type.title()}

**Context ID**: {context_id}
**Timestamp**: {datetime.now(timezone.utc).isoformat()}
**Artifact Type**: {artifact_type}
**Model**: {metadata.get("model", self.model) if metadata else self.model}

---

## Content

```
{content}
```
"""

            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=md_content.encode("utf-8"),
                ContentType="text/markdown",
            )

            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"[GEMINI CLI] Saved {artifact_type} to S3: {s3_key}")
            return s3_url

        except ClientError as e:
            logger.warning(f"[GEMINI CLI] Failed to save to S3: {e}")
            return None

    async def run(
        self,
        prompt: str,
        context_id: str | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> GeminiCLIResult:
        """
        Execute Gemini CLI and return result.

        Args:
            prompt: The prompt to send
            context_id: Optional ID for S3 logging
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            on_chunk: Optional callback for streaming output

        Returns:
            GeminiCLIResult with output and S3 URLs
        """
        import time

        start_time = time.time()

        # Generate context ID if not provided
        if context_id is None:
            context_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Save prompt to S3 before running
        s3_prompt_url = None
        if save_prompt:
            s3_prompt_url = await self._save_to_s3(
                prompt, "prompt", context_id, {"model": self.model}
            )

        try:
            # Build environment with API key
            env = os.environ.copy()
            api_key = get_google_api_key()
            if api_key:
                env["GEMINI_API_KEY"] = api_key

            # Build command
            args = ["gemini", "--model", self.model]
            if self.auto_accept:
                args.append("--auto-accept")
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

                # Preserve partial output on timeout
                duration_ms = int((time.time() - start_time) * 1000)
                partial_output = "".join(output_chunks) if output_chunks else ""

                # Save error to S3
                s3_output_url = None
                if save_output:
                    await self._save_to_s3(
                        f"# Timeout Error\n\nTimeout after {self.timeout}s\n\n"
                        f"# Partial Output ({len(partial_output)} chars)\n\n{partial_output}",
                        "error",
                        context_id,
                        {"model": self.model, "duration_ms": duration_ms},
                    )

                return GeminiCLIResult(
                    success=False,
                    output=partial_output,
                    raw_output=partial_output if partial_output else None,
                    error=f"Timeout after {self.timeout}s",
                    model=self.model,
                    duration_ms=duration_ms,
                    s3_prompt_url=s3_prompt_url,
                    s3_output_url=s3_output_url,
                )

            await process.wait()

            duration_ms = int((time.time() - start_time) * 1000)
            output = "".join(output_chunks)

            # Save output to S3
            s3_output_url = None
            if save_output and output:
                s3_output_url = await self._save_to_s3(
                    output,
                    "output",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                )

            if process.returncode != 0:
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = f"Exit code {process.returncode}: {stderr.decode()[:500]}"
                logger.error(f"[GEMINI CLI] Failed: {error_msg}")

                # Save error to S3
                if save_output:
                    await self._save_to_s3(
                        f"# Error\n\n{error_msg}\n\n# Output\n\n{output}",
                        "error",
                        context_id,
                        {"model": self.model, "duration_ms": duration_ms},
                    )

                return GeminiCLIResult(
                    success=False,
                    output=output,
                    raw_output=output,
                    error=error_msg,
                    duration_ms=duration_ms,
                    model=self.model,
                    s3_prompt_url=s3_prompt_url,
                    s3_output_url=s3_output_url,
                )

            logger.info(f"[GEMINI CLI] Completed in {duration_ms}ms")
            return GeminiCLIResult(
                success=True,
                output=output,
                raw_output=output,
                duration_ms=duration_ms,
                model=self.model,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
            )

        except FileNotFoundError:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "Gemini CLI not found"
            if save_output:
                await self._save_to_s3(
                    f"# Error\n\n{error_msg}",
                    "error",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                )
            return GeminiCLIResult(
                success=False,
                output="",
                error=error_msg,
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
            )
        except Exception as e:
            logger.exception(f"[GEMINI CLI] Error: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            if save_output:
                await self._save_to_s3(
                    f"# Exception\n\n{e!s}",
                    "error",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                )
            return GeminiCLIResult(
                success=False,
                output="",
                error=str(e),
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
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
