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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings
from turbowrap.exceptions import GeminiError
from turbowrap.llm.base import AgentResponse, BaseAgent
from turbowrap.utils.aws_secrets import get_google_api_key

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

    def analyze_screenshots(
        self,
        image_paths: list[str],
        context: dict[str, str],
    ) -> str:
        """Analyze screenshots with Gemini Vision API.

        Args:
            image_paths: List of paths to screenshot images.
            context: Context dict with keys: title, description, figma_link, website_link.

        Returns:
            Analysis insights as text.

        Raises:
            GeminiError: If analysis fails.
        """
        from google.genai import types

        # Build analysis prompt
        prompt = f"""Analizza questi screenshot per una issue di sviluppo.

**Contesto:**
- **Titolo**: {context.get("title", "N/A")}
- **Descrizione**: {context.get("description", "N/A")}
- **Link Figma**: {context.get("figma_link", "N/A")}
- **Link Sito**: {context.get("website_link", "N/A")}

**Analisi richiesta:**

Identifica e descrivi in dettaglio:

1. **Componenti UI visibili**: Elenca tutti i componenti UI presenti (bottoni, form, input,
   dropdown, etc.)
2. **Layout e design**: Struttura della pagina, grid system, spacing, allineamenti
3. **User flow**: Sequenza di azioni dell'utente visibile negli screenshot
4. **Requisiti tecnici**: Tecnologie necessarie, pattern UI da implementare
5. **Potenziali problemi**: Edge case, accessibilità, responsive design, stati error/loading

Fornisci un'analisi tecnica dettagliata e specifica, non generica."""

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
                raise GeminiError(f"Screenshot not found: {img_path}")
            except Exception as e:
                raise GeminiError(f"Error loading screenshot {img_path}: {e}") from e

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
        s3_prefix: str = "gemini-cli",
    ):
        """
        Initialize Gemini CLI runner.

        Args:
            working_dir: Working directory for CLI process
            model: Model name or type ("flash", "pro")
            timeout: Timeout in seconds
            auto_accept: Enable --auto-accept flag (auto-approve tool calls)
            s3_prefix: S3 path prefix for logs
        """
        self.settings = get_settings()
        self.working_dir = working_dir
        self.timeout = timeout
        self.auto_accept = auto_accept
        self.s3_prefix = s3_prefix

        # Resolve model name
        if model is None:
            self.model = self.settings.agents.gemini_pro_model
        elif model in GEMINI_MODEL_MAP:
            self.model = GEMINI_MODEL_MAP[model]
        else:
            self.model = model

        # S3 config
        self.s3_bucket = self.settings.thinking.s3_bucket
        self.s3_region = self.settings.thinking.s3_region
        self._s3_client: Any = None

    @property
    def s3_client(self) -> Any:
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    async def _save_to_s3(
        self,
        content: str,
        artifact_type: str,
        context_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Save artifact to S3.

        Args:
            content: Content to save
            artifact_type: "prompt", "output", or "error"
            context_id: Identifier for grouping artifacts
            metadata: Additional metadata to include

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.s3_bucket:
            return None

        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"{self.s3_prefix}/{timestamp}/{context_id}_{artifact_type}.md"

            # Build markdown content
            md_content = f"""# Gemini CLI {artifact_type.title()}

**Context ID**: {context_id}
**Timestamp**: {datetime.now(timezone.utc).isoformat()}
**Artifact Type**: {artifact_type}
**Model**: {metadata.get("model", self.model) if metadata else self.model}

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
            logger.info(f"[GEMINI CLI] Saved {artifact_type} to S3: {s3_key}")
            return s3_url

        except ClientError as e:
            logger.warning(f"[GEMINI CLI] Failed to save to S3: {e}")
            return None

    async def run(
        self,
        prompt: str,
        context_id: str | None = None,
        save_prompt: bool = True,
        save_output: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> GeminiCLIResult:
        """
        Execute Gemini CLI and return result.

        Args:
            prompt: The prompt to send
            context_id: Optional ID for S3 logging
            save_prompt: Save prompt to S3
            save_output: Save output to S3
            on_chunk: Optional callback for streaming output

        Returns:
            GeminiCLIResult with output and S3 URLs
        """
        import time

        start_time = time.time()

        # Generate context ID if not provided
        if context_id is None:
            context_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Save prompt to S3 before running
        s3_prompt_url = None
        if save_prompt:
            s3_prompt_url = await self._save_to_s3(
                prompt, "prompt", context_id, {"model": self.model}
            )

        try:
            # Build environment with API key
            env = os.environ.copy()
            api_key = get_google_api_key()
            if api_key:
                env["GEMINI_API_KEY"] = api_key

            # Build command
            args = ["gemini", "--model", self.model]
            if self.auto_accept:
                args.append("--auto-accept")
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
                    await self._save_to_s3(
                        error_content,
                        "error",
                        context_id,
                        {"model": self.model, "duration_ms": duration_ms},
                    )

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
                s3_output_url = await self._save_to_s3(
                    output,
                    "output",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                )

            if process.returncode != 0:
                stderr = await process.stderr.read() if process.stderr else b""
                error_msg = f"Exit code {process.returncode}: {stderr.decode()[:500]}"
                logger.error(f"[GEMINI CLI] Failed: {error_msg}")

                # Save error to S3
                if save_output:
                    await self._save_to_s3(
                        f"# Error\n\n{error_msg}\n\n# Output\n\n{output}",
                        "error",
                        context_id,
                        {"model": self.model, "duration_ms": duration_ms},
                    )

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
                await self._save_to_s3(
                    f"# Error\n\n{error_msg}",
                    "error",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                )
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
                await self._save_to_s3(
                    f"# Exception\n\n{e!s}",
                    "error",
                    context_id,
                    {"model": self.model, "duration_ms": duration_ms},
                )
            return GeminiCLIResult(
                success=False,
                output="",
                error=str(e),
                model=self.model,
                duration_ms=duration_ms,
                s3_prompt_url=s3_prompt_url,
            )
