"""Gemini clients for fast analysis.

Provides:
- GeminiClient: SDK client for simple prompts
- GeminiProClient: SDK client with vision capabilities
- GeminiCLI: CLI runner for autonomous tool use
"""

import asyncio
import json
import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from turbowrap.config import get_settings
from turbowrap.exceptions import GeminiError
from turbowrap.llm.base import AgentResponse, BaseAgent
from turbowrap.utils.aws_secrets import get_google_api_key
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)

# Gemini model aliases for CLI
GeminiModelType = Literal["flash", "pro"]
GEMINI_MODEL_MAP = {
    "flash": "gemini-3-flash-preview",
    "pro": "gemini-3-pro-preview",
}

# Default timeout for CLI
DEFAULT_GEMINI_TIMEOUT = 120


class GeminiClient(BaseAgent):
    """Client for Google Gemini API (Flash model for fast analysis)."""

    def __init__(self, model: str | None = None):
        """Initialize Gemini client.

        Args:
            model: Model name override. Defaults to config value.
        """
        try:
            from google import genai
        except ImportError as e:
            raise GeminiError("google-genai not installed. Run: pip install google-genai") from e

        settings = get_settings()

        # Try environment variables first, then AWS Secrets Manager
        api_key = settings.agents.effective_google_key
        if not api_key:
            # Fallback to AWS Secrets Manager
            from turbowrap.utils.aws_secrets import get_gemini_api_key, get_google_api_key

            api_key = get_google_api_key() or get_gemini_api_key()

        if not api_key:
            raise GeminiError(
                "GOOGLE_API_KEY not found! "
                "Checked: 1) env var GOOGLE_API_KEY, 2) env var GEMINI_API_KEY, "
                "3) AWS Secrets 'agent-zero/global/api-keys'"
            )

        self._client = genai.Client(api_key=api_key)
        self._model = model or settings.agents.gemini_model

    @property
    def name(self) -> str:
        return "gemini_flash"

    @property
    def model(self) -> str:
        return self._model

    @property
    def agent_type(self) -> Literal["gemini", "claude"]:
        return "gemini"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate content using Gemini.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            Generated text content.
        """
        contents = []

        # Gemini doesn't have native system prompt, so we simulate it
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": "Understood. I will follow these instructions."}],
                }
            )

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
            )
            if response.text is None:
                raise GeminiError("Gemini returned empty response")
            return response.text
        except Exception as e:
            raise GeminiError(f"Gemini API error: {e}") from e

    def generate_with_metadata(self, prompt: str, system_prompt: str = "") -> AgentResponse:
        """Generate content with token metadata.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            AgentResponse with content and metadata.
        """
        contents = []

        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": "Understood. I will follow these instructions."}],
                }
            )

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
            )

            # Extract token counts if available
            usage = getattr(response, "usage_metadata", None)
            prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
            completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None

            content = response.text
            if content is None:
                raise GeminiError("Gemini returned empty response")
            return AgentResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=self._model,
                agent_type=self.agent_type,
            )
        except Exception as e:
            raise GeminiError(f"Gemini API error: {e}") from e


class GeminiProClient(GeminiClient):
    """Client for Gemini Pro (complex reasoning tasks)."""

    def __init__(self, model: str | None = None):
        """Initialize Gemini Pro client.

        Args:
            model: Model name override. Defaults to gemini_pro_model config.
        """
        settings = get_settings()
        super().__init__(model=model or settings.agents.gemini_pro_model)

    @property
    def name(self) -> str:
        return "gemini_pro"

    def analyze_images(
        self,
        prompt: str,
        image_paths: list[str],
    ) -> str:
        """Analyze images with Gemini Vision API.

        Generic method for multimodal analysis. Business logic and prompt
        formatting should be handled by the caller.

        Args:
            prompt: The formatted prompt to send with images.
            image_paths: List of paths to image files.

        Returns:
            Analysis text from Gemini.

        Raises:
            GeminiError: If analysis fails.
        """
        from google.genai import types

        # Build parts list starting with the prompt
        parts: list[Any] = [{"text": prompt}]

        # Add each image as a Part
        for img_path in image_paths:
            try:
                with open(img_path, "rb") as f:
                    image_data = f.read()

                # Detect MIME type based on file extension
                mime_type = "image/png"
                lower_path = img_path.lower()
                if lower_path.endswith((".jpg", ".jpeg")):
                    mime_type = "image/jpeg"
                elif lower_path.endswith(".webp"):
                    mime_type = "image/webp"
                elif lower_path.endswith(".gif"):
                    mime_type = "image/gif"

                # Create Part from image bytes
                parts.append(types.Part.from_bytes(data=image_data, mime_type=mime_type))

            except FileNotFoundError:
                raise GeminiError(f"Image not found: {img_path}")
            except Exception as e:
                raise GeminiError(f"Error loading image {img_path}: {e}") from e

        # Make API call with multimodal content
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[{"role": "user", "parts": parts}],
            )
            if response.text is None:
                raise GeminiError("Gemini Vision returned empty response")
            return response.text
        except Exception as e:
            raise GeminiError(f"Gemini Vision API error: {e}") from e


# =============================================================================
# CLI Runner (subprocess-based, supports tool use)
# =============================================================================


@dataclass
class GeminiModelUsage:
    """Token usage for a single model in Gemini CLI session."""

    model: str
    requests: int = 0
    input_tokens: int = 0
    cache_reads: int = 0
    output_tokens: int = 0


@dataclass
class GeminiSessionStats:
    """Session statistics from Gemini CLI /stats command."""

    session_id: str | None = None
    tool_calls_total: int = 0
    tool_calls_success: int = 0
    tool_calls_failed: int = 0
    success_rate: float = 0.0
    wall_time_seconds: float = 0.0
    agent_active_seconds: float = 0.0
    api_time_seconds: float = 0.0
    api_time_percent: float = 0.0
    tool_time_seconds: float = 0.0
    tool_time_percent: float = 0.0
    model_usage: list[GeminiModelUsage] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens across all models."""
        return sum(m.input_tokens for m in self.model_usage)

    @property
    def total_output_tokens(self) -> int:
        """Total output tokens across all models."""
        return sum(m.output_tokens for m in self.model_usage)

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output) across all models."""
        return self.total_input_tokens + self.total_output_tokens

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "tool_calls": {
                "total": self.tool_calls_total,
                "success": self.tool_calls_success,
                "failed": self.tool_calls_failed,
                "success_rate": self.success_rate,
            },
            "performance": {
                "wall_time_seconds": self.wall_time_seconds,
                "agent_active_seconds": self.agent_active_seconds,
                "api_time_seconds": self.api_time_seconds,
                "api_time_percent": self.api_time_percent,
                "tool_time_seconds": self.tool_time_seconds,
                "tool_time_percent": self.tool_time_percent,
            },
            "model_usage": [
                {
                    "model": m.model,
                    "requests": m.requests,
                    "input_tokens": m.input_tokens,
                    "cache_reads": m.cache_reads,
                    "output_tokens": m.output_tokens,
                }
                for m in self.model_usage
            ],
            "totals": {
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "total_tokens": self.total_tokens,
            },
        }


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
    session_stats: GeminiSessionStats | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def _parse_time_string(time_str: str) -> float:
    """Parse time string like '2m 54s' or '6.2s' to seconds."""
    if not time_str:
        return 0.0

    total_seconds = 0.0
    # Match minutes
    m_match = re.search(r"(\d+)m", time_str)
    if m_match:
        total_seconds += int(m_match.group(1)) * 60
    # Match seconds (including decimals)
    s_match = re.search(r"([\d.]+)s", time_str)
    if s_match:
        total_seconds += float(s_match.group(1))
    return total_seconds


def _parse_token_count(token_str: str) -> int:
    """Parse token count string like '1,435' or '10449' to int."""
    if not token_str:
        return 0
    # Remove commas and convert
    return int(token_str.replace(",", "").strip())


def _parse_stats_output(stats_output: str) -> GeminiSessionStats:
    """Parse the output of Gemini CLI /stats command.

    Example input:
        Session Stats
        Session ID: 5023644b-f81c-4fc7-8d0d-f61906c4a4d5
        Tool Calls: 5 ( ✓ 4 x 1 )
        Success Rate: 80.0%
        Performance
        Wall Time: 2m 54s
        Agent Active: 6.2s
          » API Time: 6.2s (100.0%)
          » Tool Time: 0s (0.0%)
        Model Usage                 Reqs   Input Tokens   Cache Reads  Output Tokens
        ────────────────────────────────────────────────────────────────────────────
        gemini-2.5-flash-lite          1          1,435             0             12
        gemini-3-flash-preview         1         10,449             0             50
    """
    stats = GeminiSessionStats()

    # Session ID
    session_match = re.search(r"Session ID:\s*([\w-]+)", stats_output)
    if session_match:
        stats.session_id = session_match.group(1)

    # Tool Calls: 5 ( ✓ 4 x 1 )
    tool_match = re.search(r"Tool Calls:\s*(\d+)\s*\(\s*✓\s*(\d+)\s*x\s*(\d+)\s*\)", stats_output)
    if tool_match:
        stats.tool_calls_total = int(tool_match.group(1))
        stats.tool_calls_success = int(tool_match.group(2))
        stats.tool_calls_failed = int(tool_match.group(3))

    # Success Rate: 80.0%
    success_match = re.search(r"Success Rate:\s*([\d.]+)%", stats_output)
    if success_match:
        stats.success_rate = float(success_match.group(1))

    # Wall Time: 2m 54s
    wall_match = re.search(r"Wall Time:\s*([\dm\s.]+s)", stats_output)
    if wall_match:
        stats.wall_time_seconds = _parse_time_string(wall_match.group(1))

    # Agent Active: 6.2s
    active_match = re.search(r"Agent Active:\s*([\dm\s.]+s)", stats_output)
    if active_match:
        stats.agent_active_seconds = _parse_time_string(active_match.group(1))

    # API Time: 6.2s (100.0%)
    api_match = re.search(r"API Time:\s*([\dm\s.]+s)\s*\(([\d.]+)%\)", stats_output)
    if api_match:
        stats.api_time_seconds = _parse_time_string(api_match.group(1))
        stats.api_time_percent = float(api_match.group(2))

    # Tool Time: 0s (0.0%)
    tool_time_match = re.search(r"Tool Time:\s*([\dm\s.]+s)\s*\(([\d.]+)%\)", stats_output)
    if tool_time_match:
        stats.tool_time_seconds = _parse_time_string(tool_time_match.group(1))
        stats.tool_time_percent = float(tool_time_match.group(2))

    # Model Usage table - find lines after the header separator
    # Pattern: model_name   reqs   input_tokens   cache_reads   output_tokens
    model_lines = re.findall(
        r"^\s*([\w.-]+)\s+(\d+)\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s*$",
        stats_output,
        re.MULTILINE,
    )
    for match in model_lines:
        model_name, reqs, input_tokens, cache_reads, output_tokens = match
        # Skip if it looks like a header
        if model_name.lower() in ("model", "usage", "reqs"):
            continue
        stats.model_usage.append(
            GeminiModelUsage(
                model=model_name,
                requests=int(reqs),
                input_tokens=_parse_token_count(input_tokens),
                cache_reads=int(cache_reads),
                output_tokens=_parse_token_count(output_tokens),
            )
        )

    return stats


# Stats output marker to identify where stats begin in output
STATS_MARKER = "Session Stats"


def _parse_stream_json_stats(result_data: dict[str, Any]) -> GeminiSessionStats:
    """Parse stats from stream-json result message.

    Example result_data:
        {
            "type": "result",
            "status": "success",
            "stats": {
                "total_tokens": 626568,
                "input_tokens": 617877,
                "output_tokens": 2334,
                "cached": 354810,
                "input": 263067,
                "duration_ms": 92993,
                "tool_calls": 25
            }
        }
    """
    stats = GeminiSessionStats()

    if "stats" not in result_data:
        return stats

    s = result_data["stats"]

    # Map stream-json stats to our dataclass
    stats.tool_calls_total = s.get("tool_calls", 0)
    stats.wall_time_seconds = s.get("duration_ms", 0) / 1000.0

    # Create a single model usage entry with aggregated stats
    if s.get("total_tokens", 0) > 0 or s.get("input_tokens", 0) > 0:
        stats.model_usage.append(
            GeminiModelUsage(
                model=result_data.get("model", "unknown"),
                requests=1,
                input_tokens=s.get("input_tokens", 0),
                cache_reads=s.get("cached", 0),
                output_tokens=s.get("output_tokens", 0),
            )
        )

    return stats


class GeminiCLI:
    """
    Gemini CLI runner for autonomous tasks with tool use.

    Unlike GeminiClient (SDK), this executes the `gemini` CLI binary
    which can use tools to read files, explore code, etc.

    Usage:
        cli = GeminiCLI(working_dir=repo_path)
        result = await cli.run("Analyze this codebase...")

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
        summarize_tool_output: bool = True,
        s3_prefix: str = "gemini-cli",
    ):
        """
        Initialize Gemini CLI runner.

        Args:
            working_dir: Working directory for CLI process
            model: Model name or type ("flash", "pro")
            timeout: Timeout in seconds
            auto_accept: Enable --yolo flag (auto-approve tool calls)
            summarize_tool_output: IGNORED - Gemini CLI doesn't support this flag
            s3_prefix: S3 path prefix for logs
        """
        self.settings = get_settings()
        self.working_dir = working_dir
        self.timeout = timeout
        self.auto_accept = auto_accept
        # summarize_tool_output is ignored - Gemini CLI doesn't support it
        self.s3_prefix = s3_prefix

        # Resolve model name
        if model is None:
            self.model = self.settings.agents.gemini_pro_model
        elif model in GEMINI_MODEL_MAP:
            self.model = GEMINI_MODEL_MAP[model]
        else:
            self.model = model

        # S3 saver (unified artifact saving)
        self._s3_saver = S3ArtifactSaver(
            bucket=self.settings.thinking.s3_bucket,
            region=self.settings.thinking.s3_region,
            prefix=self.s3_prefix,
        )

    async def run(
        self,
        prompt: str,
        context_id: str | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        # Operation tracking parameters
        track_operation: bool = True,
        operation_type: str | None = None,
        repo_name: str | None = None,
        user_name: str | None = None,
        operation_details: dict[str, Any] | None = None,
    ) -> GeminiCLIResult:
        """
        Execute Gemini CLI and return result.

        Args:
            prompt: The prompt to send
            context_id: Optional ID for S3 logging
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            on_chunk: Optional callback for streaming output
            track_operation: Enable automatic operation tracking (default: True)
            operation_type: Explicit operation type ("fix", "review", etc.)
            repo_name: Repository name for display in banner
            user_name: User who initiated the operation
            operation_details: Additional metadata for the operation

        Returns:
            GeminiCLIResult with output and S3 URLs
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

        # Create wrapped chunk callback that publishes to tracker for SSE subscribers
        effective_on_chunk: Callable[[str], Awaitable[None]] | None = on_chunk
        tracker = None
        if operation:
            try:
                from turbowrap.api.services.operation_tracker import get_tracker

                tracker = get_tracker()
                if tracker.has_subscribers(operation.operation_id):
                    original_on_chunk = on_chunk

                    async def _wrapped_on_chunk(chunk: str) -> None:
                        """Callback that sends chunk to both original callback and SSE subscribers."""
                        # Call original callback if present
                        if original_on_chunk:
                            await original_on_chunk(chunk)
                        # Publish to tracker for SSE subscribers
                        await tracker.publish_event(
                            operation.operation_id, "chunk", {"content": chunk}
                        )

                    effective_on_chunk = _wrapped_on_chunk
                    logger.debug(
                        f"[GEMINI CLI] SSE subscribers active for {operation.operation_id[:8]}"
                    )
            except Exception as e:
                logger.warning(f"[GEMINI CLI] Failed to setup SSE publishing: {e}")

        # Save prompt to S3 before running
        s3_prompt_url = None
        if save_prompt:
            s3_prompt_url = await self._s3_saver.save_markdown(
                prompt, "prompt", context_id, {"model": self.model}, "Gemini CLI"
            )

            # Update operation with S3 URL for live visibility
            if operation and s3_prompt_url:
                self._update_operation(operation.operation_id, {"s3_prompt_url": s3_prompt_url})

        try:
            # Build environment with API key
            env = os.environ.copy()
            api_key = get_google_api_key()
            if api_key:
                env["GEMINI_API_KEY"] = api_key

            # Build command with stream-json output
            args = ["gemini", "--model", self.model, "-o", "stream-json"]
            if self.auto_accept:
                args.extend(["--approval-mode", "yolo"])
            # Add the prompt as positional argument
            args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            logger.info(f"[GEMINI CLI] Starting stream-json mode with model: {self.model}")
            logger.info(f"[GEMINI CLI] Prompt length: {len(prompt)} chars")

            # Launch process (no stdin needed with positional prompt)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # Parse stream-json output
            output_chunks: list[str] = []
            session_id: str | None = None
            model_from_init: str | None = None
            result_data: dict[str, Any] | None = None
            line_buffer = ""
            tools_used: set[str] = set()

            async def read_stream() -> None:
                nonlocal line_buffer, session_id, model_from_init, result_data, tools_used
                assert process.stdout is not None

                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break

                    # Decode and process line by line
                    line_buffer += chunk.decode("utf-8", errors="replace")

                    while "\n" in line_buffer:
                        line, line_buffer = line_buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            data = json.loads(line)
                            msg_type = data.get("type", "")

                            if msg_type == "init":
                                # {"type":"init","session_id":"...","model":"..."}
                                session_id = data.get("session_id")
                                model_from_init = data.get("model")
                                logger.info(
                                    f"[GEMINI CLI] Init: session={session_id}, model={model_from_init}"
                                )

                            elif msg_type == "message" and data.get("role") == "assistant":
                                # {"type":"message","role":"assistant","content":"...","delta":true}
                                content = data.get("content", "")
                                if content:
                                    output_chunks.append(content)
                                    if effective_on_chunk:
                                        await effective_on_chunk(content)

                            elif msg_type == "result":
                                # {"type":"result","status":"success","stats":{...}}
                                result_data = data
                                logger.info(f"[GEMINI CLI] Result: status={data.get('status')}")

                            elif msg_type == "tool_use":
                                # {"type":"tool_use","tool_name":"delegate_to_agent","tool_id":"...","parameters":{}}
                                tool_name = data.get("tool_name", "unknown")
                                if tool_name and tool_name != "unknown":
                                    tools_used.add(tool_name)
                                if effective_on_chunk:
                                    await effective_on_chunk(f"\n🔧 **Tool:** `{tool_name}`\n")

                            elif msg_type == "tool_result":
                                # {"type":"tool_result","tool_id":"...","status":"success|error","output":"..."}
                                status = data.get("status", "unknown")
                                status_icon = "✅" if status == "success" else "❌"
                                error_msg = (
                                    data.get("error", {}).get("message", "")
                                    if status == "error"
                                    else ""
                                )
                                if effective_on_chunk:
                                    if error_msg:
                                        await effective_on_chunk(f"{status_icon} `{error_msg}`\n")
                                    else:
                                        await effective_on_chunk(f"{status_icon} Tool completed\n")

                        except json.JSONDecodeError:
                            # Not JSON, could be raw output - skip
                            pass

            try:
                await asyncio.wait_for(read_stream(), timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.error(f"[GEMINI CLI] Timeout after {self.timeout}s")
                process.kill()

                duration_ms = int((time.time() - start_time) * 1000)
                partial_output = "".join(output_chunks)

                if operation:
                    self._fail_operation(operation.operation_id, f"Timeout after {self.timeout}s")
                    # Signal SSE subscribers that operation failed
                    if tracker:
                        await tracker.signal_completion(operation.operation_id)

                return GeminiCLIResult(
                    success=False,
                    output=partial_output,
                    raw_output=partial_output if partial_output else None,
                    error=f"Timeout after {self.timeout}s",
                    model=self.model,
                    duration_ms=duration_ms,
                    s3_prompt_url=s3_prompt_url,
                )

            await process.wait()

            duration_ms = int((time.time() - start_time) * 1000)
            output = "".join(output_chunks)

            # Parse stats from result message
            session_stats: GeminiSessionStats | None = None
            if result_data:
                try:
                    # Add model from init if available
                    if model_from_init:
                        result_data["model"] = model_from_init
                    session_stats = _parse_stream_json_stats(result_data)
                    session_stats.session_id = session_id

                    logger.info(
                        f"[GEMINI CLI] Stats: {session_stats.total_tokens} tokens, "
                        f"{session_stats.tool_calls_total} tool calls"
                    )
                except Exception as e:
                    logger.warning(f"[GEMINI CLI] Failed to parse stats: {e}")

            # Save output to S3
            s3_output_url = None
            if save_output and output:
                s3_output_url = await self._s3_saver.save_markdown(
                    output,
                    "output",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                    "Gemini CLI",
                )

            # Check result status
            status = result_data.get("status", "unknown") if result_data else "unknown"
            if process.returncode != 0 or status != "success":
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = (
                    f"Exit code {process.returncode}, status={status}: {stderr.decode()[:500]}"
                )
                logger.error(f"[GEMINI CLI] Failed: {error_msg}")

                if operation:
                    self._fail_operation(operation.operation_id, error_msg)
                    # Signal SSE subscribers that operation failed
                    if tracker:
                        await tracker.signal_completion(operation.operation_id)

                return GeminiCLIResult(
                    success=False,
                    output=output,
                    raw_output=output,
                    error=error_msg,
                    duration_ms=duration_ms,
                    model=model_from_init or self.model,
                    s3_prompt_url=s3_prompt_url,
                    s3_output_url=s3_output_url,
                    session_stats=session_stats,
                )

            # Auto-complete operation with stats
            if operation:
                self._complete_operation(
                    operation.operation_id,
                    duration_ms=duration_ms,
                    session_stats=session_stats,
                    tools_used=tools_used,
                )
                # Signal SSE subscribers that operation completed
                if tracker:
                    await tracker.signal_completion(operation.operation_id)

            logger.info(f"[GEMINI CLI] Completed in {duration_ms}ms")
            return GeminiCLIResult(
                success=True,
                output=output,
                raw_output=output,
                duration_ms=duration_ms,
                model=model_from_init or self.model,
                s3_prompt_url=s3_prompt_url,
                s3_output_url=s3_output_url,
                session_stats=session_stats,
            )

        except FileNotFoundError:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "Gemini CLI not found"
            if save_output:
                await self._s3_saver.save_markdown(
                    f"# Error\n\n{error_msg}",
                    "error",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                    "Gemini CLI",
                )
            # Auto-fail operation
            if operation:
                self._fail_operation(operation.operation_id, error_msg)
                # Signal SSE subscribers that operation failed
                if tracker:
                    await tracker.signal_completion(operation.operation_id)

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
                await self._s3_saver.save_markdown(
                    f"# Exception\n\n{e!s}",
                    "error",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                    "Gemini CLI",
                )
            # Auto-fail operation
            if operation:
                self._fail_operation(operation.operation_id, str(e)[:200])
                # Signal SSE subscribers that operation failed
                if tracker:
                    await tracker.signal_completion(operation.operation_id)

            return GeminiCLIResult(
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

        # Infer from prompt keywords
        prompt_lower = prompt.lower()[:500]
        if "fix" in prompt_lower or "correggi" in prompt_lower:
            return "fix"
        if "review" in prompt_lower or "analizza" in prompt_lower:
            return "review"
        if "lint" in prompt_lower or "mypy" in prompt_lower or "ruff" in prompt_lower:
            return "review"
        if "commit" in prompt_lower:
            return "git_commit"
        if "merge" in prompt_lower:
            return "git_merge"

        # Default: generic CLI task
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

            # Extract prompt preview (first 150 chars, cleaned)
            prompt_preview = prompt[:150].replace("\n", " ").strip()
            if len(prompt) > 150:
                prompt_preview += "..."

            operation = tracker.register(
                op_type=op_type,
                operation_id=context_id or str(uuid.uuid4()),
                repo_name=repo_name or self._extract_repo_name(),
                user=user_name,
                details={
                    "model": self.model,
                    "cli": "gemini",
                    "working_dir": str(self.working_dir) if self.working_dir else None,
                    "prompt_preview": prompt_preview,
                    "prompt_length": len(prompt),
                    **(operation_details or {}),
                },
            )

            logger.info(
                f"[GEMINI CLI] Operation registered: {operation.operation_id[:8]} "
                f"({op_type.value})"
            )
            return operation

        except Exception as e:
            import traceback

            logger.error(
                f"[GEMINI CLI] Failed to register operation: {e}\n{traceback.format_exc()}"
            )
            return None

    def _complete_operation(
        self,
        operation_id: str,
        duration_ms: int,
        session_stats: GeminiSessionStats | None = None,
        tools_used: set[str] | None = None,
    ) -> None:
        """Complete operation in tracker with session stats."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()

            # Build result with stats if available
            result: dict[str, Any] = {
                "duration_ms": duration_ms,
                "model": self.model,
            }

            if session_stats:
                result["session_stats"] = session_stats.to_dict()
                result["total_tokens"] = session_stats.total_tokens
                result["total_input_tokens"] = session_stats.total_input_tokens
                result["total_output_tokens"] = session_stats.total_output_tokens
                result["tool_calls"] = session_stats.tool_calls_total
                result["models_used"] = [m.model for m in session_stats.model_usage]

            # Add tools used (sorted for consistency)
            result["tools_used"] = sorted(tools_used) if tools_used else []

            tracker.complete(operation_id, result=result)
            logger.info(
                f"[GEMINI CLI] Operation completed: {operation_id[:8]} "
                f"({session_stats.total_tokens if session_stats else 0} tokens, "
                f"{len(tools_used or [])} tools)"
            )

        except Exception as e:
            import traceback

            logger.error(
                f"[GEMINI CLI] Failed to complete operation: {e}\n{traceback.format_exc()}"
            )

    def _fail_operation(self, operation_id: str, error: str) -> None:
        """Fail operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.fail(operation_id, error=error[:200])
            logger.info(f"[GEMINI CLI] Operation failed: {operation_id[:8]}")

        except Exception as e:
            import traceback

            logger.error(
                f"[GEMINI CLI] Failed to mark operation as failed: {e}\n{traceback.format_exc()}"
            )

    def _update_operation(self, operation_id: str, details: dict[str, Any]) -> None:
        """Update operation details in tracker (e.g., add S3 URLs)."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.update(operation_id, details=details)

        except Exception as e:
            import traceback

            logger.error(f"[GEMINI CLI] Failed to update operation: {e}\n{traceback.format_exc()}")
