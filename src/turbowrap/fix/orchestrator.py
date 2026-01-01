"""
Fix Orchestrator for TurboWrap.

Simple orchestrator that:
1. Prepares TODO files (master_todo.json + fix_todo_{code}.json)
2. Calls ONE Claude CLI with fixer.md agent
3. Evaluates fixes with Gemini Challenger
4. Commits approved fixes, retries failed ones (max 2 rounds)

Architecture:
- Claude CLI runs fixer.md which spawns sub-agents via Task tool
- Gemini evaluates ALL fixes after Claude finishes
- Approved fixes → commit → RESOLVED
- Failed fixes → retry with Gemini feedback (max 2 rounds)
"""

import asyncio
import json
import logging
import re
import secrets
import subprocess
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from turbowrap_llm import ClaudeCLI
from turbowrap_llm.claude.session import ClaudeSession

from turbowrap.chat_cli.context_generator import load_structure_documentation
from turbowrap.config import get_settings
from turbowrap.db.models import Issue
from turbowrap.fix.fix_challenger import GeminiFixChallenger
from turbowrap.fix.models import (
    ExecutionStep,
    FixChallengerStatus,
    FixContext,
    FixEventType,
    FixProgressEvent,
    FixRequest,
    FixSessionResult,
    FixStatus,
    IssueContextInfo,
    IssueEntry,
    IssueFixResult,
    IssuePlan,
    IssueTodo,
    MasterTodo,
    MasterTodoSummary,
)
from turbowrap.fix.todo_manager import TodoManager
from turbowrap.review.reviewers.utils.json_extraction import parse_llm_json
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)

# Agent paths
AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "agents"
FIXER_AGENT = AGENTS_DIR / "fixer.md"

# Constants
MAX_ROUNDS = 2
CLAUDE_CLI_TIMEOUT = 900  # 15 minutes

ProgressCallback = Callable[[FixProgressEvent], Awaitable[None]]


