"""Gemini CLI wrapper.

Async Python wrapper for the Gemini CLI with:
- Streaming output with callbacks
- Tool use tracking
- Optional S3 artifact saving
- Optional operation tracking
"""

import asyncio
import json
import logging
import os
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
    DEFAULT_GEMINI_TIMEOUT,
    GEMINI_MODEL_MAP,
    GeminiCLIResult,
    GeminiModelType,
    GeminiModelUsage,
    GeminiSessionStats,
    calculate_gemini_cost,
)
from .session import GeminiSession

logger = logging.getLogger(__name__)


def _parse_stream_json_stats(result_data: dict[str, Any]) -> GeminiSessionStats:
    """Parse stats from stream-json result message."""
    stats = GeminiSessionStats()

    if "stats" not in result_data:
        return stats

    s = result_data["stats"]
    stats.tool_calls_total = s.get("tool_calls", 0)
    stats.wall_time_seconds = s.get("duration_ms", 0) / 1000.0

    if s.get("total_tokens", 0) > 0 or s.get("input_tokens", 0) > 0:
        model_name = result_data.get("model", "unknown")
        non_cached_input = s.get("input", 0)
        cached_tokens = s.get("cached", 0)
        output_tokens = s.get("output_tokens", 0)

        cost_usd = calculate_gemini_cost(
            model=model_name,
            input_tokens=non_cached_input,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )

        stats.model_usage.append(
            GeminiModelUsage(
                model=model_name,
                requests=1,
                input_tokens=s.get("input_tokens", 0),
                cache_reads=cached_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        )

    return stats


class GeminiCLI:
    """Async Gemini CLI runner.

    Usage:
        cli = GeminiCLI(model="pro", working_dir=Path("./myrepo"))
        result = await cli.run("Analyze this codebase...")
        print(result.output)
        print(result.total_tokens)

        # With streaming
        async def on_chunk(text: str):
            print(text, end="")

        result = await cli.run("Review...", on_chunk=on_chunk)
    """

    def __init__(
        self,
        model: str | GeminiModelType = "flash",
        working_dir: Path | None = None,
        timeout: int = DEFAULT_GEMINI_TIMEOUT,
        auto_accept: bool = True,
        api_key: str | None = None,
        artifact_saver: ArtifactSaver | None = None,
        tracker: OperationTracker | None = None,
    ):
        """Initialize Gemini CLI runner.

        Args:
            model: Model name or type ("flash", "pro").
            working_dir: Working directory for CLI process.
            timeout: Timeout in seconds.
            auto_accept: Enable --yolo flag (auto-approve tool calls).
            api_key: Google API key (defaults to GOOGLE_API_KEY env var).
            artifact_saver: Optional artifact saver for S3/storage.
            tracker: Optional operation tracker for progress updates.
        """
        self.model = GEMINI_MODEL_MAP.get(model, model)

        self.working_dir = working_dir
        self.timeout = timeout
        self.auto_accept = auto_accept
        self.api_key = (
            api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )

        self._artifact_saver = artifact_saver or NoOpArtifactSaver()
        self._tracker = tracker or NoOpOperationTracker()

    def session(
        self,
        session_id: str | None = None,
        context_format: str = "xml",
    ) -> GeminiSession:
        """Create a new conversation session for multi-turn interactions.

        Args:
            session_id: Optional session ID. If not provided, generates a new one.
            context_format: Format for context prepending ("xml" or "markdown").

        Returns:
            GeminiSession that can be used as an async context manager.

        Usage:
            async with cli.session() as session:
                r1 = await session.send("What is Python?")
                r2 = await session.send("Show me an example")  # Remembers context

            # Or without context manager
            session = cli.session()
            await session.send("Hello")
            await session.send("Follow up")

        Note:
            Unlike ClaudeSession, GeminiSession uses context prepending since
            the Gemini CLI doesn't support native session resume.
        """
        return GeminiSession(
            cli=self,
            session_id=session_id,
            context_format=context_format,
        )

    async def run(
        self,
        prompt: str,
        *,
        operation_id: str | None = None,
        session_id: str | None = None,
        save_artifacts: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        publish_delay_ms: int = 0,
    ) -> GeminiCLIResult:
        """Execute Gemini CLI and return result.

        Args:
            prompt: The prompt to send.
            operation_id: Optional operation ID for tracking (generated if not provided).
            session_id: Optional session ID (generated if not provided).
            save_artifacts: Save prompt/output to artifact saver.
            on_chunk: Optional callback for streaming output.
            publish_delay_ms: SSE publish delay (-1=never, 0=immediate, >0=debounce).

        Returns:
            GeminiCLIResult with output, IDs, and stats.
        """
        start_time = time.time()

        # Generate IDs if not provided
        op_id = operation_id or str(uuid.uuid4())
        sess_id = session_id or str(uuid.uuid4())

        # Track operation start
        await self._tracker.progress(
            operation_id=op_id,
            status="running",
            session_id=sess_id,
            details={"model": self.model},
            publish_delay_ms=publish_delay_ms,
        )

        # Generate context_id for artifacts
        context_id = (
            datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + f"_{sess_id[:8]}"
        )

        # Save prompt artifact
        s3_prompt_url = None
        if save_artifacts:
            s3_prompt_url = await self._artifact_saver.save_markdown(
                content=prompt,
                artifact_type="prompt",
                context_id=context_id,
                metadata={"model": self.model, "operation_id": op_id},
            )

        try:
            # Build environment
            env = os.environ.copy()
            if self.api_key:
                env["GEMINI_API_KEY"] = self.api_key
            env["GEMINI_CODE_CONNECT"] = "false"

            # Build command
            args = ["gemini", "--model", self.model, "-o", "stream-json"]
            if self.auto_accept:
                args.extend(["--approval-mode", "yolo"])
            args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            logger.debug(f"Starting Gemini CLI with model: {self.model}")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            output_chunks: list[str] = []
            raw_output_lines: list[str] = []
            gemini_session_id: str | None = None
            model_from_init: str | None = None
            result_data: dict[str, Any] | None = None
            line_buffer = ""
            tools_used: set[str] = set()

            async def read_stream() -> None:
                nonlocal \
                    line_buffer, \
                    gemini_session_id, \
                    model_from_init, \
                    result_data, \
                    tools_used
                assert process.stdout is not None

                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break

                    line_buffer += chunk.decode("utf-8", errors="replace")

                    while "\n" in line_buffer:
                        line, line_buffer = line_buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        raw_output_lines.append(line)

                        try:
                            data = json.loads(line)
                            msg_type = data.get("type", "")

                            if msg_type == "init":
                                gemini_session_id = data.get("session_id")
                                model_from_init = data.get("model")

                            elif (
                                msg_type == "message"
                                and data.get("role") == "assistant"
                            ):
                                content = data.get("content", "")
                                if content:
                                    output_chunks.append(content)
                                    if on_chunk:
                                        await on_chunk(content)

                            elif msg_type == "result":
                                result_data = data

                            elif msg_type == "tool_use":
                                tool_name = data.get("tool_name", "unknown")
                                if tool_name and tool_name != "unknown":
                                    tools_used.add(tool_name)
                                if on_chunk:
                                    await on_chunk(f"\n🔧 **Tool:** `{tool_name}`\n")

                            elif msg_type == "tool_result":
                                status = data.get("status", "unknown")
                                status_icon = "✅" if status == "success" else "❌"
                                if on_chunk:
                                    await on_chunk(f"{status_icon} Tool completed\n")

                        except json.JSONDecodeError:
                            pass

            try:
                await asyncio.wait_for(read_stream(), timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.error(f"Timeout after {self.timeout}s")
                process.kill()

                duration_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Timeout after {self.timeout}s"

                await self._tracker.progress(
                    operation_id=op_id,
                    status="failed",
                    session_id=sess_id,
                    error=error_msg,
                    publish_delay_ms=0,
                )

                return GeminiCLIResult(
                    success=False,
                    output="".join(output_chunks),
                    operation_id=op_id,
                    session_id=sess_id,
                    error=error_msg,
                    model=self.model,
                    duration_ms=duration_ms,
                    s3_prompt_url=s3_prompt_url,
                )

            await process.wait()

            duration_ms = int((time.time() - start_time) * 1000)
            output = "".join(output_chunks)

            # Parse session stats
            session_stats: GeminiSessionStats | None = None
            if result_data:
                try:
                    if model_from_init:
                        result_data["model"] = model_from_init
                    session_stats = _parse_stream_json_stats(result_data)
                    session_stats.session_id = gemini_session_id
                except Exception as e:
                    logger.warning(f"Failed to parse stats: {e}")

            # Save output artifact
            s3_output_url = None
            if save_artifacts and raw_output_lines:
                raw_content = "\n".join(raw_output_lines)
                s3_output_url = await self._artifact_saver.save_markdown(
                    content=raw_content,
                    artifact_type="output",
                    context_id=context_id,
                    metadata={"model": self.model, "duration_ms": duration_ms},
                )

            # Build result details
            result_details: dict[str, Any] = {
                "duration_ms": duration_ms,
                "model": model_from_init or self.model,
                "tools_used": sorted(tools_used),
                "s3_prompt_url": s3_prompt_url,
                "s3_output_url": s3_output_url,
            }

            if session_stats:
                result_details["total_tokens"] = session_stats.total_tokens
                result_details["total_cost_usd"] = session_stats.total_cost_usd
                result_details["tool_calls"] = session_stats.tool_calls_total

            # Check result status
            status = result_data.get("status", "unknown") if result_data else "unknown"
            if process.returncode != 0 or status != "success":
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = f"Exit code {process.returncode}, status={status}: {stderr.decode()[:500]}"

                await self._tracker.progress(
                    operation_id=op_id,
                    status="failed",
                    session_id=sess_id,
                    error=error_msg[:200],
                    details=result_details,
                    publish_delay_ms=0,
                )

                return GeminiCLIResult(
                    success=False,
                    output=output,
                    operation_id=op_id,
                    session_id=sess_id,
                    raw_output=output,
                    error=error_msg,
                    duration_ms=duration_ms,
                    model=model_from_init or self.model,
                    s3_prompt_url=s3_prompt_url,
                    s3_output_url=s3_output_url,
                    session_stats=session_stats,
                    tools_used=tools_used,
                )

            await self._tracker.progress(
                operation_id=op_id,
                status="completed",
                session_id=sess_id,
                details=result_details,
                publish_delay_ms=0,
            )

            logger.debug(f"Completed in {duration_ms}ms")

            return GeminiCLIResult(
                success=True,
                output=output,
                operation_id=op_id,
                session_id=sess_id,
                raw_output=output,
                duration_ms=duration_ms,
                model=model_from_init or self.model,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
                session_stats=session_stats,
                tools_used=tools_used,
            )

        except FileNotFoundError:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "Gemini CLI not found"

            await self._tracker.progress(
                operation_id=op_id,
                status="failed",
                session_id=sess_id,
                error=error_msg,
                publish_delay_ms=0,
            )

            return GeminiCLIResult(
                success=False,
                output="",
                operation_id=op_id,
                session_id=sess_id,
                error=error_msg,
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
            )

        except Exception as e:
            logger.exception(f"Error: {e}")
            duration_ms = int((time.time() - start_time) * 1000)

            await self._tracker.progress(
                operation_id=op_id,
                status="failed",
                session_id=sess_id,
                error=str(e)[:200],
                publish_delay_ms=0,
            )

            return GeminiCLIResult(
                success=False,
                output="",
                operation_id=op_id,
                session_id=sess_id,
                error=str(e),
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
            )
