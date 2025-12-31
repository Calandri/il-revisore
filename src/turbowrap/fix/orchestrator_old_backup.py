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
from turbowrap.review.reviewers.utils.json_extraction import parse_llm_json
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

S3_BUCKET = "turbowrap-thinking"

logger = logging.getLogger(__name__)


def generate_branch_name(issues: list[Issue], prefix: str = "fix") -> str:
    """Generate a descriptive branch name from issue titles.

    Args:
        issues: List of issues to fix
        prefix: Branch prefix (default: "fix")

    Returns:
        A descriptive branch name like "fix/missing-validation-user-input"
    """
    if not issues:
        return f"{prefix}/{uuid.uuid4().hex[:12]}"

    # Get the first issue title
    first_title = issues[0].title if issues[0].title else ""

    # Clean and slugify the title
    # Remove common prefixes like "[BE]", "[FE]", "CRITICAL:", etc.
    slug = re.sub(r"^\[?\w{2,4}\]?\s*:?\s*", "", first_title, flags=re.IGNORECASE)

    # Convert to lowercase and replace non-alphanumeric with dashes
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug.lower())

    # Remove leading/trailing dashes and collapse multiple dashes
    slug = re.sub(r"-+", "-", slug).strip("-")

    # Truncate to reasonable length (max 40 chars for the slug part)
    if len(slug) > 40:
        # Try to cut at a word boundary
        slug = slug[:40].rsplit("-", 1)[0]

    # Add suffix if multiple issues
    if len(issues) > 1:
        slug = f"{slug}-and-{len(issues) - 1}-more"

    # Ensure we have something
    if not slug:
        slug = uuid.uuid4().hex[:12]

    return f"{prefix}/{slug}"


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


@dataclass
class BatchGroupResult:
    """Results from processing a group of batches (BE or FE) in parallel."""

    batch_updates: dict[str, dict[str, Any]]  # batch_id -> updates to batch_results
    successful_issues: list[Issue]
    failed_issues: list[Issue]
    issue_status_updates: dict[str, dict[str, Any]]  # issue_code -> status updates
    feedback: str  # Gemini feedback for retries
    all_passed: bool


AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "agents"
FIXER_AGENT = AGENTS_DIR / "fixer.md"
RE_FIXER_AGENT = AGENTS_DIR / "re_fixer.md"
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
        # Limit to max 2 iterations: 1 fix + 1 re-fix (with challenger feedback)
        # The re-fix phase is "aware" - it critically evaluates challenger feedback
        self.max_iterations = min(fix_config.max_iterations, 2)
        self.satisfaction_threshold = fix_config.satisfaction_threshold  # default 95.0

        self._agent_cache: dict[str, str] = {}

        self.s3_client = boto3.client("s3")
        self.s3_bucket = S3_BUCKET

        # S3 saver for TODO lists (uses existing lifecycle policy)
        self._todo_s3_saver = S3ArtifactSaver(
            bucket=self.settings.thinking.s3_bucket,
            region=self.settings.thinking.s3_region,
            prefix="fix-logs",  # Uses existing 10-day lifecycle rule
        )

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

    def _get_refixer_prompt_be(self) -> str:
        """Get re-fixer prompt for backend: re_fixer.md + dev_be.md.

        The re-fixer is used in iteration 2 to critically evaluate
        the challenger's feedback and decide whether to apply improvements.
        """
        refixer = self._load_agent(RE_FIXER_AGENT)
        dev_be = self._load_agent(DEV_BE_AGENT)
        principles = self._load_agent(ENGINEERING_PRINCIPLES)

        parts = [refixer]
        if dev_be:
            parts.append(f"\n\n# Backend Development Guidelines\n\n{dev_be}")
        if principles:
            parts.append(f"\n\n# Engineering Principles\n\n{principles}")

        return "\n".join(parts)

    def _get_refixer_prompt_fe(self) -> str:
        """Get re-fixer prompt for frontend: re_fixer.md + dev_fe.md.

        The re-fixer is used in iteration 2 to critically evaluate
        the challenger's feedback and decide whether to apply improvements.
        """
        refixer = self._load_agent(RE_FIXER_AGENT)
        dev_fe = self._load_agent(DEV_FE_AGENT)
        principles = self._load_agent(ENGINEERING_PRINCIPLES)

        parts = [refixer]
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

    def _generate_todo_list(self, issues: list[Issue], session_id: str, branch_name: str) -> Path:
        """Generate TODO list JSON for the fixer orchestrator.

        Groups issues by file:
        - Issues on different files -> parallel group
        - Issues on same file -> serial group (depends on parallel group)

        Args:
            issues: List of issues to fix
            session_id: Session identifier
            branch_name: Git branch name to create

        Returns:
            Path to the generated TODO list JSON file
        """
        import tempfile
        from collections import defaultdict

        # Group issues by file
        issues_by_file: dict[str, list[Issue]] = defaultdict(list)
        for issue in issues:
            file_path = str(issue.file) if issue.file else "unknown"
            issues_by_file[file_path].append(issue)

        groups = []
        group_id = 1

        # First group: one issue per file (parallel)
        parallel_issues = []
        serial_issues_by_file: dict[str, list[Issue]] = {}

        for file_path, file_issues in issues_by_file.items():
            # First issue goes to parallel group
            parallel_issues.append(file_issues[0])
            # Remaining issues go to serial groups
            if len(file_issues) > 1:
                serial_issues_by_file[file_path] = file_issues[1:]

        # Create parallel group
        if parallel_issues:
            groups.append(
                {
                    "group_id": group_id,
                    "mode": "parallel",
                    "issues": [
                        {
                            "code": str(issue.issue_code),
                            "file": str(issue.file) if issue.file else None,
                            "title": issue.title,
                            "description": issue.description,
                            "suggested_fix": issue.suggested_fix,
                            "severity": issue.severity,
                            "line": issue.line,
                            "end_line": issue.end_line,
                        }
                        for issue in parallel_issues
                    ],
                }
            )
            group_id += 1

        # Create serial groups for remaining issues (one group per file)
        for _file_path, remaining_issues in serial_issues_by_file.items():
            for issue in remaining_issues:
                groups.append(
                    {
                        "group_id": group_id,
                        "mode": "serial",
                        "depends_on": 1,  # Depends on the parallel group
                        "issues": [
                            {
                                "code": str(issue.issue_code),
                                "file": str(issue.file) if issue.file else None,
                                "title": issue.title,
                                "description": issue.description,
                                "suggested_fix": issue.suggested_fix,
                                "severity": issue.severity,
                                "line": issue.line,
                                "end_line": issue.end_line,
                            }
                        ],
                    }
                )
                group_id += 1

        todo_list = {
            "session_id": session_id,
            "branch_name": branch_name,
            "repo_path": str(self.repo_path),
            "groups": groups,
            "total_issues": len(issues),
        }

        # Write to temp file
        todo_file = Path(tempfile.gettempdir()) / f"fix_todo_{session_id}.json"
        with open(todo_file, "w", encoding="utf-8") as f:
            json.dump(todo_list, f, indent=2)

        logger.info(f"Generated TODO list at {todo_file} with {len(groups)} groups")

        # Upload to S3 in background (fire-and-forget for persistence)
        self._upload_todo_to_s3(todo_list, session_id, "todo")

        return todo_file

    def _upload_todo_to_s3(
        self, content: dict[str, Any], session_id: str, artifact_type: str
    ) -> None:
        """Upload TODO list to S3 in background (fire-and-forget).

        Does not block the main flow - S3 is for persistence/audit only.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule upload without waiting
                asyncio.create_task(
                    self._todo_s3_saver.save_json(content, artifact_type, session_id)
                )
            else:
                # Fallback for non-async context
                asyncio.run(self._todo_s3_saver.save_json(content, artifact_type, session_id))
        except Exception as e:
            # Never fail the main flow due to S3 upload issues
            logger.warning(f"[S3] TODO upload failed (non-blocking): {e}")

    def _generate_group_todo_list(
        self,
        issues: list[Issue],
        group_type: str,  # "BE" or "FE"
        session_id: str,
        branch_name: str,
    ) -> Path:
        """Generate TODO list JSON for a specific group (BE or FE).

        Creates a file with explicit parallel/serial structure:
        - parallel_group: issues on DIFFERENT files (can run together)
        - serial_groups: issues on SAME file (must run one at a time)

        Args:
            issues: List of issues for this group
            group_type: "BE" or "FE"
            session_id: Session identifier
            branch_name: Git branch name

        Returns:
            Path to the generated TODO list JSON file
        """
        import tempfile
        from collections import defaultdict

        # Group issues by file
        issues_by_file: dict[str, list[Issue]] = defaultdict(list)
        for issue in issues:
            file_path = str(issue.file) if issue.file else "unknown"
            issues_by_file[file_path].append(issue)

        # First issue per file -> parallel_group
        # Remaining issues per file -> serial_groups
        parallel_issues: list[Issue] = []
        serial_groups: list[dict[str, Any]] = []

        for file_path, file_issues in issues_by_file.items():
            # First issue goes to parallel group
            parallel_issues.append(file_issues[0])

            # Remaining issues go to serial group for this file
            if len(file_issues) > 1:
                serial_groups.append(
                    {
                        "file": file_path,
                        "description": "Issues on SAME FILE - run ONE at a time",
                        "issues": [
                            {
                                "code": str(issue.issue_code),
                                "file": str(issue.file) if issue.file else None,
                                "title": issue.title,
                                "description": issue.description,
                                "suggested_fix": issue.suggested_fix,
                                "severity": issue.severity,
                                "line": issue.line,
                                "end_line": issue.end_line,
                            }
                            for issue in file_issues[1:]
                        ],
                    }
                )

        todo_list = {
            "type": group_type,
            "session_id": session_id,
            "branch_name": branch_name,
            "repo_path": str(self.repo_path),
            "parallel_group": {
                "description": "Issues on DIFFERENT FILES - run ALL together in ONE message",
                "issues": [
                    {
                        "code": str(issue.issue_code),
                        "file": str(issue.file) if issue.file else None,
                        "title": issue.title,
                        "description": issue.description,
                        "suggested_fix": issue.suggested_fix,
                        "severity": issue.severity,
                        "line": issue.line,
                        "end_line": issue.end_line,
                    }
                    for issue in parallel_issues
                ],
            },
            "serial_groups": serial_groups,
            "total_issues": len(issues),
        }

        # Write to temp file with group type in filename
        filename = f"fix_todo_{group_type.lower()}_{session_id}.json"
        todo_file = Path(tempfile.gettempdir()) / filename
        with open(todo_file, "w", encoding="utf-8") as f:
            json.dump(todo_list, f, indent=2)

        logger.info(
            f"Generated {group_type} TODO list at {todo_file} "
            f"({len(parallel_issues)} parallel, {len(serial_groups)} serial groups)"
        )

        # Upload to S3 in background (fire-and-forget for persistence)
        self._upload_todo_to_s3(todo_list, session_id, f"todo_{group_type.lower()}")

        return todo_file

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
            if issue.line and issue.end_line:
                line_info = f"(lines {issue.line}-{issue.end_line})"
            elif issue.line:
                line_info = f"(line {issue.line})"
            else:
                line_info = ""
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
        branch_name = generate_branch_name(issues)

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
                # Branch creation is now handled by the Opus orchestrator internally
                # via Task tool with haiku model (Step 1 in fixer.md)
                logger.info(
                    f"[FIX] Branch '{branch_name}' will be created by Opus orchestrator "
                    f"via Task tool (haiku model)"
                )
                await safe_emit(
                    FixProgressEvent(
                        type=FixEventType.FIX_ISSUE_STREAMING,
                        session_id=session_id,
                        message=f"Branch '{branch_name}' will be created by Opus orchestrator",
                    )
                )

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

            # Per-issue status tracking (SOLVED vs IN_PROGRESS)
            # Key: issue_code, Value: {"status": "SOLVED"|"IN_PROGRESS", "score": float, "issue": Issue}
            issue_status_map: dict[str, dict[str, Any]] = {}
            for issue in be_issues + fe_issues:
                issue_status_map[str(issue.issue_code)] = {
                    "status": "IN_PROGRESS",
                    "score": 0.0,
                    "issue": issue,
                }

            # Store Claude fixer's per-issue output data (changes_summary, file_modified, etc.)
            # Key: issue_code, Value: {"changes_summary": str, "file_modified": str, ...}
            claude_fix_data: dict[str, dict[str, Any]] = {}

            # Initialize session context for fix operations
            # Note: Branch creation is now handled internally by Opus orchestrator via Task tool
            # so we don't have a branch_session_id to propagate. Each Opus CLI call manages
            # its own session internally.
            session_context = FixSessionContext()
            logger.info("[FIX] Session context initialized (Opus manages sessions internally)")

            # Generate separate TODO lists for BE and FE groups
            # Each file specifies parallel (different files) vs serial (same file) execution
            be_todo_path: Path | None = None
            fe_todo_path: Path | None = None

            if be_issues:
                be_todo_path = self._generate_group_todo_list(
                    issues=be_issues,
                    group_type="BE",
                    session_id=session_id,
                    branch_name=branch_name,
                )
                logger.info(f"[FIX] Generated BE TODO list: {be_todo_path}")

            if fe_issues:
                fe_todo_path = self._generate_group_todo_list(
                    issues=fe_issues,
                    group_type="FE",
                    session_id=session_id,
                    branch_name=branch_name,
                )
                logger.info(f"[FIX] Generated FE TODO list: {fe_todo_path}")

            for iteration in range(1, self.max_iterations + 1):
                if iteration == 1:
                    batches_to_process = list(batch_results.keys())
                else:
                    # For retry iterations: only include batches that have IN_PROGRESS issues
                    # Also update batch issues to exclude SOLVED ones
                    batches_to_process = []
                    for batch_id, batch_info in batch_results.items():
                        if batch_info["passed"]:
                            continue  # Skip already passed batches

                        # Filter out SOLVED issues from this batch
                        original_issues = batch_info["issues"]
                        remaining_issues = [
                            issue
                            for issue in original_issues
                            if issue_status_map.get(str(issue.issue_code), {}).get("status")
                            == "IN_PROGRESS"
                        ]

                        if remaining_issues:
                            # Update batch with only IN_PROGRESS issues
                            batch_results[batch_id]["issues"] = remaining_issues
                            batches_to_process.append(batch_id)
                            logger.info(
                                f"[FIX] {batch_id}: {len(remaining_issues)}/{len(original_issues)} issues need retry"
                            )
                        else:
                            # All issues in this batch are SOLVED
                            batch_results[batch_id]["passed"] = True
                            logger.info(f"[FIX] {batch_id}: All issues SOLVED, skipping retry")

                if not batches_to_process:
                    logger.info("All issues SOLVED, no more retries needed")
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

                # Split batches into BE and FE groups for parallel execution
                be_batch_ids = [b for b in batches_to_process if b.startswith("BE")]
                fe_batch_ids = [b for b in batches_to_process if b.startswith("FE")]

                # Log parallel execution plan
                if be_batch_ids and fe_batch_ids:
                    await safe_emit(
                        FixProgressEvent(
                            type=FixEventType.FIX_ISSUE_STREAMING,
                            session_id=session_id,
                            message=f"🚀 Running BE and FE in PARALLEL\n"
                            f"   BE: {len(be_batch_ids)} batch(es) | FE: {len(fe_batch_ids)} batch(es)",
                        )
                    )

                # Inner async function to process a batch group sequentially
                async def process_batch_group(
                    group_batch_ids: list[str],
                    group_type: str,  # "BE" or "FE"
                    group_feedback: str,
                    group_session_ctx: FixSessionContext,
                    current_iteration: int,  # Bind loop variable to avoid B023
                    group_todo_path: Path | None,  # TODO list specific to this group
                ) -> BatchGroupResult:
                    """Process a group of batches (BE or FE) sequentially within the group."""
                    group_batch_updates: dict[str, dict[str, Any]] = {}
                    group_successful: list[Issue] = []
                    group_failed: list[Issue] = []
                    group_issue_updates: dict[str, dict[str, Any]] = {}
                    group_all_passed = True
                    current_feedback = group_feedback

                    # Streaming callback for Gemini review
                    async def on_chunk_gemini_group(chunk: str) -> None:
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_CHALLENGER_EVALUATING,
                                session_id=session_id,
                                content=chunk,
                            )
                        )

                    for idx, batch_id in enumerate(group_batch_ids, 1):
                        batch_type = group_type
                        batch_idx = int(batch_id.split("-")[1])
                        batch = batch_results[batch_id]["issues"]

                        async def on_chunk_claude_group(chunk: str, bt: str = batch_type) -> None:
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
                                message=f"🔧 {batch_id} [{idx}/{len(group_batch_ids)}] "
                                f"| {len(batch)} issues, workload={batch_workload}\n"
                                f"   Issues: {issue_codes}",
                            )
                        )

                        # Step 1: Run Claude CLI for this batch
                        prompt = self._build_fix_prompt(
                            batch,
                            batch_type.lower(),
                            current_feedback,
                            current_iteration,
                            request.workspace_path,
                            request.user_notes,
                            todo_list_path=group_todo_path if current_iteration == 1 else None,
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
                        if group_session_ctx.branch_session_id:
                            logger.info(
                                f"[FIX] Fix phase resuming session: {group_session_ctx.claude_session_id[:8] if group_session_ctx.claude_session_id else 'N/A'}... | "
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
                                on_chunk=on_chunk_claude_group,
                                thinking_budget=thinking_budget,
                                session_context=group_session_ctx,
                                parent_session_id=session_id,
                                agent_type="fixer",
                                issue_codes=[str(i.issue_code) for i in batch],
                                issue_ids=[str(i.id) for i in batch],
                            )
                            if not claude_result.success:
                                error_detail = claude_result.error or "Unknown error"
                                logger.error(f"Claude CLI ({batch_id}) failed: {error_detail}")
                                await emit_log(
                                    "ERROR", f"Claude CLI failed for {batch_id}: {error_detail}"
                                )
                                group_batch_updates[batch_id] = {"passed": False, "score": 0.0}
                                group_all_passed = False
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
                                    f"Please add credits at console.anthropic.com",
                                )
                            )
                            raise
                        except Exception as e:
                            logger.error(f"Claude CLI ({batch_id}) failed with exception: {e}")
                            await emit_log("ERROR", f"Claude CLI exception: {str(e)[:100]}")
                            group_batch_updates[batch_id] = {"passed": False}
                            group_all_passed = False
                            await safe_emit(
                                FixProgressEvent(
                                    type=FixEventType.FIX_ISSUE_STREAMING,
                                    session_id=session_id,
                                    message=f"   ❌ {batch_id} Claude CLI FAILED: {str(e)[:100]}",
                                )
                            )
                            continue

                        # Parse Claude fixer's output to extract per-issue data
                        # (changes_summary, file_modified, etc.)
                        parsed_fix_data = self._parse_claude_fix_output(
                            getattr(claude_result, "output", None)
                        )
                        # Merge into global claude_fix_data for later use in IssueFixResult
                        for code, data in parsed_fix_data.items():
                            claude_fix_data[code] = data

                        # CHECK: Verify there are actual uncommitted changes
                        # If fixer identified a false positive, there will be no changes to commit
                        # FALSE POSITIVE = issue doesn't exist = SOLVED (nothing to fix)
                        uncommitted_files = await self._get_uncommitted_files()
                        if not uncommitted_files:
                            logger.info(
                                f"{batch_id}: No uncommitted changes found - "
                                f"false positive detected, marking as SOLVED"
                            )
                            await emit_log(
                                "INFO",
                                f"{batch_id}: False positive - issue doesn't exist, marking SOLVED",
                            )
                            # False positive = SOLVED (nothing to fix means issue is resolved)
                            group_batch_updates[batch_id] = {
                                "passed": True,
                                "score": 100.0,
                                "false_positive": True,
                            }
                            group_successful.extend(batch)
                            # BUGFIX: Also update per-issue status to SOLVED for false positives
                            # Without this, issue_status_map stays IN_PROGRESS and issues
                            # don't get marked as resolved in the database
                            for issue in batch:
                                code = str(issue.issue_code)
                                group_issue_updates[code] = {
                                    "status": "SOLVED",
                                    "score": 100.0,
                                    "false_positive": True,
                                }
                                logger.debug(f"[FIX] Marked false positive {code} as SOLVED")
                            await safe_emit(
                                FixProgressEvent(
                                    type=FixEventType.FIX_ISSUE_STREAMING,
                                    session_id=session_id,
                                    message=f"   ✅ {batch_id} false positive - no fix needed (SOLVED)",
                                )
                            )
                            continue

                        # ALWAYS run Gemini review (even after re-fix in iteration 2+)
                        # This ensures proper per-issue evaluation with SOLVED/IN_PROGRESS status
                        review_label = "Re-fix" if current_iteration > 1 else "Fix"
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_ISSUE_STREAMING,
                                session_id=session_id,
                                message=f"   ✅ {batch_id} Claude {review_label.lower()} complete, "
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

                        # Atomic tracking at leaf level
                        try:
                            gemini_result = await self.gemini_cli.run(
                                review_prompt,
                                operation_type="review",
                                repo_name=self.repo_path.name,
                                on_chunk=on_chunk_gemini_group,
                                track_operation=True,  # Atomic tracking at leaf level
                                operation_details={
                                    "parent_session_id": session_id,
                                    "session_id": session_id,  # For UI display
                                    "agent_type": "reviewer",
                                    "batch_id": batch_id,
                                    "iteration": current_iteration,
                                    "issue_codes": [str(i.issue_code) for i in batch],
                                    "issue_ids": [str(i.id) for i in batch],
                                },
                            )
                            gemini_output = gemini_result.output if gemini_result.success else None
                        except Exception as e:
                            logger.error(f"Gemini CLI ({batch_id}) exception: {e}")
                            await emit_log("WARNING", f"Gemini exception: {str(e)[:100]}")
                            gemini_output = None

                        # NOTE: Operation tracking is now handled atomically by GeminiCLI.run()

                        if gemini_output is None:
                            logger.warning(
                                f"Gemini CLI failed for {batch_id}, accepting fix without review"
                            )
                            await emit_log(
                                "WARNING", f"Gemini review failed for {batch_id}, accepting fix"
                            )
                            group_batch_updates[batch_id] = {"passed": True, "score": 100.0}
                            group_successful.extend(batch)
                            continue

                        score, failed_issue_codes, per_issue_scores, per_issue_data = (
                            self._parse_batch_review(gemini_output, batch)
                        )
                        if batch_id not in group_batch_updates:
                            group_batch_updates[batch_id] = {}
                        group_batch_updates[batch_id]["score"] = score
                        group_batch_updates[batch_id]["failed_issues"] = failed_issue_codes
                        group_batch_updates[batch_id]["per_issue_data"] = per_issue_data

                        # Update per-issue status map based on Gemini review (90% threshold)
                        SOLVED_THRESHOLD = 90.0
                        solved_in_batch = []
                        in_progress_in_batch = []
                        for issue in batch:
                            code = str(issue.issue_code)
                            issue_score = per_issue_scores.get(
                                code, score
                            )  # Fallback to batch score
                            if issue_score >= SOLVED_THRESHOLD:
                                group_issue_updates[code] = {
                                    "status": "SOLVED",
                                    "score": issue_score,
                                }
                                solved_in_batch.append(code)
                            else:
                                group_issue_updates[code] = {
                                    "status": "IN_PROGRESS",
                                    "score": issue_score,
                                }
                                in_progress_in_batch.append(code)

                        if solved_in_batch:
                            logger.info(
                                f"[FIX] {batch_id} SOLVED issues: {', '.join(solved_in_batch)}"
                            )
                        if in_progress_in_batch:
                            logger.info(
                                f"[FIX] {batch_id} IN_PROGRESS issues: {', '.join(in_progress_in_batch)}"
                            )

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
                                    quality_scores=per_issue_data if per_issue_data else None,
                                )
                            )
                        else:
                            await safe_emit(
                                FixProgressEvent(
                                    type=FixEventType.FIX_CHALLENGER_RESULT,
                                    session_id=session_id,
                                    message=f"   📊 {batch_id} score: {score}/100",
                                    quality_scores=per_issue_data if per_issue_data else None,
                                )
                            )

                        if score >= self.satisfaction_threshold:
                            group_batch_updates[batch_id]["passed"] = True
                            await emit_log("INFO", f"{batch_id} passed with score {score}/100")

                            # Get uncommitted files for the commit
                            uncommitted = await self._get_uncommitted_files()
                            if not uncommitted:
                                logger.warning(
                                    f"{batch_id}: No files to commit after passing review"
                                )
                                await emit_log(
                                    "WARNING",
                                    f"{batch_id}: No files to commit",
                                )
                                continue

                            batch_issue_codes = ", ".join(str(i.issue_code) for i in batch)
                            batch_commit_msg = f"[FIX] {batch_issue_codes}"
                            commit_prompt = self._load_agent(GIT_COMMITTER_AGENT)
                            commit_prompt = commit_prompt.replace(
                                "{commit_message}", batch_commit_msg
                            )
                            commit_prompt = commit_prompt.replace(
                                "{issue_codes}", batch_issue_codes
                            )
                            # Pass specific files to commit (avoid --add-all)
                            files_to_commit = " ".join(uncommitted)
                            commit_prompt = commit_prompt.replace("{files}", files_to_commit)

                            # Log session status before commit phase
                            logger.info(
                                f"[FIX] Commit phase | Session: {group_session_ctx.claude_session_id[:8] if group_session_ctx.claude_session_id else 'new'}... | "
                                f"Model: haiku | Files: {uncommitted}"
                            )

                            batch_commit_success = False

                            if request.workspace_path:
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
                                    group_failed.extend(batch)
                                    group_batch_updates[batch_id]["passed"] = False
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
                                    timeout=120,
                                    model="haiku",
                                    session_context=group_session_ctx,
                                    parent_session_id=session_id,
                                    agent_type="committer",
                                    issue_codes=[str(i.issue_code) for i in batch],
                                    issue_ids=[str(i.id) for i in batch],
                                )
                                if not commit_result.success:
                                    await emit_log("ERROR", f"Batch {batch_id} commit failed")
                                else:
                                    (
                                        batch_commit_sha,
                                        batch_modified_files,
                                        _,
                                    ) = await self._get_git_info()
                                    group_batch_updates[batch_id]["commit_sha"] = batch_commit_sha
                                    group_batch_updates[batch_id]["modified_files"] = (
                                        batch_modified_files
                                    )

                                    # NOTE: Per-batch issue updates removed to prevent race condition
                                    # with fix_session_service.update_issue_statuses()
                                    # All issue status updates now happen atomically at the end
                                    # via update_issue_statuses() in fix_session_service.py

                                    # Propagate commit_sha to SOLVED issues in per-issue status map
                                    # This ensures issues keep their commit_sha even if removed from batch
                                    for issue in batch:
                                        code = str(issue.issue_code)
                                        if (
                                            group_issue_updates.get(code, {}).get("status")
                                            == "SOLVED"
                                        ):
                                            group_issue_updates[code]["commit_sha"] = (
                                                batch_commit_sha
                                            )
                                            logger.debug(
                                                f"[FIX] Propagated commit_sha to SOLVED issue {code}"
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
                                group_successful.extend(batch)
                            else:
                                group_failed.extend(batch)
                                group_batch_updates[batch_id]["passed"] = False  # Mark as failed
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
                            group_batch_updates[batch_id]["passed"] = False
                            group_all_passed = False
                            await emit_log(
                                "WARNING",
                                f"{batch_id} needs retry "
                                f"(score {score} < {self.satisfaction_threshold})",
                            )
                            # Update feedback for this group
                            current_feedback = gemini_output or ""
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

                    # End of inner for loop - return BatchGroupResult
                    return BatchGroupResult(
                        batch_updates=group_batch_updates,
                        successful_issues=group_successful,
                        failed_issues=group_failed,
                        issue_status_updates=group_issue_updates,
                        feedback=current_feedback,
                        all_passed=group_all_passed,
                    )

                # Run BE and FE groups in parallel using asyncio.gather
                # Each group processes batches sequentially within the group
                be_session = FixSessionContext(
                    branch_session_id=session_context.branch_session_id,
                    claude_session_id=session_context.claude_session_id,
                )
                fe_session = FixSessionContext(
                    branch_session_id=session_context.branch_session_id,
                    claude_session_id=session_context.claude_session_id,
                )

                tasks = []
                if be_batch_ids:
                    tasks.append(
                        process_batch_group(
                            be_batch_ids, "BE", feedback_be, be_session, iteration, be_todo_path
                        )
                    )
                if fe_batch_ids:
                    tasks.append(
                        process_batch_group(
                            fe_batch_ids, "FE", feedback_fe, fe_session, iteration, fe_todo_path
                        )
                    )

                # Run tasks in parallel
                results: list[BatchGroupResult] = await asyncio.gather(*tasks)

                # Merge results from parallel execution
                all_passed_this_iteration = True
                for group_result in results:
                    # Merge batch updates
                    for batch_id, updates in group_result.batch_updates.items():
                        batch_results[batch_id].update(updates)

                    # Merge successful/failed issues
                    successful_issues.extend(group_result.successful_issues)
                    failed_issues.extend(group_result.failed_issues)

                    # Merge issue status updates
                    for code, status_update in group_result.issue_status_updates.items():
                        issue_status_map[code].update(status_update)

                    # Update feedback for retries
                    if group_result.feedback:
                        # Determine which group this was from
                        for batch_id in group_result.batch_updates:
                            if batch_id.startswith("BE"):
                                feedback_be = group_result.feedback
                            else:
                                feedback_fe = group_result.feedback
                            break

                    # Track if all passed
                    if not group_result.all_passed:
                        all_passed_this_iteration = False

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
                    issue_status_map=issue_status_map,
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

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # COMMIT SOLVED ISSUES FROM FAILED BATCHES
            # When batch score < threshold but individual issues are SOLVED (100%),
            # we should still commit those changes.
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            for batch_id, batch_data in batch_results.items():
                if batch_data["passed"]:
                    continue  # Already committed

                # Find SOLVED issues in this failed batch
                solved_in_failed_batch = [
                    i
                    for i in batch_data["issues"]
                    if issue_status_map.get(str(i.issue_code), {}).get("status") == "SOLVED"
                ]

                if not solved_in_failed_batch:
                    continue  # No SOLVED issues to commit

                # Check if there are uncommitted changes
                uncommitted = await self._get_uncommitted_files()
                if not uncommitted:
                    # Files might have been committed in a previous partial commit
                    # Get the commit_sha from the most recent commit so issues get marked RESOLVED
                    commit_sha, modified_files, _ = await self._get_git_info()
                    if commit_sha:
                        batch_data["commit_sha"] = commit_sha
                        batch_data["modified_files"] = modified_files
                        # Propagate commit_sha to per-issue status map for SOLVED issues
                        for issue in solved_in_failed_batch:
                            code = str(issue.issue_code)
                            if code in issue_status_map:
                                issue_status_map[code]["commit_sha"] = commit_sha
                                logger.debug(f"[FIX] Propagated commit_sha to SOLVED issue {code}")
                        logger.info(
                            f"[FIX] {batch_id}: {len(solved_in_failed_batch)} SOLVED issues "
                            f"already committed ({commit_sha[:7]})"
                        )
                    else:
                        logger.warning(
                            f"[FIX] {batch_id}: {len(solved_in_failed_batch)} SOLVED issues "
                            "but no uncommitted files and no commit found"
                        )
                    # Still mark them as successful since they were SOLVED
                    for issue in solved_in_failed_batch:
                        if issue not in successful_issues:
                            successful_issues.append(issue)
                    continue

                # Commit the SOLVED issues
                solved_issue_codes = ", ".join(str(i.issue_code) for i in solved_in_failed_batch)
                commit_msg = f"[FIX] {solved_issue_codes}"

                await emit_log(
                    "INFO",
                    f"{batch_id}: Committing {len(solved_in_failed_batch)} SOLVED issues "
                    f"(batch score {batch_data.get('score', 0):.0f}% < {self.satisfaction_threshold}%)",
                )

                commit_prompt = self._load_agent(GIT_COMMITTER_AGENT)
                commit_prompt = commit_prompt.replace("{commit_message}", commit_msg)
                commit_prompt = commit_prompt.replace("{issue_codes}", solved_issue_codes)
                files_to_commit = " ".join(uncommitted)
                commit_prompt = commit_prompt.replace("{files}", files_to_commit)

                try:
                    commit_result = await self._run_claude_cli(
                        commit_prompt,
                        timeout=120,
                        model="haiku",
                        session_context=session_context,
                        parent_session_id=session_id,
                        agent_type="committer",
                        issue_codes=[str(i.issue_code) for i in solved_in_failed_batch],
                        issue_ids=[str(i.id) for i in solved_in_failed_batch],
                    )

                    if commit_result.success:
                        commit_sha, modified_files, _ = await self._get_git_info()
                        batch_data["commit_sha"] = commit_sha
                        batch_data["modified_files"] = modified_files
                        batch_data["passed"] = (
                            True  # Mark as passed now that SOLVED issues committed
                        )

                        # Propagate commit_sha to per-issue status map for SOLVED issues
                        for issue in solved_in_failed_batch:
                            code = str(issue.issue_code)
                            if code in issue_status_map:
                                issue_status_map[code]["commit_sha"] = commit_sha
                                logger.debug(f"[FIX] Propagated commit_sha to SOLVED issue {code}")

                        await emit_log(
                            "INFO",
                            f"{batch_id} SOLVED issues committed: "
                            f"{commit_sha[:7] if commit_sha else 'unknown'}",
                        )

                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_BATCH_COMMITTED,
                                session_id=session_id,
                                message=f"   💾 {batch_id} SOLVED COMMITTED "
                                f"({commit_sha[:7] if commit_sha else 'unknown'})",
                                issue_ids=[i.id for i in solved_in_failed_batch],
                                issue_codes=[i.issue_code for i in solved_in_failed_batch],
                                commit_sha=commit_sha,
                            )
                        )

                        # Add SOLVED issues to successful list
                        for issue in solved_in_failed_batch:
                            if issue not in successful_issues:
                                successful_issues.append(issue)
                    else:
                        await emit_log(
                            "ERROR",
                            f"{batch_id} SOLVED commit failed: {commit_result.error}",
                        )
                except Exception as e:
                    await emit_log(
                        "ERROR",
                        f"{batch_id} SOLVED commit error: {str(e)[:100]}",
                    )

            # Use per-issue status map to determine final status
            # This replaces batch-level pass/fail with individual issue tracking
            for _code, status_data in issue_status_map.items():
                issue = status_data["issue"]
                if status_data["status"] == "SOLVED" and issue not in successful_issues:
                    # Issue was solved but may not have been committed yet
                    # Check if it's in a passed batch
                    for _batch_id, batch_data in batch_results.items():
                        if batch_data["passed"] and issue in batch_data.get("issues", []):
                            successful_issues.append(issue)
                            break
                elif status_data["status"] == "IN_PROGRESS" and issue not in failed_issues:
                    failed_issues.append(issue)

            # Emit FIX_BATCH_FAILED for remaining IN_PROGRESS issues
            for _batch_id, batch_data in batch_results.items():
                if not batch_data["passed"]:
                    in_progress_issues_in_batch = [
                        i
                        for i in batch_data["issues"]
                        if issue_status_map.get(str(i.issue_code), {}).get("status")
                        == "IN_PROGRESS"
                    ]
                    if in_progress_issues_in_batch:
                        await safe_emit(
                            FixProgressEvent(
                                type=FixEventType.FIX_BATCH_FAILED,
                                session_id=session_id,
                                message=f"   ❌ {_batch_id}: {len(in_progress_issues_in_batch)} issues "
                                f"FAILED after {self.max_iterations} retries",
                                issue_ids=[i.id for i in in_progress_issues_in_batch],
                                issue_codes=[i.issue_code for i in in_progress_issues_in_batch],
                                error="Score < 90% threshold",
                            )
                        )

            # Log per-issue final status summary
            solved_count = sum(1 for s in issue_status_map.values() if s["status"] == "SOLVED")
            in_progress_count = sum(
                1 for s in issue_status_map.values() if s["status"] == "IN_PROGRESS"
            )
            logger.info(
                f"[FIX] Final per-issue status: {solved_count} SOLVED, {in_progress_count} IN_PROGRESS"
            )

            # NOTE: Workspace scope validation now happens BEFORE each batch commit (in the loop above)

            # Step 3: Commits already done per-batch (atomic commits)

            # Step 4: Collect results from batch commits
            # NOTE: fix_explanation is now per-issue from claude_fix_data["changes_summary"]
            # The old _build_fix_explanation combined all issues into one text.

            actually_fixed_count = len(successful_issues)
            failed_count = len(failed_issues)

            logger.info(
                f"Fix results: {actually_fixed_count} successful, "
                f"{failed_count} failed (based on per-issue status)"
            )

            for issue in successful_issues:
                issue_file = str(issue.file)
                issue_code = str(issue.issue_code)
                fix_code = await self._get_diff_for_file(issue_file)

                # First, try to get commit_sha from per-issue status map (more reliable)
                # This handles cases where issue was removed from batch during retry
                issue_status_data = issue_status_map.get(issue_code, {})
                issue_commit_sha = issue_status_data.get("commit_sha")

                issue_codes_for_msg = issue_code
                # Check issue_status_map first for false_positive (set in group_issue_updates)
                is_false_positive = issue_status_data.get("false_positive", False)

                # Fallback to batch_results for commit_sha and other metadata
                for _batch_id, data in batch_results.items():
                    if issue in data.get("issues", []):
                        if not issue_commit_sha:
                            issue_commit_sha = data.get("commit_sha")
                        # Also check batch for false_positive if not already set
                        if not is_false_positive:
                            is_false_positive = data.get("false_positive", False)
                        issue_codes_for_msg = ", ".join(
                            str(i.issue_code) for i in data.get("issues", [])
                        )
                        break

                # Last resort: if SOLVED but still no commit_sha, get from git HEAD
                # This handles the case where issue was SOLVED in iteration 1, removed from batch,
                # and a later iteration committed without including this issue
                if not issue_commit_sha and not is_false_positive:
                    git_commit_sha, _, _ = await self._get_git_info()
                    if git_commit_sha:
                        issue_commit_sha = git_commit_sha
                        # Also update the status map for consistency
                        if issue_code in issue_status_map:
                            issue_status_map[issue_code]["commit_sha"] = git_commit_sha
                        logger.warning(
                            f"[FIX] Issue {issue_code} SOLVED but no commit_sha, "
                            f"using git HEAD: {git_commit_sha[:7]}"
                        )

                # Use per-issue data from Claude fixer if available
                issue_fix_data = claude_fix_data.get(issue_code, {})
                per_issue_explanation = issue_fix_data.get("changes_summary")
                if not per_issue_explanation:
                    # Fallback to generic message
                    per_issue_explanation = (
                        "False positive - issue does not exist in code"
                        if is_false_positive
                        else f"Fixed {issue.title}"
                    )

                # Extract scores
                # Self-evaluation score from Claude (confidence 0-100)
                self_eval = issue_fix_data.get("self_evaluation", {})
                self_score = self_eval.get("confidence") if isinstance(self_eval, dict) else None
                if self_score is not None:
                    self_score = int(self_score)

                # Gemini score from challenger
                issue_status = issue_status_map.get(issue_code, {})
                gemini_score = issue_status.get("score")
                if gemini_score is not None:
                    gemini_score = int(gemini_score)

                # Use issue's own file, not batch's modified_files
                per_issue_files = [issue_file] if issue_file else []

                issue_result = IssueFixResult(
                    issue_id=str(issue.id),
                    issue_code=issue_code,
                    status=FixStatus.COMPLETED,
                    commit_sha=issue_commit_sha,
                    commit_message=f"[FIX] {issue_codes_for_msg}",
                    changes_made=(
                        "False positive - issue does not exist in code"
                        if is_false_positive
                        else f"Fixed {issue.title}"
                    ),
                    fix_code=fix_code,
                    fix_explanation=per_issue_explanation,
                    fix_files_modified=per_issue_files,
                    started_at=result.started_at,
                    completed_at=datetime.utcnow(),
                    false_positive=is_false_positive,
                    fix_self_score=self_score,
                    fix_gemini_score=gemini_score,
                )
                result.results.append(issue_result)

            for issue in failed_issues:
                issue_code = str(issue.issue_code)
                issue_data = issue_status_map.get(issue_code, {})
                issue_score = issue_data.get("score", 0)

                # Find which batch this issue was in
                batch_label = ""
                for batch_id, batch_data in batch_results.items():
                    if issue in batch_data.get("issues", []):
                        batch_label = f" (batch {batch_id})"
                        break

                logger.warning(
                    f"Issue {issue_code} did not reach 90% threshold "
                    f"(score: {issue_score}){batch_label}"
                )
                issue_result = IssueFixResult(
                    issue_id=str(issue.id),
                    issue_code=issue_code,
                    status=FixStatus.FAILED,
                    error=f"Issue score {issue_score:.0f}% < 90% threshold{batch_info}",
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
                issue_status_map=issue_status_map,
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
    ) -> tuple[float, list[str], dict[str, float], dict[str, Any]]:
        """Parse Gemini's per-issue review output.

        Supports new JSON format with per-issue status:
        {
            "issues": {
                "FUNC-001": {"score": 95, "status": "SOLVED", ...},
                "FUNC-002": {"score": 75, "status": "IN_PROGRESS", ...}
            },
            "batch_summary": {...}
        }

        Also maintains backwards compatibility with old format.

        Args:
            output: Gemini's response
            issues: Issues in this batch

        Returns:
            Tuple of (batch_score, in_progress_codes, per_issue_scores, per_issue_data)
            - in_progress_codes: Issues with score < 90 (need retry)
            - per_issue_data: Full per-issue evaluation data
        """
        SOLVED_THRESHOLD = 90.0  # Issues >= 90% are SOLVED

        batch_score = 70.0  # default
        in_progress_issues: list[str] = []
        per_issue_scores: dict[str, float] = {}
        per_issue_data: dict[str, Any] = {}

        # Use centralized JSON extraction
        review_data = parse_llm_json(output)
        if review_data:
            # NEW FORMAT: per-issue evaluation
            if "issues" in review_data and isinstance(review_data["issues"], dict):
                logger.info("Parsing new per-issue JSON format")
                solved_count = 0
                in_progress_count = 0

                for code, issue_data in review_data["issues"].items():
                    score = float(issue_data.get("score", 0))
                    status = issue_data.get("status", "IN_PROGRESS")
                    per_issue_scores[code] = score
                    per_issue_data[code] = issue_data

                    # Determine status based on 90% threshold
                    if score >= SOLVED_THRESHOLD or status == "SOLVED":
                        solved_count += 1
                        logger.debug(f"Issue {code}: SOLVED (score={score})")
                    else:
                        in_progress_issues.append(code)
                        in_progress_count += 1
                        logger.debug(f"Issue {code}: IN_PROGRESS (score={score})")

                # Calculate batch score as average of per-issue scores
                if per_issue_scores:
                    batch_score = sum(per_issue_scores.values()) / len(per_issue_scores)

                logger.info(
                    f"Parsed {len(per_issue_scores)} issues: "
                    f"{solved_count} SOLVED, {in_progress_count} IN_PROGRESS"
                )

                # Extract batch_summary if present
                if "batch_summary" in review_data:
                    per_issue_data["_batch_summary"] = review_data["batch_summary"]

            # OLD FORMAT: backwards compatibility
            elif "quality_scores" in review_data or "satisfaction_score" in review_data:
                logger.info("Parsing old JSON format (backwards compatibility)")
                if "quality_scores" in review_data:
                    per_issue_data["_quality_scores"] = review_data["quality_scores"]
                if "satisfaction_score" in review_data:
                    batch_score = float(review_data["satisfaction_score"])
                    logger.info(f"Parsed satisfaction_score from JSON: {batch_score}")

        # Fallback: BATCH_SCORE pattern (old format)
        if not per_issue_scores:
            match = re.search(r"BATCH_SCORE:\s*(\d+)", output, re.IGNORECASE)
            if match:
                batch_score = float(match.group(1))
                logger.info(f"Parsed BATCH_SCORE (fallback): {batch_score}")
            else:
                match = re.search(r"SCORE:\s*(\d+)", output, re.IGNORECASE)
                if match:
                    batch_score = float(match.group(1))
                    logger.info(f"Parsed SCORE (fallback): {batch_score}")

        # Fallback: per-issue scores from text pattern (old format)
        if not per_issue_scores:
            for issue in issues:
                code = str(issue.issue_code)
                pattern = rf"-\s*{re.escape(code)}:\s*(\d+)"
                match = re.search(pattern, output, re.IGNORECASE)
                if match:
                    score = float(match.group(1))
                    per_issue_scores[code] = score
                    if score < SOLVED_THRESHOLD:
                        in_progress_issues.append(code)
                    logger.debug(f"Issue {code}: score {score}")

        # Fallback: FAILED_ISSUES pattern (old format)
        if not in_progress_issues:
            match = re.search(r"FAILED_ISSUES:\s*(.+?)(?:\n|$)", output, re.IGNORECASE)
            if match:
                failed_text = match.group(1).strip().lower()
                if failed_text != "none" and failed_text:
                    in_progress_issues = [
                        code.strip().upper()
                        for code in re.findall(r"[A-Z]+-\d+", match.group(1), re.IGNORECASE)
                    ]
                    logger.info(f"Parsed FAILED_ISSUES (fallback): {in_progress_issues}")

        # Derive in_progress from scores if not explicitly set
        if not in_progress_issues and per_issue_scores:
            in_progress_issues = [
                code for code, score in per_issue_scores.items() if score < SOLVED_THRESHOLD
            ]
            if in_progress_issues:
                logger.info(f"Derived IN_PROGRESS from scores: {in_progress_issues}")

        return batch_score, in_progress_issues, per_issue_scores, per_issue_data

    def _parse_claude_fix_output(self, output: str | None) -> dict[str, dict[str, Any]]:
        """Parse Claude fixer's JSON output to extract per-issue data.

        Claude fixer returns JSON like:
        {
            "issues": {
                "FUNC-001": {
                    "status": "fixed",
                    "file_modified": "src/services.py",
                    "changes_summary": "Added null check",
                    "self_evaluation": {...}
                }
            }
        }

        Args:
            output: Claude's raw output text

        Returns:
            Dict mapping issue_code to issue data (changes_summary, file_modified, etc.)
        """
        if not output:
            return {}

        per_issue_data: dict[str, dict[str, Any]] = {}

        # Use centralized JSON extraction
        fix_data = parse_llm_json(output)
        if fix_data and "issues" in fix_data and isinstance(fix_data["issues"], dict):
            for code, issue_data in fix_data["issues"].items():
                per_issue_data[code] = issue_data
                logger.debug(
                    f"Parsed Claude fix data for {code}: "
                    f"changes_summary={issue_data.get('changes_summary', 'N/A')[:50]}"
                )
            logger.info(f"Parsed Claude fix output: {len(per_issue_data)} issues")

        return per_issue_data

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
        todo_list_path: Path | None = None,
    ) -> str:
        """Build prompt for Claude CLI to fix issues.

        Args:
            issues: List of issues to fix (all same type: BE or FE)
            agent_type: "be" or "fe"
            feedback: Feedback from previous iteration
            iteration: Current iteration number
            workspace_path: Monorepo workspace restriction (e.g., "packages/frontend")
            user_notes: User-provided notes with additional context or instructions
            todo_list_path: Path to TODO list JSON for parallel/serial orchestration

        Note:
            For iteration > 1 (re-fix), we use the re-fixer agent which is aware
            of the challenger's feedback and can critically evaluate whether to
            apply the suggested improvements.
        """
        # Iteration 1: Use fixer agent
        # Iteration 2+: Use refixer agent (critically evaluates challenger feedback)
        if iteration > 1 and feedback:
            # Use re-fixer for second iteration with challenger feedback
            if agent_type == "fe":
                agent_prompt = self._get_refixer_prompt_fe()
            else:
                agent_prompt = self._get_refixer_prompt_be()
        else:
            # First iteration: use regular fixer
            if agent_type == "fe":
                agent_prompt = self._get_fixer_prompt_fe()
            else:
                agent_prompt = self._get_fixer_prompt_be()

        # Build task with all issues
        task_parts = ["# Task: Fix Code Issues\n"]

        # Add TODO list reference for orchestrator mode
        if todo_list_path:
            task_parts.append(
                f"""
