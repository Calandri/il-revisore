"""
Claude CLI-based reviewer implementation.

Uses Claude CLI subprocess instead of SDK, allowing the model to autonomously
explore the codebase via its own file reading capabilities.
"""

import asyncio
import codecs
import contextlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import (
    ChecklistResult,
    Issue,
    IssueCategory,
    IssueSeverity,
    ModelUsageInfo,
    ReviewMetrics,
    ReviewOutput,
    ReviewSummary,
)
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext
from turbowrap.utils.aws_secrets import get_anthropic_api_key

logger = logging.getLogger(__name__)

# Timeouts
CLAUDE_CLI_TIMEOUT = 300  # 5 minutes per review


class ClaudeCLIReviewer(BaseReviewer):
    """
    Code reviewer using Claude CLI.

    Instead of passing file contents in the prompt, this reviewer:
    1. Loads the specialist MD file (e.g., reviewer_be_architecture.md)
    2. Passes a list of files to analyze
    3. Runs Claude CLI with cwd=repo_path
    4. Claude CLI reads files autonomously and can explore beyond the initial list
    """

    def __init__(
        self,
        name: str = "reviewer_be",
        cli_path: str = "claude",
        timeout: int = CLAUDE_CLI_TIMEOUT,
    ):
        """
        Initialize Claude CLI reviewer.

        Args:
            name: Reviewer identifier (reviewer_be_architecture, etc.)
            cli_path: Path to Claude CLI executable
            timeout: Timeout in seconds for CLI execution
        """
        super().__init__(name, model="claude-cli")

        self.settings = get_settings()
        self.cli_path = cli_path
        self.timeout = timeout

        # S3 configuration for thinking logs
        self.s3_bucket = self.settings.thinking.s3_bucket
        self.s3_region = self.settings.thinking.s3_region
        self._s3_client = None

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    async def _save_thinking_to_s3(
        self,
        thinking_content: str,
        review_id: str,
        context: ReviewContext,
    ) -> str | None:
        """
        Save thinking content to S3.

        Args:
            thinking_content: The thinking text to save
            review_id: Unique identifier for this review
            context: Review context for metadata

        Returns:
            S3 URL if successful, None otherwise
        """
        if not thinking_content or not self.s3_bucket:
            return None

        try:
            # Create S3 key with timestamp
            timestamp = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"thinking/{timestamp}/{review_id}_{self.name}.md"

            # Create markdown content with metadata
            model = self.settings.agents.claude_model
            content = f"""# Extended Thinking - {self.name}

**Review ID**: {review_id}
**Timestamp**: {datetime.utcnow().isoformat()}
**Model**: {model}
**Files Reviewed**: {len(context.files) if context.files else 0}

---

## Thinking Process

{thinking_content}
"""

            # Upload to S3
            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )

            return f"s3://{self.s3_bucket}/{s3_key}"

        except ClientError as e:
            logger.warning(f"Failed to save thinking to S3: {e}")
            return None

    async def _save_review_to_s3(
        self,
        review_json: str,
        review_id: str,
        context: ReviewContext,
    ) -> str | None:
        """
        Save review JSON to S3 for checkpointing/resumability.

        Args:
            review_json: The review output JSON string
            review_id: Unique identifier for this review
            context: Review context for metadata

        Returns:
            S3 URL if successful, None otherwise
        """
        if not review_json or not self.s3_bucket:
            return None

        try:
            # Create S3 key with timestamp
            timestamp = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"reviews/{timestamp}/{review_id}_{self.name}.json"

            # Upload to S3
            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=review_json.encode("utf-8"),
                ContentType="application/json",
            )

            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"[CLAUDE CLI] Review saved to S3: {s3_url}")
            return s3_url

        except ClientError as e:
            logger.warning(f"Failed to save review to S3: {e}")
            return None

    async def _run_cli_and_read_output(
        self,
        prompt: str,
        context: ReviewContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[ModelUsageInfo], str | None]:
        """
        Run Claude CLI and read output from file (with stdout fallback).

        Strategy:
        1. Ask Claude to write JSON to file (most reliable)
        2. If file doesn't exist or is invalid, fallback to extracting from stdout
        3. Save result to S3 for checkpointing

        Args:
            prompt: The prompt to send to Claude CLI
            context: Review context with repo path and metadata
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Tuple of (output content or None, model usage list, error message or None)
        """
        # Output file path (Claude should write here)
        output_file = context.repo_path / f".turbowrap_review_{self.name}.json" if context.repo_path else Path(f".turbowrap_review_{self.name}.json")

        # Delete old output file if exists
        if output_file.exists():
            with contextlib.suppress(Exception):
                output_file.unlink()

        # Run Claude CLI with streaming
        cli_result, model_usage, thinking_content, _ = await self._run_claude_cli(prompt, context.repo_path, on_chunk)

        # Check if CLI failed
        if cli_result is None:
            return None, model_usage, "Claude CLI failed to execute"

        # Get review_id for S3 logging
        review_id = context.metadata.get("review_id", "unknown") if context.metadata else "unknown"

        # Save thinking to S3 if available
        if thinking_content:
            await self._save_thinking_to_s3(thinking_content, review_id, context)

        # Strategy 1: Read from file at expected path (Claude should have written it)
        output = None
        output_filename = f".turbowrap_review_{self.name}.json"
        if output_file.exists():
            try:
                file_content = output_file.read_text(encoding="utf-8").strip()
                # Validate it looks like JSON object
                if file_content.startswith("{") and file_content.endswith("}"):
                    output = file_content
                    logger.info(f"[CLAUDE CLI] Read JSON from file: {len(output)} chars")
                else:
                    logger.warning(f"[CLAUDE CLI] File content is not valid JSON: {file_content[:100]}")
            except Exception as e:
                logger.warning(f"[CLAUDE CLI] Failed to read output file: {e}")
            finally:
                # Clean up output file
                with contextlib.suppress(Exception):
                    output_file.unlink()

        # Strategy 1b: Search recursively if file not found at expected path (monorepo workaround)
        if output is None and context.repo_path:
            try:
                found_files = list(context.repo_path.rglob(output_filename))
                if found_files:
                    # Use the most recently modified file
                    found_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    found_file = found_files[0]
                    logger.warning(f"[CLAUDE CLI] File not at expected path, found at: {found_file}")
                    file_content = found_file.read_text(encoding="utf-8").strip()
                    if file_content.startswith("{") and file_content.endswith("}"):
                        output = file_content
                        logger.info(f"[CLAUDE CLI] Read JSON from fallback path: {len(output)} chars")
                    # Clean up all found files
                    for f in found_files:
                        with contextlib.suppress(Exception):
                            f.unlink()
            except Exception as e:
                logger.warning(f"[CLAUDE CLI] Recursive file search failed: {e}")

        # Strategy 2: Fallback to extracting from stdout
        if output is None and cli_result and "{" in cli_result:
            first_brace = cli_result.find("{")
            last_brace = cli_result.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                output = cli_result[first_brace:last_brace + 1]
                logger.info(f"[CLAUDE CLI] Fallback: extracted JSON from stdout: {len(output)} chars")

        if output is None:
            logger.error(f"[CLAUDE CLI] No valid JSON found. CLI result: {cli_result[:300]}")
            return None, model_usage, f"Claude CLI did not produce valid JSON. Output: {cli_result[:300]}"

        # Save to S3 for checkpointing (regardless of source)
        await self._save_review_to_s3(output, review_id, context)

        return output, model_usage, None

    async def review(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ReviewOutput:
        """
        Perform code review using Claude CLI.

        Args:
            context: Review context with repo path and metadata
            file_list: Optional list of files to analyze (uses context.files if not provided)
            on_chunk: Optional callback for streaming output chunks

        Returns:
            ReviewOutput with findings
        """
        start_time = time.time()

        # Use provided file list or fall back to context
        files_to_review = file_list or context.files

        # Build the review prompt
        prompt = self._build_review_prompt(context, files_to_review)

        # Run CLI and read output from file
        output, model_usage, error = await self._run_cli_and_read_output(prompt, context, on_chunk)

        if error:
            return self._create_error_output(error)

        # Parse the response
        review_output = self._parse_response(output, files_to_review)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()
        review_output.model_usage = model_usage

        return review_output

    async def refine(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
        file_list: list[str] | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ReviewOutput:
        """
        Refine review based on challenger feedback.

        Args:
            context: Original review context
            previous_review: Previous review output
            feedback: Challenger feedback to address
            file_list: Optional list of files
            on_chunk: Optional callback for streaming output chunks

        Returns:
            Refined ReviewOutput
        """
        start_time = time.time()

        files_to_review = file_list or context.files

        # Build refinement prompt
        prompt = self._build_refinement_prompt(context, previous_review, feedback, files_to_review)

        # Run CLI and read output from file
        output, model_usage, error = await self._run_cli_and_read_output(prompt, context, on_chunk)

        if error:
            return self._create_error_output(error)

        # Parse the response
        review_output = self._parse_response(output, files_to_review)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()
        review_output.iteration = previous_review.iteration + 1
        review_output.model_usage = model_usage

        return review_output

    def _build_review_prompt(
        self,
        context: ReviewContext,
        file_list: list[str],
    ) -> str:
        """Build the review prompt for Claude CLI."""
        sections = []

        # Include specialist prompt if available
        if context.agent_prompt:
            sections.append(context.agent_prompt)
            sections.append("\n---\n")

        # Include structure docs for architectural context
        if context.structure_docs:
            sections.append("## Repository Structure Documentation\n")
            for path, content in context.structure_docs.items():
                sections.append(f"### {path}\n{content}\n")
            sections.append("\n---\n")

        # File list to analyze
        sections.append("## Files to Analyze\n")
        sections.append("Read and analyze the following files:\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        # Output file for this reviewer - use ABSOLUTE path to prevent issues with monorepos
        output_filename = f".turbowrap_review_{self.name}.json"
        if context.repo_path:
            output_file = str(context.repo_path / output_filename)
        else:
            output_file = output_filename

        sections.append(f"""
## Important Instructions

1. **Read the files** listed above using your file reading capabilities
2. **Explore freely** - you can read other files (imports, dependencies, tests) if needed
3. **Apply your expertise** from the system prompt above
4. **CRITICAL**: Always save output to the ABSOLUTE path specified below, not a relative path

## Output Format

Output valid JSON with this schema:

{{
  "summary": {{
    "files_reviewed": <int>,
    "critical_issues": <int>,
    "high_issues": <int>,
    "medium_issues": <int>,
    "low_issues": <int>,
    "score": <float 0-10>
  }},
  "issues": [
    {{
      "id": "<REVIEWER-SEVERITY-NNN>",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "security|performance|architecture|style|logic|ux|testing|documentation",
      "file": "<file path>",
      "line": <line number or null>,
      "title": "<brief title>",
      "description": "<detailed description>",
      "suggested_fix": "<suggested fix>",
      "estimated_effort": <int 1-5>,
      "estimated_files_count": <int>
    }}
  ],
  "checklists": {{
    "security": {{ "passed": <int>, "failed": <int>, "skipped": <int> }},
    "performance": {{ "passed": <int>, "failed": <int>, "skipped": <int> }},
    "architecture": {{ "passed": <int>, "failed": <int>, "skipped": <int> }}
  }}
}}

## MANDATORY: Effort Estimation for EVERY Issue

For each issue, you MUST provide effort estimation:
- `estimated_effort` (1-5): Fix complexity
  - 1 = Trivial (typo, simple rename, one-line fix)
  - 2 = Simple (small change in one file, < 10 lines)
  - 3 = Moderate (changes in 1-2 files, needs some thought)
  - 4 = Complex (multiple files, refactoring, new patterns)
  - 5 = Major refactor (architectural change, many files)
- `estimated_files_count`: Number of files that need modification

## IMPORTANT: Save output to file

WRITE the complete JSON to this file: `{output_file}`

After writing, confirm with: "Review saved to {output_file}"
""")

        return "".join(sections)

    def _build_refinement_prompt(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
        file_list: list[str],
    ) -> str:
        """Build the refinement prompt for Claude CLI."""
        sections = []

        # Include specialist prompt
        if context.agent_prompt:
            sections.append(context.agent_prompt)
            sections.append("\n---\n")

        sections.append("# Review Refinement Request\n")

        # Include previous review (complete with all issues)
        sections.append("## Previous Review\n")
        sections.append(f"```json\n{previous_review.model_dump_json(indent=2)}\n```\n")

        sections.append("\n## Challenger Feedback\n")
        sections.append(feedback.to_refinement_prompt())

        sections.append("\n## Files to Re-analyze\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        # Output file for this reviewer - use ABSOLUTE path to prevent issues with monorepos
        output_filename = f".turbowrap_review_{self.name}.json"
        if context.repo_path:
            output_file = str(context.repo_path / output_filename)
        else:
            output_file = output_filename

        sections.append(f"""
## Refinement Instructions

1. **Read the files** again to verify the feedback
2. Address ALL missed issues identified by the challenger
3. Re-evaluate challenged issues and adjust if warranted
4. Incorporate suggested improvements
5. Maintain valid issues from the previous review
6. **CRITICAL**: Always save output to the ABSOLUTE path specified below

## IMPORTANT: Save output to file

WRITE the complete refined JSON to this file: `{output_file}`

After writing, confirm with: "Review saved to {output_file}"
""")

        return "".join(sections)

    async def _run_claude_cli(
        self,
        prompt: str,
        repo_path: Path | None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[ModelUsageInfo], str, str]:
        """
        Run Claude CLI with the prompt, streaming output.

        Args:
            prompt: The full prompt to send
            repo_path: Working directory for the CLI
            on_chunk: Optional callback for streaming chunks

        Returns:
            Tuple of (CLI output or None if failed, list of model usage info, thinking content, raw NDJSON output)
        """
        cwd = str(repo_path) if repo_path else None

        try:
            # Build environment with API key from AWS Secrets Manager
            env = os.environ.copy()
            api_key = get_anthropic_api_key()
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            else:
                logger.warning("ANTHROPIC_API_KEY not found in AWS - using environment")

            # Workaround: Bun file watcher bug on macOS /var/folders
            # Force TMPDIR to /tmp to avoid EOPNOTSUPP errors
            env["TMPDIR"] = "/tmp"

            # Workaround: Remove VSCode git socket files that crash Claude CLI
            # Claude CLI crashes when trying to watch .sock files in /var/folders
            import glob
            import tempfile
            tmpdir = tempfile.gettempdir()
            vscode_sockets = glob.glob(os.path.join(tmpdir, "vscode-git-*.sock"))
            for sock in vscode_sockets:
                try:
                    os.remove(sock)
                except OSError:
                    pass  # Socket may be in use

            # Use model from settings
            model = self.settings.agents.claude_model

            # Build CLI arguments with stream-json for real-time streaming
            # NOTE: --verbose is REQUIRED when using --print + --output-format=stream-json
            args = [
                self.cli_path,
                "--print",
                "--verbose",
                "--dangerously-skip-permissions",
                "--model",
                model,
                "--output-format",
                "stream-json",
            ]

            # Extended thinking via MAX_THINKING_TOKENS env var
            # NOTE: --settings {"alwaysThinkingEnabled": true} is BUGGY in Claude CLI v2.0.64+
            # and causes the process to hang indefinitely. Use env var instead.
            if self.settings.thinking.enabled:
                env["MAX_THINKING_TOKENS"] = str(self.settings.thinking.budget_tokens)
                logger.info(f"[CLAUDE CLI] Extended thinking enabled: MAX_THINKING_TOKENS={env['MAX_THINKING_TOKENS']}")

            logger.info(f"[CLAUDE CLI] Starting subprocess: {' '.join(args)}")
            logger.info(f"[CLAUDE CLI] Working directory: {cwd}")
            logger.info(f"[CLAUDE CLI] Prompt length: {len(prompt)} chars")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            logger.info(f"[CLAUDE CLI] Process started with PID: {process.pid}")

            # Write prompt to stdin in background task (avoids blocking on large prompts)
            # The pipe buffer is ~64KB, so large prompts would block drain() if we don't
            # read stdout concurrently
            prompt_bytes = prompt.encode()
            stdin_error = None

            async def write_stdin():
                nonlocal stdin_error
                try:
                    logger.info(f"[CLAUDE CLI] Writing {len(prompt_bytes)} bytes to stdin...")
                    process.stdin.write(prompt_bytes)
                    await process.stdin.drain()
                    process.stdin.close()
                    # CRITICAL: wait_closed() ensures Claude CLI sees EOF on stdin
                    # Without this, Claude CLI hangs waiting for more input!
                    await process.stdin.wait_closed()
                    logger.info("[CLAUDE CLI] Stdin closed successfully (EOF sent)")
                except BrokenPipeError as e:
                    stdin_error = f"BrokenPipe: {e}"
                    logger.error(f"[CLAUDE CLI] Stdin BrokenPipe: {e}")
                except Exception as e:
                    stdin_error = str(e)
                    logger.error(f"[CLAUDE CLI] Stdin error: {e}")

            # Start stdin writer as background task
            stdin_task = asyncio.create_task(write_stdin())

            # Stderr streaming task - logs --verbose output in real-time
            stderr_chunks = []

            async def read_stderr():
                stderr_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while True:
                    chunk = await process.stderr.read(1024)
                    if not chunk:
                        final = stderr_decoder.decode(b"", final=True)
                        if final:
                            stderr_chunks.append(final)
                            print(f"[CLAUDE STDERR] {final}", flush=True)
                        break
                    decoded = stderr_decoder.decode(chunk)
                    if decoded:
                        stderr_chunks.append(decoded)
                        # Print each line separately for better visibility
                        for line in decoded.split("\n"):
                            if line.strip():
                                print(f"[CLAUDE STDERR] {line}", flush=True)

            stderr_task = asyncio.create_task(read_stderr())

            # Read stdout in streaming mode with incremental UTF-8 decoder
            # This handles multi-byte UTF-8 characters split across chunk boundaries
            output_chunks = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            chunks_received = 0
            total_bytes = 0
            last_log_time = time.time()
            line_buffer = ""  # Buffer for incomplete JSON lines
            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        chunk = await process.stdout.read(1024)
                        if not chunk:
                            # Flush remaining bytes
                            decoded = decoder.decode(b"", final=True)
                            if decoded:
                                output_chunks.append(decoded)
                            logger.info(f"[CLAUDE CLI] Stream ended. Total: {chunks_received} chunks, {total_bytes} bytes")
                            break

                        chunks_received += 1
                        total_bytes += len(chunk)

                        # Log progress every 30 seconds
                        now = time.time()
                        if now - last_log_time > 30:
                            logger.info(f"[CLAUDE CLI] Streaming... {chunks_received} chunks, {total_bytes} bytes received")
                            last_log_time = now

                        # Log first chunk
                        if chunks_received == 1:
                            logger.info(f"[CLAUDE CLI] First chunk received! ({len(chunk)} bytes)")

                        # Incremental decode - handles partial multi-byte chars
                        decoded = decoder.decode(chunk)
                        if decoded:
                            output_chunks.append(decoded)

                            # Parse stream-json and extract text for streaming callback
                            if on_chunk:
                                line_buffer += decoded
                                while "\n" in line_buffer:
                                    line, line_buffer = line_buffer.split("\n", 1)
                                    if not line.strip():
                                        continue
                                    try:
                                        event = json.loads(line)
                                        # Extract text from content_block_delta events
                                        if event.get("type") == "content_block_delta":
                                            delta = event.get("delta", {})
                                            text = delta.get("text", "")
                                            if text:
                                                await on_chunk(text)
                                        # Also handle assistant message content
                                        elif event.get("type") == "assistant":
                                            message = event.get("message", {})
                                            for block in message.get("content", []):
                                                if block.get("type") == "text":
                                                    text = block.get("text", "")
                                                    if text:
                                                        await on_chunk(text)
                                    except json.JSONDecodeError:
                                        pass  # Skip non-JSON or incomplete lines
            except asyncio.TimeoutError:
                logger.error(f"[CLAUDE CLI] TIMEOUT after {self.timeout}s! Received {chunks_received} chunks, {total_bytes} bytes before timeout")
                stdin_task.cancel()
                stderr_task.cancel()
                process.kill()
                return None, [], "", ""

            # Wait for stdin and stderr tasks to complete
            await stdin_task
            await stderr_task
            if stdin_error:
                logger.error(f"[CLAUDE CLI] Stdin failed: {stdin_error}")
                # Don't return error if we got output anyway

            logger.info("[CLAUDE CLI] Waiting for process to exit...")
            await process.wait()
            logger.info(f"[CLAUDE CLI] Process exited with code {process.returncode}")

            # Get collected stderr from streaming task
            stderr_text = "".join(stderr_chunks)

            if stderr_text:
                logger.warning(f"[CLAUDE CLI] STDERR total: {len(stderr_text)} chars")

            if process.returncode != 0:
                logger.error(f"[CLAUDE CLI] FAILED with code {process.returncode}")
                logger.error(f"[CLAUDE CLI] Full stderr: {stderr_text[:2000]}")
                return None, [], "", ""

            raw_output = "".join(output_chunks)
            model_usage_list: list[ModelUsageInfo] = []
            output = ""
            thinking_chunks: list[str] = []  # Collect thinking content

            # Parse stream-json output (NDJSON - one JSON per line)
            # Look for the "result" type line which contains final output and costs
            for line in raw_output.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    event_type = event.get("type")

                    # Capture thinking content from assistant messages
                    if event_type == "assistant":
                        message = event.get("message", {})
                        content_blocks = message.get("content", [])
                        for block in content_blocks:
                            if block.get("type") == "thinking":
                                thinking_text = block.get("thinking", "")
                                if thinking_text:
                                    thinking_chunks.append(thinking_text)

                    if event_type == "result":
                        # Final result with content and model usage
                        output = event.get("result", "")

                        # Extract model usage
                        model_usage = event.get("modelUsage", {})
                        if model_usage:
                            for model_name, usage in model_usage.items():
                                info = ModelUsageInfo(
                                    model=model_name,
                                    input_tokens=usage.get("inputTokens", 0),
                                    output_tokens=usage.get("outputTokens", 0),
                                    cache_read_tokens=usage.get("cacheReadInputTokens", 0),
                                    cache_creation_tokens=usage.get("cacheCreationInputTokens", 0),
                                    cost_usd=usage.get("costUSD", 0.0),
                                )
                                model_usage_list.append(info)

                except json.JSONDecodeError:
                    # Skip non-JSON lines
                    continue

            # Combine thinking chunks
            thinking_content = "\n\n".join(thinking_chunks)

            # Fallback if no result found
            if not output:
                logger.warning("No result found in stream-json output, using raw")
                output = raw_output

            return output, model_usage_list, thinking_content, raw_output

        except FileNotFoundError:
            logger.error(f"[CLAUDE CLI] NOT FOUND at: {self.cli_path}")
            return None, [], "", ""
        except Exception as e:
            logger.exception(f"[CLAUDE CLI] EXCEPTION: {e}")
            return None, [], "", ""

    def _extract_json_from_response(self, response_text: str) -> str:
        """
        Extract JSON from Claude's response, handling:
        - Markdown code blocks (```json ... ```)
        - Conversational text before/after JSON
        - Raw JSON starting with {
        """
        text = response_text.strip()

        # Strategy 1: Look for markdown code blocks
        if "```json" in text:
            # Find content between ```json and ```
            start = text.find("```json")
            if start != -1:
                start += 7  # Length of ```json
                end = text.find("```", start)
                if end != -1:
                    return text[start:end].strip()

        # Strategy 2: Look for code blocks without language specifier
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    if in_block:
                        # End of block - check if we collected valid JSON
                        if json_lines and json_lines[0].strip().startswith("{"):
                            return "\n".join(json_lines)
                        json_lines = []
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)

        # Strategy 3: Find first { and last } to extract raw JSON
        first_brace = text.find("{")
        if first_brace != -1:
            last_brace = text.rfind("}")
            if last_brace != -1 and last_brace > first_brace:
                return text[first_brace:last_brace + 1]

        # Fallback: return original text and let JSON parser fail with proper error
        logger.warning("[CLAUDE PARSE] Could not extract JSON, returning raw text")
        return text

    def _repair_truncated_json(self, json_text: str) -> str:
        """
        Attempt to repair truncated JSON by closing open structures.

        This handles cases where Claude's output was cut off mid-JSON.
        """
        # Count open/close braces and brackets
        open_braces = json_text.count("{")
        close_braces = json_text.count("}")
        open_brackets = json_text.count("[")
        close_brackets = json_text.count("]")

        # If balanced, nothing to repair
        if open_braces == close_braces and open_brackets == close_brackets:
            return json_text

        logger.warning(
            f"[CLAUDE PARSE] Detected truncated JSON: "
            f"braces {open_braces}/{close_braces}, brackets {open_brackets}/{close_brackets}"
        )

        # Try to find a valid stopping point (after a complete issue)
        # Look for the last complete issue object
        repaired = json_text.rstrip()

        # Remove trailing incomplete content (after last complete structure)
        # Find last complete issue by looking for pattern: }, or }]
        last_complete = max(
            repaired.rfind("},"),
            repaired.rfind("}]"),
        )

        if last_complete > 0:
            # Truncate to last complete structure
            repaired = repaired[:last_complete + 2]

        # Now close any remaining open structures
        # Count again after truncation
        open_braces = repaired.count("{")
        close_braces = repaired.count("}")
        open_brackets = repaired.count("[")
        close_brackets = repaired.count("]")

        # Add missing closing characters
        # Order matters: close brackets before braces (issues array before root object)
        missing_brackets = open_brackets - close_brackets
        missing_braces = open_braces - close_braces

        if missing_brackets > 0:
            repaired += "]" * missing_brackets
        if missing_braces > 0:
            repaired += "}" * missing_braces

        return repaired

    def _parse_response(
        self,
        response_text: str,
        file_list: list[str],
    ) -> ReviewOutput:
        """Parse Claude's response into ReviewOutput."""
        try:
            json_text = self._extract_json_from_response(response_text)

            # First attempt: parse as-is
            try:
                data = json.loads(json_text)
            except json.JSONDecodeError as first_error:
                # Second attempt: try to repair truncated JSON
                logger.warning(f"[CLAUDE PARSE] First parse failed: {first_error}")
                repaired_json = self._repair_truncated_json(json_text)
                try:
                    data = json.loads(repaired_json)
                except json.JSONDecodeError:
                    # Both attempts failed, re-raise original error
                    raise first_error

            # Validate that data is a dict, not a string
            # (json.loads can return a string if input is a JSON string literal)
            if not isinstance(data, dict):
                logger.error(f"[CLAUDE PARSE] Expected dict, got {type(data).__name__}: {str(data)[:200]}")
                raise json.JSONDecodeError(
                    f"Expected JSON object, got {type(data).__name__}",
                    json_text,
                    0
                )

            # Build ReviewOutput from parsed data
            summary_data = data.get("summary", {})
            # Validate summary is a dict
            if not isinstance(summary_data, dict):
                logger.warning(f"[CLAUDE PARSE] Invalid summary type: {type(summary_data).__name__}, using defaults")
                summary_data = {}

            # Normalize score: Claude sometimes returns 0-100 instead of 0-10
            raw_score = summary_data.get("score", 10.0)
            if raw_score > 10:
                logger.warning(f"[CLAUDE PARSE] Score {raw_score} > 10, normalizing to 0-10 scale")
                raw_score = raw_score / 10.0
            # Clamp to valid range
            normalized_score = max(0.0, min(10.0, raw_score))

            summary = ReviewSummary(
                files_reviewed=summary_data.get("files_reviewed", len(file_list)),
                critical_issues=summary_data.get("critical_issues", 0),
                high_issues=summary_data.get("high_issues", 0),
                medium_issues=summary_data.get("medium_issues", 0),
                low_issues=summary_data.get("low_issues", 0),
                score=normalized_score,
            )

            # Parse issues
            issues = []
            # Category normalization for common aliases
            category_map = {
                "business_logic": "logic",
                "business": "logic",
                "functional": "logic",
                "code_quality": "style",
                "quality": "style",
                "maintainability": "architecture",
                "error_handling": "logic",
                "data_integrity": "logic",
            }
            for issue_data in data.get("issues", []):
                try:
                    # Normalize category
                    raw_category = issue_data.get("category", "style").lower()
                    normalized_category = category_map.get(raw_category, raw_category)

                    issue = Issue(
                        id=issue_data.get("id", f"{self.name.upper()}-ISSUE"),
                        severity=IssueSeverity(issue_data.get("severity", "MEDIUM")),
                        category=IssueCategory(normalized_category),
                        rule=issue_data.get("rule"),
                        file=issue_data.get("file", "unknown"),
                        line=issue_data.get("line"),
                        title=issue_data.get("title", "Issue"),
                        description=issue_data.get("description", ""),
                        current_code=issue_data.get("current_code"),
                        suggested_fix=issue_data.get("suggested_fix"),
                        references=issue_data.get("references", []),
                        flagged_by=[self.name],
                        # Effort estimation for fix batching
                        estimated_effort=issue_data.get("estimated_effort"),
                        estimated_files_count=issue_data.get("estimated_files_count"),
                    )
                    issues.append(issue)
                except Exception as e:
                    logger.warning(f"[CLAUDE PARSE] Skipping invalid issue: {e} - data: {issue_data.get('id', 'unknown')}")
                    continue

            # Parse checklists
            checklists = {}
            for category, checks in data.get("checklists", {}).items():
                # Validate checks is a dict (Claude sometimes returns malformed data)
                if not isinstance(checks, dict):
                    logger.warning(f"[CLAUDE PARSE] Skipping invalid checklist '{category}': expected dict, got {type(checks).__name__}")
                    continue
                checklists[category] = ChecklistResult(
                    passed=checks.get("passed", 0),
                    failed=checks.get("failed", 0),
                    skipped=checks.get("skipped", 0),
                )

            # Parse metrics
            metrics_data = data.get("metrics", {})
            metrics = ReviewMetrics(
                complexity_avg=metrics_data.get("complexity_avg"),
                test_coverage=metrics_data.get("test_coverage"),
                type_coverage=metrics_data.get("type_coverage"),
            )

            return ReviewOutput(
                reviewer=self.name,
                summary=summary,
                issues=issues,
                checklists=checklists,
                metrics=metrics,
            )

        except json.JSONDecodeError as e:
            logger.error(f"[CLAUDE PARSE] JSON DECODE ERROR: {e}")
            return self._create_error_output(
                f"JSON parse error: {str(e)}\n\nRaw output:\n{response_text[:1000]}"
            )

    def _create_error_output(self, error_message: str) -> ReviewOutput:
        """Create an error ReviewOutput without fake issues.

        The error will be reported through normal error handling (REVIEWER_ERROR event)
        without polluting the issues list with meta-errors.
        """
        logger.error(f"[{self.name}] Review failed: {error_message}")
        return ReviewOutput(
            reviewer=self.name,
            summary=ReviewSummary(
                files_reviewed=0,
                score=0.0,
            ),
            issues=[],  # No fake error issues - let the error be handled properly
        )
