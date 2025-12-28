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

# Python 3.11+ has asyncio.timeout, older versions need async_timeout
if sys.version_info >= (3, 11):
    asyncio_timeout = asyncio.timeout
else:
    try:
        from async_timeout import timeout as asyncio_timeout
    except ImportError:
        # Fallback: create a no-timeout context manager
        from collections.abc import AsyncIterator
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def asyncio_timeout(seconds: float) -> AsyncIterator[None]:
            yield


import codecs
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from turbowrap.config import get_settings
from turbowrap.utils.aws_secrets import get_anthropic_api_key
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)

# Model aliases
ModelType = Literal["opus", "sonnet", "haiku"]
MODEL_MAP = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-20250514",
    "haiku": "claude-haiku-4-5-20251001",
}

# Default timeout
DEFAULT_TIMEOUT = 180

# Tool presets for different use cases (only works with --print mode)
# Use preset name or custom comma-separated tool list
ToolPreset = Literal["fix", "default"]
TOOL_PRESETS: dict[str, str] = {
    # Fix: modify code + web search if needed
    "fix": "Bash,Read,Edit,Write,Glob,Grep,TodoWrite,WebFetch,WebSearch",
    # Default: all tools
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
class ClaudeContextStats:
    """Context usage statistics from Claude CLI /context command."""

    model: str = ""
    tokens_used: int = 0
    tokens_max: int = 0
    usage_percent: float = 0.0
    system_prompt_tokens: int = 0
    system_prompt_percent: float = 0.0
    system_tools_tokens: int = 0
    system_tools_percent: float = 0.0
    mcp_tools_tokens: int = 0
    mcp_tools_percent: float = 0.0
    custom_agents_tokens: int = 0
    custom_agents_percent: float = 0.0
    messages_tokens: int = 0
    messages_percent: float = 0.0
    free_space_tokens: int = 0
    free_space_percent: float = 0.0
    autocompact_buffer_tokens: int = 0
    autocompact_buffer_percent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model": self.model,
            "context": {
                "tokens_used": self.tokens_used,
                "tokens_max": self.tokens_max,
                "usage_percent": self.usage_percent,
            },
            "breakdown": {
                "system_prompt": {
                    "tokens": self.system_prompt_tokens,
                    "percent": self.system_prompt_percent,
                },
                "system_tools": {
                    "tokens": self.system_tools_tokens,
                    "percent": self.system_tools_percent,
                },
                "mcp_tools": {
                    "tokens": self.mcp_tools_tokens,
                    "percent": self.mcp_tools_percent,
                },
                "custom_agents": {
                    "tokens": self.custom_agents_tokens,
                    "percent": self.custom_agents_percent,
                },
                "messages": {
                    "tokens": self.messages_tokens,
                    "percent": self.messages_percent,
                },
                "free_space": {
                    "tokens": self.free_space_tokens,
                    "percent": self.free_space_percent,
                },
                "autocompact_buffer": {
                    "tokens": self.autocompact_buffer_tokens,
                    "percent": self.autocompact_buffer_percent,
                },
            },
        }


def _parse_token_string(token_str: str) -> int:
    """Parse token string like '3.4k' or '175.0k' or '317' to int."""
    if not token_str:
        return 0
    token_str = token_str.strip().lower()
    if token_str.endswith("k"):
        return int(float(token_str[:-1]) * 1000)
    return int(float(token_str.replace(",", "")))


