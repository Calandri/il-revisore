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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from turbowrap.config import get_settings
from turbowrap.exceptions import GeminiError
from turbowrap.llm.base import AgentResponse, BaseAgent
from turbowrap.llm.mixins import OperationTrackingMixin
from turbowrap.utils.aws_secrets import get_google_api_key
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)

GeminiModelType = Literal["flash", "pro"]
GEMINI_MODEL_MAP = {
    "flash": "gemini-3-flash-preview",
    "pro": "gemini-3-pro-preview",
}

# Gemini pricing per 1M tokens (USD)
# Reference: https://ai.google.dev/pricing
GEMINI_PRICING: dict[str, dict[str, float]] = {
    # Gemini 2.0 Flash
    "gemini-2.0-flash": {
        "input": 0.10,
        "output": 0.40,
        "cached": 0.025,
    },
    "gemini-2.0-flash-lite": {
        "input": 0.075,
        "output": 0.30,
        "cached": 0.01875,
    },
    # Gemini 2.5 Flash (preview)
    "gemini-2.5-flash-preview-05-20": {
        "input": 0.15,
        "output": 0.60,
        "cached": 0.0375,
    },
    # Gemini 3 Flash (preview) - using 2.5 pricing as estimate
    "gemini-3-flash-preview": {
        "input": 0.15,
        "output": 0.60,
        "cached": 0.0375,
    },
    # Gemini 1.5 Pro
    "gemini-1.5-pro": {
        "input": 1.25,
        "output": 5.00,
        "cached": 0.3125,
    },
    # Gemini 2.5 Pro (preview)
    "gemini-2.5-pro-preview-05-06": {
        "input": 1.25,
        "output": 10.00,
        "cached": 0.3125,
    },
    # Gemini 3 Pro (preview) - using 2.5 pricing as estimate
    "gemini-3-pro-preview": {
        "input": 1.25,
        "output": 10.00,
        "cached": 0.3125,
    },
}

# Default pricing for unknown models (conservative estimate)
DEFAULT_GEMINI_PRICING = {
    "input": 0.15,
    "output": 0.60,
    "cached": 0.0375,
}

DEFAULT_GEMINI_TIMEOUT = 120