def generate_branch_name(issues: list[Issue], prefix: str = "fix") -> str:
    """Generate a descriptive branch name from issue titles."""
    if not issues:
        return f"{prefix}/{uuid.uuid4().hex[:12]}"

    first_title = str(issues[0].title) if issues[0].title else ""
    slug = re.sub(r"^\[?\w{2,4}\]?\s*:?\s*", "", first_title, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")

    if len(slug) > 40:
        slug = slug[:40].rsplit("-", 1)[0]

    if len(issues) > 1:
        slug = f"{slug}-and-{len(issues) - 1}-more"

    if not slug:
        slug = uuid.uuid4().hex[:12]

    return f"{prefix}/{slug}"


def generate_fix_flow_id(issues: list[Issue]) -> str:
    """Generate a human-readable fix flow ID from issue codes.

    Format: fix_{issue_codes}_{random6}
    Example: fix_BE-001-FE-003_aB3xY9

    Args:
        issues: List of issues to include in the ID.

    Returns:
        A unique, readable fix flow identifier.
    """
    # Generate 6 URL-safe characters for uniqueness (uses secrets for crypto-safe randomness)
    short_id = secrets.token_urlsafe(4)[:6]  # 4 bytes → 6 base64 chars

    if not issues:
        return f"fix_{short_id}"

    # Get unique issue codes, sorted for consistency
    codes = sorted({str(i.issue_code) for i in issues if i.issue_code})

    if not codes:
        return f"fix_{short_id}"

    # Limit to first 3 codes to keep ID reasonable
    if len(codes) > 3:
        codes_str = "-".join(codes[:3]) + f"-plus{len(codes) - 3}"
    else:
        codes_str = "-".join(codes)

    return f"fix_{codes_str}_{short_id}"


class FixOrchestrator:
    """
    Simple Fix Orchestrator.

    Flow:
    1. Create TODO files (master_todo.json + issue TODOs)
    2. Call Claude CLI with fixer.md → fixes all issues
    3. Gemini evaluates ALL fixes
    4. Commit approved, retry failed (max 2 rounds)

    Uses turbowrap_llm.ClaudeCLI with:
    - TurboWrapTrackerAdapter for operation tracking
    - S3ArtifactSaver for prompt/output persistence
    - ClaudeSession for multi-round conversations with --resume
    """

    def __init__(
        self,
        repo_path: Path,
        fix_flow_id: str | None = None,
        repo_id: str | None = None,
        repo_name: str | None = None,
    ):
        """Initialize orchestrator.

        Args:
            repo_path: Path to the repository.
            fix_flow_id: Fix flow ID for hierarchical tracking (groups all operations).
            repo_id: Repository ID for operation tracking.
            repo_name: Repository name for operation tracking.
        """
        self.repo_path = repo_path
        self.fix_flow_id = fix_flow_id
        self.repo_id = repo_id
        self.repo_name = repo_name or repo_path.name
        self.settings = get_settings()
        self.satisfaction_threshold = self.settings.fix_challenger.satisfaction_threshold
        # S3 for fix log storage (lazy loaded)
        self._s3_client: Any | None = None
        self.s3_bucket = self.settings.thinking.s3_bucket
        # CLI and session (created on first use)
        self._cli: ClaudeCLI | None = None
        self._session: ClaudeSession | None = None

    @property
    def s3_client(self) -> Any:
        """Lazy load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3")
        return self._s3_client

    async def fix_issues(
        self,
        request: FixRequest,
        issues: list[Issue],
        emit: ProgressCallback | None = None,
        operation_id: str | None = None,
    ) -> FixSessionResult:
        """
        Fix issues with challenger loop.

        Args:
            request: Fix request with repository info
            issues: List of issues to fix
            emit: Progress callback for SSE events
            operation_id: Optional operation ID for tracking

        Returns:
            FixSessionResult with all issue outcomes
        """
        session_id = str(uuid.uuid4())
        parent_session_id = operation_id
        branch_name = request.existing_branch_name or generate_branch_name(issues)

        await self._emit_session_started(emit, session_id, branch_name, issues)

        try:
            # Setup fix session components
            cli, challenger, master_todo_path = await self._setup_fix_session(
                session_id, branch_name, issues, request
            )

            # Run fix rounds
            all_results, gemini_feedback = await self._run_fix_rounds(
                cli,
                challenger,
                master_todo_path,
                session_id,
                parent_session_id,
                branch_name,
                issues,
                request,
                emit,
            )

            # Mark remaining pending issues as failed
            self._mark_remaining_failed(issues, all_results)

            # Build final result and save to S3
            final_result = self._build_result(session_id, request, branch_name, issues, all_results)
            await self._save_fix_log_to_s3(session_id, final_result, issues, gemini_feedback)

            return final_result

        except Exception as e:
            logger.exception(f"[FIX] Unexpected error: {e}")
            await self._emit(emit, FixEventType.FIX_SESSION_ERROR, {"error": str(e)})
            return self._build_error_result(session_id, request, branch_name, issues, str(e))

    async def _emit_session_started(
        self,
        emit: ProgressCallback | None,
        session_id: str,
        branch_name: str,
        issues: list[Issue],
    ) -> None:
        """Emit session started event."""
        await self._emit(
            emit,
            FixEventType.FIX_SESSION_STARTED,
            {
                "session_id": session_id,
                "branch_name": branch_name,
                "issue_count": len(issues),
            },
        )

    async def _setup_fix_session(
        self,
        session_id: str,
        branch_name: str,
        issues: list[Issue],
        request: FixRequest,
    ) -> tuple[ClaudeCLI, GeminiFixChallenger, Path]:
        """Setup fix session components: TODO files, CLI, and Challenger.

        Creates the CLI with:
        - TurboWrapTrackerAdapter for operation tracking
        - S3ArtifactSaver for prompt/output persistence
        - Agent MD file for fixer instructions
        """
        # Lazy imports to avoid circular dependency
        from turbowrap.api.services.llm_adapters import TurboWrapTrackerAdapter
        from turbowrap.api.services.operation_tracker import OperationType, get_tracker

        # Prepare TODO files
        todo_manager = TodoManager(session_id)
        master_todo, issue_todos = self._create_todos(issues, session_id, branch_name, request)
        await todo_manager.save_all(master_todo, issue_todos)
        master_todo_path = todo_manager.get_local_path()

        # Create S3 artifact saver
        artifact_saver = S3ArtifactSaver(
            bucket=self.settings.thinking.s3_bucket,
            region=self.settings.thinking.s3_region,
            prefix="fix-logs",
        )

        # Extract issue info for tracker
        issue_codes = [str(i.issue_code) for i in issues if i.issue_code]
        issue_ids = [str(i.id) for i in issues]

        # Create tracker adapter with issue details
        tracker = TurboWrapTrackerAdapter(
            tracker=get_tracker(),
            operation_type=OperationType.FIX,
            repo_id=self.repo_id,
            repo_name=self.repo_name,
            branch=branch_name,
            parent_session_id=self.fix_flow_id,
            initial_details={
                "issue_codes": issue_codes,
                "issue_ids": issue_ids,
                "issue_count": len(issues),
                "working_dir": str(self.repo_path),
                "session_id": session_id,
            },
        )

        # Initialize Claude CLI with new package
        cli = ClaudeCLI(
            working_dir=self.repo_path,
            model="opus",
            thinking_enabled=True,
            thinking_budget=16000,  # Extended thinking for complex fixes
            agent_md_path=FIXER_AGENT if FIXER_AGENT.exists() else None,
            artifact_saver=artifact_saver,
            tracker=tracker,
        )

        self._cli = cli
        logger.info(
            f"[FIX] Created CLI with S3 saver and tracker "
            f"(issues: {issue_codes}, fix_flow_id: {self.fix_flow_id})"
        )

        # Initialize Gemini Challenger with repo_path and fix_flow_id for
        # hierarchical operation tracking and streaming
        challenger = GeminiFixChallenger(
            repo_path=self.repo_path,
            fix_flow_id=self.fix_flow_id,
            satisfaction_threshold=self.satisfaction_threshold,
        )

        return cli, challenger, master_todo_path

    def _get_or_create_session(
        self,
        cli: ClaudeCLI,
        session_id: str | None,
    ) -> ClaudeSession:
        """Get existing session or create a new one.

        Args:
            cli: The ClaudeCLI instance.
            session_id: Existing session ID to resume, or None for new session.

        Returns:
            ClaudeSession instance.
        """
        # If resuming from a previous session (e.g., clarify phase or previous round)
        if session_id:
            if self._session and self._session.session_id == session_id:
                # Reuse existing session object
                logger.info(f"[FIX] Reusing session: {session_id[:8]}...")
                return self._session
            # Create session with resume=True to use --resume
            logger.info(f"[FIX] Resuming session: {session_id[:8]}...")
            self._session = cli.session(session_id=session_id, resume=True)
            return self._session

        # Create new session (first call)
        logger.info("[FIX] Creating new session...")
        self._session = cli.session()
        return self._session

    async def _run_fix_rounds(
        self,
        cli: ClaudeCLI,
        challenger: GeminiFixChallenger,
        master_todo_path: Path,
        session_id: str,
        parent_session_id: str | None,
        branch_name: str,
        issues: list[Issue],
        request: FixRequest,
        emit: ProgressCallback | None,
    ) -> tuple[dict[str, IssueFixResult], str]:
        """Run fix rounds with challenger loop."""
        all_results: dict[str, IssueFixResult] = {}
        pending_issues = issues.copy()
        claude_session_id = request.clarify_session_id
        gemini_feedback: str = ""

        for round_num in range(1, MAX_ROUNDS + 1):
            logger.info(f"[FIX] Round {round_num}/{MAX_ROUNDS} - {len(pending_issues)} issues")

            # Execute single round
            round_result = await self._execute_single_round(
                cli,
                challenger,
                master_todo_path,
                session_id,
                parent_session_id,
                branch_name,
                pending_issues,
                request,
                emit,
                round_num,
                claude_session_id,
                gemini_feedback,
            )

            if round_result is None:
                # CLI failed
                return all_results, gemini_feedback

            approved, failed, gemini_feedback, gemini_scores, claude_session_id, fix_results = (
                round_result
            )

            # Process approved issues
            if approved:
                await self._process_approved_issues(
                    approved, fix_results, gemini_scores, round_num, branch_name, all_results, emit
                )

            # Check if done
            if not failed:
                break

            pending_issues = failed

        return all_results, gemini_feedback

    async def _execute_single_round(
        self,
        cli: ClaudeCLI,
        challenger: GeminiFixChallenger,
        master_todo_path: Path,
        session_id: str,
        parent_session_id: str | None,
        branch_name: str,
        pending_issues: list[Issue],
        request: FixRequest,
        emit: ProgressCallback | None,
        round_num: int,
        claude_session_id: str | None,
        previous_feedback: str,
    ) -> tuple[list[Issue], list[Issue], str, dict[str, int], str | None, dict[str, Any]] | None:
        """Execute a single fix round. Returns None if CLI fails."""
        await self._emit(
            emit,
            FixEventType.FIX_STEP_STARTED,
            {"round": round_num, "issue_count": len(pending_issues)},
        )

        # Build prompt
        if round_num == 1:
            prompt = self._build_fix_prompt(master_todo_path, branch_name, request.workspace_path)
        else:
            prompt = self._build_refix_prompt(
                [str(i.issue_code) for i in pending_issues], previous_feedback
            )

        # Call Claude CLI via session (supports multi-round with --resume)
        await self._emit(
            emit,
            FixEventType.FIX_ISSUE_GENERATING,
            {"round": round_num, "message": "Claude is fixing issues..."},
        )

        # Get or create session (resumes from clarify phase or previous round)
        session = self._get_or_create_session(cli, claude_session_id)
        logger.info(
            f"[FIX] Sending prompt to session {session.session_id[:8]}... "
            f"(round {round_num}, issues: {len(pending_issues)})"
        )

        result = await session.send(prompt)

        if not result.success:
            logger.error(f"[FIX] Claude CLI failed: {result.error}")
            return None

        # Update claude_session_id for next round (use the session's ID)
        new_claude_session_id = session.session_id

        fix_results = parse_llm_json(result.output) or {}

        # Aggregate sub-task results back to parent issues (if any)
        fix_results = self._aggregate_subtask_results(fix_results, pending_issues)

        self._log_fix_results(fix_results)

        # Evaluate with Gemini
        await self._emit(
            emit,
            FixEventType.FIX_CHALLENGER_EVALUATING,
            {"round": round_num, "message": "Gemini is evaluating fixes..."},
        )

        approved, failed, gemini_feedback, gemini_scores = await self._evaluate_fixes(
            challenger, fix_results, pending_issues, branch_name, session_id, parent_session_id
        )

        logger.info(f"[FIX] Round {round_num}: {len(approved)} approved, {len(failed)} failed")

        return approved, failed, gemini_feedback, gemini_scores, new_claude_session_id, fix_results

    def _log_fix_results(self, fix_results: dict[str, Any]) -> None:
        """Log parsed fix results for debugging."""
        logger.info(f"[FIX] Parsed fix_results keys: {list(fix_results.keys())}")
        if "issues" in fix_results:
            for code, data in fix_results["issues"].items():
                summary = data.get("changes_summary", "MISSING")
                summary_preview = summary[:100] if summary else "MISSING"
                subtasks = data.get("subtasks", [])
                logger.info(
                    f"[FIX] Issue {code}: status={data.get('status')}, "
                    f"subtasks={subtasks}, changes_summary={summary_preview}"
                )

    def _aggregate_subtask_results(
        self,
        fix_results: dict[str, Any],
        issues: list[Issue],
    ) -> dict[str, Any]:
        """Aggregate sub-task results back to parent issues.

        If the fixer agent returned sub-task codes (e.g., BE-001-models),
        this method aggregates them back to the parent issue (BE-001).

        The fixer.md agent SHOULD already aggregate, but this is a fallback
        in case it doesn't.
        """
        issues_data = fix_results.get("issues", {})
        if not issues_data:
            return fix_results

        # Build mapping of parent issue codes for validation
        valid_parent_codes = {str(issue.issue_code) for issue in issues if issue.issue_code}

        # Separate parent results from orphan sub-task results
        parent_results: dict[str, Any] = {}
        orphan_subtasks: dict[str, list[tuple[str, Any]]] = defaultdict(list)

        for code, data in issues_data.items():
            # Check if this is already a parent result (has subtasks field or is a valid parent)
            if data.get("subtasks") or code in valid_parent_codes:
                parent_results[code] = data
            else:
                # This might be a sub-task code like BE-001-models
                # Try to extract parent code by removing suffix
                for valid_code in valid_parent_codes:
                    if code.startswith(f"{valid_code}-"):
                        orphan_subtasks[valid_code].append((code, data))
                        break
                else:
                    # Not a sub-task, keep as-is (unknown issue code)
                    parent_results[code] = data

        # Aggregate orphan sub-tasks into their parents
        for parent_code, subtask_list in orphan_subtasks.items():
            if parent_code in parent_results:
                # Parent already exists, merge subtasks info
                existing = parent_results[parent_code]
                existing_subtasks = existing.get("subtasks", [])
                existing.setdefault("subtasks", existing_subtasks)
                for subtask_code, _ in subtask_list:
                    if subtask_code not in existing["subtasks"]:
                        existing["subtasks"].append(subtask_code)
            else:
                # Need to aggregate from scratch
                all_files = []
                all_summaries = []
                all_statuses = []
                all_confidences = []
                subtask_codes = []

                for subtask_code, subtask_data in subtask_list:
                    subtask_codes.append(subtask_code)

                    # Collect files
                    files = subtask_data.get("files_modified", [])
                    if not files:
                        file_mod = subtask_data.get("file_modified")
                        if file_mod:
                            files = [file_mod]
                    all_files.extend(files)

                    # Collect summary
                    summary = subtask_data.get("changes_summary", "")
                    if summary:
                        # Add subtask label to summary
                        suffix = subtask_code.replace(f"{parent_code}-", "")
                        all_summaries.append(f"[{suffix}] {summary}")

                    # Collect status
                    status = subtask_data.get("status", "unknown")
                    all_statuses.append(status)

                    # Collect confidence
                    self_eval = subtask_data.get("self_evaluation", {})
                    if isinstance(self_eval, dict):
                        conf = self_eval.get("confidence")
                        if conf is not None:
                            all_confidences.append(conf)

                # Compute aggregate status
                if all(s == "fixed" for s in all_statuses):
                    agg_status = "fixed"
                elif any(s == "failed" for s in all_statuses):
                    agg_status = "failed"
                elif any(s == "fixed" for s in all_statuses):
                    agg_status = "partial"
                else:
                    agg_status = "skipped"

                # Compute average confidence
                avg_confidence = (
                    int(sum(all_confidences) / len(all_confidences)) if all_confidences else None
                )

                parent_results[parent_code] = {
                    "status": agg_status,
                    "files_modified": list(set(all_files)),
                    "changes_summary": " ".join(all_summaries),
                    "self_evaluation": {
                        "confidence": avg_confidence,
                        "completeness": "full" if agg_status == "fixed" else "partial",
                        "risks": [],
                    },
                    "subtasks": subtask_codes,
                }

        # Log aggregation if any happened
        if orphan_subtasks:
            logger.info(
                f"[FIX] Aggregated {sum(len(v) for v in orphan_subtasks.values())} "
                f"sub-tasks into {len(orphan_subtasks)} parent issues"
            )

        return {**fix_results, "issues": parent_results}

    async def _process_approved_issues(
        self,
        approved: list[Issue],
        fix_results: dict[str, Any],
        gemini_scores: dict[str, int],
        round_num: int,
        branch_name: str,
        all_results: dict[str, IssueFixResult],
        emit: ProgressCallback | None,
    ) -> None:
        """Process approved issues: commit and record results."""
        await self._emit(
            emit,
            FixEventType.FIX_BATCH_COMMITTED,
            {"round": round_num, "approved_count": len(approved)},
        )

        commit_sha = await self._commit_fixes(approved, round_num, branch_name)

        for issue in approved:
            issue_code = str(issue.issue_code)
            issue_data = fix_results.get("issues", {}).get(issue_code, {})

            # Extract files_modified (handle both singular and plural forms)
            # Plural form comes from aggregated sub-task results
            files_modified = issue_data.get("files_modified", [])
            if not files_modified:
                # Fallback to singular form from single-agent output
                file_modified = issue_data.get("file_modified")
                files_modified = [file_modified] if file_modified else []

            # Extract self_evaluation.confidence → fix_self_score
            self_eval = issue_data.get("self_evaluation", {})
            self_score = self_eval.get("confidence") if isinstance(self_eval, dict) else None

            # Check if this was from aggregated sub-tasks
            subtasks = issue_data.get("subtasks", [])

            all_results[issue_code] = IssueFixResult(
                issue_id=str(issue.id),
                issue_code=issue_code,
                status=FixStatus.COMPLETED,
                commit_sha=commit_sha,
                changes_made=issue_data.get("changes_summary"),
                fix_explanation=issue_data.get("changes_summary"),
                fix_files_modified=files_modified,
                fix_self_score=self_score,
                fix_gemini_score=gemini_scores.get(issue_code),
            )

            if subtasks:
                logger.info(f"[FIX] Issue {issue_code} aggregated from sub-tasks: {subtasks}")

    def _mark_remaining_failed(
        self,
        issues: list[Issue],
        all_results: dict[str, IssueFixResult],
    ) -> None:
        """Mark remaining issues (not in all_results) as failed."""
        for issue in issues:
            issue_code = str(issue.issue_code)
            if issue_code not in all_results:
                all_results[issue_code] = IssueFixResult(
                    issue_id=str(issue.id),
                    issue_code=issue_code,
                    status=FixStatus.FAILED,
                    error=f"Failed after {MAX_ROUNDS} rounds",
                )

    def _create_todos(
        self,
        issues: list[Issue],
        session_id: str,
        branch_name: str,
        request: FixRequest,
    ) -> tuple[MasterTodo, list[IssueTodo]]:
        """Create MasterTodo and IssueTodos from issues."""
        # Group issues by file for parallel/serial execution
        issues_by_file: dict[str, list[Issue]] = defaultdict(list)
        for issue in issues:
            file_path = str(issue.file) if issue.file else "unknown"
            issues_by_file[file_path].append(issue)

        # Build execution steps
        # Step 1: First issue per file (parallel - different files)
        # Step 2+: Remaining issues per file (serial - same file)
        execution_steps: list[ExecutionStep] = []
        issue_todos: list[IssueTodo] = []

        # Step 1: Parallel (one issue per file)
        parallel_issues: list[IssueEntry] = []
        for _file_path, file_issues in issues_by_file.items():
            issue = file_issues[0]
            issue_code = str(issue.issue_code)

            parallel_issues.append(
                IssueEntry(
                    code=issue_code,
                    todo_file=f"/tmp/fix_session_{session_id}/fix_todo_{issue_code}.json",
                    agent_type="fixer-single",
                )
            )

            issue_todos.append(self._create_issue_todo(issue, session_id, request))

        if parallel_issues:
            execution_steps.append(
                ExecutionStep(
                    step=1,
                    reason="Issues on different files - can run in parallel",
                    issues=parallel_issues,
                )
            )

        # Step 2+: Serial groups (remaining issues per file)
        step_num = 2
        for file_path, file_issues in issues_by_file.items():
            if len(file_issues) > 1:
                serial_issues: list[IssueEntry] = []
                for issue in file_issues[1:]:
                    issue_code = str(issue.issue_code)

                    serial_issues.append(
                        IssueEntry(
                            code=issue_code,
                            todo_file=f"/tmp/fix_session_{session_id}/fix_todo_{issue_code}.json",
                            agent_type="fixer-single",
                        )
                    )

                    issue_todos.append(self._create_issue_todo(issue, session_id, request))

                execution_steps.append(
                    ExecutionStep(
                        step=step_num,
                        reason=f"Issues on same file ({file_path}) - run after step 1",
                        issues=serial_issues,
                    )
                )
                step_num += 1

        master_todo = MasterTodo(
            session_id=session_id,
            branch_name=branch_name,
            execution_steps=execution_steps,
            summary=MasterTodoSummary(
                total_issues=len(issues),
                total_steps=len(execution_steps),
            ),
        )

        return master_todo, issue_todos

    def _create_issue_todo(
        self,
        issue: Issue,
        session_id: str,
        request: FixRequest,
    ) -> IssueTodo:
        """Create IssueTodo for a single issue."""
        # Get code snippet
        code_snippet = self._get_code_snippet(issue)

        return IssueTodo(
            issue_code=str(issue.issue_code),
            issue_id=str(issue.id),
            file=str(issue.file) if issue.file else None,
            line=issue.line,
            end_line=issue.end_line,
            title=issue.title or "",
            description=issue.description or "",
            suggested_fix=issue.suggested_fix,
            severity=issue.severity or "MEDIUM",
            category=issue.category or "general",
            clarifications=[],  # Will be populated from pre-fix clarify phase
            context=IssueContextInfo(
                file_content_snippet=code_snippet,
                related_files=[],
                existing_patterns=[],
            ),
            plan=IssuePlan(
                approach="patch",
                steps=["Apply the suggested fix"],
                estimated_lines_changed=10,
                risks=[],
                verification="Verify the issue is resolved",
            ),
        )

    def _get_code_snippet(self, issue: Issue, context_lines: int = 5) -> str:
        """Extract code snippet from file around the issue location."""
        if issue.current_code:
            return str(issue.current_code)

        if not issue.line or not issue.file:
            return ""

        try:
            file_path = self.repo_path / issue.file
            if not file_path.exists():
                return f"[File not found: {issue.file}]"

            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            issue_line = int(issue.line) if issue.line else 1
            issue_end_line = int(issue.end_line) if issue.end_line else issue_line
            start_line = max(1, issue_line - context_lines)
            end_line = min(len(lines), issue_end_line + context_lines)

            snippet_lines = []
            for i in range(start_line - 1, end_line):
                line_num = i + 1
                marker = ">>>" if issue_line <= line_num <= issue_end_line else "   "
                snippet_lines.append(f"{marker} {line_num:4d} | {lines[i].rstrip()}")

            return "\n".join(snippet_lines)
        except Exception as e:
            return f"[Error reading file: {e}]"

    def _build_fix_prompt(
        self,
        master_todo_path: Path,
        branch_name: str,
        workspace_path: str | None = None,
    ) -> str:
        """Build prompt for first fix round."""
        parts = [
            f"""# Fix Issues

## Master TODO
Read the execution plan: `{master_todo_path}`

## Branch
{branch_name}
"""
        ]

        # Structure documentation
        structure_doc = load_structure_documentation(self.repo_path, workspace_path)
        if structure_doc:
            parts.append(f"""
## Repository Structure
{structure_doc}
""")

        # Monorepo restriction
        if workspace_path:
            parts.append(f"""
## CRITICAL: Monorepo Scope
ONLY modify files within: `{workspace_path}/`
Changes outside this folder will be BLOCKED and REVERTED.
""")

        return "\n".join(parts)

    def _build_refix_prompt(
        self,
        failed_codes: list[str],
        gemini_feedback: str,
    ) -> str:
        """Build prompt for re-fix round with Gemini feedback."""
        return f"""# Re-fix Failed Issues

The following issues failed Gemini validation. Please fix them based on the feedback.

## Failed Issues
{', '.join(failed_codes)}

## Gemini Challenger Feedback
{gemini_feedback}

## Instructions
1. Read each failed issue's TODO file again
2. Apply the improvements suggested by Gemini
3. Focus ONLY on the specific problems identified
4. Return the same JSON format with updated results
"""

    async def _evaluate_fixes(
        self,
        challenger: GeminiFixChallenger,
        fix_results: dict[str, Any],
        issues: list[Issue],
        branch_name: str,
        session_id: str,
        parent_session_id: str | None,
    ) -> tuple[list[Issue], list[Issue], str, dict[str, int]]:
        """
        Evaluate all fixes with Gemini Challenger using CLI.

        The challenger runs in the repo directory and can:
        - Run git diff to see actual changes
        - Read files directly
        - Verify fixes match what was claimed

        Returns:
            Tuple of (approved_issues, failed_issues, feedback_text, gemini_scores)
            gemini_scores: dict mapping issue_code -> satisfaction_score (0-100)
        """
        approved: list[Issue] = []
        failed: list[Issue] = []
        feedback_parts: list[str] = []
        gemini_scores: dict[str, int] = {}

        issues_data = fix_results.get("issues", {})

        # Pre-filter issues: skip those that don't need Gemini evaluation
        issues_to_evaluate: list[Issue] = []
        contexts: list[FixContext] = []

        for issue in issues:
            issue_code = str(issue.issue_code)
            issue_data = issues_data.get(issue_code, {})

            status = issue_data.get("status", "unknown")
            if status == "skipped":
                approved.append(issue)  # Skipped = no changes needed
                continue

            if status != "fixed":
                failed.append(issue)
                feedback_parts.append(f"## {issue_code}\nStatus: {status} (not fixed)\n")
                continue

            # Build context for Gemini evaluation
            file_path = issue.file
            if not file_path:
                approved.append(issue)  # Can't evaluate without file
                continue

            context = FixContext(
                issue_id=str(issue.id),
                issue_code=issue_code,
                file_path=str(file_path),
                line=issue.line,
                title=issue.title or "",
                description=issue.description or "",
                current_code=issue.current_code or "",
                suggested_fix=issue.suggested_fix,
                category=issue.category or "general",
                severity=issue.severity or "MEDIUM",
            )

            issues_to_evaluate.append(issue)
            contexts.append(context)

        # If no issues need evaluation, return early
        if not contexts:
            return approved, failed, "\n".join(feedback_parts), gemini_scores

        # Call Gemini CLI with batch evaluation
        try:
            logger.info(f"[FIX] Evaluating {len(contexts)} issues with Gemini CLI")

            feedback_map = await challenger.evaluate_batch(
                issues=contexts,
                branch_name=branch_name,
                fixer_output=fix_results,
            )

            # Process results
            for issue, context in zip(issues_to_evaluate, contexts, strict=True):
                issue_code = context.issue_code
                feedback = feedback_map.get(issue_code)

                if feedback is None:
                    # No feedback = fallback to approved
                    approved.append(issue)
                    continue

                # Store Gemini score for this issue
                gemini_scores[issue_code] = int(feedback.satisfaction_score)

                if feedback.status == FixChallengerStatus.APPROVED:
                    approved.append(issue)
                else:
                    failed.append(issue)
                    feedback_parts.append(
                        f"## {issue_code} (score: {feedback.satisfaction_score:.0f}/100)\n"
                        f"{feedback.to_refinement_prompt()}\n"
                    )

        except Exception as e:
            logger.exception(f"[FIX] Gemini CLI evaluation failed: {e}")
            # On error, approve all (trust Claude)
            for issue in issues_to_evaluate:
                approved.append(issue)

        return approved, failed, "\n".join(feedback_parts), gemini_scores

    async def _commit_fixes(
        self,
        issues: list[Issue],
        round_num: int,
        branch_name: str,
    ) -> str | None:
        """Commit approved fixes."""
        try:
            # Get modified files from git (non-blocking)
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "status", "--porcelain"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            if not result.stdout.strip():
                logger.info("[FIX] No changes to commit")
                return None

            # Stage all changes (non-blocking)
            await asyncio.to_thread(
                subprocess.run,
                ["git", "add", "-A"],
                cwd=self.repo_path,
                check=True,
            )

            # Build commit message
            issue_codes = [str(i.issue_code) for i in issues]
            if len(issue_codes) == 1:
                commit_msg = f"fix({issue_codes[0]}): automated fix round {round_num}"
            else:
                commit_msg = f"fix: automated fixes for {', '.join(issue_codes[:3])}"
                if len(issue_codes) > 3:
                    commit_msg += f" and {len(issue_codes) - 3} more"

            # Commit (non-blocking)
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "commit", "-m", commit_msg],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"[FIX] Commit failed: {result.stderr}")
                return None

            # Get commit SHA (non-blocking)
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            commit_sha = result.stdout.strip()
            logger.info(f"[FIX] Committed: {commit_sha[:8]}")
            return commit_sha

        except Exception as e:
            logger.error(f"[FIX] Commit error: {e}")
            return None

    def _build_result(
        self,
        session_id: str,
        request: FixRequest,
        branch_name: str,
        issues: list[Issue],
        results: dict[str, IssueFixResult],
    ) -> FixSessionResult:
        """Build final session result."""
        fixed = sum(1 for r in results.values() if r.status == FixStatus.COMPLETED)
        failed = sum(1 for r in results.values() if r.status == FixStatus.FAILED)

        if fixed == len(issues):
            status = FixStatus.COMPLETED
        elif fixed > 0:
            status = FixStatus.PARTIAL
        else:
            status = FixStatus.FAILED

        return FixSessionResult(
            session_id=session_id,
            repository_id=request.repository_id,
            task_id=request.task_id,
            branch_name=branch_name,
            status=status,
            issues_requested=len(issues),
            issues_fixed=fixed,
            issues_failed=failed,
            results=list(results.values()),
        )

    def _build_error_result(
        self,
        session_id: str,
        request: FixRequest,
        branch_name: str,
        issues: list[Issue],
        error: str,
    ) -> FixSessionResult:
        """Build error session result."""
        return FixSessionResult(
            session_id=session_id,
            repository_id=request.repository_id,
            task_id=request.task_id,
            branch_name=branch_name,
            status=FixStatus.FAILED,
            issues_requested=len(issues),
            issues_fixed=0,
            issues_failed=len(issues),
            results=[
                IssueFixResult(
                    issue_id=str(issue.id),
                    issue_code=str(issue.issue_code),
                    status=FixStatus.FAILED,
                    error=error,
                )
                for issue in issues
            ],
        )

    async def _emit(
        self,
        emit: ProgressCallback | None,
        event_type: FixEventType,
        data: dict[str, Any],
    ) -> None:
        """Emit progress event if callback provided."""
        if emit:
            try:
                await emit(FixProgressEvent(type=event_type, **data))
            except Exception as e:
                logger.warning(f"[FIX] Failed to emit event: {e}")

    async def _save_fix_log_to_s3(
        self,
        session_id: str,
        result: FixSessionResult,
        issues: list[Issue],
        gemini_feedback: str | None = None,
    ) -> str | None:
        """
        Save fix session log to S3 for debugging.

        Path: s3://{bucket}/fix-logs/{date}/{session_id}.json
        Retention: 10 days (configured via S3 lifecycle)
        """
        try:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            s3_key = f"fix-logs/{date_str}/{session_id}.json"

            log_data = {
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "status": result.status.value,
                "branch_name": result.branch_name,
                "issues_requested": result.issues_requested,
                "issues_fixed": result.issues_fixed,
                "issues_failed": result.issues_failed,
                "repo_path": str(self.repo_path),
                "satisfaction_threshold": self.satisfaction_threshold,
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
                        "issue_code": r.issue_code,
                        "status": r.status.value,
                        "commit_sha": r.commit_sha,
                        "fix_code": r.fix_code,
                        "fix_explanation": r.fix_explanation,
                        "fix_files_modified": r.fix_files_modified,
                        "error": r.error,
                        "fix_self_score": r.fix_self_score,
                        "fix_gemini_score": r.fix_gemini_score,
                    }
                    for r in result.results
                ],
                "gemini_feedback": gemini_feedback[:3000] if gemini_feedback else None,
            }

            # Prepare body outside of thread call
            body = json.dumps(log_data, indent=2, default=str).encode("utf-8")
            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=body,
                ContentType="application/json",
            )

            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"[FIX] Log saved to {s3_url}")
            return s3_url

        except ClientError as e:
            logger.warning(f"[FIX] Failed to save log to S3: {e}")
            return None
        except Exception as e:
            logger.warning(f"[FIX] Failed to save log to S3: {e}")
            return None