def _parse_context_output(context_output: str) -> ClaudeContextStats:
    """Parse the output of Claude CLI /context command.

    Example input:
        Context Usage
        ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁   claude-opus-4-5-20251101 · 93k/200k tokens (47%)
        ...
        ⛁ System prompt: 3.4k tokens (1.7%)
        ⛁ System tools: 17.2k tokens (8.6%)
        ⛁ MCP tools: 26.1k tokens (13.0%)
        ⛁ Custom agents: 1.4k tokens (0.7%)
        ⛁ Messages: 317 tokens (0.2%)
        ⛶ Free space: 107k (53.3%)
        ⛝ Autocompact buffer: 45.0k tokens (22.5%)
    """
    stats = ClaudeContextStats()

    # Model and main usage: claude-opus-4-5-20251101 · 93k/200k tokens (47%)
    main_match = re.search(
        r"(claude-[\w-]+)\s*[·•]\s*([\d.]+k?)\s*/\s*([\d.]+k?)\s*tokens\s*\(([\d.]+)%\)",
        context_output,
    )
    if main_match:
        stats.model = main_match.group(1)
        stats.tokens_used = _parse_token_string(main_match.group(2))
        stats.tokens_max = _parse_token_string(main_match.group(3))
        stats.usage_percent = float(main_match.group(4))

    # System prompt: 3.4k tokens (1.7%)
    sys_prompt_match = re.search(
        r"System prompt:\s*([\d.]+k?)\s*tokens?\s*\(([\d.]+)%\)", context_output
    )
    if sys_prompt_match:
        stats.system_prompt_tokens = _parse_token_string(sys_prompt_match.group(1))
        stats.system_prompt_percent = float(sys_prompt_match.group(2))

    # System tools: 17.2k tokens (8.6%)
    sys_tools_match = re.search(
        r"System tools:\s*([\d.]+k?)\s*tokens?\s*\(([\d.]+)%\)", context_output
    )
    if sys_tools_match:
        stats.system_tools_tokens = _parse_token_string(sys_tools_match.group(1))
        stats.system_tools_percent = float(sys_tools_match.group(2))

    # MCP tools: 26.1k tokens (13.0%)
    mcp_match = re.search(r"MCP tools:\s*([\d.]+k?)\s*tokens?\s*\(([\d.]+)%\)", context_output)
    if mcp_match:
        stats.mcp_tools_tokens = _parse_token_string(mcp_match.group(1))
        stats.mcp_tools_percent = float(mcp_match.group(2))

    # Custom agents: 1.4k tokens (0.7%)
    agents_match = re.search(
        r"Custom agents:\s*([\d.]+k?)\s*tokens?\s*\(([\d.]+)%\)", context_output
    )
    if agents_match:
        stats.custom_agents_tokens = _parse_token_string(agents_match.group(1))
        stats.custom_agents_percent = float(agents_match.group(2))

    # Messages: 317 tokens (0.2%)
    messages_match = re.search(r"Messages:\s*([\d.]+k?)\s*tokens?\s*\(([\d.]+)%\)", context_output)
    if messages_match:
        stats.messages_tokens = _parse_token_string(messages_match.group(1))
        stats.messages_percent = float(messages_match.group(2))

    # Free space: 107k (53.3%)
    free_match = re.search(r"Free space:\s*([\d.]+k?)\s*\(([\d.]+)%\)", context_output)
    if free_match:
        stats.free_space_tokens = _parse_token_string(free_match.group(1))
        stats.free_space_percent = float(free_match.group(2))

    # Autocompact buffer: 45.0k tokens (22.5%)
    buffer_match = re.search(
        r"Autocompact buffer:\s*([\d.]+k?)\s*tokens?\s*\(([\d.]+)%\)", context_output
    )
    if buffer_match:
        stats.autocompact_buffer_tokens = _parse_token_string(buffer_match.group(1))
        stats.autocompact_buffer_percent = float(buffer_match.group(2))

    return stats