def calculate_gemini_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Calculate cost for Gemini API usage.

    Args:
        model: Model name
        input_tokens: Number of input tokens (non-cached)
        output_tokens: Number of output tokens
        cached_tokens: Number of cached input tokens

    Returns:
        Cost in USD
    """
    # Get pricing for model, fallback to default
    pricing = GEMINI_PRICING.get(model, DEFAULT_GEMINI_PRICING)

    # Calculate cost (pricing is per 1M tokens)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]

    return input_cost + output_cost + cached_cost


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

        for img_path in image_paths:
            try:
                with open(img_path, "rb") as f:
                    image_data = f.read()

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


# CLI Runner (subprocess-based, supports tool use)


@dataclass
class GeminiModelUsage:
    """Token usage for a single model in Gemini CLI session."""

    model: str
    requests: int = 0
    input_tokens: int = 0
    cache_reads: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


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

    stats.tool_calls_total = s.get("tool_calls", 0)
    stats.wall_time_seconds = s.get("duration_ms", 0) / 1000.0

    # Create a single model usage entry with aggregated stats
    if s.get("total_tokens", 0) > 0 or s.get("input_tokens", 0) > 0:
        model_name = result_data.get("model", "unknown")
        # Gemini CLI provides:
        # - "input": non-cached input tokens
        # - "cached": cached input tokens
        # - "input_tokens": total input (input + cached) - for reference only
        # - "output_tokens": output tokens
        non_cached_input = s.get("input", 0)
        cached_tokens = s.get("cached", 0)
        output_tokens = s.get("output_tokens", 0)

        # Calculate cost from tokens using pricing table
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
                input_tokens=s.get("input_tokens", 0),  # Total input for display
                cache_reads=cached_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        )

    return stats


class GeminiCLI(OperationTrackingMixin):
    """
    Gemini CLI runner for autonomous tasks with tool use.

    Unlike GeminiClient (SDK), this executes the `gemini` CLI binary
    which can use tools to read files, explore code, etc.

    Usage:
        cli = GeminiCLI(working_dir=repo_path)
        result = await cli.run("Analyze this codebase...")

        async def on_chunk(text: str):
            print(text, end="")
        result = await cli.run("Review...", on_chunk=on_chunk)
    """

    # OperationTrackingMixin config
    cli_name = "gemini"

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
        self.s3_prefix = s3_prefix

        if model is None:
            self.model = self.settings.agents.gemini_pro_model
        elif model in GEMINI_MODEL_MAP:
            self.model = GEMINI_MODEL_MAP[model]
        else:
            self.model = model

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
        context_id: str | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        track_operation: bool = True,
        user_name: str | None = None,
        operation_details: dict[str, Any] | None = None,
    ) -> GeminiCLIResult:
        """
        Execute Gemini CLI and return result.

        Args:
            prompt: The prompt to send
            operation_type: Operation type ("fix", "review", "git_merge", etc.) - REQUIRED
            repo_name: Repository name for tracking - REQUIRED
            context_id: Optional ID for S3 logging
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            on_chunk: Optional callback for streaming output
            track_operation: Enable automatic operation tracking (default: True)
            user_name: User who initiated the operation (optional)
            operation_details: Additional metadata for the operation (optional)

        Returns:
            GeminiCLIResult with output and S3 URLs
        """
        import time

        start_time = time.time()

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
        # NOTE: Always publish, subscribers can join at any time during the operation
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
                    # Publish to tracker for SSE subscribers (they can join anytime)
                    await tracker.publish_event(operation.operation_id, "chunk", {"content": chunk})

                effective_on_chunk = _wrapped_on_chunk
                logger.debug(
                    f"[GEMINI CLI] SSE publishing enabled for {operation.operation_id[:8]}"
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

            # Disable IDE/VS Code connection
            env["GEMINI_CODE_CONNECT"] = "false"

            # Build command with stream-json output and sandbox mode
            args = ["gemini", "--model", self.model, "-o", "stream-json", "--sandbox"]
            if self.auto_accept:
                args.extend(["--approval-mode", "yolo"])
            args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            logger.info(f"[GEMINI CLI] Starting stream-json mode with model: {self.model}")
            logger.info(f"[GEMINI CLI] Prompt length: {len(prompt)} chars")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            output_chunks: list[str] = []
            raw_output_lines: list[str] = []  # ALL raw JSON lines for S3
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
                                session_id = data.get("session_id")
                                model_from_init = data.get("model")
                                logger.info(
                                    f"[GEMINI CLI] Init: session={session_id}, model={model_from_init}"
                                )

                            elif msg_type == "message" and data.get("role") == "assistant":
                                content = data.get("content", "")
                                if content:
                                    output_chunks.append(content)
                                    if effective_on_chunk:
                                        await effective_on_chunk(content)

                            elif msg_type == "result":
                                result_data = data
                                logger.info(f"[GEMINI CLI] Result: status={data.get('status')}")

                            elif msg_type == "tool_use":
                                tool_name = data.get("tool_name", "unknown")
                                if tool_name and tool_name != "unknown":
                                    tools_used.add(tool_name)
                                if effective_on_chunk:
                                    await effective_on_chunk(f"\n🔧 **Tool:** `{tool_name}`\n")

                            elif msg_type == "tool_result":
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

            session_stats: GeminiSessionStats | None = None
            if result_data:
                try:
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

            # Save output to S3 - BOTH raw JSONL and readable markdown
            s3_output_url = None
            if save_output:
                if raw_output_lines:
                    raw_content = "\n".join(raw_output_lines)
                    s3_output_url = await self._s3_saver.save_raw(
                        raw_content,
                        "output",
                        context_id,
                    )
                if output:
                    await self._s3_saver.save_markdown(
                        output,
                        "output_readable",
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

            if operation:
                self._complete_operation(
                    operation.operation_id,
                    duration_ms=duration_ms,
                    session_stats=session_stats,
                    tools_used=tools_used,
                    s3_prompt_url=s3_prompt_url,
                    s3_output_url=s3_output_url,
                )
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
            if operation:
                self._fail_operation(operation.operation_id, error_msg)
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
            if operation:
                self._fail_operation(operation.operation_id, str(e)[:200])
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

    def _complete_operation(
        self,
        operation_id: str,
        duration_ms: int,
        session_stats: GeminiSessionStats | None = None,
        tools_used: set[str] | None = None,
        s3_prompt_url: str | None = None,
        s3_output_url: str | None = None,
    ) -> None:
        """Complete operation in tracker with session stats and S3 URLs."""
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
                # Read cost directly from model usage (if provided by Gemini CLI)
                result["cost_usd"] = sum(m.cost_usd for m in session_stats.model_usage)
                # Include detailed model usage with costs
                result["model_usage"] = [
                    {
                        "model": m.model,
                        "requests": m.requests,
                        "input_tokens": m.input_tokens,
                        "cache_reads": m.cache_reads,
                        "output_tokens": m.output_tokens,
                        "cost_usd": m.cost_usd,
                    }
                    for m in session_stats.model_usage
                ]

            result["tools_used"] = sorted(tools_used) if tools_used else []

            result["s3_prompt_url"] = s3_prompt_url
            result["s3_output_url"] = s3_output_url

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
