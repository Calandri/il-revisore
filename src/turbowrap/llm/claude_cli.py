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
import sys

if sys.version_info >= (3, 11):
    asyncio_timeout = asyncio.timeout
else:
    try:
        from async_timeout import timeout as asyncio_timeout
    except ImportError:
        from collections.abc import AsyncIterator
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def asyncio_timeout(seconds: float) -> AsyncIterator[None]:
            yield


import codecs
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from turbowrap.config import get_settings
from turbowrap.llm.mixins import OperationTrackingMixin
from turbowrap.utils.aws_secrets import get_anthropic_api_key
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)

ModelType = Literal["opus", "sonnet", "haiku"]
MODEL_MAP = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
}

DEFAULT_TIMEOUT = 180

ToolPreset = Literal["fix", "default"]
TOOL_PRESETS: dict[str, str] = {
    # Task tool needed for Opus orchestrator to launch sub-agents (git-branch-creator, fixer-single)
    "fix": "Bash,Read,Edit,Write,Glob,Grep,TodoWrite,WebFetch,WebSearch,Task",
    "default": "default",
}


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
    session_id: str | None = None  # Session ID for --resume


class ClaudeCLI(OperationTrackingMixin):
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

    # OperationTrackingMixin config
    cli_name = "claude"

    def __init__(
        self,
        agent_md_path: Path | None = None,
        working_dir: Path | None = None,
        model: str | ModelType | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        s3_prefix: str = "claude-cli",
        verbose: bool = True,
        skip_permissions: bool = True,
        github_token: str | None = None,
        tools: str | ToolPreset | None = None,
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
            github_token: GitHub token for git operations (passed to subprocess env)
            tools: Tool preset name ("fix", "default") or custom comma-separated list.
                   None = all tools (default behavior). Only works with --print mode.
        """
        self.settings = get_settings()
        self.agent_md_path = agent_md_path
        self.working_dir = working_dir
        self.timeout = timeout
        self.s3_prefix = s3_prefix
        self.verbose = verbose
        self.skip_permissions = skip_permissions
        self.github_token = github_token

        if tools is None:
            self.tools = None
        elif tools in TOOL_PRESETS:
            self.tools = TOOL_PRESETS[tools]
        else:
            self.tools = tools

        if model is None:
            self.model = self.settings.agents.claude_model
        elif model in MODEL_MAP:
            self.model = MODEL_MAP[model]
        else:
            self.model = model

        self._s3_saver = S3ArtifactSaver(
            bucket=self.settings.thinking.s3_bucket,
            region=self.settings.thinking.s3_region,
            prefix=self.s3_prefix,
        )

        self._agent_prompt: str | None = None

    def load_agent_prompt(self) -> str | None:
        """Load agent prompt from MD file if configured.

        Strips YAML front matter (---...---) if present, as it's metadata
        for Claude Code and would cause CLI argument parsing issues.
        """
        if self._agent_prompt is not None:
            return self._agent_prompt

        if self.agent_md_path is None:
            return None

        if not self.agent_md_path.exists():
            logger.warning(f"Agent MD file not found: {self.agent_md_path}")
            return None

        content = self.agent_md_path.read_text()

        if content.startswith("---"):
            end_idx = content.find("---", 3)
            if end_idx != -1:
                content = content[end_idx + 3 :].lstrip("\n")
                logger.info(
                    f"[CLAUDE CLI] Stripped YAML front matter from {self.agent_md_path.name}"
                )

        self._agent_prompt = content
        return self._agent_prompt

    async def run(
        self,
        prompt: str,
        # Required operation tracking parameters
        operation_type: str,
        repo_name: str,
        # Optional parameters
        context_id: str | None = None,
        thinking_budget: int | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        save_thinking: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_thinking: Callable[[str], Awaitable[None]] | None = None,
        on_stderr: Callable[[str], Awaitable[None]] | None = None,
        track_operation: bool = True,
        user_name: str | None = None,
        operation_details: dict[str, Any] | None = None,
        # Session persistence
        resume_session_id: str | None = None,
    ) -> ClaudeCLIResult:
        """Execute Claude CLI and return structured result.

        Args:
            prompt: The prompt to send to Claude
            operation_type: Operation type ("fix", "review", "commit", etc.) - REQUIRED
            repo_name: Repository name for display in banner - REQUIRED
            context_id: Optional ID for S3 logging (e.g., review_id, issue_id)
            thinking_budget: Override thinking budget (None = use default from config)
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            save_thinking: Save thinking to S3
            on_chunk: Callback for streaming output chunks (text only)
            on_thinking: Callback for streaming thinking chunks (extended thinking)
            on_stderr: Callback for streaming stderr (--verbose output)
            track_operation: Enable automatic operation tracking (default: True)
            user_name: User who initiated the operation (optional)
            operation_details: Additional metadata for the operation (optional)
            resume_session_id: Session ID to resume (uses --resume instead of --session-id)

        Returns:
            ClaudeCLIResult with output, thinking, usage info, session_id, and S3 URLs
        """
        start_time = time.time()

        # Session ID logic:
        # - HEAD (first call): Generate new UUID, same for session and operation
        # - TAIL (resume): Use resume_session_id for Claude CLI, NEW UUID for operation
        is_resume = bool(resume_session_id)

        # For Claude CLI: session_id MUST be a valid UUID (Claude CLI requirement)
        # context_id is only used for logging/artifacts, NOT as session_id
        session_id = resume_session_id or str(uuid.uuid4())

        # For operation tracking:
        # - HEAD: same as session_id (unified - single source of truth)
        # - TAIL: NEW UUID (separate operation, linked via parent_session_id in details)
        if is_resume:
            operation_id = context_id or str(uuid.uuid4())  # New operation for resume calls
        else:
            operation_id = session_id  # Unified with session for first call

        operation = None
        if track_operation:
            operation = self._register_operation(
                context_id=operation_id,  # Use operation_id (not session_id for resume!)
                prompt=prompt,
                operation_type=operation_type,
                repo_name=repo_name,
                user_name=user_name,
                operation_details=operation_details,
            )

        try:
            return await self._run_with_tracking(
                prompt=prompt,
                context_id=context_id,
                thinking_budget=thinking_budget,
                save_prompt=save_prompt,
                save_output=save_output,
                save_thinking=save_thinking,
                on_chunk=on_chunk,
                on_thinking=on_thinking,
                on_stderr=on_stderr,
                operation=operation,
                start_time=start_time,
                session_id=session_id,  # Claude CLI session (resume if resuming)
                is_resume=is_resume,
            )
        except Exception as e:
            if operation:
                self._fail_operation(operation.operation_id, f"Unexpected error: {e!s}"[:200])
            raise

    async def _run_with_tracking(
        self,
        prompt: str,
        context_id: str | None,
        thinking_budget: int | None,
        save_prompt: bool,
        save_output: bool,
        save_thinking: bool,
        on_chunk: Callable[[str], Awaitable[None]] | None,
        on_thinking: Callable[[str], Awaitable[None]] | None,
        on_stderr: Callable[[str], Awaitable[None]] | None,
        operation: Any,
        start_time: float,
        session_id: str,  # Unified ID (same as operation_id)
        is_resume: bool = False,
    ) -> ClaudeCLIResult:
        """Internal method that runs CLI with operation tracking.

        Separated to allow try/except wrapper in run() for guaranteed operation closure.
        """
        full_prompt = self._build_full_prompt(prompt)

        effective_on_chunk: Callable[[str], Awaitable[None]] | None = on_chunk
        tracker = None
        if operation:
            try:
                from turbowrap.api.services.operation_tracker import get_tracker

                tracker = get_tracker()
                original_on_chunk = on_chunk

                async def _wrapped_on_chunk(chunk: str) -> None:
                    """Callback that sends chunk to both original callback and SSE subscribers."""
                    if original_on_chunk:
                        await original_on_chunk(chunk)
                    await tracker.publish_event(operation.operation_id, "chunk", {"content": chunk})

                effective_on_chunk = _wrapped_on_chunk
                logger.debug(
                    f"[CLAUDE CLI] SSE publishing enabled for {operation.operation_id[:8]}"
                )
            except Exception as e:
                logger.warning(f"[CLAUDE CLI] Failed to setup SSE publishing: {e}")

        if context_id is None:
            context_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        s3_prompt_url = None
        if save_prompt:
            s3_prompt_url = await self._s3_saver.save_markdown(
                full_prompt, "prompt", context_id, {"model": self.model}, "Claude CLI"
            )

            if operation and s3_prompt_url:
                self._update_operation(operation.operation_id, {"s3_prompt_url": s3_prompt_url})

        (
            output,
            model_usage,
            thinking,
            raw_output,
            error,
            _,  # session_id returned by _execute_cli (same as passed session_id)
            tools_used,
            agents_launched,
        ) = await self._execute_cli(
            full_prompt,
            thinking_budget,
            effective_on_chunk,
            on_thinking,
            on_stderr,
            session_id,  # Unified ID (same as operation_id)
            is_resume,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        s3_output_url = None
        s3_thinking_url = None

        if save_output:
            if raw_output:
                s3_output_url = await self._s3_saver.save_raw(
                    raw_output,
                    "output",
                    context_id,
                )
            if output:
                await self._s3_saver.save_markdown(
                    output,
                    "output_readable",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms, "error": bool(error)},
                    "Claude CLI",
                )

        if save_thinking and thinking:
            s3_thinking_url = await self._s3_saver.save_markdown(
                thinking,
                "thinking",
                context_id,
                {"model": self.model, "error": bool(error)},
                "Claude CLI",
            )

        if error and save_output:
            await self._s3_saver.save_markdown(
                f"# Error\n\n{error}\n\n# Raw Output\n\n{raw_output or 'None'}",
                "error",
                context_id,
                {"model": self.model, "duration_ms": duration_ms},
                "Claude CLI",
            )

        if error:
            if operation:
                self._fail_operation(operation.operation_id, error)
                if tracker:
                    await tracker.signal_completion(operation.operation_id)

            return ClaudeCLIResult(
                success=False,
                output=output or "",
                error=error,
                thinking=thinking,
                raw_output=raw_output,
                model_usage=model_usage,
                duration_ms=duration_ms,
                model=self.model,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
                s3_thinking_url=s3_thinking_url,
                session_id=session_id,
            )

        if operation:
            self._complete_operation(
                operation.operation_id,
                duration_ms=duration_ms,
                model_usage=model_usage,
                tools_used=tools_used,
                agents_launched=agents_launched,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
            )
            if tracker:
                await tracker.signal_completion(operation.operation_id)

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
            session_id=session_id,
        )

    def run_sync(
        self,
        prompt: str,
        operation_type: str,
        repo_name: str,
        context_id: str | None = None,
        thinking_budget: int | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        save_thinking: bool = True,
    ) -> ClaudeCLIResult:
        """Sync wrapper for run().

        Use this when calling from non-async code.
        Note: Streaming callbacks are not supported in sync mode.

        Args:
            prompt: The prompt to send to Claude
            operation_type: Operation type ("fix", "review", etc.) - REQUIRED
            repo_name: Repository name for tracking - REQUIRED
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self.run(
                        prompt=prompt,
                        operation_type=operation_type,
                        repo_name=repo_name,
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
                    operation_type=operation_type,
                    repo_name=repo_name,
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
        on_thinking: Callable[[str], Awaitable[None]] | None,
        on_stderr: Callable[[str], Awaitable[None]] | None,
        session_id: str,  # Unified ID (same as operation_id) - NEVER generate here
        is_resume: bool = False,
    ) -> tuple[
        str | None, list[ModelUsage], str | None, str | None, str | None, str | None, set[str], int
    ]:
        """Execute Claude CLI subprocess.

        Args:
            prompt: The prompt to send.
            thinking_budget: Token budget for extended thinking.
            on_chunk: Callback for text output chunks.
            on_thinking: Callback for thinking chunks (extended thinking).
            on_stderr: Callback for stderr output.
            session_id: Unified session ID (same as operation_id for tracking).
            is_resume: If True, uses --resume flag; otherwise uses --session-id.

        Returns:
            Tuple of (output, model_usage, thinking, raw_output, error, session_id, tools_used, agents_launched)
        """
        try:
            env = os.environ.copy()

            if self.github_token:
                env["GITHUB_TOKEN"] = self.github_token
                logger.info(
                    f"[CLAUDE CLI] GITHUB_TOKEN set in env (length={len(self.github_token)})"
                )
            else:
                logger.warning("[CLAUDE CLI] No GITHUB_TOKEN provided - git auth may fail")

            api_key = get_anthropic_api_key() or os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            else:
                return None, [], None, None, "ANTHROPIC_API_KEY not found", None, set(), 0

            env["TMPDIR"] = "/tmp"

            if self.settings.thinking.enabled:
                budget = thinking_budget or self.settings.thinking.budget_tokens
                env["MAX_THINKING_TOKENS"] = str(budget)
                logger.info(f"[CLAUDE CLI] Extended thinking: {budget} tokens")

            # session_id is now passed in (unified with operation_id)
            if is_resume:
                logger.info(f"[CLAUDE CLI] Resuming session: {session_id[:8]}...")
            else:
                logger.info(f"[CLAUDE CLI] New session: {session_id[:8]}...")

            args = [
                "claude",
                "--print",
                "--model",
                self.model,
                "--output-format",
                "stream-json",
                "--include-partial-messages",
            ]

            if self.tools and self.tools != "default":
                args.extend(["--tools", self.tools])
                logger.info(f"[CLAUDE CLI] Tools limited to: {self.tools}")

            if is_resume:
                args.extend(["--resume", session_id])
            else:
                args.extend(["--session-id", session_id])

            if self.verbose:
                args.append("--verbose")

            if self.skip_permissions:
                args.append("--dangerously-skip-permissions")

            args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            args_display = " ".join(args[:-1])
            logger.info(f"[CLAUDE CLI] Command: {args_display} <prompt>")
            logger.info(
                f"[CLAUDE CLI] Flags: verbose={self.verbose}, "
                f"skip_permissions={self.skip_permissions}"
            )
            logger.info(f"[CLAUDE CLI] Model: {self.model}, CWD: {cwd}")
            logger.info(f"[CLAUDE CLI] Prompt length: {len(prompt)} chars")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            logger.info(f"[CLAUDE CLI] Process started with PID: {process.pid}")

            stderr_chunks = []

            async def read_stderr() -> None:
                stderr_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                assert process.stderr is not None
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
                                logger.info(f"[CLAUDE STDERR] {line}")
                                if on_stderr:
                                    await on_stderr(line)

            stderr_task = asyncio.create_task(read_stderr())

            output_chunks = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            chunks_received = 0
            total_bytes = 0
            line_buffer = ""
            in_thinking_block = False
            current_block_type = ""

            assert process.stdout is not None
            try:
                async with asyncio_timeout(self.timeout):
                    while True:
                        chunk = await process.stdout.read(1024)
                        if not chunk:
                            decoded = decoder.decode(b"", final=True)
                            if decoded:
                                output_chunks.append(decoded)
                            logger.info(
                                f"[CLAUDE CLI] Stream ended: {chunks_received} chunks, "
                                f"{total_bytes} bytes"
                            )
                            break

                        chunks_received += 1
                        total_bytes += len(chunk)

                        if chunks_received == 1:
                            logger.info(f"[CLAUDE CLI] First chunk received ({len(chunk)} bytes)")

                        decoded = decoder.decode(chunk)
                        if decoded:
                            output_chunks.append(decoded)

                            if on_chunk:
                                line_buffer += decoded
                                while "\n" in line_buffer:
                                    line, line_buffer = line_buffer.split("\n", 1)
                                    if not line.strip():
                                        continue
                                    try:
                                        event = json.loads(line)
                                        event_type = event.get("type", "")

                                        if event_type == "stream_event":
                                            event = event.get("event", {})
                                            event_type = event.get("type", "")

                                        if event_type == "content_block_start":
                                            block = event.get("content_block", {})
                                            block_type = block.get("type", "")
                                            if block_type == "thinking":
                                                in_thinking_block = True
                                                current_block_type = "thinking"
                                                if not on_thinking:
                                                    await on_chunk("\n🧠 ")
                                            elif block_type == "tool_use":
                                                current_block_type = "tool_use"
                                                tool_name = block.get("name", "unknown")
                                                await on_chunk(f"\n🔧 **Tool:** `{tool_name}`\n")
                                            else:
                                                current_block_type = block_type
                                        elif event_type == "content_block_stop":
                                            if in_thinking_block:
                                                in_thinking_block = False
                                                if not on_thinking:
                                                    await on_chunk("\n\n")
                                            elif current_block_type == "tool_use":
                                                await on_chunk("✅ Tool completed\n")
                                            current_block_type = ""

                                        elif event_type == "content_block_delta":
                                            delta = event.get("delta", {})
                                            delta_type = delta.get("type", "")
                                            if delta_type == "text_delta":
                                                text = delta.get("text", "")
                                                if text:
                                                    await on_chunk(text)
                                            elif delta_type == "thinking_delta":
                                                thinking_chunk = delta.get("thinking", "")
                                                if thinking_chunk:
                                                    if on_thinking:
                                                        await on_thinking(thinking_chunk)
                                                    else:
                                                        await on_chunk(thinking_chunk)
                                        elif event_type == "assistant":
                                            for block in event.get("message", {}).get(
                                                "content", []
                                            ):
                                                if block.get("type") == "text":
                                                    await on_chunk(block.get("text", ""))
                                                elif block.get("type") == "thinking":
                                                    thinking_block = block.get("thinking", "")
                                                    if thinking_block:
                                                        if on_thinking:
                                                            await on_thinking(thinking_block)
                                                        else:
                                                            await on_chunk(
                                                                f"\n🧠 {thinking_block}\n"
                                                            )
                                    except json.JSONDecodeError:
                                        pass

            except asyncio.TimeoutError:
                logger.error(f"[CLAUDE CLI] TIMEOUT after {self.timeout}s!")
                stderr_task.cancel()
                process.kill()
                return None, [], None, None, f"Timeout after {self.timeout}s", session_id, set(), 0

            await stderr_task

            logger.info("[CLAUDE CLI] Waiting for process to exit...")
            # Wait for process with timeout (30s should be enough after output is done)
            try:
                await asyncio.wait_for(process.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error("[CLAUDE CLI] Process wait timeout after 30s, killing")
                process.kill()
                return None, [], None, None, "Process wait timeout", session_id, set(), 0
            logger.info(f"[CLAUDE CLI] Process exited with code {process.returncode}")

            stderr_text = "".join(stderr_chunks)
            if stderr_text:
                if process.returncode != 0:
                    logger.error(f"[CLAUDE CLI] STDERR: {stderr_text[:2000]}")
                else:
                    logger.warning(f"[CLAUDE CLI] Output: {stderr_text[:2000]}")

            raw_output = "".join(output_chunks) if output_chunks else None

            if process.returncode != 0:
                output: str | None = None
                model_usage: list[ModelUsage] = []
                thinking: str | None = None
                api_error: str | None = None
                tools_used: set[str] = set()
                agents_launched: int = 0
                if raw_output:
                    (output, model_usage, thinking, api_error, tools_used, agents_launched) = (
                        self._parse_stream_json(raw_output)
                    )
                    logger.info(
                        f"[CLAUDE CLI] Exit {process.returncode} "
                        f"got output: {len(raw_output)} bytes"
                    )

                error_msg = f"Exit code {process.returncode}: {stderr_text[:500]}"
                if api_error:
                    error_msg = f"{error_msg}\nAPI Error: {api_error}"

                return (
                    output,
                    model_usage,
                    thinking,
                    raw_output,
                    error_msg,
                    session_id,
                    tools_used,
                    agents_launched,
                )

            if not raw_output:
                logger.warning("[CLAUDE CLI] No output received from CLI")
                return None, [], None, None, "No output received from CLI", session_id, set(), 0

            (output, model_usage, thinking, api_error, tools_used, agents_launched) = (
                self._parse_stream_json(raw_output)
            )

            if api_error:
                return (
                    output,
                    model_usage,
                    thinking,
                    raw_output,
                    api_error,
                    session_id,
                    tools_used,
                    agents_launched,
                )

            return (
                output,
                model_usage,
                thinking,
                raw_output,
                None,
                session_id,
                tools_used,
                agents_launched,
            )

        except FileNotFoundError:
            return None, [], None, None, "Claude CLI not found", None, set(), 0
        except Exception as e:
            logger.exception(f"[CLAUDE CLI] Exception: {e}")
            return None, [], None, None, str(e), None, set(), 0

    def _parse_stream_json(
        self, raw_output: str
    ) -> tuple[str, list[ModelUsage], str | None, str | None, set[str], int]:
        """Parse stream-json NDJSON output.

        Handles both regular events and stream_event wrappers
        (from --include-partial-messages).

        Returns:
            Tuple of (output, model_usage, thinking, api_error, tools_used, agents_launched)
        """
        output = ""
        model_usage_list = []
        thinking_chunks = []
        api_error = None
        tools_used: set[str] = set()
        agents_launched: int = 0  # Count Task tool invocations (sub-agents)

        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type")

                if event_type == "stream_event":
                    event = event.get("event", {})
                    event_type = event.get("type")

                if event_type == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "thinking":
                            thinking_text = block.get("thinking", "")
                            if thinking_text and isinstance(thinking_text, str):
                                thinking_chunks.append(thinking_text)
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name")
                            if tool_name:
                                tools_used.add(tool_name)
                                if tool_name == "Task":
                                    agents_launched += 1

                if event_type == "result":
                    output = event.get("result", "")

                    if event.get("is_error"):
                        api_error = output
                        logger.error(f"[CLAUDE CLI] API error: {output}")

                    usage_data = event.get("modelUsage") or {}
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

        if not output and not api_error:
            logger.warning("[CLAUDE CLI] No result in stream-json, using raw output")
            output = raw_output

        return output, model_usage_list, thinking, api_error, tools_used, agents_launched

    def _complete_operation(
        self,
        operation_id: str,
        duration_ms: int,
        model_usage: list[ModelUsage],
        tools_used: set[str] | None = None,
        agents_launched: int = 0,
        s3_prompt_url: str | None = None,
        s3_output_url: str | None = None,
    ) -> None:
        """Complete operation in tracker with model usage stats and S3 URLs."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()

            # Calculate totals
            total_input = sum(u.input_tokens for u in model_usage)
            total_output = sum(u.output_tokens for u in model_usage)
            total_tokens = total_input + total_output
            total_cost = sum(u.cost_usd for u in model_usage)
            total_cache_read = sum(u.cache_read_tokens for u in model_usage)
            total_cache_creation = sum(u.cache_creation_tokens for u in model_usage)

            # Build detailed model usage for DB
            model_usage_list = [
                {
                    "model": u.model,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cache_read_tokens": u.cache_read_tokens,
                    "cache_creation_tokens": u.cache_creation_tokens,
                    "cost_usd": u.cost_usd,
                }
                for u in model_usage
            ]

            tracker.complete(
                operation_id,
                result={
                    "duration_ms": duration_ms,
                    "model": self.model,
                    # Legacy fields (for backward compatibility)
                    "tokens": total_tokens,
                    "cost_usd": total_cost,
                    # New detailed fields (aligned with Gemini)
                    "total_tokens": total_tokens,
                    "total_input_tokens": total_input,
                    "total_output_tokens": total_output,
                    "total_cache_read_tokens": total_cache_read,
                    "total_cache_creation_tokens": total_cache_creation,
                    "models_used": list({u.model for u in model_usage}),
                    "model_usage": model_usage_list,
                    "tools_used": sorted(tools_used) if tools_used else [],
                    "agents_launched": agents_launched,
                    # S3 artifact URLs
                    "s3_prompt_url": s3_prompt_url,
                    "s3_output_url": s3_output_url,
                },
            )
            logger.info(
                f"[CLAUDE CLI] Operation completed: {operation_id[:8]} "
                f"({total_tokens} tokens, ${total_cost:.4f}, {len(tools_used or [])} tools)"
            )

        except Exception as e:
            logger.warning(f"[CLAUDE CLI] Failed to complete operation: {e}")
