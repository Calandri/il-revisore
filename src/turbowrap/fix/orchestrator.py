"""
Fix Orchestrator for TurboWrap.

Coordinates Claude CLI (fixer) and Gemini CLI (reviewer).
Both CLIs have full access to the system - they do ALL the work.

Uses the centralized ClaudeCLI utility for Claude CLI subprocess execution.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from turbowrap.chat_cli.context_generator import load_structure_documentation
from turbowrap.config import get_settings
from turbowrap.db.models import Issue
from turbowrap.fix.models import (
    FixEventType,
    FixProgressEvent,
    FixRequest,
    FixSessionResult,
    FixStatus,
    IssueFixResult,
)
from turbowrap.llm.claude_cli import ClaudeCLI, ClaudeCLIResult

# Import GeminiCLI from shared orchestration utilities
from turbowrap.orchestration.cli_runner import GeminiCLI

S3_BUCKET = "turbowrap-thinking"

logger = logging.getLogger(__name__)

MAX_SESSION_TOKENS = 150_000  # 150k token limit (50k margin on 200k Opus)


@dataclass
class FixSessionContext:
    """Tracking for session persistence in fix flow.

    Maintains Claude session ID across batches and tracks token usage.
    Uses cache_read_tokens from the LATEST request to determine context size -
    this is how much context Claude is loading from session memory.

    When context size exceeds MAX_SESSION_TOKENS, /compact is triggered which
    compresses the context within the same session.

    branch_session_id: Initial session from branch creation, propagated through
    fix and commit phases to reuse cached codebase import (~33% cost savings).
    """

    claude_session_id: str | None = None
    branch_session_id: str | None = None  # Session from branch creation for cache reuse
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    last_cache_read_tokens: int = 0  # Context size = how much Claude reads from cache
    last_cache_creation_tokens: int = 0
    compaction_count: int = 0

    @property
    def cumulative_tokens(self) -> int:
        """Total tokens used in this session (for reporting)."""
        return self.cumulative_input_tokens + self.cumulative_output_tokens

    @property
    def context_size(self) -> int:
        """Current context size = cache_read_tokens from last request.

        This shows how much context Claude is loading from its session memory.
        After /compact, this value will decrease.
        """
        return self.last_cache_read_tokens

    def needs_compaction(self, threshold: int = MAX_SESSION_TOKENS) -> bool:
        """Check if context needs compaction based on cache_read_tokens."""
        return self.last_cache_read_tokens >= threshold


class BillingError(Exception):
    """Raised when Claude CLI returns a billing/credit error."""

    pass


AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "agents"
FIXER_AGENT = AGENTS_DIR / "fixer.md"
FIX_CHALLENGER_AGENT = AGENTS_DIR / "fix_challenger.md"
DEV_BE_AGENT = AGENTS_DIR / "dev_be.md"
DEV_FE_AGENT = AGENTS_DIR / "dev_fe.md"
ENGINEERING_PRINCIPLES = AGENTS_DIR / "engineering_principles.md"
GIT_BRANCH_CREATOR_AGENT = AGENTS_DIR / "git_branch_creator.md"
GIT_COMMITTER_AGENT = AGENTS_DIR / "git_committer.md"

FRONTEND_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".html", ".vue", ".svelte"}
BACKEND_EXTENSIONS = {".py", ".go", ".java", ".rb", ".php", ".rs", ".c", ".cpp", ".h"}

ProgressCallback = Callable[[FixProgressEvent], Awaitable[None]]

# Timeouts
CLAUDE_CLI_TIMEOUT = 900  # 15 minutes per fix
GEMINI_CLI_TIMEOUT = 120  # 2 minutes per review


MAX_ISSUES_PER_CLI_CALL = 5  # Max issues per batch (fallback if no estimates)
MAX_WORKLOAD_POINTS_PER_BATCH = 15  # Max workload points per batch
DEFAULT_EFFORT = 3  # Default effort if not estimated (1-5 scale)
DEFAULT_FILES = 1  # Default files to modify if not estimated


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

        fix_config = self.settings.fix_challenger
        self.max_iterations = fix_config.max_iterations  # default 3
        self.satisfaction_threshold = fix_config.satisfaction_threshold  # default 95.0

        self._agent_cache: dict[str, str] = {}

        self.s3_client = boto3.client("s3")
        self.s3_bucket = S3_BUCKET

        self.gemini_cli = GeminiCLI(
            working_dir=repo_path,
            timeout=GEMINI_CLI_TIMEOUT,
        )

        self._github_token_cache: str | None = None

    def _get_github_token(self) -> str | None:
        """Get GitHub token from database settings.

        Used to authenticate git operations in Claude CLI subprocess.
        Token is passed via environment variable, not in prompts (for security).
        """
        if self._github_token_cache is not None:
            return self._github_token_cache

        from turbowrap.db.models import Setting
        from turbowrap.db.session import get_session_local

        db = None
        try:
            SessionLocal = get_session_local()
            db = SessionLocal()
            setting = db.query(Setting).filter(Setting.key == "github_token").first()
            if setting and setting.value:
                self._github_token_cache = str(setting.value)
                logger.info(
                    f"[FIX] GitHub token found in DB (length={len(self._github_token_cache)})"
                )
                return self._github_token_cache
            logger.warning("[FIX] GitHub token NOT found in DB settings")
        except Exception as e:
            logger.warning(f"Failed to get GitHub token from DB: {e}")
        finally:
            if db is not None:
                db.close()

        return None

    def _load_agent(self, agent_path: Path) -> str:
        """Load agent prompt from MD file, stripping frontmatter."""
        cache_key = str(agent_path)
        if cache_key in self._agent_cache:
            return self._agent_cache[cache_key]

        if not agent_path.exists():
            logger.warning(f"Agent file not found: {agent_path}")
            return ""

        content = agent_path.read_text(encoding="utf-8")

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
                be_issues.append(issue)

        return be_issues, fe_issues

    def _get_challenger_prompt(self) -> str:
        """Get fix challenger prompt."""
        return self._load_agent(FIX_CHALLENGER_AGENT)

    def _get_code_snippet(self, issue: Issue, context_lines: int = 5) -> str:
        """Extract code snippet from file around the issue location.

        Args:
            issue: The issue with file path and line numbers
            context_lines: Number of lines to show before/after the issue

        Returns:
            Code snippet with line numbers, or empty string if file not found
        """
        if issue.current_code:
            line_info = (
                f"(lines {issue.line}-{issue.end_line})"
                if issue.line and issue.end_line
                else f"(line {issue.line})" if issue.line else ""
            )
            return f"{line_info}\n{issue.current_code}"

        if not issue.line:
            return ""

        try:
            file_path = self.repo_path / issue.file
            if not file_path.exists():
                return f"[File not found: {issue.file}]"

            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            issue_line: int = issue.line  # type: ignore[assignment]
            issue_end_line: int = int(issue.end_line) if issue.end_line else issue_line
            start_line = max(1, issue_line - context_lines)
            end_line = min(len(lines), issue_end_line + context_lines)

            snippet_lines = []
            for i in range(start_line - 1, end_line):
                line_num = i + 1
                marker = ">>>" if issue_line <= line_num <= issue_end_line else "   "
                snippet_lines.append(f"{marker} {line_num:4d} | {lines[i].rstrip()}")

            return "\n".join(snippet_lines)
        except Exception as e:
            logger.warning(f"Failed to read code snippet for {issue.file}:{issue.line}: {e}")
            return f"[Error reading file: {e}]"

    async def fix_issues(
        self,
        request: FixRequest,
        issues: list[Issue],
        emit: ProgressCallback | None = None,
        operation_id: str | None = None,
    ) -> FixSessionResult:
        """
        Fix issues with parallel BE/FE execution.

        Flow:
        1. Classify issues into BE and FE
        2. Launch Claude CLI(s) in parallel if both types exist
        3. Gemini CLI reviews ALL changes
        4. If score < threshold, retry with feedback (max iterations)
        5. Commit when approved

        Args:
            request: Fix request with config
            issues: Issues to fix
            emit: Progress callback
            operation_id: Optional operation ID for tracker (uses session_id if not provided)
        """
        session_id = operation_id or str(uuid.uuid4())
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

        async def emit_log(level: str, message: str) -> None:
            """Emit a log event for UI toast notifications."""
            await safe_emit(
                FixProgressEvent(
                    type=FixEventType.FIX_LOG,
                    session_id=session_id,
                    message=message,
                    log_level=level,
                )
            )

        try:
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

            # Handle branch: either use existing or create new from main
            if request.use_existing_branch and request.existing_branch_name:
                # Use existing branch - just checkout
                branch_name = request.existing_branch_name
                result.branch_name = branch_name
                logger.info(f"Using existing branch: {branch_name}")
                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_STREAMING,
                        session_id=session_id,
                        message=f"Continuing on existing branch: {branch_name}",
                    )
                )
                # Simple checkout - no need for full agent
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "checkout",
                    branch_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.repo_path),
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise Exception(f"Failed to checkout branch {branch_name}: {stderr.decode()}")
            else:
                branch_creator_prompt = self._load_agent(GIT_BRANCH_CREATOR_AGENT)
                branch_creator_prompt = branch_creator_prompt.replace("{branch_name}", branch_name)
                branch_result = await self._run_claude_cli(
                    branch_creator_prompt,
                    timeout=60,
                    model="haiku",
                    parent_session_id=session_id,
                    agent_type="branch_creator",
                )

                # Capture branch session ID for later reuse (FASE 3)
                branch_session_id = branch_result.session_id
                logger.info(
                    f"[FIX] Branch created with session: {branch_session_id[:8] if branch_session_id else 'N/A'}... "
                    f"(will be propagated to fix and commit phases)"
                )

                # Check for errors
                if not branch_result.success:
                    specific_error = branch_result.error or "Unknown error"
                    error_msg = f"Failed to create branch '{branch_name}': {specific_error}"
                    logger.error(f"[FIX] {error_msg}")
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message=f"❌ {error_msg}",
                        )
                    )
                    raise Exception(error_msg)

            feedback_be = ""
            feedback_fe = ""
            last_gemini_output: str | None = None  # Store for fix explanation

            claude_prompts: list[dict[str, Any]] = []  # [{type: "be"|"fe", batch: N, prompt: str}]
            gemini_prompt: str | None = None

            def get_issue_workload(issue: Issue) -> int:
                """Calculate workload points for an issue based on estimates."""
                effort = int(issue.estimated_effort) if issue.estimated_effort else DEFAULT_EFFORT
                files = (
                    int(issue.estimated_files_count)
                    if issue.estimated_files_count
                    else DEFAULT_FILES
                )
                return effort * files

            def batch_issues_by_workload(issues_to_batch: list[Issue]) -> list[list[Issue]]:
                """Split issues into batches based on workload estimates."""
                batches: list[list[Issue]] = []
                current_batch: list[Issue] = []
                current_workload = 0

                for issue in issues_to_batch:
                    workload = get_issue_workload(issue)
                    if current_batch and (
                        current_workload + workload > MAX_WORKLOAD_POINTS_PER_BATCH
                        or len(current_batch) >= MAX_ISSUES_PER_CLI_CALL
                    ):
                        batches.append(current_batch)
                        current_batch = []
                        current_workload = 0
                    current_batch.append(issue)
                    current_workload += workload

                if current_batch:
                    batches.append(current_batch)
                return batches

            all_be_batches = batch_issues_by_workload(be_issues) if has_be else []
            all_fe_batches = batch_issues_by_workload(fe_issues) if has_fe else []
            len(all_be_batches) + len(all_fe_batches)

            # Track batch results across iterations
            batch_results: dict[str, dict[str, Any]] = {}
            for idx in range(len(all_be_batches)):
                batch_results[f"BE-{idx + 1}"] = {
                    "passed": False,
                    "score": 0.0,
                    "failed_issues": [],
                    "issues": all_be_batches[idx],
                }
            for idx in range(len(all_fe_batches)):
                batch_results[f"FE-{idx + 1}"] = {
                    "passed": False,
                    "score": 0.0,
                    "failed_issues": [],
                    "issues": all_fe_batches[idx],
                }

            # Track all issues that have been successfully fixed
            successful_issues: list[Issue] = []
            failed_issues: list[Issue] = []

            # Initialize session context with branch session if available (FASE 4)
            if not request.use_existing_branch and branch_session_id:
                # Unified session mode: propagate branch session to fix and commit phases
                session_context = FixSessionContext(
                    branch_session_id=branch_session_id,
                    claude_session_id=branch_session_id,  # Start with same session
                )
                logger.info(
                    f"[FIX] ✓ Unified session mode enabled: {branch_session_id[:8]}... "
                    f"(fix and commit will reuse cache from branch creation)"
                )
            else:
                # Fallback to isolated sessions
                session_context = FixSessionContext()
                logger.info("[FIX] Using isolated sessions (no branch session to propagate)")

            for iteration in range(1, self.max_iterations + 1):
                if iteration == 1:
                    batches_to_process = list(batch_results.keys())
                else:
                    batches_to_process = [
                        batch_id
                        for batch_id, result in batch_results.items()
                        if not result["passed"]
                    ]

                if not batches_to_process:
                    logger.info("All batches passed, no more retries needed")
                    break

                be_retry = [b for b in batches_to_process if b.startswith("BE")]
                fe_retry = [b for b in batches_to_process if b.startswith("FE")]
                plan_parts = []
                if be_retry:
                    plan_parts.append(
                        f"{len(be_retry)} BE batch{'es' if len(be_retry) > 1 else ''}"
                    )
                if fe_retry:
                    plan_parts.append(
                        f"{len(fe_retry)} FE batch{'es' if len(fe_retry) > 1 else ''}"
                    )
                plan_msg = " + ".join(plan_parts) if plan_parts else "No batches"

                if iteration > 1:
                    failed_batch_ids = ", ".join(batches_to_process)
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_GENERATING,
                            session_id=session_id,
                            message=f"══════ Iteration {iteration}/{self.max_iterations} ══════\n"
                            f"📋 Retrying FAILED batches: {failed_batch_ids}",
                        )
                    )
                else:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_GENERATING,
                            session_id=session_id,
                            message=f"══════ Iteration {iteration}/{self.max_iterations} ══════\n"
                            f"📋 Plan: {plan_msg} ({len(batches_to_process)} total, "
                            f"1 Gemini review per batch)",
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

                completed_batches = 0
                all_passed_this_iteration = True

                for batch_id in batches_to_process:
                    batch_type = "BE" if batch_id.startswith("BE") else "FE"
                    batch_idx = int(batch_id.split("-")[1])
                    batch = batch_results[batch_id]["issues"]
                    completed_batches += 1

                    feedback = feedback_be if batch_type == "BE" else feedback_fe

                    async def on_chunk_claude(chunk: str, bt: str = batch_type) -> None:
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_ISSUE_STREAMING,
                                session_id=session_id,
                                content=chunk,
                                batch_type=bt,
                            )
                        )

                    batch_workload = sum(get_issue_workload(i) for i in batch)
                    issue_codes = ", ".join(str(i.issue_code) for i in batch)
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message=f"🔧 {batch_id} "
                            f"[{completed_batches}/{len(batches_to_process)}] "
                            f"| {len(batch)} issues, workload={batch_workload}\n"
                            f"   Issues: {issue_codes}",
                        )
                    )

                    # Step 1: Run Claude CLI for this batch
                    prompt = self._build_fix_prompt(
                        batch,
                        batch_type.lower(),
                        feedback,
                        iteration,
                        request.workspace_path,
                        request.user_notes,
                    )
                    if iteration == 1:
                        claude_prompts.append(
                            {
                                "type": batch_type.lower(),
                                "batch": batch_idx,
                                "issues": [i.issue_code for i in batch],
                                "prompt": prompt,
                            }
                        )

                    thinking_budget = None
                    if batch_workload > 10:
                        base_budget = self.settings.thinking.budget_tokens
                        thinking_budget = min(16000, base_budget + (batch_workload - 10) * 1000)
                        logger.info(
                            f"Heavy batch (workload={batch_workload}), "
                            f"thinking budget: {thinking_budget}"
                        )
                        await emit_log(
                            "INFO", f"Heavy batch: thinking budget {thinking_budget} tokens"
                        )

                    # Log session status before fix phase
                    if session_context.branch_session_id:
                        logger.info(
                            f"[FIX] Fix phase resuming session: {session_context.claude_session_id[:8] if session_context.claude_session_id else 'N/A'}... | "
                            f"Model: opus | Cache READ expected (reusing branch cache)"
                        )
                    else:
                        logger.info(
                            "[FIX] Fix phase starting new session | "
                            "Model: opus | Cache CREATION expected"
                        )

                    try:
                        claude_result: ClaudeCLIResult = await self._run_claude_cli(
                            prompt,
                            on_chunk=on_chunk_claude,
                            thinking_budget=thinking_budget,
                            session_context=session_context,
                            parent_session_id=session_id,
                            agent_type="fixer",
                        )
                        if not claude_result.success:
                            error_detail = claude_result.error or "Unknown error"
                            logger.error(f"Claude CLI ({batch_id}) failed: {error_detail}")
                            await emit_log(
                                "ERROR", f"Claude CLI failed for {batch_id}: {error_detail}"
                            )
                            batch_results[batch_id]["passed"] = False
                            batch_results[batch_id]["score"] = 0.0
                            all_passed_this_iteration = False
                            await safe_emit(
                                FixProgressEvent(
                                    type=FixEventType.FIX_ISSUE_STREAMING,
                                    session_id=session_id,
                                    message=f"   ❌ {batch_id} Claude CLI FAILED",
                                )
                            )
                            continue
                    except BillingError as e:
                        await emit_log("ERROR", f"Billing error: {str(e)[:100]}")
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_BILLING_ERROR,
                                session_id=session_id,
                                error=str(e),
                                message=f"💳 BILLING ERROR: {e}\n\n"
                                f"Ricarica il credito su console.anthropic.com",
                            )
                        )
                        raise
                    except Exception as e:
                        logger.error(f"Claude CLI ({batch_id}) failed with exception: {e}")
                        await emit_log("ERROR", f"Claude CLI exception: {str(e)[:100]}")
                        batch_results[batch_id]["passed"] = False
                        all_passed_this_iteration = False
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_ISSUE_STREAMING,
                                session_id=session_id,
                                message=f"   ❌ {batch_id} Claude CLI FAILED: {str(e)[:100]}",
                            )
                        )
                        continue

                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message=f"   ✅ {batch_id} Claude fix complete, "
                            f"running Gemini review...",
                        )
                    )

                    # Step 2: Run Gemini review for THIS BATCH immediately
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_CHALLENGER_EVALUATING,
                            session_id=session_id,
                            message=f"🔍 Gemini reviewing {batch_id}...",
                        )
                    )

                    review_prompt = self._build_review_prompt_per_batch(
                        batch, batch_type, batch_idx, request.workspace_path
                    )
                    if iteration == 1 and completed_batches == 1:
                        gemini_prompt = review_prompt  # Save first for S3 logging

                    # Atomic tracking at leaf level
                    gemini_result = await self.gemini_cli.run(
                        review_prompt,
                        operation_type="review",
                        repo_name=self.repo_path.name,
                        on_chunk=on_chunk_gemini,
                        track_operation=True,  # Atomic tracking at leaf level
                        operation_details={
                            "parent_session_id": session_id,
                            "agent_type": "reviewer",
                            "batch_id": batch_id,
                        },
                    )
                    gemini_output = gemini_result.output if gemini_result.success else None
                    last_gemini_output = gemini_output

                    # NOTE: Operation tracking is now handled atomically by GeminiCLI.run()

                    if gemini_output is None:
                        logger.warning(
                            f"Gemini CLI failed for {batch_id}, accepting fix without review"
                        )
                        await emit_log(
                            "WARNING", f"Gemini review failed for {batch_id}, accepting fix"
                        )
                        batch_results[batch_id]["passed"] = True
                        batch_results[batch_id]["score"] = 100.0
                        successful_issues.extend(batch)
                        continue

                    score, failed_issue_codes, per_issue_scores, quality_scores = (
                        self._parse_batch_review(gemini_output, batch)
                    )
                    batch_results[batch_id]["score"] = score
                    batch_results[batch_id]["failed_issues"] = failed_issue_codes

                    if per_issue_scores:
                        scores_summary = " | ".join(
                            [f"{code}: {int(s)}" for code, s in per_issue_scores.items()]
                        )
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_CHALLENGER_RESULT,
                                session_id=session_id,
                                message=f"   📊 {batch_id} score: {score}/100 | "
                                f"Per-issue: {scores_summary}",
                                quality_scores=quality_scores if quality_scores else None,
                            )
                        )
                    else:
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_CHALLENGER_RESULT,
                                session_id=session_id,
                                message=f"   📊 {batch_id} score: {score}/100",
                                quality_scores=quality_scores if quality_scores else None,
                            )
                        )

                    if score >= self.satisfaction_threshold:
                        batch_results[batch_id]["passed"] = True
                        await emit_log("INFO", f"{batch_id} passed with score {score}/100")

                        batch_issue_codes = ", ".join(str(i.issue_code) for i in batch)
                        batch_commit_msg = f"[FIX] {batch_issue_codes}"
                        commit_prompt = self._load_agent(GIT_COMMITTER_AGENT)
                        commit_prompt = commit_prompt.replace("{commit_message}", batch_commit_msg)
                        commit_prompt = commit_prompt.replace("{issue_codes}", batch_issue_codes)

                        # Log session status before commit phase
                        if session_context.branch_session_id:
                            logger.info(
                                f"[FIX] Commit phase resuming session: {session_context.claude_session_id[:8] if session_context.claude_session_id else 'N/A'}... | "
                                f"Model: haiku | Cache READ expected (reusing branch cache)"
                            )
                        else:
                            logger.info(
                                "[FIX] Commit phase starting new session | "
                                "Model: haiku | Cache CREATION expected"
                            )

                        batch_commit_success = False

                        if request.workspace_path:
                            uncommitted = await self._get_uncommitted_files()
                            violations = self._validate_workspace_scope(
                                uncommitted,
                                request.workspace_path,
                                request.allowed_extra_paths,
                            )
                            if violations:
                                await emit_log(
                                    "ERROR",
                                    f"Batch {batch_id} scope violation: {violations[:3]}",
                                )
                                await self._revert_uncommitted_changes()
                                failed_issues.extend(batch)
                                batch_results[batch_id]["passed"] = False
                                await safe_emit(
                                    FixProgressEvent(
                                        type=FixEventType.FIX_BATCH_FAILED,
                                        session_id=session_id,
                                        message=f"   ❌ {batch_id} scope violation",
                                        issue_ids=[i.id for i in batch],
                                        issue_codes=[i.issue_code for i in batch],
                                        error=f"Files outside workspace: {violations[:3]}",
                                    )
                                )
                                continue  # Skip to next batch

                        try:
                            commit_result = await self._run_claude_cli(
                                commit_prompt,
                                timeout=30,
                                model="haiku",
                                session_context=session_context,  # FASE 5: Propagate session
                                parent_session_id=session_id,
                                agent_type="committer",
                            )
                            if not commit_result.success:
                                await emit_log("ERROR", f"Batch {batch_id} commit failed")
                            else:
                                (
                                    batch_commit_sha,
                                    batch_modified_files,
                                    _,
                                ) = await self._get_git_info()
                                batch_results[batch_id]["commit_sha"] = batch_commit_sha
                                batch_results[batch_id]["modified_files"] = batch_modified_files

                                await self._update_batch_issues_resolved(
                                    batch, batch_commit_sha, branch_name, session_id
                                )

                                await emit_log(
                                    "INFO",
                                    f"{batch_id} committed: {batch_commit_sha[:7] if batch_commit_sha else 'unknown'}",
                                )

                                # Emit batch committed event
                                await safe_emit(
                                    FixProgressEvent(
                                        type=FixEventType.FIX_BATCH_COMMITTED,
                                        session_id=session_id,
                                        message=f"   💾 {batch_id} COMMITTED ({batch_commit_sha[:7] if batch_commit_sha else 'unknown'})",
                                        issue_ids=[i.id for i in batch],
                                        issue_codes=[i.issue_code for i in batch],
                                        commit_sha=batch_commit_sha,
                                    )
                                )
                                batch_commit_success = True
                        except Exception as e:
                            await emit_log(
                                "ERROR", f"Batch {batch_id} commit error: {str(e)[:100]}"
                            )

                        if batch_commit_success:
                            successful_issues.extend(batch)
                        else:
                            failed_issues.extend(batch)
                            batch_results[batch_id]["passed"] = False  # Mark as failed
                            await safe_emit(
                                FixProgressEvent(
                                    type=FixEventType.FIX_BATCH_FAILED,
                                    session_id=session_id,
                                    message=f"   ❌ {batch_id} commit failed",
                                    issue_ids=[i.id for i in batch],
                                    issue_codes=[i.issue_code for i in batch],
                                    error="Git commit failed",
                                )
                            )

                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_CHALLENGER_APPROVED,
                                session_id=session_id,
                                message=f"   ✅ {batch_id} PASSED ({score}/100)",
                                issue_ids=[i.id for i in batch],
                                issue_codes=[i.issue_code for i in batch],
                            )
                        )
                    else:
                        batch_results[batch_id]["passed"] = False
                        all_passed_this_iteration = False
                        await emit_log(
                            "WARNING",
                            f"{batch_id} needs retry "
                            f"(score {score} < {self.satisfaction_threshold})",
                        )
                        if batch_type == "BE":
                            feedback_be = gemini_output
                        else:
                            feedback_fe = gemini_output
                        failed_msg = (
                            f", failed issues: {', '.join(failed_issue_codes)}"
                            if failed_issue_codes
                            else ""
                        )
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_REGENERATING,
                                session_id=session_id,
                                message=f"   ⚠️ {batch_id} NEEDS RETRY "
                                f"({score} < {self.satisfaction_threshold}){failed_msg}",
                            )
                        )

                passed_batches = [b for b, r in batch_results.items() if r["passed"]]
                failed_batches = [b for b, r in batch_results.items() if not r["passed"]]

                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_STREAMING,
                        session_id=session_id,
                        message=f"══════ Iteration {iteration} Complete ══════\n"
                        f"✅ Passed: {len(passed_batches)} batches | "
                        f"⚠️ Failed: {len(failed_batches)} batches",
                    )
                )

                # Save logs after each iteration so we have partial data if session crashes
                await self._save_fix_log_to_s3(
                    session_id,
                    result,
                    issues,
                    last_gemini_output,
                    claude_prompts=claude_prompts,
                    gemini_prompt=gemini_prompt,
                    batch_results=batch_results,
                    current_iteration=iteration,
                    is_partial=True,  # Still in progress
                )

                if all_passed_this_iteration:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_CHALLENGER_APPROVED,
                            session_id=session_id,
                            message="🎉 All batches passed! No more retries needed.",
                        )
                    )
                    break

            for _batch_id, batch_data in batch_results.items():
                if not batch_data["passed"]:
                    failed_issues.extend(batch_data["issues"])
                    # Emit FIX_BATCH_FAILED for UI
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_BATCH_FAILED,
                            session_id=session_id,
                            message=f"   ❌ {_batch_id} FAILED after {self.max_iterations} retries",
                            issue_ids=[i.id for i in batch_data["issues"]],
                            issue_codes=[i.issue_code for i in batch_data["issues"]],
                            error=f"Score {batch_data.get('score', 0)} < {self.satisfaction_threshold}",
                        )
                    )

            # NOTE: Workspace scope validation now happens BEFORE each batch commit (in the loop above)

            # Step 3: Commits already done per-batch (atomic commits)

            # Step 4: Collect results from batch commits
            fix_explanation = self._build_fix_explanation(successful_issues, last_gemini_output)

            actually_fixed_count = len(successful_issues)
            failed_count = len(failed_issues)

            logger.info(
                f"Fix results: {actually_fixed_count} successful, "
                f"{failed_count} failed (based on batch_results)"
            )

            for issue in successful_issues:
                issue_file = str(issue.file)
                fix_code = await self._get_diff_for_file(issue_file)

                issue_commit_sha = None
                issue_modified_files: list[str] = []
                issue_codes_for_msg = str(issue.issue_code)
                for _batch_id, data in batch_results.items():
                    if issue in data.get("issues", []):
                        issue_commit_sha = data.get("commit_sha")
                        issue_modified_files = data.get("modified_files", [])
                        issue_codes_for_msg = ", ".join(
                            str(i.issue_code) for i in data.get("issues", [])
                        )
                        break

                issue_result = IssueFixResult(
                    issue_id=str(issue.id),
                    issue_code=str(issue.issue_code),
                    status=FixStatus.COMPLETED,
                    commit_sha=issue_commit_sha,
                    commit_message=f"[FIX] {issue_codes_for_msg}",
                    changes_made=f"Fixed {issue.title}",
                    fix_code=fix_code,
                    fix_explanation=fix_explanation,
                    fix_files_modified=issue_modified_files,
                    started_at=result.started_at,
                    completed_at=datetime.utcnow(),
                )
                result.results.append(issue_result)

            for issue in failed_issues:
                batch_info = ""
                for batch_id, data in batch_results.items():
                    if issue in data.get("issues", []):
                        batch_info = f" (batch {batch_id}, score: {data.get('score', 'N/A')})"
                        break

                logger.warning(f"Issue {issue.issue_code} batch failed Gemini review{batch_info}")
                issue_result = IssueFixResult(
                    issue_id=str(issue.id),
                    issue_code=str(issue.issue_code),
                    status=FixStatus.FAILED,
                    error=f"Batch did not pass Gemini review "
                    f"(score < {self.satisfaction_threshold}){batch_info}",
                    started_at=result.started_at,
                    completed_at=datetime.utcnow(),
                )
                result.results.append(issue_result)

            result.status = FixStatus.COMPLETED if actually_fixed_count > 0 else FixStatus.FAILED
            result.issues_fixed = actually_fixed_count
            result.issues_failed = failed_count
            result.completed_at = datetime.utcnow()

            await safe_emit(
                FixProgressEvent(
                    type=FixEventType.FIX_SESSION_COMPLETED,
                    session_id=session_id,
                    branch_name=branch_name,
                    issues_fixed=result.issues_fixed,
                    issues_failed=result.issues_failed,
                    message=f"Fixed {actually_fixed_count}/{len(issues)} issues"
                    + (f" ({failed_count} failed Gemini review)" if failed_count > 0 else ""),
                )
            )

            # Save fix log to S3 for debugging (10 day retention)
            await self._save_fix_log_to_s3(
                session_id,
                result,
                issues,
                last_gemini_output,
                claude_prompts=claude_prompts,
                gemini_prompt=gemini_prompt,
                batch_results=batch_results,
                current_iteration=None,  # Completed
                is_partial=False,  # Session complete
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

    def _build_review_prompt_per_batch(
        self,
        issues: list[Issue],
        batch_type: str,
        batch_idx: int,
        workspace_path: str | None = None,
    ) -> str:
        """Build review prompt for a single batch with per-issue scoring.

        Args:
            issues: Issues in this batch
            batch_type: "BE" or "FE"
            batch_idx: Batch number (1-indexed)
            workspace_path: Monorepo workspace restriction (e.g., "packages/frontend")

        Returns:
            Prompt asking Gemini to score EACH issue individually
        """
        agent_prompt = self._get_challenger_prompt()

        # Build detailed issue context
        issue_details = []
        issue_codes = []
        for issue in issues:
            issue_codes.append(str(issue.issue_code))
            detail = f"""### {issue.issue_code}: {issue.title}
