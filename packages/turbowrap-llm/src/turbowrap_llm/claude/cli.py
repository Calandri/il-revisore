"""Claude CLI wrapper.

Async-first Python wrapper for the Claude CLI with:
- Streaming output with callbacks
- Session resume capability
- Optional S3 artifact saving
- Optional operation tracking
"""

import asyncio
import codecs
import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..hooks import (
    ArtifactSaver,
    NoOpArtifactSaver,
    NoOpOperationTracker,
    OperationTracker,
)
from .models import (
    DEFAULT_TIMEOUT,
    MODEL_MAP,
    TOOL_PRESETS,
    ClaudeCLIResult,
    ModelType,
    ModelUsage,
    ToolPreset,
)
from .session import ClaudeSession

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


logger = logging.getLogger(__name__)


class ClaudeCLI:
    """Async Claude CLI runner.

    Usage:
        # Basic usage
        cli = ClaudeCLI(model="opus")
        result = await cli.run("Analyze this code...")
        print(result.output)
        print(result.session_id)  # Save for resume

        # With working directory
        cli = ClaudeCLI(model="haiku", working_dir=Path("./myrepo"))
        result = await cli.run("Quick analysis...")

        # With artifact saver
        from turbowrap_llm.hooks import S3ArtifactSaver
        saver = S3ArtifactSaver(bucket="my-bucket")
        cli = ClaudeCLI(model="sonnet", artifact_saver=saver)
        result = await cli.run("Fix this bug...")
        print(result.s3_output_url)

        # Resume session
        result = await cli.run("Continue...", resume_id=previous_session_id)
    """

    def __init__(
        self,
        model: str | ModelType = "sonnet",
        working_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        agent_md_path: Path | None = None,
        api_key: str | None = None,
        verbose: bool = True,
        skip_permissions: bool = True,
        github_token: str | None = None,
        tools: str | ToolPreset | None = None,
        thinking_enabled: bool = True,
        thinking_budget: int = 10000,
        artifact_saver: ArtifactSaver | None = None,
        tracker: OperationTracker | None = None,
    ):
        """Initialize Claude CLI runner.

        Args:
            model: Model name or type ("opus", "sonnet", "haiku").
            working_dir: Working directory for the CLI process.
            timeout: Timeout in seconds.
            agent_md_path: Path to agent MD file with instructions.
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var).
            verbose: Enable --verbose flag (required for stream-json).
            skip_permissions: Enable --dangerously-skip-permissions flag.
            github_token: GitHub token for git operations.
            tools: Tool preset ("fix", "default") or custom comma-separated list.
            thinking_enabled: Enable extended thinking.
            thinking_budget: Token budget for extended thinking.
            artifact_saver: Optional artifact saver for S3/storage.
            tracker: Optional operation tracker for progress updates.
        """
        self.model = MODEL_MAP.get(model, model)

        self.working_dir = working_dir
        self.timeout = timeout
        self.agent_md_path = agent_md_path
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.verbose = verbose
        self.skip_permissions = skip_permissions
        self.github_token = github_token
        self.thinking_enabled = thinking_enabled
        self.thinking_budget = thinking_budget

        if tools is None:
            self.tools = None
        elif tools in TOOL_PRESETS:
            self.tools = TOOL_PRESETS[tools]
        else:
            self.tools = tools

        self._artifact_saver = artifact_saver or NoOpArtifactSaver()
        self._tracker = tracker or NoOpOperationTracker()
        self._agent_prompt: str | None = None

    def load_agent_prompt(self) -> str | None:
        """Load agent prompt from MD file if configured.

        Strips YAML front matter (---...---) if present.
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
                logger.debug(
                    f"Stripped YAML front matter from {self.agent_md_path.name}"
                )

        self._agent_prompt = content
        return self._agent_prompt

    async def run(
        self,
        prompt: str,
        *,
        operation_id: str | None = None,
        session_id: str | None = None,
        resume_id: str | None = None,
        thinking_budget: int | None = None,
        save_artifacts: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_thinking: Callable[[str], Awaitable[None]] | None = None,
        on_stderr: Callable[[str], Awaitable[None]] | None = None,
        publish_delay_ms: int = 0,
    ) -> ClaudeCLIResult:
        """Execute Claude CLI and return structured result.

        Args:
            prompt: The prompt to send to Claude.
            operation_id: Optional operation ID for tracking (generated if not provided).
            session_id: Optional session ID (generated if not provided).
            resume_id: Optional session ID to resume from.
            thinking_budget: Override thinking budget.
            save_artifacts: Save prompt/output to artifact saver.
            on_chunk: Callback for streaming output chunks.
            on_thinking: Callback for streaming thinking chunks.
            on_stderr: Callback for streaming stderr.
            publish_delay_ms: SSE publish delay (-1=never, 0=immediate, >0=debounce).

        Returns:
            ClaudeCLIResult with output, IDs, usage info, and S3 URLs.
        """
        start_time = time.time()

        # Generate IDs if not provided
        op_id = operation_id or str(uuid.uuid4())
        sess_id = session_id or str(uuid.uuid4())

        # Build full prompt early for artifact saving
        full_prompt = self._build_full_prompt(prompt)

        # Generate context_id for artifacts
        context_id = (
            datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + f"_{sess_id[:8]}"
        )

        # Save prompt artifact BEFORE reporting "running" status
        # so it's available for live viewing
        s3_prompt_url = None
        if save_artifacts:
            s3_prompt_url = await self._artifact_saver.save_markdown(
                content=full_prompt,
                artifact_type="prompt",
                context_id=context_id,
                metadata={"model": self.model, "operation_id": op_id},
            )

        # Track operation start with prompt URL
        await self._tracker.progress(
            operation_id=op_id,
            status="running",
            session_id=sess_id,
            details={
                "model": self.model,
                "resume": bool(resume_id),
                "s3_prompt_url": s3_prompt_url,
                "working_dir": str(self.working_dir) if self.working_dir else None,
            },
            publish_delay_ms=publish_delay_ms,
        )

        try:
            return await self._run_internal(
                full_prompt=full_prompt,
                operation_id=op_id,
                session_id=sess_id,
                resume_id=resume_id,
                thinking_budget=thinking_budget,
                save_artifacts=save_artifacts,
                on_chunk=on_chunk,
                on_thinking=on_thinking,
                on_stderr=on_stderr,
                start_time=start_time,
                publish_delay_ms=publish_delay_ms,
                context_id=context_id,
                s3_prompt_url=s3_prompt_url,
            )
        except Exception as e:
            await self._tracker.progress(
                operation_id=op_id,
                status="failed",
                session_id=sess_id,
                error=str(e)[:200],
                publish_delay_ms=0,  # Immediate on error
            )
            raise

    async def _run_internal(
        self,
        full_prompt: str,
        operation_id: str,
        session_id: str,
        resume_id: str | None,
        thinking_budget: int | None,
        save_artifacts: bool,
        on_chunk: Callable[[str], Awaitable[None]] | None,
        on_thinking: Callable[[str], Awaitable[None]] | None,
        on_stderr: Callable[[str], Awaitable[None]] | None,
        start_time: float,
        publish_delay_ms: int,
        context_id: str,
        s3_prompt_url: str | None,
    ) -> ClaudeCLIResult:
        """Internal run method."""

        # Create wrapper callbacks that forward to tracker for live streaming
        async def wrapped_on_chunk(chunk: str) -> None:
            # Forward to user callback if provided
            if on_chunk:
                await on_chunk(chunk)
            # Update tracker with streaming content (don't block on errors)
            try:
                await self._tracker.progress(
                    operation_id=operation_id,
                    status="streaming",
                    session_id=session_id,
                    details={"chunk": chunk, "type": "output"},
                    publish_delay_ms=publish_delay_ms,
                )
            except Exception as e:
                logger.debug(f"Tracker streaming error (ignored): {e}")

        async def wrapped_on_thinking(thinking_chunk: str) -> None:
            # Forward to user callback if provided
            if on_thinking:
                await on_thinking(thinking_chunk)
            # Update tracker with thinking content (don't block on errors)
            try:
                await self._tracker.progress(
                    operation_id=operation_id,
                    status="streaming",
                    session_id=session_id,
                    details={"chunk": thinking_chunk, "type": "thinking"},
                    publish_delay_ms=publish_delay_ms,
                )
            except Exception as e:
                logger.debug(f"Tracker thinking streaming error (ignored): {e}")

        # Execute CLI with wrapped callbacks
        (
            output,
            model_usage,
            thinking,
            raw_output,
            error,
            tools_used,
            agents_launched,
            duration_api_ms,
            num_turns,
        ) = await self._execute_cli(
            full_prompt,
            thinking_budget,
            wrapped_on_chunk,  # Always use wrapper for tracker
            wrapped_on_thinking if self.thinking_enabled else None,
            on_stderr,
            session_id,
            resume_id,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # Save output artifacts
        s3_output_url = None
        s3_thinking_url = None

        if save_artifacts:
            if raw_output:
                s3_output_url = await self._artifact_saver.save_markdown(
                    content=raw_output,
                    artifact_type="output",
                    context_id=context_id,
                    metadata={"model": self.model, "duration_ms": duration_ms},
                )

            if thinking:
                s3_thinking_url = await self._artifact_saver.save_markdown(
                    content=thinking,
                    artifact_type="thinking",
                    context_id=context_id,
                    metadata={"model": self.model},
                )

        # Build result details with token breakdown
        total_input_tokens = sum(u.input_tokens for u in model_usage)
        total_output_tokens = sum(u.output_tokens for u in model_usage)
        total_cache_read_tokens = sum(u.cache_read_tokens for u in model_usage)
        total_cache_creation_tokens = sum(u.cache_creation_tokens for u in model_usage)
        total_cost = sum(u.cost_usd for u in model_usage)
        models_used = [u.model for u in model_usage]

        result_details: dict[str, Any] = {
            "duration_ms": duration_ms,
            "model": self.model,
            # Token breakdown for TurboWrap tracker
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cache_read_tokens": total_cache_read_tokens,
            "total_cache_creation_tokens": total_cache_creation_tokens,
            "cost_usd": total_cost,
            "models_used": models_used,
            # Legacy fields for backwards compatibility
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_cost_usd": total_cost,
            # Other details
            "tools_used": sorted(tools_used),
            "agents_launched": agents_launched,
            "s3_prompt_url": s3_prompt_url,
            "s3_output_url": s3_output_url,
            "working_dir": str(self.working_dir) if self.working_dir else None,
        }

        # Track completion/failure
        if error:
            await self._tracker.progress(
                operation_id=operation_id,
                status="failed",
                session_id=session_id,
                error=error[:200],
                details=result_details,
                publish_delay_ms=0,  # Immediate on error
            )

            return ClaudeCLIResult(
                success=False,
                output=output or "",
                operation_id=operation_id,
                session_id=session_id,
                error=error,
                thinking=thinking,
                raw_output=raw_output,
                model_usage=model_usage,
                duration_ms=duration_ms,
                duration_api_ms=duration_api_ms,
                num_turns=num_turns,
                model=self.model,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
                s3_thinking_url=s3_thinking_url,
                tools_used=tools_used,
                agents_launched=agents_launched,
            )

        await self._tracker.progress(
            operation_id=operation_id,
            status="completed",
            session_id=session_id,
            details=result_details,
            publish_delay_ms=0,  # Immediate on completion
        )

        return ClaudeCLIResult(
            success=True,
            output=output or "",
            operation_id=operation_id,
            session_id=session_id,
            thinking=thinking,
            raw_output=raw_output,
            model_usage=model_usage,
            duration_ms=duration_ms,
            duration_api_ms=duration_api_ms,
            num_turns=num_turns,
            model=self.model,
            s3_prompt_url=s3_prompt_url,
            s3_output_url=s3_output_url,
            s3_thinking_url=s3_thinking_url,
            tools_used=tools_used,
            agents_launched=agents_launched,
        )

    def run_sync(
        self,
        prompt: str,
        *,
        operation_id: str | None = None,
        session_id: str | None = None,
        resume_id: str | None = None,
        thinking_budget: int | None = None,
        save_artifacts: bool = True,
    ) -> ClaudeCLIResult:
        """Sync wrapper for run().

        Note: Streaming callbacks are not supported in sync mode.
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
                        operation_id=operation_id,
                        session_id=session_id,
                        resume_id=resume_id,
                        thinking_budget=thinking_budget,
                        save_artifacts=save_artifacts,
                    ),
                )
                return future.result()
        else:
            return asyncio.run(
                self.run(
                    prompt=prompt,
                    operation_id=operation_id,
                    session_id=session_id,
                    resume_id=resume_id,
                    thinking_budget=thinking_budget,
                    save_artifacts=save_artifacts,
                )
            )

    def session(
        self, session_id: str | None = None, resume: bool = False
    ) -> ClaudeSession:
        """Create a new conversation session for multi-turn interactions.

        Args:
            session_id: Optional session ID. If not provided, generates a new one.
            resume: If True and session_id is provided, resume existing session
                (use --resume instead of --session-id on first message).

        Returns:
            ClaudeSession that can be used as an async context manager.

        Usage:
            # New session
            async with cli.session() as session:
                r1 = await session.send("What is Python?")
                r2 = await session.send("Show me an example")  # Remembers context

            # Resume existing session
            session = cli.session(session_id="abc-123", resume=True)
            await session.send("Continue from where we left off")
        """
        return ClaudeSession(cli=self, session_id=session_id, resume=resume)

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
        session_id: str,
        resume_id: str | None,
    ) -> tuple[
        str | None,
        list[ModelUsage],
        str | None,
        str | None,
        str | None,
        set[str],
        int,
        int,
        int,
    ]:
        """Execute Claude CLI subprocess.

        Returns:
            Tuple of (output, model_usage, thinking, raw_output, error, tools_used, agents_launched,
                      duration_api_ms, num_turns)
        """
        try:
            env = os.environ.copy()

            if self.github_token:
                env["GITHUB_TOKEN"] = self.github_token

            if self.api_key:
                env["ANTHROPIC_API_KEY"] = self.api_key
            else:
                return None, [], None, None, "ANTHROPIC_API_KEY not found", set(), 0, 0, 0

            env["TMPDIR"] = "/tmp"

            if self.thinking_enabled:
                budget = thinking_budget or self.thinking_budget
                env["MAX_THINKING_TOKENS"] = str(budget)
                logger.debug(f"Extended thinking: {budget} tokens")

            # Determine if resuming
            is_resume = bool(resume_id)
            cli_session_id = resume_id if is_resume else session_id

            if is_resume:
                logger.info(f"Resuming session: {cli_session_id[:8]}...")
            else:
                logger.info(f"New session: {cli_session_id[:8]}...")

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

            if is_resume:
                args.extend(["--resume", cli_session_id])
            else:
                args.extend(["--session-id", cli_session_id])

            if self.verbose:
                args.append("--verbose")

            if self.skip_permissions:
                args.append("--dangerously-skip-permissions")

            args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            logger.debug(f"Command: claude --print --model {self.model} ...")
            logger.debug(f"CWD: {cwd}, Prompt length: {len(prompt)} chars")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            logger.debug(f"Process started with PID: {process.pid}")

            stderr_chunks: list[str] = []

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
                        if on_stderr:
                            for line in decoded.split("\n"):
                                if line.strip():
                                    await on_stderr(line)

            stderr_task = asyncio.create_task(read_stderr())

            output_chunks: list[str] = []
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
                            logger.debug(
                                f"Stream ended: {chunks_received} chunks, {total_bytes} bytes"
                            )
                            break

                        chunks_received += 1
                        total_bytes += len(chunk)

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
                                        await self._process_stream_event(
                                            event,
                                            on_chunk,
                                            on_thinking,
                                            in_thinking_block,
                                            current_block_type,
                                        )
                                    except json.JSONDecodeError:
                                        pass

            except asyncio.TimeoutError:
                logger.error(f"TIMEOUT after {self.timeout}s!")
                stderr_task.cancel()
                process.kill()
                return None, [], None, None, f"Timeout after {self.timeout}s", set(), 0, 0, 0

            await stderr_task

            try:
                await asyncio.wait_for(process.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.error("Process wait timeout after 30s, killing")
                process.kill()
                return None, [], None, None, "Process wait timeout", set(), 0, 0, 0

            logger.debug(f"Process exited with code {process.returncode}")

            stderr_text = "".join(stderr_chunks)
            raw_output = "".join(output_chunks) if output_chunks else None

            if process.returncode != 0:
                output: str | None = None
                model_usage: list[ModelUsage] = []
                thinking: str | None = None
                api_error: str | None = None
                tools_used: set[str] = set()
                agents_launched: int = 0
                duration_api_ms: int = 0
                num_turns: int = 0

                if raw_output:
                    (
                        output,
                        model_usage,
                        thinking,
                        api_error,
                        tools_used,
                        agents_launched,
                        duration_api_ms,
                        num_turns,
                    ) = self._parse_stream_json(raw_output)

                error_msg = f"Exit code {process.returncode}: {stderr_text[:500]}"
                if api_error:
                    error_msg = f"{error_msg}\nAPI Error: {api_error}"

                return (
                    output,
                    model_usage,
                    thinking,
                    raw_output,
                    error_msg,
                    tools_used,
                    agents_launched,
                    duration_api_ms,
                    num_turns,
                )

            if not raw_output:
                return (
                    None,
                    [],
                    None,
                    None,
                    "No output received from CLI",
                    set(),
                    0,
                    0,
                    0,
                )

            (
                output,
                model_usage,
                thinking,
                api_error,
                tools_used,
                agents_launched,
                duration_api_ms,
                num_turns,
            ) = self._parse_stream_json(raw_output)

            if api_error:
                return (
                    output,
                    model_usage,
                    thinking,
                    raw_output,
                    api_error,
                    tools_used,
                    agents_launched,
                    duration_api_ms,
                    num_turns,
                )

            return (
                output,
                model_usage,
                thinking,
                raw_output,
                None,
                tools_used,
                agents_launched,
                duration_api_ms,
                num_turns,
            )

        except FileNotFoundError:
            return None, [], None, None, "Claude CLI not found", set(), 0, 0, 0
        except Exception as e:
            logger.exception(f"Exception: {e}")
            return None, [], None, None, str(e), set(), 0, 0, 0

    async def _process_stream_event(
        self,
        event: dict[str, Any],
        on_chunk: Callable[[str], Awaitable[None]],
        on_thinking: Callable[[str], Awaitable[None]] | None,
        in_thinking_block: bool,
        current_block_type: str,
    ) -> None:
        """Process a single stream event."""
        event_type = event.get("type", "")

        if event_type == "stream_event":
            event = event.get("event", {})
            event_type = event.get("type", "")

        if event_type == "content_block_start":
            block = event.get("content_block", {})
            block_type = block.get("type", "")
            if block_type == "thinking":
                if not on_thinking:
                    await on_chunk("\n🧠 ")
            elif block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                await on_chunk(f"\n🔧 **Tool:** `{tool_name}`\n")

        elif event_type == "content_block_stop":
            if in_thinking_block and not on_thinking:
                await on_chunk("\n\n")
            elif current_block_type == "tool_use":
                await on_chunk("✅ Tool completed\n")

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
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    await on_chunk(block.get("text", ""))
                elif block.get("type") == "thinking":
                    thinking_text = block.get("thinking", "")
                    if thinking_text:
                        if on_thinking:
                            await on_thinking(thinking_text)
                        else:
                            await on_chunk(f"\n🧠 {thinking_text}\n")

    def _parse_stream_json(
        self, raw_output: str
    ) -> tuple[str, list[ModelUsage], str | None, str | None, set[str], int, int, int]:
        """Parse stream-json NDJSON output.

        Returns:
            Tuple of (output, model_usage, thinking, api_error, tools_used, agents_launched,
                      duration_api_ms, num_turns)
        """
        output = ""
        model_usage_list: list[ModelUsage] = []
        thinking_chunks: list[str] = []
        api_error = None
        tools_used: set[str] = set()
        agents_launched: int = 0
        duration_api_ms: int = 0
        num_turns: int = 0

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
                        logger.error(f"API error: {output}")

                    # Extract new fields from result event
                    duration_api_ms = event.get("duration_api_ms", 0)
                    num_turns = event.get("num_turns", 0)

                    usage_data = event.get("modelUsage") or {}
                    for model_name, usage in usage_data.items():
                        model_usage_list.append(
                            ModelUsage(
                                model=model_name,
                                input_tokens=usage.get("inputTokens", 0),
                                output_tokens=usage.get("outputTokens", 0),
                                cache_read_tokens=usage.get("cacheReadInputTokens", 0),
                                cache_creation_tokens=usage.get(
                                    "cacheCreationInputTokens", 0
                                ),
                                cost_usd=usage.get("costUSD", 0.0),
                                web_search_requests=usage.get("webSearchRequests", 0),
                                context_window=usage.get("contextWindow", 0),
                            )
                        )

            except json.JSONDecodeError:
                continue

        thinking = "\n\n".join(thinking_chunks) if thinking_chunks else None

        if not output and not api_error:
            logger.warning("No result in stream-json, using raw output")
            output = raw_output

        return (
            output,
            model_usage_list,
            thinking,
            api_error,
            tools_used,
            agents_launched,
            duration_api_ms,
            num_turns,
        )
