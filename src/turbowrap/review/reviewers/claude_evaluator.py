"""
Claude CLI-based repository evaluator.

Produces comprehensive quality scores (0-100) for 6 dimensions.
Runs after all reviewers complete, with full context.
"""

import asyncio
import codecs
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings
from turbowrap.review.models.evaluation import RepositoryEvaluation
from turbowrap.review.models.report import RepositoryInfo, ReviewerResult
from turbowrap.review.models.review import Issue
from turbowrap.utils.aws_secrets import get_anthropic_api_key

logger = logging.getLogger(__name__)

# Timeouts
EVALUATOR_TIMEOUT = 180  # 3 minutes for evaluation

# Agent file path
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
EVALUATOR_AGENT = AGENTS_DIR / "evaluator.md"


class ClaudeEvaluator:
    """
    Repository evaluator using Claude CLI.

    Produces 6 quality metrics (0-100) based on:
    - Repository structure (STRUCTURE.md)
    - Issues found by reviewers
    - File contents
    - Repository metadata
    """

    def __init__(
        self,
        cli_path: str = "claude",
        timeout: int = EVALUATOR_TIMEOUT,
    ):
        """
        Initialize Claude evaluator.

        Args:
            cli_path: Path to Claude CLI executable
            timeout: Timeout in seconds for CLI execution
        """
        self.settings = get_settings()
        self.cli_path = cli_path
        self.timeout = timeout
        self._agent_prompt: str | None = None

        # S3 config
        self.s3_bucket = self.settings.thinking.s3_bucket
        self.s3_region = self.settings.thinking.s3_region
        self._s3_client = None

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    async def _save_evaluation_to_s3(
        self,
        prompt: str,
        output: str,
        evaluation: RepositoryEvaluation | None,
        repo_name: str | None = None,
        review_id: str | None = None,
    ) -> str | None:
        """Save evaluation prompt and output to S3.

        Args:
            prompt: The prompt sent to Claude
            output: Raw output from Claude
            evaluation: Parsed evaluation result
            repo_name: Repository name for identification
            review_id: Review ID for grouping

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.s3_bucket:
            return None

        try:
            timestamp = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
            review_id = review_id or f"eval_{int(datetime.utcnow().timestamp())}"
            s3_key = f"evaluations/{timestamp}/{review_id}_evaluation.md"

            eval_json = evaluation.model_dump_json(indent=2) if evaluation else "Failed to parse"

            content = f"""# Repository Evaluation

**Review ID**: {review_id}
**Repository**: {repo_name or 'Unknown'}
**Timestamp**: {datetime.utcnow().isoformat()}

---

## Prompt

```
{prompt}
```

---

## Raw Output

```
{output}
```

---

## Parsed Evaluation

