"""
Fix Orchestrator for TurboWrap.

Coordinates Claude CLI (fixer) and Gemini CLI (reviewer).
Both CLIs have full access to the system - they do ALL the work.

Uses the centralized ClaudeCLI utility for Claude CLI subprocess execution.
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
    ScopeValidationError,
)
from turbowrap.utils.aws_secrets import get_google_api_key
from turbowrap.utils.claude_cli import ClaudeCLI

# S3 bucket for fix logs (same as thinking logs)
S3_BUCKET = "turbowrap-thinking"

logger = logging.getLogger(__name__)


class BillingError(Exception):
    """Raised when Claude CLI returns a billing/credit error."""

    pass


# Agent file paths
AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "agents"
FIXER_AGENT = AGENTS_DIR / "fixer.md"
FIX_CHALLENGER_AGENT = AGENTS_DIR / "fix_challenger.md"
DEV_BE_AGENT = AGENTS_DIR / "dev_be.md"
DEV_FE_AGENT = AGENTS_DIR / "dev_fe.md"
ENGINEERING_PRINCIPLES = AGENTS_DIR / "engineering_principles.md"
GIT_BRANCH_CREATOR_AGENT = AGENTS_DIR / "git_branch_creator.md"
GIT_COMMITTER_AGENT = AGENTS_DIR / "git_committer.md"

# File extensions for frontend vs backend
FRONTEND_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".html", ".vue", ".svelte"}
BACKEND_EXTENSIONS = {".py", ".go", ".java", ".rb", ".php", ".rs", ".c", ".cpp", ".h"}

# Type for progress callback
ProgressCallback = Callable[[FixProgressEvent], Awaitable[None]]

# Timeouts
CLAUDE_CLI_TIMEOUT = 900  # 15 minutes per fix
GEMINI_CLI_TIMEOUT = 120  # 2 minutes per review

# Parallelism limits - prevent macOS file watcher exhaustion (EOPNOTSUPP)
# Sequential execution: first all BE issues, then all FE issues (not parallel)
# This avoids file watcher limit issues on macOS

# Issue batching - don't overload a single Claude CLI with too many issues
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

        # Get challenger settings from config
        fix_config = self.settings.fix_challenger
        self.max_iterations = fix_config.max_iterations  # default 3
        self.satisfaction_threshold = fix_config.satisfaction_threshold  # default 95.0

        # Load agent prompts
        self._agent_cache: dict[str, str] = {}

        # S3 client for logging
        self.s3_client = boto3.client("s3")
        self.s3_bucket = S3_BUCKET

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

    def _get_code_snippet(self, issue: Issue, context_lines: int = 5) -> str:
        """Extract code snippet from file around the issue location.

        Args:
            issue: The issue with file path and line numbers
            context_lines: Number of lines to show before/after the issue

        Returns:
            Code snippet with line numbers, or empty string if file not found
        """
        if issue.current_code:
            # Already have the code, return it with line info
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

            start_line = max(1, issue.line - context_lines)
            end_line = min(len(lines), (issue.end_line or issue.line) + context_lines)

            snippet_lines = []
            for i in range(start_line - 1, end_line):
                line_num = i + 1
                marker = (
                    ">>>" if issue.line <= line_num <= (issue.end_line or issue.line) else "   "
                )
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
                # Create new branch from main (using agent)
                branch_creator_prompt = self._load_agent(GIT_BRANCH_CREATOR_AGENT)
                branch_creator_prompt = branch_creator_prompt.replace("{branch_name}", branch_name)
                await self._run_claude_cli(branch_creator_prompt, timeout=60)

            feedback_be = ""
            feedback_fe = ""
            last_gemini_output: str | None = None  # Store for fix explanation

            # Collect prompts for S3 logging
            claude_prompts: list[dict] = []  # [{type: "be"|"fe", batch: N, prompt: str}]
            gemini_prompt: str | None = None

            # Helper functions for batch processing
            def get_issue_workload(issue: Issue) -> int:
                """Calculate workload points for an issue based on estimates."""
                effort = issue.estimated_effort or DEFAULT_EFFORT
                files = issue.estimated_files_count or DEFAULT_FILES
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

            # Calculate ALL batches upfront (once, before iterations)
            all_be_batches = batch_issues_by_workload(be_issues) if has_be else []
            all_fe_batches = batch_issues_by_workload(fe_issues) if has_fe else []
            len(all_be_batches) + len(all_fe_batches)

            # Track batch results across iterations
            # Key: "BE-1", "FE-2", etc. Value: {"passed": bool, "score": float, "failed_issues": list}
            batch_results: dict[str, dict] = {}
            for idx in range(len(all_be_batches)):
                batch_results[f"BE-{idx+1}"] = {
                    "passed": False,
                    "score": 0.0,
                    "failed_issues": [],
                    "issues": all_be_batches[idx],
                }
            for idx in range(len(all_fe_batches)):
                batch_results[f"FE-{idx+1}"] = {
                    "passed": False,
                    "score": 0.0,
                    "failed_issues": [],
                    "issues": all_fe_batches[idx],
                }

            # Track all issues that have been successfully fixed
            successful_issues: list[Issue] = []
            failed_issues: list[Issue] = []

            for iteration in range(1, self.max_iterations + 1):
                # Determine which batches to process this iteration
                if iteration == 1:
                    # First iteration: process ALL batches
                    batches_to_process = list(batch_results.keys())
                else:
                    # Subsequent iterations: only retry FAILED batches
                    batches_to_process = [
                        batch_id
                        for batch_id, result in batch_results.items()
                        if not result["passed"]
                    ]

                if not batches_to_process:
                    logger.info("All batches passed, no more retries needed")
                    break

                # Show iteration plan
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
                            message=f"══════ Iteration {iteration}/{self.max_iterations} ══════\n📋 Retrying FAILED batches: {failed_batch_ids}",
                        )
                    )
                else:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_GENERATING,
                            session_id=session_id,
                            message=f"══════ Iteration {iteration}/{self.max_iterations} ══════\n📋 Plan: {plan_msg} ({len(batches_to_process)} total, 1 Gemini review per batch)",
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

                # Process each batch: Claude fix -> Gemini review (per batch)
                for batch_id in batches_to_process:
                    batch_type = "BE" if batch_id.startswith("BE") else "FE"
                    batch_idx = int(batch_id.split("-")[1])
                    batch = batch_results[batch_id]["issues"]
                    completed_batches += 1

                    # Get feedback for this batch from previous iteration
                    feedback = feedback_be if batch_type == "BE" else feedback_fe

                    # Create streaming callback for this batch
                    async def on_chunk_claude(chunk: str, bt=batch_type) -> None:
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_ISSUE_STREAMING,
                                session_id=session_id,
                                content=f"[{bt}] {chunk}",
                            )
                        )

                    batch_workload = sum(get_issue_workload(i) for i in batch)
                    issue_codes = ", ".join(str(i.issue_code) for i in batch)
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message=f"🔧 {batch_id} [{completed_batches}/{len(batches_to_process)}] | {len(batch)} issues, workload={batch_workload}\n   Issues: {issue_codes}",
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

                    # Calculate thinking budget based on workload
                    # Heavy batches (workload > 10) get more thinking budget for complex reasoning
                    thinking_budget = None
                    if batch_workload > 10:
                        # Scale: base 8k + 1k per workload point above 10, max 16k
                        base_budget = self.settings.thinking.budget_tokens
                        thinking_budget = min(16000, base_budget + (batch_workload - 10) * 1000)
                        logger.info(
                            f"Heavy batch (workload={batch_workload}), thinking budget: {thinking_budget}"
                        )
                        await emit_log(
                            "INFO", f"Heavy batch: thinking budget {thinking_budget} tokens"
                        )

                    try:
                        output = await self._run_claude_cli(
                            prompt, on_chunk=on_chunk_claude, thinking_budget=thinking_budget
                        )
                        if output is None:
                            logger.error(f"Claude CLI ({batch_id}) failed: returned None")
                            await emit_log("ERROR", f"Claude CLI failed for {batch_id}")
                            # Mark batch as failed
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
                                message=f"💳 BILLING ERROR: {e}\n\nRicarica il credito su console.anthropic.com",
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
                            message=f"   ✅ {batch_id} Claude fix complete, running Gemini review...",
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

                    gemini_output = await self._run_gemini_cli(
                        review_prompt, on_chunk=on_chunk_gemini
                    )
                    last_gemini_output = gemini_output

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

                    # Parse per-batch review
                    score, failed_issue_codes, per_issue_scores, quality_scores = (
                        self._parse_batch_review(gemini_output, batch)
                    )
                    batch_results[batch_id]["score"] = score
                    batch_results[batch_id]["failed_issues"] = failed_issue_codes

                    # Show per-issue scores and quality scores
                    if per_issue_scores:
                        scores_summary = " | ".join(
                            [f"{code}: {int(s)}" for code, s in per_issue_scores.items()]
                        )
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_CHALLENGER_RESULT,
                                session_id=session_id,
                                message=f"   📊 {batch_id} score: {score}/100 | Per-issue: {scores_summary}",
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
                        successful_issues.extend(batch)
                        await emit_log("INFO", f"{batch_id} passed with score {score}/100")
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_CHALLENGER_APPROVED,
                                session_id=session_id,
                                message=f"   ✅ {batch_id} PASSED ({score}/100)",
                                # Include issue IDs so frontend can mark chips green
                                issue_ids=[i.id for i in batch],
                                issue_codes=[i.issue_code for i in batch],
                            )
                        )
                    else:
                        batch_results[batch_id]["passed"] = False
                        all_passed_this_iteration = False
                        await emit_log(
                            "WARNING",
                            f"{batch_id} needs retry (score {score} < {self.satisfaction_threshold})",
                        )
                        # Store feedback for retry
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
                                message=f"   ⚠️ {batch_id} NEEDS RETRY ({score} < {self.satisfaction_threshold}){failed_msg}",
                            )
                        )

                # End of iteration summary
                passed_batches = [b for b, r in batch_results.items() if r["passed"]]
                failed_batches = [b for b, r in batch_results.items() if not r["passed"]]

                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_STREAMING,
                        session_id=session_id,
                        message=f"══════ Iteration {iteration} Complete ══════\n✅ Passed: {len(passed_batches)} batches | ⚠️ Failed: {len(failed_batches)} batches",
                    )
                )

                # ========== INCREMENTAL S3 SAVE ==========
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

            # After all iterations, collect failed issues from batches that never passed
            for _batch_id, batch_data in batch_results.items():
                if not batch_data["passed"]:
                    failed_issues.extend(batch_data["issues"])

            # ============== WORKSPACE SCOPE VALIDATION ==============
            # Before committing, validate that all modified files are within the workspace scope
            # This is a CRITICAL safety check for monorepos - prevents Claude from modifying
            # files outside the designated workspace folder
            if request.workspace_path:
                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_VALIDATING,
                        session_id=session_id,
                        message=f"🔒 Validating workspace scope: {request.workspace_path}",
                    )
                )

                # Get all uncommitted files (staged, unstaged, untracked)
                uncommitted_files = await self._get_uncommitted_files()
                logger.info(f"Uncommitted files: {uncommitted_files}")

                # Check for violations
                violations = self._validate_workspace_scope(
                    uncommitted_files, request.workspace_path
                )

                if violations:
                    # CRITICAL: Files modified outside workspace!
                    # Revert ALL changes and raise error
                    logger.error(
                        f"Workspace scope violation! Files outside '{request.workspace_path}': {violations}"
                    )

                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_SESSION_ERROR,
                            session_id=session_id,
                            error="🚫 BLOCKED: Modified files outside workspace scope",
                            message=f"Violations: {', '.join(violations[:5])}{'...' if len(violations) > 5 else ''}",
                        )
                    )

                    # Revert all changes
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message="⏪ Reverting all uncommitted changes...",
                        )
                    )
                    await self._revert_uncommitted_changes()

                    # Raise exception to abort
                    raise ScopeValidationError(violations, request.workspace_path)

                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_STREAMING,
                        session_id=session_id,
                        message=f"✅ Workspace scope validated ({len(uncommitted_files)} files in scope)",
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

            # Commit using agent
            commit_message = f"[FIX] {issue_codes}"
            commit_prompt = self._load_agent(GIT_COMMITTER_AGENT)
            commit_prompt = commit_prompt.replace("{commit_message}", commit_message)
            commit_prompt = commit_prompt.replace("{issue_codes}", issue_codes)
            await self._run_claude_cli(commit_prompt, timeout=30)

            # Step 4: Collect git info and build results
            commit_sha, modified_files, _ = await self._get_git_info()
            fix_explanation = self._build_fix_explanation(successful_issues, last_gemini_output)

            # Count issues based on batch_results (Gemini approval is the source of truth)
            # If Gemini approved a batch (score >= threshold), those issues are COMPLETED
            # This is more reliable than file-path matching which can fail with path format differences
            actually_fixed_count = len(successful_issues)
            failed_count = len(failed_issues)

            logger.info(
                f"Fix results: {actually_fixed_count} successful, {failed_count} failed (based on batch_results)"
            )
            logger.info(f"Modified files in commit: {modified_files}")

            # Create IssueFixResult for SUCCESSFUL issues (from passed batches)
            for issue in successful_issues:
                issue_file = str(issue.file)
                # Get diff for display (best effort, doesn't affect status)
                fix_code = await self._get_diff_for_file(issue_file)

                issue_result = IssueFixResult(
                    issue_id=issue.id,
                    issue_code=str(issue.issue_code),
                    status=FixStatus.COMPLETED,
                    commit_sha=commit_sha,
                    commit_message=f"[FIX] {issue_codes}",
                    changes_made=f"Fixed {issue.title}",
                    fix_code=fix_code,
                    fix_explanation=fix_explanation,
                    fix_files_modified=modified_files,
                    started_at=result.started_at,
                    completed_at=datetime.utcnow(),
                )
                result.results.append(issue_result)

            # Create FAILED results for issues from batches that didn't pass Gemini review
            for issue in failed_issues:
                # Find which batch this issue was in and get the score
                batch_info = ""
                for batch_id, data in batch_results.items():
                    if issue in data.get("issues", []):
                        batch_info = f" (batch {batch_id}, score: {data.get('score', 'N/A')})"
                        break

                logger.warning(f"Issue {issue.issue_code} batch failed Gemini review{batch_info}")
                issue_result = IssueFixResult(
                    issue_id=issue.id,
                    issue_code=str(issue.issue_code),
                    status=FixStatus.FAILED,
                    error=f"Batch did not pass Gemini review (score < {self.satisfaction_threshold}){batch_info}",
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
            # Final save with is_partial=False (session completed)
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
            issue_codes.append(issue.issue_code)
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
## ⚠️ WORKSPACE SCOPE CHECK

This is a MONOREPO with restricted workspace: `{workspace_path}/`

**CRITICAL**: When reviewing `git diff`, verify that ALL modified files are within the workspace scope.
If any files outside `{workspace_path}/` were modified, this is a CRITICAL failure - score 0.

"""

        task = f"""
# Task: Review Batch {batch_type}-{batch_idx} Fixes
{workspace_check}
## Issues in This Batch

{issues_section}

## Instructions
1. Run `git diff` to see the changes made for these {len(issues)} issues
2. For EACH issue, evaluate if the fix correctly addresses the problem
3. Check for bugs, security issues, or breaking changes
4. Give a score (0-100) for EACH issue

## Output Format (CRITICAL - follow exactly!)

Start with the OVERALL batch score:
BATCH_SCORE: <number>

Then list EACH issue with its individual score:
ISSUE_SCORES:
- {issue_codes_list.split(', ')[0] if issue_codes else 'ISSUE-XXX'}: <score> | <brief reason>
{chr(10).join(f'- {code}: <score> | <brief reason>' for code in issue_codes[1:]) if len(issue_codes) > 1 else ''}

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

        # Try to parse JSON block from output
        json_match = re.search(r"```json\s*([\s\S]*?)```", output)
        if json_match:
            try:
                review_data = json.loads(json_match.group(1))
                # Extract quality_scores from JSON
                if "quality_scores" in review_data:
                    quality_scores = review_data["quality_scores"]
                    logger.info(f"Parsed quality_scores: {quality_scores}")
                # Also try to get satisfaction_score from JSON
                if "satisfaction_score" in review_data:
                    batch_score = float(review_data["satisfaction_score"])
                    logger.info(f"Parsed satisfaction_score from JSON: {batch_score}")
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse JSON block: {e}")

        # Parse BATCH_SCORE (fallback or override)
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

        # Parse per-issue scores
        for issue in issues:
            code = issue.issue_code
            # Look for pattern: - ISSUE-123: 95 | reason
            pattern = rf"-\s*{re.escape(code)}:\s*(\d+)"
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                per_issue_scores[code] = float(match.group(1))
                logger.debug(f"Issue {code}: score {per_issue_scores[code]}")

        # Parse FAILED_ISSUES
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

        # If no explicit FAILED_ISSUES, derive from per_issue_scores
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
        # Load agent prompt based on type
        if agent_type == "fe":
            agent_prompt = self._get_fixer_prompt_fe()
        else:
            agent_prompt = self._get_fixer_prompt_be()

        # Build task with all issues
        task_parts = ["# Task: Fix Code Issues\n"]

        # Add structure documentation for repository context
        structure_doc = self._load_structure_doc(workspace_path)
        if structure_doc:
            # Wrap XML in semantic tags for better LLM parsing
            if structure_doc.strip().startswith("<?xml"):
                task_parts.append(
                    f"""
