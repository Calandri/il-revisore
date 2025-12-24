"""
Fix Orchestrator for TurboWrap.

Coordinates Claude CLI (fixer) and Gemini CLI (reviewer).
Both CLIs have full access to the system - they do ALL the work.
"""

import asyncio
import codecs
import json
import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from turbowrap.config import get_settings
from turbowrap.db.models import Issue
from turbowrap.fix.models import (
    FixEventType,
    FixProgressEvent,
    FixRequest,
    FixSessionResult,
    FixStatus,
)
from turbowrap.utils.aws_secrets import get_anthropic_api_key, get_google_api_key

logger = logging.getLogger(__name__)

# Agent file paths
AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "agents"
FIXER_AGENT = AGENTS_DIR / "fixer.md"
FIX_CHALLENGER_AGENT = AGENTS_DIR / "fix_challenger.md"
DEV_BE_AGENT = AGENTS_DIR / "dev_be.md"
DEV_FE_AGENT = AGENTS_DIR / "dev_fe.md"
ENGINEERING_PRINCIPLES = AGENTS_DIR / "engineering_principles.md"

# File extensions for frontend vs backend
FRONTEND_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".html", ".vue", ".svelte"}
BACKEND_EXTENSIONS = {".py", ".go", ".java", ".rb", ".php", ".rs", ".c", ".cpp", ".h"}

# Type for progress callback
ProgressCallback = Callable[[FixProgressEvent], Awaitable[None]]

# Timeouts
CLAUDE_CLI_TIMEOUT = 300  # 5 minutes per fix
GEMINI_CLI_TIMEOUT = 120  # 2 minutes per review


