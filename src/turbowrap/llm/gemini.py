"""Gemini clients for fast analysis.

Provides:
- GeminiClient: SDK client for simple prompts
- GeminiProClient: SDK client with vision capabilities
- GeminiCLI: CLI runner for autonomous tool use
"""

import asyncio
import codecs
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
            summarize_tool_output: Summarize long tool outputs to reduce tokens
            s3_prefix: S3 path prefix for logs
        """
        self.settings = get_settings()
        self.working_dir = working_dir
        self.timeout = timeout
        self.auto_accept = auto_accept
        self.summarize_tool_output = summarize_tool_output
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

            # Build command
            args = ["gemini", "--model", self.model]
            if self.auto_accept:
                args.extend(["--approval-mode", "yolo"])
            if self.summarize_tool_output:
                args.append("--summarize-tool-output")
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
                    error_content = (
                        f"# Timeout Error\n\nTimeout after {self.timeout}s\n\n"
                        f"# Partial Output ({len(partial_output)} chars)\n\n"
                        f"{partial_output}"
                    )
                    await self._s3_saver.save_markdown(
                        error_content,
                        "error",
                        context_id,
                        {"model": self.model, "duration_ms": duration_ms},
                        "Gemini CLI",
                    )

                # Auto-fail operation on timeout
                if operation:
                    self._fail_operation(operation.operation_id, f"Timeout after {self.timeout}s")

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
                s3_output_url = await self._s3_saver.save_markdown(
                    output,
                    "output",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                    "Gemini CLI",
                )

            if process.returncode != 0:
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = f"Exit code {process.returncode}: {stderr.decode()[:500]}"
                logger.error(f"[GEMINI CLI] Failed: {error_msg}")

                # Save error to S3
                if save_output:
                    await self._s3_saver.save_markdown(
                        f"# Error\n\n{error_msg}\n\n# Output\n\n{output}",
                        "error",
                        context_id,
                        {"model": self.model, "duration_ms": duration_ms},
                        "Gemini CLI",
                    )

                # Auto-fail operation
                if operation:
                    self._fail_operation(operation.operation_id, error_msg)

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

            # Auto-complete operation
            if operation:
                self._complete_operation(operation.operation_id, duration_ms=duration_ms)

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
            logger.warning(f"[GEMINI CLI] Failed to register operation: {e}")
            return None

    def _complete_operation(self, operation_id: str, duration_ms: int) -> None:
        """Complete operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.complete(
                operation_id,
                result={
                    "duration_ms": duration_ms,
                    "model": self.model,
                },
            )
            logger.info(f"[GEMINI CLI] Operation completed: {operation_id[:8]}")

        except Exception as e:
            logger.warning(f"[GEMINI CLI] Failed to complete operation: {e}")

    def _fail_operation(self, operation_id: str, error: str) -> None:
        """Fail operation in tracker."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.fail(operation_id, error=error[:200])
            logger.info(f"[GEMINI CLI] Operation failed: {operation_id[:8]}")

        except Exception as e:
            logger.warning(f"[GEMINI CLI] Failed to mark operation as failed: {e}")

    def _update_operation(self, operation_id: str, details: dict[str, Any]) -> None:
        """Update operation details in tracker (e.g., add S3 URLs)."""
        try:
            from turbowrap.api.services.operation_tracker import get_tracker

            tracker = get_tracker()
            tracker.update(operation_id, details=details)

        except Exception as e:
            logger.warning(f"[GEMINI CLI] Failed to update operation: {e}")