## Repository Structure

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
## Repository Structure

Use this structure documentation to understand the codebase architecture:

{structure_doc}

---
"""
                )

        # Add workspace scope restriction if set
        if workspace_path:
            task_parts.append(
                f"""
## ⚠️ WORKSPACE SCOPE RESTRICTION

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

        # Add user notes if provided
        if user_notes:
            task_parts.append(
                f"""
## Developer Notes

The developer has provided the following additional context and instructions:

<user-notes>
{user_notes}
</user-notes>

**Take these notes into account when implementing the fixes.**

---
"""
            )

        for i, issue in enumerate(issues, 1):
            # Get code snippet with context (marks problematic lines with >>>)
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
## Issue {i}: {issue.issue_code}
**Title**: {issue.title}
**Severity**: {issue.severity}
**Category**: {issue.category}
**File**: {issue.file}
**Location**: {location}

### Description
{issue.description}

### Problematic Code (lines marked with >>> need fixing)
```
{code_snippet or f"[No snippet available - read {issue.file}]"}
```

### Suggested Fix
{issue.suggested_fix or "Use your best judgment based on the issue description"}

---
"""
            )

        task_parts.append(
            """
## Instructions
1. Read the files to understand context
2. Make the fixes - one by one
3. Keep changes minimal
4. Do NOT commit - just fix the code
"""
        )

        if feedback and iteration > 1:
            task_parts.append(
                f"""
