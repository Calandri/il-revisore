"""Grok clients for xAI API.

Provides:
- GrokClient: SDK client for simple prompts and streaming
- GrokCLI: CLI runner for autonomous tool use (wraps grok binary)
"""

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from turbowrap.config import get_settings
from turbowrap.exceptions import GrokError
from turbowrap.llm.base import AgentResponse, BaseAgent
from turbowrap.llm.mixins import OperationTrackingMixin
from turbowrap.utils.aws_secrets import get_grok_api_key
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_GROK_MODEL = "grok-4-1-fast-reasoning"
DEFAULT_GROK_TIMEOUT = 120


class GrokClient(BaseAgent):
    """Client for xAI Grok API using official SDK.

    Supports:
    - Text generation with streaming
    - Multi-turn chat
    - Tool/function calling
    """

    def __init__(self, model: str | None = None):
        """Initialize Grok client.

        Args:
            model: Model name. Defaults to grok-4-1-fast-reasoning.
        """
        try:
            from xai_sdk import Client
        except ImportError as e:
            raise GrokError("xai-sdk not installed. Run: uv add xai-sdk") from e

        # Get API key from env or AWS Secrets
        api_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
        if not api_key:
            api_key = get_grok_api_key()

        if not api_key:
            raise GrokError(
                "GROK_API_KEY not found! "
                "Checked: 1) env var GROK_API_KEY, 2) env var XAI_API_KEY, "
                "3) AWS Secrets 'agent-zero/global/api-keys'"
            )

        # Set env var for SDK auto-discovery
        os.environ["XAI_API_KEY"] = api_key

        self._client = Client()
        self._model = model or DEFAULT_GROK_MODEL

    @property
    def name(self) -> str:
        return "grok"

    @property
    def model(self) -> str:
        return self._model

    @property
    def agent_type(self) -> Literal["grok", "gemini", "claude"]:
        return "grok"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate content using Grok.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            Generated text content.
        """
        from xai_sdk.chat import system, user

        messages = []
        if system_prompt:
            messages.append(system(system_prompt))
        messages.append(user(prompt))

        try:
            chat = self._client.chat.create(model=self._model, messages=messages)
            response = chat.sample()
            return response.content or ""
        except Exception as e:
            raise GrokError(f"Grok API error: {e}") from e

    def generate_with_metadata(self, prompt: str, system_prompt: str = "") -> AgentResponse:
        """Generate content with token metadata.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            AgentResponse with content and metadata.
        """
        from xai_sdk.chat import system, user

        messages = []
        if system_prompt:
            messages.append(system(system_prompt))
        messages.append(user(prompt))

        try:
            chat = self._client.chat.create(model=self._model, messages=messages)
            response = chat.sample()

            # Extract usage if available
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None

            return AgentResponse(
                content=response.content or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=self._model,
                agent_type=self.agent_type,
            )
        except Exception as e:
            raise GrokError(f"Grok API error: {e}") from e

    def stream(self, prompt: str, system_prompt: str = "") -> AsyncIterator[str]:
        """Stream response chunks.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Yields:
            Text chunks as they arrive.
        """
        from xai_sdk.chat import system, user

        messages = []
        if system_prompt:
            messages.append(system(system_prompt))
        messages.append(user(prompt))

        try:
            chat = self._client.chat.create(model=self._model, messages=messages)
            for _response, chunk in chat.stream():
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            raise GrokError(f"Grok streaming error: {e}") from e


# =============================================================================
# CLI Runner (subprocess-based, supports tool use)
# =============================================================================


@dataclass
class GrokCLIMessage:
    """A message from Grok CLI output."""

    role: str  # "user", "assistant", "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass
class GrokSessionStats:
    """Session statistics from Grok CLI execution."""

    session_id: str | None = None
    total_messages: int = 0
    assistant_messages: int = 0
    tool_calls: int = 0
    duration_ms: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "total_messages": self.total_messages,
            "assistant_messages": self.assistant_messages,
            "tool_calls": self.tool_calls,
            "duration_ms": self.duration_ms,
            "model": self.model,
        }


@dataclass
class GrokCLIResult:
    """Result from Grok CLI execution."""

    success: bool
    output: str
    messages: list[GrokCLIMessage] = field(default_factory=list)
    raw_output: str | None = None
    duration_ms: int = 0
    model: str = ""
    error: str | None = None
    s3_prompt_url: str | None = None
    s3_output_url: str | None = None
    session_stats: GrokSessionStats | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class GrokCLI(OperationTrackingMixin):
    """
    Grok CLI runner for autonomous tasks with tool use.

    Wraps the `grok` CLI binary which can use tools to read files,
    explore code, execute commands, etc.

    Usage:
        cli = GrokCLI(working_dir=repo_path)
        result = await cli.run("Analyze this codebase...")

        # With streaming callback
        async def on_chunk(text: str):
            print(text, end="")
        result = await cli.run("Review...", on_chunk=on_chunk)
    """

    # OperationTrackingMixin config
    cli_name = "grok"

    def __init__(
        self,
        working_dir: Path | None = None,
        model: str | None = None,
        timeout: int = DEFAULT_GROK_TIMEOUT,
        max_tool_rounds: int = 400,
        s3_prefix: str = "grok-cli",
    ):
        """
        Initialize Grok CLI runner.

        Args:
            working_dir: Working directory for CLI process
            model: Model name. Defaults to grok-4-1-fast-reasoning.
            timeout: Timeout in seconds
            max_tool_rounds: Max tool execution rounds (default 400)
            s3_prefix: S3 path prefix for logs
        """
        self.settings = get_settings()
        self.working_dir = working_dir
        self.timeout = timeout
        self.max_tool_rounds = max_tool_rounds
        self.s3_prefix = s3_prefix
        self.model = model or DEFAULT_GROK_MODEL

        # S3 saver
        self._s3_saver = S3ArtifactSaver(
            bucket=self.settings.thinking.s3_bucket,
            region=self.settings.thinking.s3_region,
            prefix=self.s3_prefix,
        )

    async def run(
        self,
        prompt: str,
        # Required operation tracking parameters
        operation_type: str,
        repo_name: str,
        # Optional parameters
        context_id: str | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        headless: bool = True,
        track_operation: bool = True,
        user_name: str | None = None,
        operation_details: dict[str, Any] | None = None,
    ) -> GrokCLIResult:
        """
        Execute Grok CLI and return result.

        Args:
            prompt: The prompt to send
            operation_type: Operation type ("fix", "review", etc.) - REQUIRED
            repo_name: Repository name for tracking - REQUIRED
            context_id: Optional ID for S3 logging
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            on_chunk: Optional callback for streaming output
            headless: Use -p flag for non-interactive mode (default True)
            track_operation: Enable automatic operation tracking
            user_name: User who initiated the operation (optional)
            operation_details: Additional metadata (optional)

        Returns:
            GrokCLIResult with output, messages, and stats
        """
        import time

        start_time = time.time()

        # Generate context ID if not provided
        if context_id is None:
            context_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Auto-register operation if tracking enabled
        operation = None
        if track_operation:
            operation = self._register_operation(
                context_id=context_id,
                prompt=prompt,
                operation_type=operation_type,
                repo_name=repo_name,
                user_name=user_name,
                operation_details=operation_details,
            )

        # Save prompt to S3
        s3_prompt_url = None
        if save_prompt:
            s3_prompt_url = await self._s3_saver.save_markdown(
                prompt, "prompt", context_id, {"model": self.model}, "Grok CLI"
            )

            if operation and s3_prompt_url:
                self._update_operation(operation.operation_id, {"s3_prompt_url": s3_prompt_url})

        try:
            # Build environment with API key
            env = os.environ.copy()
            api_key = os.environ.get("GROK_API_KEY") or get_grok_api_key()
            if api_key:
                env["GROK_API_KEY"] = api_key

            # Build command
            args = ["grok", "-m", self.model, "--max-tool-rounds", str(self.max_tool_rounds)]
            if headless:
                args.extend(["-p", prompt])
            else:
                args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            logger.info(f"[GROK CLI] Starting with model: {self.model}")
            logger.info(f"[GROK CLI] Prompt length: {len(prompt)} chars")

            # Launch process
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
            raw_output_lines: list[str] = []  # ALL raw JSON lines for S3
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

                        # Capture ALL raw lines for S3
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

                            # Extract tool names from tool_calls
                            if tool_calls_data:
                                for tc in tool_calls_data:
                                    # Try common field names for tool name
                                    tool_name = tc.get("name") or tc.get("function", {}).get("name")
                                    if tool_name:
                                        tools_used.add(tool_name)

                            if role == "assistant" and content:
                                output_chunks.append(content)
                                if on_chunk:
                                    await on_chunk(content)

                            elif role == "tool" and on_chunk:
                                # Show tool result indicator
                                tool_preview = content[:100] if content else ""
                                await on_chunk(f"\n[Tool result: {tool_preview}...]\n")

                        except json.JSONDecodeError:
                            # Not JSON - could be raw output
                            if line and on_chunk:
                                await on_chunk(line + "\n")
                            output_chunks.append(line)

            try:
                await asyncio.wait_for(read_stream(), timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.error(f"[GROK CLI] Timeout after {self.timeout}s")
                process.kill()

                duration_ms = int((time.time() - start_time) * 1000)
                partial_output = "\n".join(output_chunks)

                if operation:
                    self._fail_operation(operation.operation_id, f"Timeout after {self.timeout}s")

                return GrokCLIResult(
                    success=False,
                    output=partial_output,
                    messages=messages,
                    raw_output=partial_output,
                    error=f"Timeout after {self.timeout}s",
                    model=self.model,
                    duration_ms=duration_ms,
                    s3_prompt_url=s3_prompt_url,
                )

            await process.wait()

            duration_ms = int((time.time() - start_time) * 1000)
            output = "\n".join(output_chunks)

            # Build session stats
            session_stats = GrokSessionStats(
                session_id=context_id,
                total_messages=len(messages),
                assistant_messages=len([m for m in messages if m.role == "assistant"]),
                tool_calls=len([m for m in messages if m.tool_calls]),
                duration_ms=duration_ms,
                model=self.model,
            )

            # Save output to S3 - BOTH raw JSONL and readable markdown
            s3_output_url = None
            if save_output:
                # 1. Raw JSONL with EVERYTHING (primary - for debugging)
                if raw_output_lines:
                    raw_content = "\n".join(raw_output_lines)
                    s3_output_url = await self._s3_saver.save_raw(
                        raw_content,
                        "output",
                        context_id,
                    )
                # 2. Also save readable markdown for humans
                if output:
                    await self._s3_saver.save_markdown(
                        output,
                        "output_readable",
                        context_id,
                        {"model": self.model, "duration_ms": duration_ms},
                        "Grok CLI",
                    )

            # Check exit code
            if process.returncode != 0:
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = f"Exit code {process.returncode}: {stderr.decode()[:500]}"
                logger.error(f"[GROK CLI] Failed: {error_msg}")

                if operation:
                    self._fail_operation(operation.operation_id, error_msg)

                return GrokCLIResult(
                    success=False,
                    output=output,
                    messages=messages,
                    raw_output=output,
                    error=error_msg,
                    duration_ms=duration_ms,
                    model=self.model,
                    s3_prompt_url=s3_prompt_url,
                    s3_output_url=s3_output_url,
                    session_stats=session_stats,
                )

            # Complete operation
            if operation:
                self._complete_operation(
                    operation.operation_id,
                    duration_ms=duration_ms,
                    session_stats=session_stats,
                    tools_used=tools_used,
                )

            logger.info(f"[GROK CLI] Completed in {duration_ms}ms")
            return GrokCLIResult(
                success=True,
                output=output,
                messages=messages,
                raw_output=output,
                duration_ms=duration_ms,
                model=self.model,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
                session_stats=session_stats,
            )

        except FileNotFoundError:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "Grok CLI not found. Install: npm install -g @vibe-kit/grok-cli"
            if operation:
                self._fail_operation(operation.operation_id, error_msg)

            return GrokCLIResult(
                success=False,
                output="",
                error=error_msg,
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
            )
        except Exception as e:
            logger.exception(f"[GROK CLI] Error: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            if operation:
                self._fail_operation(operation.operation_id, str(e)[:200])

            return GrokCLIResult(
                success=False,
                output="",
                error=str(e),
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
            )

    def _infer_operation_type(self, explicit_type: str | None, prompt: str) -> str:
        """Infer operation type from context."""
        if explicit_type:
            return explicit_type

        prompt_lower = prompt.lower()[:500]
        if "fix" in prompt_lower or "correggi" in prompt_lower:
            return "fix"
        if "review" in prompt_lower or "analizza" in prompt_lower:
            return "review"
        if "lint" in prompt_lower or "ruff" in prompt_lower:
            return "review"

        return "cli_task"

    def _extract_repo_name(self) -> str | None:
        """Extract repository name from working_dir."""
        if self.working_dir:
            return self.working_dir.name
        return None

    def _register_operation(
        self,
        context_id: str | None,
        prompt: str,
        operation_type: str | None,
        repo_name: str | None,
        user_name: str | None,
        operation_details: dict[str, Any] | None,
    ) -> Any:
        """Register operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import OperationType, get_tracker

            tracker = get_tracker()
            op_type_str = self._infer_operation_type(operation_type, prompt)

            try:
                op_type = OperationType(op_type_str)
            except ValueError:
                op_type = OperationType.CLI_TASK

            prompt_preview = prompt[:150].replace("\n", " ").strip()
            if len(prompt) > 150:
                prompt_preview += "..."

            # Extract parent_session_id as first-class field (for hierarchical queries)
            details_copy = dict(operation_details or {})
            parent_session_id = details_copy.pop("parent_session_id", None)

            operation = tracker.register(
                op_type=op_type,
                operation_id=context_id or str(uuid.uuid4()),
                repo_name=repo_name or self._extract_repo_name(),
                user=user_name,
                parent_session_id=parent_session_id,
                details={
                    "model": self.model,
                    "cli": "grok",
                    "working_dir": str(self.working_dir) if self.working_dir else None,
                    "prompt_preview": prompt_preview,
                    "prompt_length": len(prompt),
                    **details_copy,
                },
            )

            logger.info(
                f"[GROK CLI] Operation registered: {operation.operation_id[:8]} ({op_type.value})"
            )
            return operation

        except Exception as e:
            logger.warning(f"[GROK CLI] Failed to register operation: {e}")
            return None

    def _complete_operation(
        self,
        operation_id: str,
        duration_ms: int,
        session_stats: GrokSessionStats | None = None,
        tools_used: set[str] | None = None,
    ) -> None:
        """Complete operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            result: dict[str, Any] = {"duration_ms": duration_ms, "model": self.model}

            if session_stats:
                result["session_stats"] = session_stats.to_dict()
                result["tool_calls"] = session_stats.tool_calls

            # Add tools used (sorted for consistency)
            result["tools_used"] = sorted(tools_used) if tools_used else []

            tracker.complete(operation_id, result=result)
            logger.info(
                f"[GROK CLI] Operation completed: {operation_id[:8]} "
                f"({len(tools_used or [])} tools)"
            )

        except Exception as e:
            logger.warning(f"[GROK CLI] Failed to complete operation: {e}")

    def _fail_operation(self, operation_id: str, error: str) -> None:
        """Fail operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.fail(operation_id, error=error[:200])
            logger.info(f"[GROK CLI] Operation failed: {operation_id[:8]}")

        except Exception as e:
            logger.warning(f"[GROK CLI] Failed to mark operation as failed: {e}")

    def _update_operation(self, operation_id: str, details: dict[str, Any]) -> None:
        """Update operation details in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.update(operation_id, details=details)

        except Exception as e:
            logger.warning(f"[GROK CLI] Failed to update operation: {e}")