## TODO List (Orchestration)

Read the TODO list at: `{todo_list_path}`

This JSON file contains:
- `branch_name`: Git branch to work on
- `parallel_group`: Issues on DIFFERENT files (run ALL together in ONE message)
- `serial_groups`: Issues on SAME file (run ONE at a time, after parallel)
- Issue details for each fix

**Follow the TODO list exactly:**
1. Process `parallel_group` first - all issues can run in parallel
2. Then process each `serial_groups` item sequentially
3. Return aggregated JSON with results for each issue

---
"""
            )

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

        # For iteration > 1, include structured challenger feedback
        if feedback and iteration > 1:
            task_parts.append(
                f"""
---

# Challenger Feedback (EVALUATE CRITICALLY!)

The automated code reviewer (Gemini) evaluated your previous fix and found issues.
**The reviewer is NOT infallible** - it may have flagged things incorrectly or made invalid suggestions.

**Your job**: Critically evaluate EACH point below. Apply improvements ONLY if they are genuinely valid.

<challenger-feedback>
{feedback}
</challenger-feedback>

**Remember**:
- If the feedback is about a real bug you missed → FIX IT
- If the feedback is stylistic or out of scope → IGNORE IT
- If the feedback is wrong or misunderstood context → IGNORE IT
- Trust your original decision if it was correct
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
        issue_codes: list[str] | None = None,
        issue_ids: list[str] | None = None,
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
            issue_codes: List of issue codes being fixed (for live-tasks display)
            issue_ids: List of issue IDs being fixed (for live-tasks links)
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
                "session_id": parent_session_id,  # For UI display
                "agent_type": agent_type or "fixer",
                "issue_codes": issue_codes or [],
                "issue_ids": issue_ids or [],
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
                "session_id": parent_session_id,  # For UI display
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

        DEPRECATED: This function is no longer called to prevent race conditions
        with fix_session_service.update_issue_statuses(). All issue status updates
        now happen atomically at the end of the fix session.

        Kept for reference and potential future use in isolated scenarios.

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
                # Safety: Don't mark resolved without a commit
                if not commit_sha:
                    logger.warning(
                        f"Skipping RESOLVED update for {len(issues)} issues: no commit_sha"
                    )
                    return

                for issue in issues:
                    db_issue = db.query(IssueModel).filter(IssueModel.id == issue.id).first()
                    if db_issue:
                        db_issue.status = IssueStatus.RESOLVED.value  # type: ignore[assignment]
                        db_issue.resolution_note = (  # type: ignore[assignment]
                            f"Fixed in commit {commit_sha[:7]}"
                        )
                        db_issue.fix_commit_sha = commit_sha  # type: ignore[assignment]
                        db_issue.fix_branch = branch_name  # type: ignore[assignment]
                        db_issue.fix_session_id = session_id  # type: ignore[assignment]
                        db_issue.resolved_at = datetime.utcnow()  # type: ignore[assignment]
                        db_issue.fixed_at = datetime.utcnow()  # type: ignore[assignment]
                        db_issue.fixed_by = "fixer_claude"  # type: ignore[assignment]
                db.commit()
                logger.info(f"Updated {len(issues)} issues to RESOLVED (commit {commit_sha[:7]})")
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
        issue_status_map: dict[str, dict[str, Any]] | None = None,
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
            issue_status_map: Per-issue status tracking (SOLVED/IN_PROGRESS)

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
                # Per-issue status tracking (SOLVED vs IN_PROGRESS)
                "per_issue_status": (
                    {
                        code: {
                            "status": data["status"],
                            "score": data["score"],
                        }
                        for code, data in (issue_status_map or {}).items()
                    }
                    if issue_status_map
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
