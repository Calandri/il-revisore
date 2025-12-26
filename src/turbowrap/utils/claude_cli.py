"""Centralized Claude CLI utility for TurboWrap.

This module provides a unified interface for running Claude CLI subprocess
across all TurboWrap components (reviewers, analyzers, fixers, etc.).

Features:
- Async-first with sync wrapper
- S3 logging for prompts, outputs, and thinking
- Agent MD file support for custom instructions
- Model selection (opus, sonnet, haiku)
- Extended thinking via MAX_THINKING_TOKENS
- stream-json output parsing
"""

import asyncio
import codecs
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings
from turbowrap.utils.aws_secrets import get_anthropic_api_key

logger = logging.getLogger(__name__)

# Model aliases
ModelType = Literal["opus", "sonnet", "haiku"]
MODEL_MAP = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-20250514",
    "haiku": "claude-haiku-3-5-20241022",
}

# Default timeout
DEFAULT_TIMEOUT = 180


@dataclass
class ModelUsage:
    """Token usage information from Claude CLI."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ClaudeCLIResult:
    """Result from Claude CLI execution."""

    success: bool
    output: str
    thinking: str | None = None
    raw_output: str | None = None
    model_usage: list[ModelUsage] = field(default_factory=list)
    duration_ms: int = 0
    model: str = ""
    error: str | None = None
    s3_prompt_url: str | None = None
    s3_output_url: str | None = None
    s3_thinking_url: str | None = None


class ClaudeCLI:
    """Centralized Claude CLI runner with S3 logging.

    Usage:
        # Basic usage
        cli = ClaudeCLI()
        result = await cli.run("Analyze this code...")

        # With agent MD file
        cli = ClaudeCLI(agent_md_path=Path("agents/reviewer_be.md"))
        result = await cli.run("Review the following files...")

        # With custom model and working directory
        cli = ClaudeCLI(model="haiku", working_dir=repo_path)
        result = await cli.run("Quick analysis...")

        # Sync wrapper
        result = cli.run_sync("Simple prompt")
    """

    def __init__(
        self,
        agent_md_path: Path | None = None,
        working_dir: Path | None = None,
        model: str | ModelType | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        s3_prefix: str = "claude-cli",
        verbose: bool = True,
        skip_permissions: bool = True,
    ):
        """Initialize Claude CLI runner.

        Args:
            agent_md_path: Path to agent MD file with instructions
            working_dir: Working directory for the CLI process
            model: Model name or type ("opus", "sonnet", "haiku"). Default: from settings
            timeout: Timeout in seconds
            s3_prefix: S3 path prefix for logs
            verbose: Enable --verbose flag (required for stream-json)
            skip_permissions: Enable --dangerously-skip-permissions flag
        """
        self.settings = get_settings()
        self.agent_md_path = agent_md_path
        self.working_dir = working_dir
        self.timeout = timeout
        self.s3_prefix = s3_prefix
        self.verbose = verbose
        self.skip_permissions = skip_permissions

        # Resolve model name
        if model is None:
            self.model = self.settings.agents.claude_model
        elif model in MODEL_MAP:
            self.model = MODEL_MAP[model]
        else:
            self.model = model

        # S3 config
        self.s3_bucket = self.settings.thinking.s3_bucket
        self.s3_region = self.settings.thinking.s3_region
        self._s3_client = None

        # Agent prompt cache
        self._agent_prompt: str | None = None

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    def load_agent_prompt(self) -> str | None:
        """Load agent prompt from MD file if configured."""
        if self._agent_prompt is not None:
            return self._agent_prompt

        if self.agent_md_path is None:
            return None

        if not self.agent_md_path.exists():
            logger.warning(f"Agent MD file not found: {self.agent_md_path}")
            return None

        self._agent_prompt = self.agent_md_path.read_text()
        return self._agent_prompt

    async def run(
        self,
        prompt: str,
        context_id: str | None = None,
        thinking_budget: int | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        save_thinking: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_stderr: Callable[[str], Awaitable[None]] | None = None,
    ) -> ClaudeCLIResult:
        """Execute Claude CLI and return structured result.

        Args:
            prompt: The prompt to send to Claude
            context_id: Optional ID for S3 logging (e.g., review_id, issue_id)
            thinking_budget: Override thinking budget (None = use default from config)
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            save_thinking: Save thinking to S3
            on_chunk: Callback for streaming output chunks
            on_stderr: Callback for streaming stderr (--verbose output)

        Returns:
            ClaudeCLIResult with output, thinking, usage info, and S3 URLs
        """
        start_time = time.time()

        # Build full prompt with agent instructions
        full_prompt = self._build_full_prompt(prompt)

        # Generate context ID if not provided
        if context_id is None:
            context_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # Save prompt to S3 before running
        s3_prompt_url = None
        if save_prompt:
            s3_prompt_url = await self._save_to_s3(
                full_prompt, "prompt", context_id, {"model": self.model}
            )

        # Run CLI
        output, model_usage, thinking, raw_output, error = await self._execute_cli(
            full_prompt, thinking_budget, on_chunk, on_stderr
        )

        duration_ms = int((time.time() - start_time) * 1000)

        if error:
            return ClaudeCLIResult(
                success=False,
                output="",
                error=error,
                duration_ms=duration_ms,
                model=self.model,
                s3_prompt_url=s3_prompt_url,
            )

        # Save output and thinking to S3
        s3_output_url = None
        s3_thinking_url = None

        if save_output and output:
            s3_output_url = await self._save_to_s3(
                output, "output", context_id, {"model": self.model, "duration_ms": duration_ms}
            )

        if save_thinking and thinking:
            s3_thinking_url = await self._save_to_s3(
                thinking, "thinking", context_id, {"model": self.model}
            )

        return ClaudeCLIResult(
            success=True,
            output=output or "",
            thinking=thinking,
            raw_output=raw_output,
            model_usage=model_usage,
            duration_ms=duration_ms,
            model=self.model,
            s3_prompt_url=s3_prompt_url,
            s3_output_url=s3_output_url,
            s3_thinking_url=s3_thinking_url,
        )

    def run_sync(
        self,
        prompt: str,
        context_id: str | None = None,
        thinking_budget: int | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        save_thinking: bool = True,
    ) -> ClaudeCLIResult:
        """Sync wrapper for run().

        Use this when calling from non-async code.
        Note: Streaming callbacks are not supported in sync mode.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # Already in async context - create new event loop in thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self.run(
                        prompt=prompt,
                        context_id=context_id,
                        thinking_budget=thinking_budget,
                        save_prompt=save_prompt,
                        save_output=save_output,
                        save_thinking=save_thinking,
                    ),
                )
                return future.result()
        else:
            return asyncio.run(
                self.run(
                    prompt=prompt,
                    context_id=context_id,
                    thinking_budget=thinking_budget,
                    save_prompt=save_prompt,
                    save_output=save_output,
                    save_thinking=save_thinking,
                )
            )

    def _build_full_prompt(self, prompt: str) -> str:
        """Build full prompt with agent instructions."""
        agent_prompt = self.load_agent_prompt()
        if agent_prompt:
            return f"{agent_prompt}\n\n---\n\n{prompt}"
        return prompt

    async def _execute_cli(
        self,
        prompt: str,
        thinking_budget: int | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
        on_stderr: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[str | None, list[ModelUsage], str | None, str | None, str | None]:
        """Execute Claude CLI subprocess.

        Returns:
            Tuple of (output, model_usage, thinking, raw_output, error)
        """
        try:
            # Build environment
            env = os.environ.copy()

            # Get API key from AWS Secrets Manager or environment
            api_key = get_anthropic_api_key() or os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            else:
                return None, [], None, None, "ANTHROPIC_API_KEY not found"

            # Workaround: Bun file watcher bug on macOS /var/folders
            env["TMPDIR"] = "/tmp"

            # Set thinking budget
            if self.settings.thinking.enabled:
                budget = thinking_budget or self.settings.thinking.budget_tokens
                env["MAX_THINKING_TOKENS"] = str(budget)
                logger.info(f"[CLAUDE CLI] Extended thinking: {budget} tokens")

            # Build CLI arguments
            args = [
                "claude",
                "--print",
                "--model",
                self.model,
                "--output-format",
                "stream-json",
            ]

            if self.verbose:
                args.append("--verbose")

            if self.skip_permissions:
                args.append("--dangerously-skip-permissions")

            cwd = str(self.working_dir) if self.working_dir else None

            logger.info(f"[CLAUDE CLI] Starting: {' '.join(args)}")
            logger.info(f"[CLAUDE CLI] Model: {self.model}, CWD: {cwd}")
            logger.info(f"[CLAUDE CLI] Prompt length: {len(prompt)} chars")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            logger.info(f"[CLAUDE CLI] Process started with PID: {process.pid}")

            # Write prompt to stdin
            stdin_error = None

            async def write_stdin():
                nonlocal stdin_error
                try:
                    prompt_bytes = prompt.encode()
                    logger.info(f"[CLAUDE CLI] Writing {len(prompt_bytes)} bytes to stdin...")
                    process.stdin.write(prompt_bytes)
                    await process.stdin.drain()
                    process.stdin.close()
                    await process.stdin.wait_closed()
                    logger.info("[CLAUDE CLI] Stdin closed (EOF sent)")
                except BrokenPipeError as e:
                    stdin_error = f"BrokenPipe: {e}"
                    logger.error(f"[CLAUDE CLI] Stdin BrokenPipe: {e}")
                except Exception as e:
                    stdin_error = str(e)
                    logger.error(f"[CLAUDE CLI] Stdin error: {e}")

            stdin_task = asyncio.create_task(write_stdin())

            # Read stderr
            stderr_chunks = []

            async def read_stderr():
                stderr_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while True:
                    chunk = await process.stderr.read(1024)
                    if not chunk:
                        final = stderr_decoder.decode(b"", final=True)
                        if final:
                            stderr_chunks.append(final)
                            if on_stderr:
                                await on_stderr(final)
                        break
                    decoded = stderr_decoder.decode(chunk)
                    if decoded:
                        stderr_chunks.append(decoded)
                        for line in decoded.split("\n"):
                            if line.strip():
                                logger.debug(f"[CLAUDE STDERR] {line}")
                                if on_stderr:
                                    await on_stderr(line)

            stderr_task = asyncio.create_task(read_stderr())

            # Read stdout with streaming
            output_chunks = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            chunks_received = 0
            total_bytes = 0
            line_buffer = ""

            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        chunk = await process.stdout.read(1024)
                        if not chunk:
                            decoded = decoder.decode(b"", final=True)
                            if decoded:
                                output_chunks.append(decoded)
                            logger.info(
                                f"[CLAUDE CLI] Stream ended: {chunks_received} chunks, {total_bytes} bytes"
                            )
                            break

                        chunks_received += 1
                        total_bytes += len(chunk)

                        if chunks_received == 1:
                            logger.info(f"[CLAUDE CLI] First chunk received ({len(chunk)} bytes)")

                        decoded = decoder.decode(chunk)
                        if decoded:
                            output_chunks.append(decoded)

                            # Parse stream-json for streaming callback
                            if on_chunk:
                                line_buffer += decoded
                                while "\n" in line_buffer:
                                    line, line_buffer = line_buffer.split("\n", 1)
                                    if not line.strip():
                                        continue
                                    try:
                                        event = json.loads(line)
                                        if event.get("type") == "content_block_delta":
                                            text = event.get("delta", {}).get("text", "")
                                            if text:
                                                await on_chunk(text)
                                        elif event.get("type") == "assistant":
                                            for block in event.get("message", {}).get("content", []):
                                                if block.get("type") == "text":
                                                    await on_chunk(block.get("text", ""))
                                    except json.JSONDecodeError:
                                        pass

            except asyncio.TimeoutError:
                logger.error(f"[CLAUDE CLI] TIMEOUT after {self.timeout}s!")
                stdin_task.cancel()
                stderr_task.cancel()
                process.kill()
                return None, [], None, None, f"Timeout after {self.timeout}s"

            await stdin_task
            await stderr_task

            if stdin_error:
                logger.error(f"[CLAUDE CLI] Stdin failed: {stdin_error}")

            logger.info("[CLAUDE CLI] Waiting for process to exit...")
            await process.wait()
            logger.info(f"[CLAUDE CLI] Process exited with code {process.returncode}")

            stderr_text = "".join(stderr_chunks)
            if stderr_text and process.returncode != 0:
                logger.error(f"[CLAUDE CLI] STDERR: {stderr_text[:2000]}")

            if process.returncode != 0:
                return None, [], None, None, f"Exit code {process.returncode}: {stderr_text[:500]}"

            # Parse stream-json output
            raw_output = "".join(output_chunks)
            output, model_usage, thinking = self._parse_stream_json(raw_output)

            return output, model_usage, thinking, raw_output, None

        except FileNotFoundError:
            return None, [], None, None, "Claude CLI not found"
        except Exception as e:
            logger.exception(f"[CLAUDE CLI] Exception: {e}")
            return None, [], None, None, str(e)

    def _parse_stream_json(
        self, raw_output: str
    ) -> tuple[str, list[ModelUsage], str | None]:
        """Parse stream-json NDJSON output.

        Returns:
            Tuple of (output, model_usage, thinking)
        """
        output = ""
        model_usage_list = []
        thinking_chunks = []

        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type")

                # Capture thinking from assistant messages
                if event_type == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "thinking":
                            thinking_text = block.get("thinking", "")
                            if thinking_text:
                                thinking_chunks.append(thinking_text)

                # Extract final result
                if event_type == "result":
                    output = event.get("result", "")

                    # Check for API errors
                    if event.get("is_error"):
                        logger.error(f"[CLAUDE CLI] API error: {output}")

                    # Extract model usage
                    usage_data = event.get("modelUsage", {})
                    for model_name, usage in usage_data.items():
                        model_usage_list.append(
                            ModelUsage(
                                model=model_name,
                                input_tokens=usage.get("inputTokens", 0),
                                output_tokens=usage.get("outputTokens", 0),
                                cache_read_tokens=usage.get("cacheReadInputTokens", 0),
                                cache_creation_tokens=usage.get("cacheCreationInputTokens", 0),
                                cost_usd=usage.get("costUSD", 0.0),
                            )
                        )

            except json.JSONDecodeError:
                continue

        thinking = "\n\n".join(thinking_chunks) if thinking_chunks else None

        # Fallback if no result found
        if not output:
            logger.warning("[CLAUDE CLI] No result in stream-json, using raw output")
            output = raw_output

        return output, model_usage_list, thinking

    async def _save_to_s3(
        self,
        content: str,
        artifact_type: str,
        context_id: str,
        metadata: dict | None = None,
    ) -> str | None:
        """Save artifact to S3.

        Args:
            content: Content to save
            artifact_type: "prompt", "output", or "thinking"
            context_id: Identifier for grouping artifacts
            metadata: Additional metadata to include

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.s3_bucket:
            return None

        try:
            timestamp = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"{self.s3_prefix}/{timestamp}/{context_id}_{artifact_type}.md"

            # Build markdown content
            md_content = f"""# Claude CLI {artifact_type.title()}

**Context ID**: {context_id}
**Timestamp**: {datetime.utcnow().isoformat()}
**Artifact Type**: {artifact_type}
**Model**: {metadata.get('model', self.model) if metadata else self.model}

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
            logger.info(f"[CLAUDE CLI] Saved {artifact_type} to S3: {s3_key}")
            return s3_url

        except ClientError as e:
            logger.warning(f"[CLAUDE CLI] Failed to save to S3: {e}")
            return None