class FixOrchestrator:
    """
    Orchestrates fixing via Claude CLI and review via Gemini CLI.

    Both CLIs have FULL access to the system:
    - Claude CLI: reads files, writes files, creates files, runs commands
    - Gemini CLI: reads git diff, evaluates changes, provides feedback

    We just coordinate and pass messages between them.
    """

    def __init__(self, repo_path: Path):
        """Initialize with repository path."""
        self.repo_path = repo_path
        self.settings = get_settings()

        # Get challenger settings from config
        fix_config = self.settings.fix_challenger
        self.max_iterations = fix_config.max_iterations  # default 3
        self.satisfaction_threshold = fix_config.satisfaction_threshold  # default 80.0

        # Load agent prompts
        self._agent_cache: dict[str, str] = {}

    def _load_agent(self, agent_path: Path) -> str:
        """Load agent prompt from MD file, stripping frontmatter."""
        cache_key = str(agent_path)
        if cache_key in self._agent_cache:
            return self._agent_cache[cache_key]

        if not agent_path.exists():
            logger.warning(f"Agent file not found: {agent_path}")
            return ""

        content = agent_path.read_text(encoding="utf-8")

        # Strip YAML frontmatter (--- ... ---)
        if content.startswith("---"):
            end_match = re.search(r"\n---\n", content[3:])
            if end_match:
                content = content[3 + end_match.end() :]

        self._agent_cache[cache_key] = content.strip()
        return self._agent_cache[cache_key]

    def _is_frontend_file(self, file_path: str) -> bool:
        """Check if file is a frontend file based on extension."""
        ext = Path(file_path).suffix.lower()
        return ext in FRONTEND_EXTENSIONS

    def _is_backend_file(self, file_path: str) -> bool:
        """Check if file is a backend file based on extension."""
        ext = Path(file_path).suffix.lower()
        return ext in BACKEND_EXTENSIONS

    def _get_fixer_prompt_be(self) -> str:
        """Get fixer prompt for backend: fixer.md + dev_be.md."""
        fixer = self._load_agent(FIXER_AGENT)
        dev_be = self._load_agent(DEV_BE_AGENT)
        principles = self._load_agent(ENGINEERING_PRINCIPLES)

        parts = [fixer]
        if dev_be:
            parts.append(f"\n\n# Backend Development Guidelines\n\n{dev_be}")
        if principles:
            parts.append(f"\n\n# Engineering Principles\n\n{principles}")

        return "\n".join(parts)

    def _get_fixer_prompt_fe(self) -> str:
        """Get fixer prompt for frontend: fixer.md + dev_fe.md."""
        fixer = self._load_agent(FIXER_AGENT)
        dev_fe = self._load_agent(DEV_FE_AGENT)
        principles = self._load_agent(ENGINEERING_PRINCIPLES)

        parts = [fixer]
        if dev_fe:
            parts.append(f"\n\n# Frontend Development Guidelines\n\n{dev_fe}")
        if principles:
            parts.append(f"\n\n# Engineering Principles\n\n{principles}")

        return "\n".join(parts)

    def _classify_issues(self, issues: list[Issue]) -> tuple[list[Issue], list[Issue]]:
        """Classify issues into backend and frontend lists."""
        be_issues = []
        fe_issues = []

        for issue in issues:
            if self._is_backend_file(str(issue.file)):
                be_issues.append(issue)
            elif self._is_frontend_file(str(issue.file)):
                fe_issues.append(issue)
            else:
                # Default to backend for unknown extensions
                be_issues.append(issue)

        return be_issues, fe_issues

    def _get_challenger_prompt(self) -> str:
        """Get fix challenger prompt."""
        return self._load_agent(FIX_CHALLENGER_AGENT)

    async def fix_issues(
        self,
        request: FixRequest,
        issues: list[Issue],
        emit: ProgressCallback | None = None,
    ) -> FixSessionResult:
        """
        Fix issues with parallel BE/FE execution.

        Flow:
        1. Classify issues into BE and FE
        2. Launch Claude CLI(s) in parallel if both types exist
        3. Gemini CLI reviews ALL changes
        4. If score < threshold, retry with feedback (max iterations)
        5. Commit when approved
        """
        session_id = str(uuid.uuid4())
        branch_name = f"fix/{request.task_id[:20]}"

        result = FixSessionResult(
            session_id=session_id,
            repository_id=request.repository_id,
            task_id=request.task_id,
            branch_name=branch_name,
            status=FixStatus.PENDING,
            issues_requested=len(issues),
            started_at=datetime.utcnow(),
        )

        async def safe_emit(event: FixProgressEvent) -> None:
            if emit:
                try:
                    await emit(event)
                except Exception as e:
                    logger.error(f"Error emitting progress: {e}")

        try:
            # Classify issues
            be_issues, fe_issues = self._classify_issues(issues)
            has_be = len(be_issues) > 0
            has_fe = len(fe_issues) > 0

            await safe_emit(
                FixProgressEvent(
                    type=FixEventType.FIX_SESSION_STARTED,
                    session_id=session_id,
                    branch_name=branch_name,
                    total_issues=len(issues),
                    message=f"Starting fix: {len(be_issues)} BE + {len(fe_issues)} FE issues",
                )
            )

            # Create branch
            await self._run_claude_cli(
                f"Create and checkout a new git branch called '{branch_name}' if it doesn't exist. If it exists, just checkout to it.",
                timeout=30,
            )

            feedback_be = ""
            feedback_fe = ""

            for iteration in range(1, self.max_iterations + 1):
                # Step 1: Launch Claude CLI(s) in parallel
                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_GENERATING,
                        session_id=session_id,
                        message=f"Fixing (iteration {iteration}/{self.max_iterations})...",
                    )
                )

                # Create streaming callbacks for BE and FE
                async def on_chunk_be(chunk: str) -> None:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            content=f"[BE] {chunk}",
                        )
                    )

                async def on_chunk_fe(chunk: str) -> None:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            content=f"[FE] {chunk}",
                        )
                    )

                tasks = []
                task_types = []

                if has_be:
                    prompt_be = self._build_fix_prompt(be_issues, "be", feedback_be, iteration)
                    tasks.append(self._run_claude_cli(prompt_be, on_chunk=on_chunk_be))
                    task_types.append("be")
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message=f"→ Claude CLI (BE): fixing {len(be_issues)} issues",
                        )
                    )

                if has_fe:
                    prompt_fe = self._build_fix_prompt(fe_issues, "fe", feedback_fe, iteration)
                    tasks.append(self._run_claude_cli(prompt_fe, on_chunk=on_chunk_fe))
                    task_types.append("fe")
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message=f"→ Claude CLI (FE): fixing {len(fe_issues)} issues",
                        )
                    )

                # Run in parallel
                outputs = await asyncio.gather(*tasks, return_exceptions=True)

                # Check for failures
                for i, output in enumerate(outputs):
                    if isinstance(output, Exception) or output is None:
                        logger.error(f"Claude CLI ({task_types[i]}) failed: {output}")

                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_STREAMING,
                        session_id=session_id,
                        message="Claude CLI(s) completed",
                    )
                )

                # Step 2: Gemini reviews ALL changes together
                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_CHALLENGER_EVALUATING,
                        session_id=session_id,
                        message=f"Gemini CLI reviewing all changes (iteration {iteration})...",
                    )
                )

                # Streaming callback for Gemini review
                async def on_chunk_gemini(chunk: str) -> None:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_CHALLENGER_EVALUATING,
                            session_id=session_id,
                            content=chunk,
                        )
                    )

                review_prompt = self._build_review_prompt_batch(issues)
                gemini_output = await self._run_gemini_cli(review_prompt, on_chunk=on_chunk_gemini)

                if gemini_output is None:
                    logger.warning("Gemini CLI failed, accepting fixes without review")
                    break

                score = self._parse_score(gemini_output)

                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_CHALLENGER_RESULT,
                        session_id=session_id,
                        message=f"Score: {score}/100 (threshold: {self.satisfaction_threshold})",
                        content=gemini_output[:500],
                    )
                )

                if score >= self.satisfaction_threshold:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_CHALLENGER_APPROVED,
                            session_id=session_id,
                            message=f"Fix approved with score {score}/100!",
                        )
                    )
                    break
                # Parse feedback for next iteration
                feedback_be = gemini_output
                feedback_fe = gemini_output
                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_REGENERATING,
                        session_id=session_id,
                        message=f"Score {score} < {self.satisfaction_threshold}, retrying...",
                    )
                )

            # Step 3: Commit all changes
            await safe_emit(
                FixProgressEvent(
                    type=FixEventType.FIX_ISSUE_COMMITTING,
                    session_id=session_id,
                    message="Committing all changes...",
                )
            )

            issue_codes = ", ".join(str(i.issue_code) for i in issues[:3])
            if len(issues) > 3:
                issue_codes += f" (+{len(issues) - 3} more)"

            commit_prompt = f"""
Commit all changes with this message:
[FIX] {issue_codes}

Use: git add -A && git commit -m "[FIX] {issue_codes}"
"""
            await self._run_claude_cli(commit_prompt, timeout=30)

            result.status = FixStatus.COMPLETED
            result.issues_fixed = len(issues)
            result.completed_at = datetime.utcnow()

            await safe_emit(
                FixProgressEvent(
                    type=FixEventType.FIX_SESSION_COMPLETED,
                    session_id=session_id,
                    branch_name=branch_name,
                    issues_fixed=result.issues_fixed,
                    message=f"Fixed {len(issues)} issues",
                )
            )

            return result

        except Exception as e:
            logger.exception("Fix session failed")
            result.status = FixStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.utcnow()

            await safe_emit(
                FixProgressEvent(
                    type=FixEventType.FIX_SESSION_ERROR,
                    session_id=session_id,
                    error=str(e),
                )
            )

            return result

    def _build_review_prompt_batch(self, issues: list[Issue]) -> str:
        """Build review prompt for all issues."""
        agent_prompt = self._get_challenger_prompt()

        issue_list = "\n".join(f"- {i.issue_code}: {i.title} ({i.file})" for i in issues)

        task = f"""
# Task: Review ALL Fixes

## Issues Fixed
{issue_list}

## Instructions
1. Run `git diff` to see ALL changes
2. Evaluate if each fix correctly addresses its issue
3. Check for bugs, security issues, or breaking changes
4. Score from 0-100 for the OVERALL fix quality

## Output Format
Start your response with the score on its own line:
SCORE: <number>

Then provide detailed feedback for any issues found.
"""

        return f"{agent_prompt}\n\n---\n\n{task}"

    def _build_fix_prompt(
        self,
        issues: list[Issue],
        agent_type: str,
        feedback: str,
        iteration: int,
    ) -> str:
        """Build prompt for Claude CLI to fix issues.

        Args:
            issues: List of issues to fix (all same type: BE or FE)
            agent_type: "be" or "fe"
            feedback: Feedback from previous iteration
            iteration: Current iteration number
        """
        # Load agent prompt based on type
        if agent_type == "fe":
            agent_prompt = self._get_fixer_prompt_fe()
        else:
            agent_prompt = self._get_fixer_prompt_be()

        # Build task with all issues
        task_parts = ["# Task: Fix Code Issues\n"]

        for i, issue in enumerate(issues, 1):
            task_parts.append(f"""
## Issue {i}: {issue.issue_code}
**Title**: {issue.title}
**Severity**: {issue.severity}
**Category**: {issue.category}
**File**: {issue.file}
**Line**: {issue.line or "N/A"}

### Description
{issue.description}

### Current Code
```
{issue.current_code or "Read the file at " + issue.file}
```

### Suggested Fix
{issue.suggested_fix or "Use your best judgment"}

---
""")

        task_parts.append("""
## Instructions
1. Read the files to understand context
2. Make the fixes - one by one
3. Keep changes minimal
4. Do NOT commit - just fix the code
""")

        if feedback and iteration > 1:
            task_parts.append(f"""
## Feedback from Previous Attempt (Iteration {iteration})
The reviewer found issues with the previous fix. Address this feedback:

{feedback}
""")

        task = "\n".join(task_parts)

        # Combine agent prompt with task
        return f"{agent_prompt}\n\n---\n\n{task}"

    def _parse_score(self, output: str) -> float:
        """Extract score from Gemini output."""
        # Look for "SCORE: XX" pattern
        match = re.search(r"SCORE:\s*(\d+)", output, re.IGNORECASE)
        if match:
            return float(match.group(1))

        # Fallback: look for any number followed by /100
        match = re.search(r"(\d+)\s*/\s*100", output)
        if match:
            return float(match.group(1))

        # Default to 70 if can't parse
        logger.warning("Could not parse score from Gemini output, defaulting to 70")
        return 70.0

    async def _run_claude_cli(
        self,
        prompt: str,
        timeout: int = CLAUDE_CLI_TIMEOUT,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """Run Claude CLI with prompt and optional streaming callback."""
        try:
            # Build environment with API key from AWS Secrets Manager
            env = os.environ.copy()
            api_key = get_anthropic_api_key()
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key

            # Use Opus model from settings
            model = self.settings.agents.claude_model

            # Build CLI arguments with stream-json for real-time streaming
            args = [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                "--model",
                model,
                "--output-format",
                "stream-json",
                "--verbose",
            ]

            # Add extended thinking settings if enabled
            if self.settings.thinking.enabled:
                thinking_settings = {"alwaysThinkingEnabled": True}
                args.extend(["--settings", json.dumps(thinking_settings)])
                logger.info("Extended thinking enabled for Claude CLI")

            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
            )

            # Write prompt to stdin
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
            process.stdin.close()

            # Read stdout in streaming mode with incremental UTF-8 decoder
            # This handles multi-byte UTF-8 characters split across chunk boundaries
            output_chunks: list[str] = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            try:
                async with asyncio.timeout(timeout):
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
                            # Emit chunk for streaming
                            if on_chunk:
                                await on_chunk(decoded)

            except asyncio.TimeoutError:
                logger.error(f"Claude CLI timed out after {timeout}s")
                process.kill()
                return None

            await process.wait()

            if process.returncode != 0:
                stderr = await process.stderr.read()
                logger.error(f"Claude CLI failed: {stderr.decode()}")
                return None

            # Parse stream-json output (NDJSON)
            raw_output = "".join(output_chunks)
            for line in raw_output.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "result":
                        # Log model usage
                        model_usage = event.get("modelUsage", {})
                        if model_usage:
                            for model_name, usage in model_usage.items():
                                logger.info(
                                    f"  {model_name}: in={usage.get('inputTokens', 0)}, "
                                    f"out={usage.get('outputTokens', 0)}, "
                                    f"cost=${usage.get('costUSD', 0):.4f}"
                                )
                        total_cost = event.get("total_cost_usd", 0)
                        logger.info(f"Claude CLI total cost: ${total_cost:.4f}")
                        return event.get("result", "")
                except json.JSONDecodeError:
                    continue

            # Fallback to raw output
            logger.warning("No result found in stream-json, using raw output")
            return raw_output

        except asyncio.TimeoutError:
            logger.error(f"Claude CLI timed out after {timeout}s")
            return None
        except Exception:
            logger.exception("Claude CLI error")
            return None

    async def _run_gemini_cli(
        self,
        prompt: str,
        timeout: int = GEMINI_CLI_TIMEOUT,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """Run Gemini CLI with prompt and optional streaming callback."""
        try:
            # Build environment with API key from AWS Secrets Manager
            env = os.environ.copy()
            api_key = get_google_api_key()
            if api_key:
                env["GOOGLE_API_KEY"] = api_key

            # Use Pro model from settings (for better reasoning in review)
            model = self.settings.agents.gemini_pro_model

            process = await asyncio.create_subprocess_exec(
                "gemini",
                "-m",
                model,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
            )

            # Write prompt to stdin
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
            process.stdin.close()

            # Read stdout in streaming mode with incremental UTF-8 decoder
            # This handles multi-byte UTF-8 characters split across chunk boundaries
            output_chunks: list[str] = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            try:
                async with asyncio.timeout(timeout):
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
                            # Emit chunk for streaming
                            if on_chunk:
                                await on_chunk(decoded)

            except asyncio.TimeoutError:
                logger.error(f"Gemini CLI timed out after {timeout}s")
                process.kill()
                return None

            await process.wait()

            if process.returncode != 0:
                stderr = await process.stderr.read()
                logger.error(f"Gemini CLI failed: {stderr.decode()}")
                return None

            return "".join(output_chunks)

        except asyncio.TimeoutError:
            logger.error(f"Gemini CLI timed out after {timeout}s")
            return None
        except Exception:
            logger.exception("Gemini CLI error")
            return None