```json
{eval_json}
```
"""

            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )

            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"[EVALUATOR] Saved evaluation to S3: {s3_url}")
            return s3_url

        except ClientError as e:
            logger.warning(f"Failed to save evaluation to S3: {e}")
            return None

    def _load_agent_prompt(self) -> str:
        """Load evaluator agent prompt from MD file."""
        if self._agent_prompt is not None:
            return self._agent_prompt

        if not EVALUATOR_AGENT.exists():
            logger.warning(f"Evaluator agent file not found: {EVALUATOR_AGENT}")
            return ""

        content = EVALUATOR_AGENT.read_text(encoding="utf-8")

        # Strip YAML frontmatter (--- ... ---)
        if content.startswith("---"):
            end_match = re.search(r"\n---\n", content[3:])
            if end_match:
                content = content[3 + end_match.end() :]

        self._agent_prompt = content.strip()
        return self._agent_prompt

    async def evaluate(
        self,
        structure_docs: dict[str, str],
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
        repo_path: Path | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        review_id: str | None = None,
    ) -> RepositoryEvaluation | None:
        """
        Evaluate repository and produce quality scores.

        Args:
            structure_docs: STRUCTURE.md contents by path
            issues: All deduplicated issues from reviewers
            reviewer_results: Results from each reviewer
            repo_info: Repository metadata
            repo_path: Path to repository (for Claude CLI cwd)
            on_chunk: Optional callback for streaming output
            review_id: Review ID for S3 logging

        Returns:
            RepositoryEvaluation with 6 scores, or None if evaluation failed
        """
        prompt = self._build_prompt(structure_docs, issues, reviewer_results, repo_info)

        output = await self._run_claude_cli(prompt, repo_path, on_chunk)

        if output is None:
            logger.error("Evaluator CLI returned None")
            # Save failed attempt to S3 for debugging
            await self._save_evaluation_to_s3(
                prompt, "CLI returned None", None, repo_info.name, review_id
            )
            return None

        evaluation = self._parse_response(output)

        # Save to S3 for debugging
        await self._save_evaluation_to_s3(prompt, output, evaluation, repo_info.name, review_id)

        return evaluation

    def _build_prompt(
        self,
        structure_docs: dict[str, str],
        issues: list[Issue],
        reviewer_results: list[ReviewerResult],
        repo_info: RepositoryInfo,
    ) -> str:
        """Build the evaluation prompt with all context."""
        sections = []

        # Agent prompt
        agent_prompt = self._load_agent_prompt()
        if agent_prompt:
            sections.append(agent_prompt)
            sections.append("\n---\n")

        # Repository info
        sections.append("# Repository Context\n")
        sections.append(f"- **Name**: {repo_info.name or 'Unknown'}\n")
        sections.append(f"- **Type**: {repo_info.type.value}\n")
        sections.append(f"- **Branch**: {repo_info.branch or 'Unknown'}\n")

        # Structure docs
        if structure_docs:
            sections.append("\n## Repository Structure\n")
            for path, content in structure_docs.items():
                # Truncate long structure docs
                truncated = content[:5000] if len(content) > 5000 else content
                sections.append(f"### {path}\n```\n{truncated}\n```\n")

        # Reviewer results summary
        sections.append("\n## Reviewer Results\n")
        for result in reviewer_results:
            status_emoji = "✅" if result.status == "completed" else "❌"
            sections.append(
                f"- **{result.name}**: {status_emoji} {result.issues_found} issues, "
                f"satisfaction: {result.final_satisfaction or 'N/A'}\n"
            )

        # Issues summary by severity
        sections.append("\n## Issues Found\n")
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for issue in issues:
            severity = (
                issue.severity.value if hasattr(issue.severity, "value") else str(issue.severity)
            )
            if severity in severity_counts:
                severity_counts[severity] += 1

        sections.append(f"- **CRITICAL**: {severity_counts['CRITICAL']}\n")
        sections.append(f"- **HIGH**: {severity_counts['HIGH']}\n")
        sections.append(f"- **MEDIUM**: {severity_counts['MEDIUM']}\n")
        sections.append(f"- **LOW**: {severity_counts['LOW']}\n")
        sections.append(f"- **Total**: {len(issues)}\n")

        # Issue details (limit to first 30 to avoid token explosion)
        if issues:
            sections.append("\n### Issue Details\n")
            for _i, issue in enumerate(issues[:30]):
                severity = (
                    issue.severity.value
                    if hasattr(issue.severity, "value")
                    else str(issue.severity)
                )
                category = (
                    issue.category.value
                    if hasattr(issue.category, "value")
                    else str(issue.category)
                )
                sections.append(
                    f"- **[{severity}]** `{issue.file}`: {issue.title} " f"({category})\n"
                )
            if len(issues) > 30:
                sections.append(f"... and {len(issues) - 30} more issues\n")

        sections.append("\n---\n")
        sections.append("\n**Now evaluate this repository and output JSON.**\n")

        return "".join(sections)

    async def _run_claude_cli(
        self,
        prompt: str,
        repo_path: Path | None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """
        Run Claude CLI with the prompt.

        Uses robust pattern with:
        - Background stdin writing (avoids deadlock on large prompts)
        - Concurrent stderr reading (real-time error visibility)
        - Progress logging (debugging aid)

        Args:
            prompt: The full prompt to send
            repo_path: Working directory for the CLI
            on_chunk: Optional callback for streaming chunks

        Returns:
            CLI output or None if failed
        """
        cwd = str(repo_path) if repo_path else None

        try:
            # ============================================================
            # SECTION 1: Environment Setup
            # - Copy current env to avoid modifying global state
            # - Add API key from AWS Secrets Manager (or env var fallback)
            # - Set TMPDIR to /tmp to avoid Bun file watcher bug on macOS
            # ============================================================
            env = os.environ.copy()
            api_key = get_anthropic_api_key()
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            env["TMPDIR"] = "/tmp"

            # ============================================================
            # SECTION 2: CLI Arguments
            # - --print: One-shot mode (no interactive session)
            # - --verbose: Required for stream-json output
            # - --dangerously-skip-permissions: Skip permission prompts
            # - --output-format stream-json: NDJSON streaming format
            # ============================================================
            model = self.settings.agents.claude_model
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

            # Extended thinking via env var (--settings flag is buggy)
            if self.settings.thinking.enabled:
                env["MAX_THINKING_TOKENS"] = str(self.settings.thinking.budget_tokens)
                logger.info(
                    f"[EVALUATOR] Extended thinking: MAX_THINKING_TOKENS={env['MAX_THINKING_TOKENS']}"
                )

            logger.info(f"[EVALUATOR] Starting CLI: {' '.join(args)}")
            logger.info(f"[EVALUATOR] Working dir: {cwd}")
            logger.info(f"[EVALUATOR] Prompt length: {len(prompt)} chars")

            # ============================================================
            # SECTION 3: Start Subprocess
            # - stdin=PIPE: We'll write the prompt here
            # - stdout=PIPE: We'll read the response here
            # - stderr=PIPE: We'll read errors/verbose output here
            # ============================================================
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            logger.info(f"[EVALUATOR] Process started with PID: {process.pid}")

            # ============================================================
            # SECTION 4: Background Stdin Writer
            # WHY: Pipe buffer is ~64KB. If prompt > 64KB and we write
            # synchronously, we'll block waiting for reader to consume.
            # But we're not reading yet → DEADLOCK!
            # SOLUTION: Write in background task while reading stdout.
            # ============================================================
            prompt_bytes = prompt.encode()
            stdin_error: str | None = None

            async def write_stdin():
                nonlocal stdin_error
                try:
                    logger.info(f"[EVALUATOR] Writing {len(prompt_bytes)} bytes to stdin...")
                    process.stdin.write(prompt_bytes)
                    await process.stdin.drain()
                    process.stdin.close()
                    # CRITICAL: wait_closed() signals EOF to Claude CLI
                    await process.stdin.wait_closed()
                    logger.info("[EVALUATOR] Stdin closed (EOF sent)")
                except BrokenPipeError as e:
                    stdin_error = f"BrokenPipe: {e}"
                    logger.error(f"[EVALUATOR] Stdin BrokenPipe: {e}")
                except Exception as e:
                    stdin_error = str(e)
                    logger.error(f"[EVALUATOR] Stdin error: {e}")

            stdin_task = asyncio.create_task(write_stdin())

            # ============================================================
            # SECTION 5: Background Stderr Reader
            # WHY: --verbose outputs progress to stderr. Reading it
            # concurrently lets us see errors in real-time instead of
            # waiting until process exits (or timeout).
            # ============================================================
            stderr_chunks: list[str] = []

            async def read_stderr():
                stderr_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while True:
                    chunk = await process.stderr.read(1024)
                    if not chunk:
                        final = stderr_decoder.decode(b"", final=True)
                        if final:
                            stderr_chunks.append(final)
                        break
                    decoded = stderr_decoder.decode(chunk)
                    if decoded:
                        stderr_chunks.append(decoded)
                        # Log each line for visibility
                        for line in decoded.split("\n"):
                            if line.strip():
                                logger.debug(f"[EVALUATOR STDERR] {line}")

            stderr_task = asyncio.create_task(read_stderr())

            # ============================================================
            # SECTION 6: Main Loop - Read Stdout with Timeout
            # - Incremental UTF-8 decoder handles multi-byte chars
            # - Progress logging every 30 seconds
            # - Timeout kills process and cancels tasks
            # ============================================================
            output_chunks: list[str] = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            chunks_received = 0
            total_bytes = 0
            last_log_time = time.time()

            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        chunk = await process.stdout.read(1024)
                        if not chunk:
                            # Flush remaining bytes
                            decoded = decoder.decode(b"", final=True)
                            if decoded:
                                output_chunks.append(decoded)
                                if on_chunk:
                                    await on_chunk(decoded)
                            logger.info(
                                f"[EVALUATOR] Stream ended. Total: {chunks_received} chunks, {total_bytes} bytes"
                            )
                            break

                        chunks_received += 1
                        total_bytes += len(chunk)

                        # Progress log every 30 seconds
                        now = time.time()
                        if now - last_log_time > 30:
                            logger.info(
                                f"[EVALUATOR] Streaming... {chunks_received} chunks, {total_bytes} bytes"
                            )
                            last_log_time = now

                        # Log first chunk (confirms CLI is responding)
                        if chunks_received == 1:
                            logger.info(f"[EVALUATOR] First chunk received! ({len(chunk)} bytes)")

                        decoded = decoder.decode(chunk)
                        if decoded:
                            output_chunks.append(decoded)
                            if on_chunk:
                                await on_chunk(decoded)

            except asyncio.TimeoutError:
                logger.error(
                    f"[EVALUATOR] TIMEOUT after {self.timeout}s! Received {chunks_received} chunks, {total_bytes} bytes"
                )
                stdin_task.cancel()
                stderr_task.cancel()
                process.kill()
                return None

            # ============================================================
            # SECTION 7: Wait for Tasks and Process
            # ============================================================
            await stdin_task
            await stderr_task

            if stdin_error:
                logger.error(f"[EVALUATOR] Stdin failed: {stdin_error}")

            logger.info("[EVALUATOR] Waiting for process to exit...")
            await process.wait()
            logger.info(f"[EVALUATOR] Process exited with code {process.returncode}")

            stderr_text = "".join(stderr_chunks)
            if stderr_text:
                logger.debug(f"[EVALUATOR] Stderr total: {len(stderr_text)} chars")

            if process.returncode != 0:
                logger.error(f"[EVALUATOR] FAILED with code {process.returncode}")
                logger.error(f"[EVALUATOR] Stderr: {stderr_text[:1000]}")
                return None

            # ============================================================
            # SECTION 8: Parse Stream-JSON Output
            # Format: One JSON object per line (NDJSON)
            # Look for {"type": "result", "result": "..."} line
            # ============================================================
            raw_output = "".join(output_chunks)
            for line in raw_output.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "result":
                        result = event.get("result", "")
                        logger.info(f"[EVALUATOR] Got result: {len(result)} chars")
                        return result
                except json.JSONDecodeError:
                    continue

            # Fallback to raw output if no result event found
            logger.warning("[EVALUATOR] No result event in stream-json, using raw output")
            return raw_output

        except FileNotFoundError:
            logger.error(f"[EVALUATOR] CLI not found at: {self.cli_path}")
            return None
        except Exception as e:
            logger.exception(f"[EVALUATOR] Exception: {e}")
            return None

    def _parse_response(self, response_text: str) -> RepositoryEvaluation | None:
        """Parse Claude's JSON response into RepositoryEvaluation."""
        try:
            # Extract JSON from response
            json_text = self._extract_json(response_text)
            data = json.loads(json_text)

            # Calculate overall if not provided
            overall = data.get("overall_score")
            if overall is None:
                overall = RepositoryEvaluation.calculate_overall(
                    functionality=data.get("functionality", 50),
                    code_quality=data.get("code_quality", 50),
                    comment_quality=data.get("comment_quality", 50),
                    architecture_quality=data.get("architecture_quality", 50),
                    effectiveness=data.get("effectiveness", 50),
                    code_duplication=data.get("code_duplication", 50),
                )

            return RepositoryEvaluation(
                functionality=data.get("functionality", 50),
                code_quality=data.get("code_quality", 50),
                comment_quality=data.get("comment_quality", 50),
                architecture_quality=data.get("architecture_quality", 50),
                effectiveness=data.get("effectiveness", 50),
                code_duplication=data.get("code_duplication", 50),
                overall_score=overall,
                summary=data.get("summary", "Evaluation completed."),
                strengths=data.get("strengths", []),
                weaknesses=data.get("weaknesses", []),
                evaluated_at=datetime.utcnow(),
                evaluator_model=self.settings.agents.claude_model,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Evaluator JSON parse error: {e}")
            logger.error(f"Raw response: {response_text[:1000]}")
            return None
        except Exception as e:
            logger.error(f"Evaluator parse error: {e}")
            return None

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response text."""
        text = text.strip()

        # Look for markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                return text[start:end].strip()

        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end != -1:
                potential = text[start:end].strip()
                if potential.startswith("{"):
                    return potential

        # Find first { and last }
        first_brace = text.find("{")
        if first_brace != -1:
            last_brace = text.rfind("}")
            if last_brace > first_brace:
                return text[first_brace : last_brace + 1]

        return text