- **File**: {issue.file}
- **Severity**: {issue.severity}
- **Category**: {issue.category}
- **Description**: {issue.description}"""
            if issue.suggested_fix:
                detail += f"\n- **Suggested Fix**: {issue.suggested_fix}"
            if issue.current_code:
                detail += f"\n- **Problematic Code**:\n```\n{issue.current_code}\n```"
            issue_details.append(detail)

        issues_section = "\n\n".join(issue_details)
        issue_codes_list = ", ".join(issue_codes)

        # Add workspace scope check if set
        workspace_check = ""
        if workspace_path:
            workspace_check = f"""

This is a MONOREPO with restricted workspace: `{workspace_path}/`

**CRITICAL**: When reviewing `git diff`, verify that ALL modified files
are within the workspace scope.
If any files outside `{workspace_path}/` were modified, this is a CRITICAL failure - score 0.

"""

        task = f"""
{workspace_check}

{issues_section}

1. Run `git diff` to see the changes made for these {len(issues)} issues
2. For EACH issue, evaluate if the fix correctly addresses the problem
3. Check for bugs, security issues, or breaking changes
4. Give a score (0-100) for EACH issue

## Output Format (CRITICAL - follow exactly!)

Start with the OVERALL batch score:
BATCH_SCORE: <number>