## Feedback from Previous Attempt (Iteration {iteration})
The reviewer found issues with the previous fix. Address this feedback:

{feedback}
"""
            )

        task = "\n".join(task_parts)

        # Combine agent prompt with task
        return f"{agent_prompt}\n\n---\n\n{task}"

    def _parse_score(self, output: str) -> float:
        """Extract score from Gemini output."""
        # Look for "SCORE: XX" pattern
        match = re.search(r"SCORE:\s*(\d+)", output, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            logger.info(f"Parsed SCORE: {score}")
            return score

        # Look for "satisfaction_score": XX in JSON (most direct)
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

        # Default to 70 if can't parse
        logger.warning(
            f"Could not parse score from Gemini output, defaulting to 70. Output: {output[:500]}"
        )
        return 70.0

    def _get_claude_cli(self, timeout: int = CLAUDE_CLI_TIMEOUT) -> ClaudeCLI:
        """Create ClaudeCLI instance for fix operations."""
        return ClaudeCLI(
            working_dir=self.repo_path,
            model="opus",  # Use Opus for comprehensive fixes
            timeout=timeout,
            s3_prefix="fix",
        )

    async def _run_claude_cli(
        self,
        prompt: str,
        timeout: int = CLAUDE_CLI_TIMEOUT,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        thinking_budget: int | None = None,
    ) -> str | None:
        """Run Claude CLI with prompt and optional streaming callback.

        Uses the centralized ClaudeCLI utility for execution.

        Args:
            prompt: The prompt to send to Claude
            timeout: Timeout in seconds
            on_chunk: Callback for streaming chunks
            thinking_budget: Override thinking budget (None = use default from config)
        """
        # Create ClaudeCLI with appropriate timeout
        cli = self._get_claude_cli(timeout)

        # Wrap on_chunk to add stderr prefix for stderr streaming
        async def on_stderr(line: str) -> None:
            if on_chunk:
                print(f"[CLAUDE FIX STDERR] {line}", flush=True)
                await on_chunk(f"[stderr] {line}\n")

        # Run with the centralized utility
        result = await cli.run(
            prompt,
            context_id=f"fix_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            thinking_budget=thinking_budget,
            save_prompt=True,
            save_output=True,
            save_thinking=True,
            on_chunk=on_chunk,
            on_stderr=on_stderr,
        )

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
            return None

        # Log model usage
        for usage in result.model_usage:
            logger.info(
                f"  {usage.model}: in={usage.input_tokens}, "
                f"out={usage.output_tokens}, cost=${usage.cost_usd:.4f}"
            )

        return result.output

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
                env["GEMINI_API_KEY"] = api_key

            # Use Pro model from settings (for better reasoning in review)
            model = self.settings.agents.gemini_pro_model

            # Gemini CLI expects prompt as positional argument, not stdin
            # Use --yolo to auto-approve any tool calls
            process = await asyncio.create_subprocess_exec(
                "gemini",
                "-m",
                model,
                "--yolo",
                prompt,  # Prompt as positional argument
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
            )

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

    async def _get_git_info(self) -> tuple[str | None, list[str], str | None]:
        """Get git info after commit.

        Returns:
            Tuple of (commit_sha, modified_files, diff_content)
        """
        commit_sha = None
        modified_files: list[str] = []
        diff_content = None

        try:
            # Get commit SHA
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

            # Get modified files from last commit
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

            # Get diff of last commit (limited to 2000 chars)
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
                # Return first 500 chars of added code
                return "\n".join(added_lines)[:500]
        except Exception as e:
            logger.warning(f"Failed to get diff for {file_path}: {e}")
        return None

    # ============== Workspace Scope Validation ==============

    async def _get_uncommitted_files(self) -> list[str]:
        """Get list of all uncommitted files (staged, unstaged, and untracked).

        Returns:
            List of file paths relative to repo root
        """
        all_files: set[str] = set()

        try:
            # 1. Staged files (git diff --cached --name-only)
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

            # 2. Unstaged modified files (git diff --name-only)
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
    ) -> list[str]:
        """Validate that all modified files are within the workspace scope.

        Args:
            modified_files: List of modified file paths (relative to repo root)
            workspace_path: Allowed workspace path (e.g., "packages/frontend")

        Returns:
            List of files that are OUTSIDE the workspace scope (violations)
        """
        if not workspace_path:
            # No workspace restriction
            return []

        # Normalize workspace path (remove trailing slash)
        workspace = workspace_path.rstrip("/")
        violations: list[str] = []

        for file_path in modified_files:
            # Check if file is within workspace
            # File must start with workspace path (e.g., "packages/frontend/src/...")
            if not file_path.startswith(workspace + "/") and file_path != workspace:
                violations.append(file_path)
                logger.warning(
                    f"File outside workspace scope: {file_path} (workspace: {workspace})"
                )

        return violations

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
            # 1. Unstage all staged changes
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

        # List what was fixed
        parts.append("## Changes Made\n")
        for issue in issues:
            parts.append(f"- **{issue.issue_code}**: {issue.title}\n")

        # Add Gemini's review summary if available
        if gemini_output:
            # Extract key points from Gemini output
            parts.append("\n## Review Summary\n")
            # Take first 500 chars of Gemini output
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
        claude_prompts: list[dict] | None = None,
        gemini_prompt: str | None = None,
        # Incremental save params
        batch_results: dict[str, dict] | None = None,
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
                # Incremental save metadata
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
                # Prompts sent to CLIs (for debugging)
                "claude_prompts": claude_prompts or [],
                "gemini_prompt": gemini_prompt,
                # Batch results for incremental saves (shows per-batch status)
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

            # Upload to S3
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