# Context output marker to identify where context stats begin
CONTEXT_MARKER = "Context Usage"


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
    context_stats: ClaudeContextStats | None = None
    session_id: str | None = None  # Session ID for --resume


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

        # Resolve tools: preset name -> tool list, or use as-is
        if tools is None:
            self.tools = None  # Use all tools (default)
        elif tools in TOOL_PRESETS:
            self.tools = TOOL_PRESETS[tools]
        else:
            self.tools = tools  # Custom comma-separated list

        # Resolve model name
        if model is None:
            self.model = self.settings.agents.claude_model
        elif model in MODEL_MAP:
            self.model = MODEL_MAP[model]
        else:
            self.model = model

        # S3 saver (unified artifact saving)
        self._s3_saver = S3ArtifactSaver(
            bucket=self.settings.thinking.s3_bucket,
            region=self.settings.thinking.s3_region,
            prefix=self.s3_prefix,
        )

        # Agent prompt cache
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

        # Strip YAML front matter if present (starts with ---)
        # This is metadata for Claude Code, not part of the prompt
        if content.startswith("---"):
            # Find closing ---
            end_idx = content.find("---", 3)
            if end_idx != -1:
                # Skip past the closing --- and any following newlines
                content = content[end_idx + 3 :].lstrip("\n")
                logger.info(
                    f"[CLAUDE CLI] Stripped YAML front matter from {self.agent_md_path.name}"
                )

        self._agent_prompt = content
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
        on_thinking: Callable[[str], Awaitable[None]] | None = None,
        on_stderr: Callable[[str], Awaitable[None]] | None = None,
        # Operation tracking parameters
        track_operation: bool = True,
        operation_type: str | None = None,
        repo_name: str | None = None,
        user_name: str | None = None,
        operation_details: dict[str, Any] | None = None,
        # Session persistence
        resume_session_id: str | None = None,
    ) -> ClaudeCLIResult:
        """Execute Claude CLI and return structured result.

        Args:
            prompt: The prompt to send to Claude
            context_id: Optional ID for S3 logging (e.g., review_id, issue_id)
            thinking_budget: Override thinking budget (None = use default from config)
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            save_thinking: Save thinking to S3
            on_chunk: Callback for streaming output chunks (text only)
            on_thinking: Callback for streaming thinking chunks (extended thinking)
            on_stderr: Callback for streaming stderr (--verbose output)
            track_operation: Enable automatic operation tracking (default: True)
            operation_type: Explicit operation type ("fix", "review", etc.)
            repo_name: Repository name for display in banner
            user_name: User who initiated the operation
            operation_details: Additional metadata for the operation
            resume_session_id: Session ID to resume (uses --resume instead of --session-id)

        Returns:
            ClaudeCLIResult with output, thinking, usage info, session_id, and S3 URLs
        """
        start_time = time.time()

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
                resume_session_id=resume_session_id,
            )
        except Exception as e:
            # Ensure operation is always closed on unexpected exceptions
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
        resume_session_id: str | None = None,
    ) -> ClaudeCLIResult:
        """Internal method that runs CLI with operation tracking.

        Separated to allow try/except wrapper in run() for guaranteed operation closure.
        """
        # Build full prompt with agent instructions
        full_prompt = self._build_full_prompt(prompt)

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
                        f"[CLAUDE CLI] SSE subscribers active for {operation.operation_id[:8]}"
                    )
            except Exception as e:
                logger.warning(f"[CLAUDE CLI] Failed to setup SSE publishing: {e}")

        # Generate context ID if not provided
        if context_id is None:
            context_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Save prompt to S3 before running
        s3_prompt_url = None
        if save_prompt:
            s3_prompt_url = await self._s3_saver.save_markdown(
                full_prompt, "prompt", context_id, {"model": self.model}, "Claude CLI"
            )

            # Update operation with S3 URL for live visibility
            if operation and s3_prompt_url:
                self._update_operation(operation.operation_id, {"s3_prompt_url": s3_prompt_url})

        # Run CLI (use wrapped callback for SSE streaming)
        (
            output,
            model_usage,
            thinking,
            raw_output,
            error,
            session_id,
            tools_used,
        ) = await self._execute_cli(
            full_prompt,
            thinking_budget,
            effective_on_chunk,
            on_thinking,
            on_stderr,
            resume_session_id,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # Save output and thinking to S3 (ALWAYS, even on error - for debugging)
        s3_output_url = None
        s3_thinking_url = None

        if save_output and output:
            s3_output_url = await self._s3_saver.save_markdown(
                output,
                "output",
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

        # Save error details to S3 if there's an error
        if error and save_output:
            await self._s3_saver.save_markdown(
                f"# Error\n\n{error}\n\n# Raw Output\n\n{raw_output or 'None'}",
                "error",
                context_id,
                {"model": self.model, "duration_ms": duration_ms},
                "Claude CLI",
            )

        if error:
            # Auto-fail operation
            if operation:
                self._fail_operation(operation.operation_id, error)
                # Signal SSE subscribers that operation failed
                if tracker:
                    await tracker.signal_completion(operation.operation_id)

            # For API errors (is_error=true), we still have output with the error message
            # Return success=False but include the output so caller can inspect error details
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

        # Auto-complete operation
        if operation:
            self._complete_operation(
                operation.operation_id,
                duration_ms=duration_ms,
                model_usage=model_usage,
                tools_used=tools_used,
            )
            # Signal SSE subscribers that operation completed
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
        on_thinking: Callable[[str], Awaitable[None]] | None,
        on_stderr: Callable[[str], Awaitable[None]] | None,
        resume_session_id: str | None = None,
    ) -> tuple[
        str | None, list[ModelUsage], str | None, str | None, str | None, str | None, set[str]
    ]:
        """Execute Claude CLI subprocess.

        Args:
            prompt: The prompt to send.
            thinking_budget: Token budget for extended thinking.
            on_chunk: Callback for text output chunks.
            on_thinking: Callback for thinking chunks (extended thinking).
            on_stderr: Callback for stderr output.
            resume_session_id: Session ID to resume (uses --resume instead of --session-id).

        Returns:
            Tuple of (output, model_usage, thinking, raw_output, error, session_id, tools_used)
        """
        try:
            # Build environment
            env = os.environ.copy()

            # GitHub token for git operations (credential helper reads from this)
            if self.github_token:
                env["GITHUB_TOKEN"] = self.github_token
                logger.info(
                    f"[CLAUDE CLI] GITHUB_TOKEN set in env (length={len(self.github_token)})"
                )
            else:
                logger.warning("[CLAUDE CLI] No GITHUB_TOKEN provided - git auth may fail")

            # Get API key from AWS Secrets Manager or environment
            api_key = get_anthropic_api_key() or os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            else:
                return None, [], None, None, "ANTHROPIC_API_KEY not found", None, set()

            # Workaround: Bun file watcher bug on macOS /var/folders
            env["TMPDIR"] = "/tmp"

            # Set thinking budget
            if self.settings.thinking.enabled:
                budget = thinking_budget or self.settings.thinking.budget_tokens
                env["MAX_THINKING_TOKENS"] = str(budget)
                logger.info(f"[CLAUDE CLI] Extended thinking: {budget} tokens")

            # Session management: resume existing or create new
            if resume_session_id:
                session_id = resume_session_id
                logger.info(f"[CLAUDE CLI] Resuming session: {session_id[:8]}...")
            else:
                session_id = str(uuid.uuid4())
                logger.info(f"[CLAUDE CLI] New session: {session_id[:8]}...")

            # Build CLI arguments
            # --include-partial-messages is REQUIRED for real-time streaming!
            args = [
                "claude",
                "--print",
                "--model",
                self.model,
                "--output-format",
                "stream-json",
                "--include-partial-messages",  # CRITICAL for streaming!
            ]

            # Tools: limit available tools (only works with --print mode)
            if self.tools and self.tools != "default":
                args.extend(["--tools", self.tools])
                logger.info(f"[CLAUDE CLI] Tools limited to: {self.tools}")

            # Session: resume existing or start new with specific ID
            if resume_session_id:
                args.extend(["--resume", session_id])
            else:
                args.extend(["--session-id", session_id])

            if self.verbose:
                args.append("--verbose")

            if self.skip_permissions:
                args.append("--dangerously-skip-permissions")

            # Prompt as last argument
            args.append(prompt)

            cwd = str(self.working_dir) if self.working_dir else None

            # Log full command for debugging (all args except prompt)
            args_display = " ".join(args[:-1])  # All args except last (prompt)
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

            # Read stderr
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

            # Read stdout with streaming
            output_chunks = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            chunks_received = 0
            total_bytes = 0
            line_buffer = ""
            in_thinking_block = False  # Track if we're streaming a thinking block
            current_block_type = ""  # Track current content block type (thinking, tool_use, text)

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

                            # Parse stream-json for streaming callback
                            # With --include-partial-messages, events are wrapped in stream_event
                            if on_chunk:
                                line_buffer += decoded
                                while "\n" in line_buffer:
                                    line, line_buffer = line_buffer.split("\n", 1)
                                    if not line.strip():
                                        continue
                                    try:
                                        event = json.loads(line)
                                        event_type = event.get("type", "")

                                        # Unwrap stream_event wrapper
                                        if event_type == "stream_event":
                                            event = event.get("event", {})
                                            event_type = event.get("type", "")

                                        # Track thinking and tool_use block state
                                        if event_type == "content_block_start":
                                            block = event.get("content_block", {})
                                            block_type = block.get("type", "")
                                            if block_type == "thinking":
                                                in_thinking_block = True
                                                current_block_type = "thinking"
                                                # Only add prefix if using on_chunk for thinking
                                                if not on_thinking:
                                                    await on_chunk("\n🧠 ")
                                            elif block_type == "tool_use":
                                                # Tool use block: show tool name
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

                                        # Extract text and thinking from content_block_delta
                                        elif event_type == "content_block_delta":
                                            delta = event.get("delta", {})
                                            delta_type = delta.get("type", "")
                                            if delta_type == "text_delta":
                                                text = delta.get("text", "")
                                                if text:
                                                    await on_chunk(text)
                                            elif delta_type == "thinking_delta":
                                                # Stream thinking to dedicated callback if available
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
                                                    # Stream complete thinking block
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
                return None, [], None, None, f"Timeout after {self.timeout}s", session_id, set()

            await stderr_task

            logger.info("[CLAUDE CLI] Waiting for process to exit...")
            await process.wait()
            logger.info(f"[CLAUDE CLI] Process exited with code {process.returncode}")

            stderr_text = "".join(stderr_chunks)
            if stderr_text:
                if process.returncode != 0:
                    logger.error(f"[CLAUDE CLI] STDERR: {stderr_text[:2000]}")
                else:
                    # Log as WARNING so it appears in Log Viewer even on success
                    logger.warning(f"[CLAUDE CLI] Output: {stderr_text[:2000]}")

            # Parse stream-json output (ALWAYS - even on error to preserve output for debugging)
            raw_output = "".join(output_chunks) if output_chunks else None

            if process.returncode != 0:
                # Still parse output to extract any useful information
                output: str | None = None
                model_usage: list[ModelUsage] = []
                thinking: str | None = None
                api_error: str | None = None
                tools_used: set[str] = set()
                if raw_output:
                    (output, model_usage, thinking, api_error, tools_used) = (
                        self._parse_stream_json(raw_output)
                    )
                    logger.info(
                        f"[CLAUDE CLI] Exit {process.returncode} "
                        f"got output: {len(raw_output)} bytes"
                    )

                error_msg = f"Exit code {process.returncode}: {stderr_text[:500]}"
                if api_error:
                    error_msg = f"{error_msg}\nAPI Error: {api_error}"

                return output, model_usage, thinking, raw_output, error_msg, session_id, tools_used

            # Normal success path
            if not raw_output:
                logger.warning("[CLAUDE CLI] No output received from CLI")
                return None, [], None, None, "No output received from CLI", session_id, set()

            (output, model_usage, thinking, api_error, tools_used) = self._parse_stream_json(
                raw_output
            )

            # Return API error as the error field if present
            if api_error:
                return output, model_usage, thinking, raw_output, api_error, session_id, tools_used

            return output, model_usage, thinking, raw_output, None, session_id, tools_used

        except FileNotFoundError:
            return None, [], None, None, "Claude CLI not found", None, set()
        except Exception as e:
            logger.exception(f"[CLAUDE CLI] Exception: {e}")
            return None, [], None, None, str(e), None, set()

    def _parse_stream_json(
        self, raw_output: str
    ) -> tuple[str, list[ModelUsage], str | None, str | None, set[str]]:
        """Parse stream-json NDJSON output.

        Handles both regular events and stream_event wrappers
        (from --include-partial-messages).

        Returns:
            Tuple of (output, model_usage, thinking, api_error, tools_used)
        """
        output = ""
        model_usage_list = []
        thinking_chunks = []
        api_error = None
        tools_used: set[str] = set()

        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type")

                # Unwrap stream_event wrapper (from --include-partial-messages)
                if event_type == "stream_event":
                    event = event.get("event", {})
                    event_type = event.get("type")

                # Capture thinking and tool_use from assistant messages
                if event_type == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "thinking":
                            thinking_text = block.get("thinking", "")
                            # Ensure thinking is a string (could be dict/list in malformed response)
                            if thinking_text and isinstance(thinking_text, str):
                                thinking_chunks.append(thinking_text)
                        # Track tool usage
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name")
                            if tool_name:
                                tools_used.add(tool_name)

                # Extract final result
                if event_type == "result":
                    output = event.get("result", "")

                    # Check for API errors (billing, rate limits, etc.)
                    if event.get("is_error"):
                        api_error = output
                        logger.error(f"[CLAUDE CLI] API error: {output}")

                    # Extract model usage (handle null explicitly)
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

        # Fallback if no result found
        if not output and not api_error:
            logger.warning("[CLAUDE CLI] No result in stream-json, using raw output")
            output = raw_output

        return output, model_usage_list, thinking, api_error, tools_used

    def _infer_operation_type(self, explicit_type: str | None, prompt: str) -> str:
        """Infer operation type from context.

        Args:
            explicit_type: Explicitly provided type
            prompt: The prompt being executed

        Returns:
            OperationType value string
        """
        if explicit_type:
            return explicit_type

        # Infer from agent_md_path
        if self.agent_md_path:
            agent_name = self.agent_md_path.stem.lower()
            if "fix" in agent_name:
                return "fix"
            if "review" in agent_name:
                return "review"
            if "commit" in agent_name:
                return "git_commit"
            if "merge" in agent_name:
                return "git_merge"
            if "push" in agent_name:
                return "git_push"
            if "pull" in agent_name:
                return "git_pull"
            if "lint" in agent_name or "analyzer" in agent_name:
                return "review"

        # Infer from prompt keywords
        prompt_lower = prompt.lower()[:500]
        if "fix" in prompt_lower or "correggi" in prompt_lower:
            return "fix"
        if "review" in prompt_lower or "analizza" in prompt_lower:
            return "review"
        if "commit" in prompt_lower:
            return "git_commit"
        if "merge" in prompt_lower:
            return "git_merge"
        if "push" in prompt_lower:
            return "git_push"

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
        """Register operation in tracker.

        Returns:
            Operation instance or None if registration fails
        """
        try:
            from turbowrap.api.services.operation_tracker import OperationType, get_tracker

            tracker = get_tracker()
            op_type_str = self._infer_operation_type(operation_type, prompt)

            # Convert string to OperationType enum
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
                    "cli": "claude",
                    "agent": self.agent_md_path.stem if self.agent_md_path else None,
                    "working_dir": str(self.working_dir) if self.working_dir else None,
                    "prompt_preview": prompt_preview,
                    "prompt_length": len(prompt),
                    **(operation_details or {}),
                },
            )

            logger.info(
                f"[CLAUDE CLI] Operation registered: {operation.operation_id[:8]} "
                f"({op_type.value})"
            )
            return operation

        except Exception as e:
            # Don't fail the CLI execution if tracking fails
            logger.warning(f"[CLAUDE CLI] Failed to register operation: {e}")
            return None

    def _complete_operation(
        self,
        operation_id: str,
        duration_ms: int,
        model_usage: list[ModelUsage],
        tools_used: set[str] | None = None,
    ) -> None:
        """Complete operation in tracker with model usage stats."""
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
                },
            )
            logger.info(
                f"[CLAUDE CLI] Operation completed: {operation_id[:8]} "
                f"({total_tokens} tokens, ${total_cost:.4f}, {len(tools_used or [])} tools)"
            )

        except Exception as e:
            logger.warning(f"[CLAUDE CLI] Failed to complete operation: {e}")

    def _fail_operation(self, operation_id: str, error: str) -> None:
        """Fail operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.fail(operation_id, error=error[:200])
            logger.info(f"[CLAUDE CLI] Operation failed: {operation_id[:8]}")

        except Exception as e:
            logger.warning(f"[CLAUDE CLI] Failed to mark operation as failed: {e}")

    def _update_operation(self, operation_id: str, details: dict[str, Any]) -> None:
        """Update operation details in tracker (e.g., add S3 URLs)."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.update(operation_id, details=details)

        except Exception as e:
            logger.warning(f"[CLAUDE CLI] Failed to update operation: {e}")