Then list EACH issue with its individual score:
ISSUE_SCORES:
- {issue_codes_list.split(", ")[0] if issue_codes else "ISSUE-XXX"}: <score> | <brief reason>
{chr(10).join(f"- {code}: <score> | <brief reason>" for code in issue_codes[1:])}
{" " if len(issue_codes) > 1 else ""}

Issues with score < 95 need to be re-fixed in the next iteration.
List which specific issues FAILED (score < 95):
FAILED_ISSUES: <comma-separated issue codes, or "none">
"""

        return f"{agent_prompt}\n\n---\n\n{task}"

    def _parse_batch_review(
        self, output: str, issues: list[Issue]
    ) -> tuple[float, list[str], dict[str, float], dict[str, int]]:
        """Parse Gemini's per-batch review output.

        Args:
            output: Gemini's response
            issues: Issues in this batch

        Returns:
            Tuple of (batch_score, failed_issue_codes, per_issue_scores, quality_scores)
        """
        batch_score = 70.0  # default
        failed_issues: list[str] = []
        per_issue_scores: dict[str, float] = {}
        quality_scores: dict[str, int] = {}

        json_match = re.search(r"```json\s*([\s\S]*?)```", output)
        if json_match:
            try:
                review_data = json.loads(json_match.group(1))
                # Extract quality_scores from JSON
                if "quality_scores" in review_data:
                    quality_scores = review_data["quality_scores"]
                    logger.info(f"Parsed quality_scores: {quality_scores}")
                if "satisfaction_score" in review_data:
                    batch_score = float(review_data["satisfaction_score"])
                    logger.info(f"Parsed satisfaction_score from JSON: {batch_score}")
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse JSON block: {e}")

        match = re.search(r"BATCH_SCORE:\s*(\d+)", output, re.IGNORECASE)
        if match:
            batch_score = float(match.group(1))
            logger.info(f"Parsed BATCH_SCORE: {batch_score}")
        elif not quality_scores:  # Only use old fallback if no JSON parsed
            # Fallback to old SCORE pattern
            match = re.search(r"SCORE:\s*(\d+)", output, re.IGNORECASE)
            if match:
                batch_score = float(match.group(1))
                logger.info(f"Parsed SCORE (fallback): {batch_score}")

        for issue in issues:
            code = str(issue.issue_code)
            pattern = rf"-\s*{re.escape(code)}:\s*(\d+)"
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                per_issue_scores[code] = float(match.group(1))
                logger.debug(f"Issue {code}: score {per_issue_scores[code]}")

        match = re.search(r"FAILED_ISSUES:\s*(.+?)(?:\n|$)", output, re.IGNORECASE)
        if match:
            failed_text = match.group(1).strip().lower()
            if failed_text != "none" and failed_text:
                # Extract issue codes (format: ISSUE-123, ISSUE-456)
                failed_issues = [
                    code.strip().upper()
                    for code in re.findall(r"[A-Z]+-\d+", match.group(1), re.IGNORECASE)
                ]
                logger.info(f"Parsed FAILED_ISSUES: {failed_issues}")

        if not failed_issues and per_issue_scores:
            failed_issues = [
                code
                for code, score in per_issue_scores.items()
                if score < self.satisfaction_threshold
            ]
            if failed_issues:
                logger.info(f"Derived FAILED_ISSUES from scores: {failed_issues}")

        return batch_score, failed_issues, per_issue_scores, quality_scores

    def _load_structure_doc(self, workspace_path: str | None = None) -> str | None:
        """Load structure documentation for context.

        Args:
            workspace_path: Optional monorepo workspace path

        Returns:
            Structure documentation content, or None if not found
        """
        return load_structure_documentation(self.repo_path, workspace_path)

    def _build_fix_prompt(
        self,
        issues: list[Issue],
        agent_type: str,
        feedback: str,
        iteration: int,
        workspace_path: str | None = None,
        user_notes: str | None = None,
    ) -> str:
        """Build prompt for Claude CLI to fix issues.

        Args:
            issues: List of issues to fix (all same type: BE or FE)
            agent_type: "be" or "fe"
            feedback: Feedback from previous iteration
            iteration: Current iteration number
            workspace_path: Monorepo workspace restriction (e.g., "packages/frontend")
            user_notes: User-provided notes with additional context or instructions
        """
        if agent_type == "fe":
            agent_prompt = self._get_fixer_prompt_fe()
        else:
            agent_prompt = self._get_fixer_prompt_be()

        # Build task with all issues
        task_parts = ["# Task: Fix Code Issues\n"]

        structure_doc = self._load_structure_doc(workspace_path)
        if structure_doc:
            if structure_doc.strip().startswith("<?xml"):
                task_parts.append(
                    f"""

