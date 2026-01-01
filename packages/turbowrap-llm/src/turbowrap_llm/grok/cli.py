"""Grok CLI wrapper.

Async Python wrapper for the Grok CLI with:
- Streaming output with callbacks
- Tool use tracking
- JSONL output parsing
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
    DEFAULT_GROK_MODEL,
    DEFAULT_GROK_TIMEOUT,
    GrokCLIMessage,
    GrokCLIResult,
    GrokSessionStats,
)

logger = logging.getLogger(__name__)


class GrokCLI:
    """Async Grok CLI runner.

    Usage:
        cli = GrokCLI(model="grok-4-1-fast-reasoning", working_dir=Path("./myrepo"))
        result = await cli.run("Analyze this codebase...")
        print(result.output)

        # With streaming
        async def on_chunk(text: str):
            print(text, end="")

        result = await cli.run("Review...", on_chunk=on_chunk)
    """

    def __init__(
        self,
        model: str = DEFAULT_GROK_MODEL,
        working_dir: Path | None = None,
        timeout: int = DEFAULT_GROK_TIMEOUT,
        max_tool_rounds: int = 400,
        api_key: str | None = None,
        artifact_saver: ArtifactSaver | None = None,
        tracker: OperationTracker | None = None,
    ):
        """Initialize Grok CLI runner.

        Args:
            model: Model name. Defaults to grok-4-1-fast-reasoning.
            working_dir: Working directory for CLI process.
            timeout: Timeout in seconds.
            max_tool_rounds: Max tool execution rounds.
            api_key: Grok API key (defaults to GROK_API_KEY env var).
            artifact_saver: Optional artifact saver for S3/storage.
            tracker: Optional operation tracker for progress updates.
        """
        self.model = model
        self.working_dir = working_dir
        self.timeout = timeout
        self.max_tool_rounds = max_tool_rounds
        self.api_key = api_key or os.environ.get("GROK_API_KEY")

        self._artifact_saver = artifact_saver or NoOpArtifactSaver()
        self._tracker = tracker or NoOpOperationTracker()

    async def run(
        self,
        prompt: str,
        *,
        operation_id: str | None = None,
        session_id: str | None = None,
        save_artifacts: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        headless: bool = True,
        publish_delay_ms: int = 0,
    ) -> GrokCLIResult:
        """Execute Grok CLI and return result.

        Args:
            prompt: The prompt to send.
            operation_id: Optional operation ID for tracking (generated if not provided).
            session_id: Optional session ID (generated if not provided).
            save_artifacts: Save prompt/output to artifact saver.
            on_chunk: Optional callback for streaming output.
            headless: Use -p flag for non-interactive mode.
            publish_delay_ms: SSE publish delay (-1=never, 0=immediate, >0=debounce).

        Returns:
            GrokCLIResult with output, messages, and stats.
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
                env["GROK_API_KEY"] = self.api_key

            # Build command
            args = [
                "grok",
                "-m",
                self.model,
                "--max-tool-rounds",
                str(self.max_tool_rounds),
            ]
            if headless:
                args.extend(["-p", prompt])
            else:
                args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            logger.debug(f"Starting Grok CLI with model: {self.model}")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # Parse JSONL output
            messages: list[GrokCLIMessage] = []
            output_chunks: list[str] = []
            raw_output_lines: list[str] = []
            line_buffer = ""
            tools_used: set[str] = set()

            async def read_stream() -> None:
                nonlocal line_buffer, tools_used
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
                            role = data.get("role", "")
                            content = data.get("content", "")

                            tool_calls_data = data.get("tool_calls")
                            msg = GrokCLIMessage(
                                role=role,
                                content=content,
                                tool_calls=tool_calls_data,
                                tool_call_id=data.get("tool_call_id"),
                            )
                            messages.append(msg)

                            # Extract tool names
                            if tool_calls_data:
                                for tc in tool_calls_data:
                                    tool_name = tc.get("name") or tc.get(
                                        "function", {}
                                    ).get("name")
                                    if tool_name:
                                        tools_used.add(tool_name)

                            if role == "assistant" and content:
                                output_chunks.append(content)
                                if on_chunk:
                                    await on_chunk(content)

                            elif role == "tool" and on_chunk:
                                tool_preview = content[:100] if content else ""
                                await on_chunk(f"\n[Tool result: {tool_preview}...]\n")

                        except json.JSONDecodeError:
                            if line and on_chunk:
                                await on_chunk(line + "\n")
                            output_chunks.append(line)

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

                return GrokCLIResult(
                    success=False,
                    output="\n".join(output_chunks),
                    operation_id=op_id,
                    session_id=sess_id,
                    messages=messages,
                    raw_output="\n".join(output_chunks),
                    error=error_msg,
                    model=self.model,
                    duration_ms=duration_ms,
                    s3_prompt_url=s3_prompt_url,
                )

            await process.wait()

            duration_ms = int((time.time() - start_time) * 1000)
            output = "\n".join(output_chunks)

            # Build session stats
            session_stats = GrokSessionStats(
                session_id=sess_id,
                total_messages=len(messages),
                assistant_messages=len([m for m in messages if m.role == "assistant"]),
                tool_calls=len([m for m in messages if m.tool_calls]),
                duration_ms=duration_ms,
                model=self.model,
            )

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
                "model": self.model,
                "tools_used": sorted(tools_used),
                "tool_calls": session_stats.tool_calls,
                "s3_prompt_url": s3_prompt_url,
                "s3_output_url": s3_output_url,
            }

            # Check exit code
            if process.returncode != 0:
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = f"Exit code {process.returncode}: {stderr.decode()[:500]}"

                await self._tracker.progress(
                    operation_id=op_id,
                    status="failed",
                    session_id=sess_id,
                    error=error_msg[:200],
                    details=result_details,
                    publish_delay_ms=0,
                )

                return GrokCLIResult(
                    success=False,
                    output=output,
                    operation_id=op_id,
                    session_id=sess_id,
                    messages=messages,
                    raw_output=output,
                    error=error_msg,
                    duration_ms=duration_ms,
                    model=self.model,
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

            return GrokCLIResult(
                success=True,
                output=output,
                operation_id=op_id,
                session_id=sess_id,
                messages=messages,
                raw_output=output,
                duration_ms=duration_ms,
                model=self.model,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
                session_stats=session_stats,
                tools_used=tools_used,
            )

        except FileNotFoundError:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "Grok CLI not found. Install: npm install -g @vibe-kit/grok-cli"

            await self._tracker.progress(
                operation_id=op_id,
                status="failed",
                session_id=sess_id,
                error=error_msg,
                publish_delay_ms=0,
            )

            return GrokCLIResult(
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

            return GrokCLIResult(
                success=False,
                output="",
                operation_id=op_id,
                session_id=sess_id,
                error=str(e),
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
            )