Use this structure documentation to understand the codebase architecture:

<repository-structure>
{structure_doc}
</repository-structure>

---
"""
                )
            else:
                task_parts.append(
                    f"""

Use this structure documentation to understand the codebase architecture:

{structure_doc}

---
"""
                )

        if workspace_path:
            task_parts.append(
                f"""

**CRITICAL**: This is a MONOREPO. You are ONLY allowed to modify files within:
```
{workspace_path}/
```

DO NOT modify any files outside this folder. If a fix requires changes outside this scope:
1. STOP and explain what additional changes would be needed
2. Do NOT attempt to modify files outside the workspace
3. The system will BLOCK and REVERT any changes outside the workspace

---
"""
            )

        if user_notes:
            task_parts.append(
                f"""

The developer has provided the following additional context and instructions:

<user-notes>
{user_notes}
</user-notes>

**Take these notes into account when implementing the fixes.**

---
"""
            )

        for _i, issue in enumerate(issues, 1):
            code_snippet = self._get_code_snippet(issue, context_lines=5)

            # Build location info
            if issue.line and issue.end_line and issue.line != issue.end_line:
                location = f"Lines {issue.line}-{issue.end_line}"
            elif issue.line:
                location = f"Line {issue.line}"
            else:
                location = "Location not specified"

            task_parts.append(
                f"""
**Title**: {issue.title}
**Severity**: {issue.severity}
**Category**: {issue.category}
**File**: {issue.file}
**Location**: {location}

{issue.description}

```
{code_snippet or f"[No snippet available - read {issue.file}]"}
```

{issue.suggested_fix or "Use your best judgment based on the issue description"}

---
"""
            )

        task_parts.append(
            """
1. Read the files to understand context
2. Make the fixes - one by one
3. Keep changes minimal
4. Do NOT commit - just fix the code
"""
        )

        if feedback and iteration > 1:
            task_parts.append(
                f"""
The reviewer found issues with the previous fix. Address this feedback:

{feedback}
"""
            )

        task = "\n".join(task_parts)

        return f"{agent_prompt}\n\n---\n\n{task}"

    def _parse_score(self, output: str) -> float:
        """Extract score from Gemini output."""
        match = re.search(r"SCORE:\s*(\d+)", output, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            logger.info(f"Parsed SCORE: {score}")
            return score

        match = re.search(r'"satisfaction_score"\s*:\s*(\d+)', output)
        if match:
            score = float(match.group(1))
            logger.info(f"Parsed satisfaction_score from JSON: {score}")
            return score

        # Fallback: look for any number followed by /100
        match = re.search(r"(\d+)\s*/\s*100", output)
        if match:
            score = float(match.group(1))
            logger.info(f"Parsed XX/100: {score}")
            return score

        logger.warning(
            f"Could not parse score from Gemini output, defaulting to 70. Output: {output[:500]}"
        )
        return 70.0

    def _get_claude_cli(self, timeout: int = CLAUDE_CLI_TIMEOUT, model: str = "opus") -> ClaudeCLI:
        """Create ClaudeCLI instance for fix operations."""
        return ClaudeCLI(
            working_dir=self.repo_path,
            model=model,
            timeout=timeout,
            s3_prefix="fix",
            github_token=self._get_github_token(),
            tools="fix",  # Limit tools to reduce system prompt size
        )

    async def _run_claude_cli(
        self,
        prompt: str,
        timeout: int = CLAUDE_CLI_TIMEOUT,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        thinking_budget: int | None = None,
        model: str = "opus",
        session_context: FixSessionContext | None = None,
        parent_session_id: str | None = None,
        agent_type: str | None = None,
    ) -> ClaudeCLIResult:
        """Run Claude CLI with prompt and optional streaming callback.

        Uses the centralized ClaudeCLI utility for execution.
        Supports session persistence via session_context.
        Each call creates its own Operation for atomic tracking.

        Args:
            prompt: The prompt to send to Claude
            timeout: Timeout in seconds
            on_chunk: Callback for streaming chunks
            thinking_budget: Override thinking budget (None = use default from config)
            model: Model alias (opus, sonnet, haiku)
            session_context: Optional session context for persistence between batches
            parent_session_id: Parent session ID for linking sub-operations
            agent_type: Type of agent (fixer, committer, branch_creator) for tracking
        """
        # Check if compaction is needed before this call (based on context_size = cache_read)
        if session_context and session_context.needs_compaction():
            await self._compact_context(session_context, on_chunk, parent_session_id)

        cli = self._get_claude_cli(timeout, model)

        async def on_stderr(line: str) -> None:
            if on_chunk:
                print(f"[CLAUDE FIX STDERR] {line}", flush=True)
                await on_chunk(f"[stderr] {line}\n")

        # Run with the centralized utility
        # Each CLI call creates its own Operation for atomic tracking
        result = await cli.run(
            prompt,
            operation_type="fix",
            repo_name=self.repo_path.name,
            context_id=f"fix_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            thinking_budget=thinking_budget,
            save_prompt=True,
            save_output=True,
            save_thinking=True,
            on_chunk=on_chunk,
            on_stderr=on_stderr,
            track_operation=True,  # Atomic tracking at leaf level
            operation_details={
                "parent_session_id": parent_session_id,
                "agent_type": agent_type or "fixer",
            },
            resume_session_id=session_context.claude_session_id if session_context else None,
        )

        if session_context and result.success:
            session_context.claude_session_id = result.session_id
            for usage in result.model_usage:
                session_context.cumulative_input_tokens += usage.input_tokens
                session_context.cumulative_output_tokens += usage.output_tokens
                session_context.last_cache_read_tokens = usage.cache_read_tokens
                session_context.last_cache_creation_tokens = usage.cache_creation_tokens

            logger.info(
                f"[FIX] Session {result.session_id[:8] if result.session_id else 'N/A'}... | "
                f"Context size: {session_context.context_size:,} / {MAX_SESSION_TOKENS:,} tokens"
            )

        # NOTE: Operation tracking is now handled atomically by ClaudeCLI.run()

        if not result.success:
            # Check for billing errors
            if result.error:
                billing_keywords = [
                    "credit balance",
                    "billing",
                    "payment",
                    "insufficient funds",
                    "quota exceeded",
                    "rate limit",
                ]
                if any(kw in result.error.lower() for kw in billing_keywords):
                    logger.error(f"Claude CLI billing error: {result.error}")
                    raise BillingError(result.error)

            logger.error(f"Claude CLI failed: {result.error}")
            return result

        for usage in result.model_usage:
            logger.info(
                f"  {usage.model}: in={usage.input_tokens}, "
                f"out={usage.output_tokens}, cost=${usage.cost_usd:.4f}"
            )

        return result

    async def _compact_context(
        self,
        session_context: FixSessionContext,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        parent_session_id: str | None = None,
    ) -> None:
        """Compact session context using Claude's /compact slash command.

        Uses the EXISTING Claude session (with --resume) and sends /compact
        which triggers Claude's built-in context compaction. The session_id
        remains the same - only the context gets compressed.

        After compaction, cache_read_tokens in the next request will show
        the new (smaller) context size.
        """
        logger.info(
            f"[FIX] Context compaction triggered at context_size={session_context.context_size:,} tokens"
        )

        if on_chunk:
            await on_chunk(
                f"\n🔄 **Context Compaction** | "
                f"context size {session_context.context_size:,} tokens reached limit, "
                f"running /compact...\n"
            )

        cli = self._get_claude_cli(timeout=120)  # May take time to compact

        result = await cli.run(
            "/compact",  # Claude's slash command for context compaction
            operation_type="compaction",
            repo_name=self.repo_path.name,
            context_id=f"compaction_{session_context.compaction_count}",
            save_prompt=False,
            save_output=True,
            save_thinking=False,
            on_chunk=on_chunk,
            track_operation=True,  # Atomic tracking at leaf level
            operation_details={
                "parent_session_id": parent_session_id,
                "agent_type": "compaction",
            },
            resume_session_id=session_context.claude_session_id,  # Same session!
        )

        if result.success:
            session_context.cumulative_input_tokens = 0
            session_context.cumulative_output_tokens = 0
            session_context.last_cache_read_tokens = 0  # Will be updated by next request
            session_context.last_cache_creation_tokens = 0
            session_context.compaction_count += 1

            logger.info(
                f"[FIX] Context compacted (#{session_context.compaction_count}), "
                f"session continues: {session_context.claude_session_id[:8] if session_context.claude_session_id else 'N/A'}..."
            )

            if on_chunk:
                await on_chunk(
                    f"\n✅ Context compacted (#{session_context.compaction_count}), "
                    f"session continues\n\n"
                )
        else:
            logger.warning(f"[FIX] Compaction failed: {result.error}")
            if on_chunk:
                await on_chunk(f"⚠️ Compaction failed: {result.error}, continuing anyway\n")

    # NOTE: _run_gemini_cli method moved to turbowrap.orchestration.cli_runner.GeminiCLI

    async def _get_git_info(self) -> tuple[str | None, list[str], str | None]:
        """Get git info after commit.

        Returns:
            Tuple of (commit_sha, modified_files, diff_content)
        """
        commit_sha = None
        modified_files: list[str] = []
        diff_content = None

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "rev-parse",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                commit_sha = stdout.decode().strip()[:40]

            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                modified_files = [
                    f.strip() for f in stdout.decode().strip().split("\n") if f.strip()
                ]

            proc = await asyncio.create_subprocess_exec(
                "git",
                "show",
                "--stat",
                "--format=",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                diff_content = stdout.decode()[:2000]

        except Exception as e:
            logger.warning(f"Failed to get git info: {e}")

        return commit_sha, modified_files, diff_content

    async def _get_diff_for_file(self, file_path: str) -> str | None:
        """Get diff for a specific file from last commit.

        Returns:
            Diff content (max 500 chars for display)
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "show",
                "--format=",
                "HEAD",
                "--",
                file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                diff = stdout.decode()
                # Extract just the added lines (+ prefix)
                added_lines = [
                    line[1:]
                    for line in diff.split("\n")
                    if line.startswith("+") and not line.startswith("+++")
                ]
                return "\n".join(added_lines)[:500]
        except Exception as e:
            logger.warning(f"Failed to get diff for {file_path}: {e}")
        return None

    async def _get_uncommitted_files(self) -> list[str]:
        """Get list of all uncommitted files (staged, unstaged, and untracked).

        Returns:
            List of file paths relative to repo root
        """
        all_files: set[str] = set()

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "--cached",
                "--name-only",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                staged = [f.strip() for f in stdout.decode().strip().split("\n") if f.strip()]
                all_files.update(staged)
                if staged:
                    logger.debug(f"Staged files: {staged}")

            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "--name-only",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                unstaged = [f.strip() for f in stdout.decode().strip().split("\n") if f.strip()]
                all_files.update(unstaged)
                if unstaged:
                    logger.debug(f"Unstaged files: {unstaged}")

            # 3. Untracked files (git ls-files --others --exclude-standard)
            proc = await asyncio.create_subprocess_exec(
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                untracked = [f.strip() for f in stdout.decode().strip().split("\n") if f.strip()]
                all_files.update(untracked)
                if untracked:
                    logger.debug(f"Untracked files: {untracked}")

        except Exception as e:
            logger.warning(f"Failed to get uncommitted files: {e}")

        return list(all_files)

    def _validate_workspace_scope(
        self,
        modified_files: list[str],
        workspace_path: str,
        allowed_extra_paths: list[str] | None = None,
    ) -> list[str]:
        """Validate that all modified files are within the workspace scope.

        Args:
            modified_files: List of modified file paths (relative to repo root)
            workspace_path: Allowed workspace path (e.g., "packages/frontend")
            allowed_extra_paths: Additional allowed paths (e.g., ["frontend/", "shared/"])

        Returns:
            List of files that are OUTSIDE the workspace scope (violations)
        """
        if not workspace_path:
            return []

        # Build list of allowed paths
        allowed = [workspace_path.rstrip("/")]
        if allowed_extra_paths:
            allowed.extend(p.rstrip("/") for p in allowed_extra_paths)

        violations: list[str] = []

        for file_path in modified_files:
            if file_path.startswith("."):
                continue

            # Check if file is within any allowed path
            is_allowed = any(file_path.startswith(p + "/") or file_path == p for p in allowed)
            if not is_allowed:
                violations.append(file_path)
                logger.warning(f"File outside workspace scope: {file_path} (allowed: {allowed})")

        return violations

    async def _add_allowed_paths(self, repo_id: str, new_paths: set[str]) -> None:
        """Add paths to the repository's allowed_extra_paths in the database.

        Called when user approves scope violation during fix.

        Args:
            repo_id: Repository ID
            new_paths: Set of paths to add (e.g., {"frontend/", "shared/"})
        """
        from turbowrap.db.models import Repository
        from turbowrap.db.session import get_session_local

        def update_db() -> None:
            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                repo = db.query(Repository).filter(Repository.id == repo_id).first()
                if repo:
                    current: list[str] = repo.allowed_extra_paths or []  # type: ignore[assignment]
                    updated = list(set(current) | new_paths)
                    repo.allowed_extra_paths = updated  # type: ignore[assignment]
                    db.commit()
                    logger.info(f"Updated allowed_extra_paths for {repo_id}: {updated}")
            finally:
                db.close()

        # Run in thread pool to avoid blocking async loop
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_db)

    async def _update_batch_issues_resolved(
        self,
        issues: list[Issue],
        commit_sha: str | None,
        branch_name: str,
        session_id: str,
    ) -> None:
        """Update issues to RESOLVED after successful batch commit.

        Uses same pattern as _update_allowed_extra_paths - runs DB update
        in thread pool to avoid blocking async loop.

        Args:
            issues: Issues in this batch
            commit_sha: Git commit SHA
            branch_name: Branch name for the fix
            session_id: Fix session ID
        """
        from datetime import datetime

        from turbowrap.db.models import Issue as IssueModel
        from turbowrap.db.models import IssueStatus
        from turbowrap.db.session import get_session_local

        def update_db() -> None:
            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                for issue in issues:
                    db_issue = db.query(IssueModel).filter(IssueModel.id == issue.id).first()
                    if db_issue:
                        db_issue.status = IssueStatus.RESOLVED.value  # type: ignore[assignment]
                        db_issue.resolution_note = (  # type: ignore[assignment]
                            f"Fixed in commit {commit_sha[:7]}" if commit_sha else "Fixed"
                        )
                        db_issue.fix_commit_sha = commit_sha  # type: ignore[assignment]
                        db_issue.fix_branch = branch_name  # type: ignore[assignment]
                        db_issue.fix_session_id = session_id  # type: ignore[assignment]
                        db_issue.resolved_at = datetime.utcnow()  # type: ignore[assignment]
                        db_issue.fixed_at = datetime.utcnow()  # type: ignore[assignment]
                        db_issue.fixed_by = "fixer_claude"  # type: ignore[assignment]
                db.commit()
                logger.info(
                    f"Updated {len(issues)} issues to RESOLVED (commit {commit_sha[:7] if commit_sha else 'unknown'})"
                )
            finally:
                db.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_db)

    async def _revert_uncommitted_changes(self) -> bool:
        """Revert all uncommitted changes (staged, unstaged, and untracked).

        This is a hard reset to clean state:
        1. git reset HEAD -- . (unstage all)
        2. git checkout -- . (discard modifications)
        3. git clean -fd (remove untracked files)

        Returns:
            True if revert succeeded, False otherwise
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "reset",
                "HEAD",
                "--",
                ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            await proc.communicate()
            logger.info("git reset HEAD -- . completed")

            # 2. Discard all modifications to tracked files
            proc = await asyncio.create_subprocess_exec(
                "git",
                "checkout",
                "--",
                ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            await proc.communicate()
            logger.info("git checkout -- . completed")

            # 3. Remove untracked files and directories
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clean",
                "-fd",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                cleaned = stdout.decode().strip()
                if cleaned:
                    logger.info(f"git clean -fd output: {cleaned}")

            logger.info("All uncommitted changes reverted")
            return True

        except Exception as e:
            logger.error(f"Failed to revert uncommitted changes: {e}")
            return False

    def _build_fix_explanation(
        self,
        issues: list[Issue],
        gemini_output: str | None,
    ) -> str:
        """Build fix explanation from issues and Gemini review.

        Returns:
            PR-style explanation of the fix
        """
        parts = []

        parts.append("## Changes Made\n")
        for issue in issues:
            parts.append(f"- **{issue.issue_code}**: {issue.title}\n")

        if gemini_output:
            # Extract key points from Gemini output
            parts.append("\n## Review Summary\n")
            summary = gemini_output[:500]
            if len(gemini_output) > 500:
                summary += "..."
            parts.append(summary)

        return "".join(parts)

    async def _save_fix_log_to_s3(
        self,
        session_id: str,
        result: FixSessionResult,
        issues: list[Issue],
        gemini_output: str | None,
        claude_prompts: list[dict[str, Any]] | None = None,
        gemini_prompt: str | None = None,
        batch_results: dict[str, dict[str, Any]] | None = None,
        current_iteration: int | None = None,
        is_partial: bool = False,
    ) -> str | None:
        """
        Save fix session log to S3 for debugging.

        Path: s3://turbowrap-thinking/fix-logs/{date}/{session_id}.json
        Retention: 10 days (configured via S3 lifecycle)

        Args:
            session_id: Fix session ID
            result: Current FixSessionResult (may be partial)
            issues: All issues being fixed
            gemini_output: Last Gemini review output
            claude_prompts: Claude prompts sent (for debugging)
            gemini_prompt: Gemini prompt template
            batch_results: Current batch results state (for incremental saves)
            current_iteration: Current iteration number (for incremental saves)
            is_partial: True if this is an incremental save (session still in progress)

        Returns:
            S3 URL if saved, None if failed
        """
        try:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            s3_key = f"fix-logs/{date_str}/{session_id}.json"

            # Build log content
            log_data = {
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "status": result.status.value,
                "branch_name": result.branch_name,
                "issues_requested": result.issues_requested,
                "issues_fixed": result.issues_fixed,
                "repo_path": str(self.repo_path),
                "max_iterations": self.max_iterations,
                "satisfaction_threshold": self.satisfaction_threshold,
                "is_partial": is_partial,
                "current_iteration": current_iteration,
                "issues": [
                    {
                        "id": issue.id,
                        "code": issue.issue_code,
                        "title": issue.title,
                        "file": issue.file,
                        "severity": issue.severity,
                    }
                    for issue in issues
                ],
                "results": [
                    {
                        "issue_id": r.issue_id,
                        "status": r.status.value,
                        "commit_sha": r.commit_sha,
                        "fix_code": r.fix_code,
                        "fix_explanation": r.fix_explanation,
                        "fix_files_modified": r.fix_files_modified,
                        "error": r.error,
                    }
                    for r in result.results
                ],
                "gemini_review": gemini_output[:2000] if gemini_output else None,
                "claude_prompts": claude_prompts or [],
                "gemini_prompt": gemini_prompt,
                "batch_results": (
                    {
                        batch_id: {
                            "passed": data["passed"],
                            "score": data["score"],
                            "failed_issues": data.get("failed_issues", []),
                            "issue_codes": [i.issue_code for i in data.get("issues", [])],
                        }
                        for batch_id, data in (batch_results or {}).items()
                    }
                    if batch_results
                    else None
                ),
            }

            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.put_object(
                    Bucket=self.s3_bucket,
                    Key=s3_key,
                    Body=json.dumps(log_data, indent=2, default=str).encode("utf-8"),
                    ContentType="application/json",
                ),
            )

            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"Fix log saved to {s3_url}")
            return s3_url

        except ClientError as e:
            logger.warning(f"Failed to save fix log to S3: {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to save fix log to S3: {e}")
            return None
