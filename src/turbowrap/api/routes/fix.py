"""Fix routes for issue remediation."""

import asyncio
import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from turbowrap.api.deps import get_db
from turbowrap.db.models import Issue, IssueStatus, Repository, Task, LinearIssue, Setting
from turbowrap.linear import LinearStateManager
from turbowrap.review.integrations.linear import LinearClient
from turbowrap.fix import (
    ClarificationAnswer,
    ClarificationQuestion,
    FixEventType,
    FixOrchestrator,
    FixProgressEvent,
    FixRequest,
)
from turbowrap.utils.aws_secrets import get_anthropic_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fix", tags=["fix"])

# Agent file path
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
GIT_MERGER_AGENT = AGENTS_DIR / "git_merger.md"


def _load_agent(agent_path: Path) -> str:
    """Load agent prompt from MD file, stripping frontmatter."""
    if not agent_path.exists():
        logger.warning(f"Agent file not found: {agent_path}")
        return ""

    content = agent_path.read_text(encoding="utf-8")

    # Strip YAML frontmatter (--- ... ---)
    if content.startswith("---"):
        import re
        end_match = re.search(r"\n---\n", content[3:])
        if end_match:
            content = content[3 + end_match.end():]

    return content.strip()

# Store for pending clarifications (session_id -> Question)
_pending_clarifications: dict[str, ClarificationQuestion] = {}
_clarification_answers: dict[str, asyncio.Future] = {}

# Idempotency tracking
IDEMPOTENCY_TTL_SECONDS = 3600  # 1 hour


@dataclass
class IdempotencyEntry:
    """Entry for tracking idempotent requests."""
    session_id: str
    status: str  # "in_progress", "completed", "failed"
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    result: Optional[dict] = None


class IdempotencyStore:
    """Thread-safe store for idempotency tracking.

    Prevents duplicate fix requests for the same set of issues.
    Uses an idempotency key based on issue IDs or a client-provided header.
    """

    def __init__(self):
        self._store: dict[str, IdempotencyEntry] = {}
        self._lock = threading.RLock()

    def generate_key(
        self,
        repository_id: str,
        task_id: str,
        issue_ids: list[str],
        client_key: Optional[str] = None,
    ) -> str:
        """Generate idempotency key.

        Args:
            repository_id: Repository ID.
            task_id: Task ID.
            issue_ids: List of issue IDs.
            client_key: Optional client-provided idempotency key.

        Returns:
            Idempotency key string.
        """
        if client_key:
            return f"client:{client_key}"

        # Generate key from issue IDs
        sorted_ids = sorted(issue_ids)
        data = f"{repository_id}:{task_id}:{','.join(sorted_ids)}"
        return f"auto:{hashlib.sha256(data.encode()).hexdigest()[:16]}"

    def check_and_register(
        self,
        key: str,
        session_id: str,
    ) -> tuple[bool, Optional[IdempotencyEntry]]:
        """Check if request is duplicate and register if not.

        Args:
            key: Idempotency key.
            session_id: New session ID.

        Returns:
            Tuple of (is_duplicate, existing_entry).
            If is_duplicate is True, existing_entry contains the prior request.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)

        with self._lock:
            # Clean up expired entries
            expired_keys = [
                k for k, v in self._store.items()
                if v.created_at < cutoff
            ]
            for k in expired_keys:
                del self._store[k]

            # Check for existing entry
            existing = self._store.get(key)
            if existing:
                # Only consider it a duplicate if still in progress or recent
                if existing.status == "in_progress":
                    logger.info(f"Duplicate fix request blocked (in progress): {key}")
                    return True, existing
                elif existing.created_at > cutoff:
                    logger.info(f"Duplicate fix request detected (recent): {key}")
                    return True, existing

            # Register new entry
            self._store[key] = IdempotencyEntry(
                session_id=session_id,
                status="in_progress",
            )
            return False, None

    def update_status(
        self,
        key: str,
        status: str,
        result: Optional[dict] = None,
    ) -> None:
        """Update entry status.

        Args:
            key: Idempotency key.
            status: New status.
            result: Optional result data.
        """
        with self._lock:
            if key in self._store:
                self._store[key].status = status
                self._store[key].completed_at = datetime.utcnow()
                self._store[key].result = result

    def remove(self, key: str) -> None:
        """Remove an entry (e.g., on cancellation)."""
        with self._lock:
            self._store.pop(key, None)


# Global idempotency store
_idempotency_store = IdempotencyStore()


class FixStartRequest(BaseModel):
    """Request to start fixing issues."""

    repository_id: str = Field(..., description="Repository ID")
    task_id: str = Field(..., description="Task ID that found the issues")
    issue_ids: list[str] = Field(..., min_length=1, description="Issue IDs to fix")

    # Branch handling - allows continuing on existing branch instead of creating new one
    use_existing_branch: bool = Field(
        default=False, description="If True, use existing branch instead of creating new one from main"
    )
    existing_branch_name: Optional[str] = Field(
        default=None, description="Name of existing branch to use (required if use_existing_branch=True)"
    )


class ClarificationAnswerRequest(BaseModel):
    """Request with clarification answer."""

    session_id: str = Field(..., description="Fix session ID")
    question_id: str = Field(..., description="Question ID")
    answer: str = Field(..., description="User's answer")


class IssueListResponse(BaseModel):
    """Issue list response."""

    id: str
    issue_code: str
    severity: str
    category: str
    file: str
    line: Optional[int]
    title: str
    description: str
    status: str
    created_at: datetime

    # Fix result fields (populated when resolved)
    fix_code: Optional[str] = None
    fix_explanation: Optional[str] = None
    fix_files_modified: Optional[list[str]] = None
    fix_commit_sha: Optional[str] = None
    fix_branch: Optional[str] = None
    fixed_at: Optional[datetime] = None
    fixed_by: Optional[str] = None


class IssueUpdateRequest(BaseModel):
    """Request to update issue status."""

    status: str = Field(..., description="New status")
    resolution_note: Optional[str] = Field(default=None, description="Resolution note")


@router.get("/issues/{repository_id}", response_model=list[IssueListResponse])
def list_issues(
    repository_id: str,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    task_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List issues for a repository.

    Args:
        repository_id: Repository UUID
        status: Filter by status (open, in_progress, resolved, ignored)
        severity: Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)
        task_id: Filter by task ID
    """
    query = db.query(Issue).filter(Issue.repository_id == repository_id)

    if status:
        statuses = [s.strip() for s in status.split(",")]
        query = query.filter(Issue.status.in_(statuses))

    if severity:
        severities = [s.strip() for s in severity.split(",")]
        query = query.filter(Issue.severity.in_(severities))

    if task_id:
        query = query.filter(Issue.task_id == task_id)

    issues = query.order_by(Issue.severity, Issue.created_at.desc()).all()

    return [
        IssueListResponse(
            id=i.id,
            issue_code=i.issue_code,
            severity=i.severity,
            category=i.category,
            file=i.file,
            line=i.line,
            title=i.title,
            description=i.description,
            status=i.status,
            created_at=i.created_at,
            # Fix result fields
            fix_code=i.fix_code,
            fix_explanation=i.fix_explanation,
            fix_files_modified=i.fix_files_modified,
            fix_commit_sha=i.fix_commit_sha,
            fix_branch=i.fix_branch,
            fixed_at=i.fixed_at,
            fixed_by=i.fixed_by,
        )
        for i in issues
    ]


@router.patch("/issues/{issue_id}")
def update_issue(
    issue_id: str,
    data: IssueUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update issue status."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Validate status
    valid_statuses = [s.value for s in IssueStatus]
    if data.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid: {valid_statuses}",
        )

    issue.status = data.status
    if data.resolution_note:
        issue.resolution_note = data.resolution_note

    if data.status == IssueStatus.RESOLVED.value:
        issue.resolved_at = datetime.utcnow()

    db.commit()
    db.refresh(issue)

    return {"status": "updated", "issue_id": issue_id, "new_status": data.status}


@router.post("/start")
async def start_fix(
    request: FixStartRequest,
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(
        default=None,
        description="Optional client-provided idempotency key. "
        "If not provided, a key is generated from issue IDs."
    ),
):
    """
    Start fixing issues with SSE streaming.

    Fixes are applied serially. Each fix includes:
    1. Validation that issue is still applicable
    2. Analysis for clarification needs
    3. Fix generation with Claude
    4. File modification and commit

    Idempotency:
    - If the same set of issues is already being fixed, returns 409 Conflict
    - Use X-Idempotency-Key header to track specific requests
    - Idempotency keys expire after 1 hour
    """
    import uuid

    # Generate idempotency key
    idempotency_key = _idempotency_store.generate_key(
        repository_id=request.repository_id,
        task_id=request.task_id,
        issue_ids=request.issue_ids,
        client_key=x_idempotency_key,
    )

    # Generate session ID early for idempotency tracking
    session_id = str(uuid.uuid4())

    # Check for duplicate request
    is_duplicate, existing = _idempotency_store.check_and_register(
        key=idempotency_key,
        session_id=session_id,
    )

    if is_duplicate and existing:
        if existing.status == "in_progress":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Fix session already in progress for these issues",
                    "session_id": existing.session_id,
                    "status": existing.status,
                    "started_at": existing.created_at.isoformat(),
                },
            )
        else:
            # Return previous result
            return {
                "status": "duplicate",
                "message": "Request already processed",
                "previous_session_id": existing.session_id,
                "previous_status": existing.status,
                "completed_at": existing.completed_at.isoformat() if existing.completed_at else None,
            }

    # Verify repository
    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        _idempotency_store.remove(idempotency_key)
        raise HTTPException(status_code=404, detail="Repository not found")

    # Verify task
    task = db.query(Task).filter(Task.id == request.task_id).first()
    if not task:
        _idempotency_store.remove(idempotency_key)
        raise HTTPException(status_code=404, detail="Task not found")

    # Load issues
    issues = (
        db.query(Issue)
        .filter(Issue.id.in_(request.issue_ids))
        .filter(Issue.repository_id == request.repository_id)
        .all()
    )

    if not issues:
        _idempotency_store.remove(idempotency_key)
        raise HTTPException(status_code=404, detail="No valid issues found")

    # Order issues by the requested order
    issue_order = {id: i for i, id in enumerate(request.issue_ids)}
    issues = sorted(issues, key=lambda x: issue_order.get(x.id, 999))

    # Set issues to in_progress immediately
    for issue in issues:
        issue.status = IssueStatus.IN_PROGRESS.value
    db.commit()

    # Capture for closure
    repo_path = Path(repo.local_path)
    fix_request = FixRequest(
        repository_id=request.repository_id,
        task_id=request.task_id,
        issue_ids=[i.id for i in issues],
        use_existing_branch=request.use_existing_branch,
        existing_branch_name=request.existing_branch_name,
    )

    async def generate() -> AsyncIterator[dict]:
        """Generate SSE events from fix progress."""
        event_queue: asyncio.Queue[FixProgressEvent] = asyncio.Queue()
        session_id = None

        async def progress_callback(event: FixProgressEvent):
            """Enqueue progress events."""
            nonlocal session_id
            if event.session_id:
                session_id = event.session_id
            await event_queue.put(event)

        async def run_fix():
            """Run fix in background."""
            try:
                orchestrator = FixOrchestrator(repo_path=repo_path)
                result = await orchestrator.fix_issues(
                    request=fix_request,
                    issues=issues,
                    emit=progress_callback,
                )

                # Update issue statuses in database
                completed_count = 0
                failed_count = 0
                for issue_result in result.results:
                    db_issue = db.query(Issue).filter(Issue.id == issue_result.issue_id).first()
                    if db_issue:
                        if issue_result.status.value == "completed":
                            db_issue.status = IssueStatus.RESOLVED.value
                            db_issue.resolved_at = datetime.utcnow()
                            db_issue.resolution_note = (
                                f"Fixed in commit {issue_result.commit_sha}"
                                if issue_result.commit_sha
                                else "Fixed"
                            )
                            # Save fix result fields
                            db_issue.fix_code = issue_result.fix_code
                            db_issue.fix_explanation = issue_result.fix_explanation
                            db_issue.fix_files_modified = issue_result.fix_files_modified
                            db_issue.fix_commit_sha = issue_result.commit_sha
                            db_issue.fix_branch = result.branch_name
                            db_issue.fix_session_id = result.session_id  # For S3 log retrieval
                            db_issue.fixed_at = datetime.utcnow()
                            db_issue.fixed_by = "fixer_claude"
                            completed_count += 1
                        elif issue_result.status.value == "failed":
                            db_issue.status = IssueStatus.OPEN.value  # Reset to open on failure
                            db_issue.resolution_note = f"Fix failed: {issue_result.error}"
                            failed_count += 1
                db.commit()

                # Auto-transition Linear issues to in_review after successful commit
                # Get commit_sha from first successful result (FixSessionResult doesn't have commit_sha)
                commit_sha = next((r.commit_sha for r in result.results if r.commit_sha), None)
                if commit_sha and result.branch_name:
                    try:
                        # Get task to check for linked Linear issues
                        task = db.query(Task).filter(Task.id == request.task_id).first()
                        if task:
                            # Check if task has linked Linear issues (via relationship)
                            linear_issues = db.query(LinearIssue).filter(
                                LinearIssue.task_id == task.id,
                                LinearIssue.is_active == True
                            ).all()

                            if linear_issues:
                                # Get Linear client
                                linear_api_key = db.query(Setting).filter(
                                    Setting.key == "linear_api_key"
                                ).first()

                                if linear_api_key and linear_api_key.value:
                                    linear_client = LinearClient(api_key=linear_api_key.value)
                                    state_manager = LinearStateManager(linear_client)

                                    for linear_issue in linear_issues:
                                        try:
                                            success = await state_manager.auto_transition_after_commit(
                                                linear_issue,
                                                commit_sha,  # Use extracted commit_sha, not result.commit_sha
                                                result.branch_name
                                            )
                                            if success:
                                                logger.info(
                                                    f"Auto-transitioned Linear issue {linear_issue.linear_identifier} to in_review"
                                                )
                                        except Exception as e:
                                            logger.error(
                                                f"Failed to auto-transition Linear issue {linear_issue.linear_identifier}: {e}"
                                            )

                                    # Commit Linear issue updates
                                    db.commit()
                    except Exception as e:
                        logger.error(f"Error during Linear auto-transition: {e}")
                        # Don't fail the entire fix if Linear transition fails

                # Mark idempotency entry as completed
                _idempotency_store.update_status(
                    idempotency_key,
                    "completed",
                    {
                        "completed": completed_count,
                        "failed": failed_count,
                        "total": len(result.results),
                    },
                )

            except Exception as e:
                logger.exception("Fix session error")
                # Reset all issues to open on error
                for issue in issues:
                    db_issue = db.query(Issue).filter(Issue.id == issue.id).first()
                    if db_issue and db_issue.status == IssueStatus.IN_PROGRESS.value:
                        db_issue.status = IssueStatus.OPEN.value
                db.commit()
                # Mark idempotency entry as failed
                _idempotency_store.update_status(idempotency_key, "failed")
                await event_queue.put(
                    FixProgressEvent(
                        type=FixEventType.FIX_SESSION_ERROR,
                        error=str(e),
                        message=f"Fix failed: {str(e)[:100]}",
                    )
                )
            finally:
                await event_queue.put(None)

        # Start fix task
        fix_task = asyncio.create_task(run_fix())

        try:
            # Stream events
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event.to_sse()
        except asyncio.CancelledError:
            fix_task.cancel()
            raise

    return EventSourceResponse(generate())


@router.post("/clarification/answer")
async def submit_clarification(data: ClarificationAnswerRequest):
    """
    Submit answer to a clarification question.

    This unblocks the fix process waiting for user input.
    """
    question_id = data.question_id

    if question_id not in _clarification_answers:
        raise HTTPException(
            status_code=404,
            detail="No pending clarification with this ID",
        )

    answer = ClarificationAnswer(
        question_id=question_id,
        answer=data.answer,
    )

    # Resolve the future
    future = _clarification_answers[question_id]
    if not future.done():
        future.set_result(answer)

    return {"status": "received", "question_id": question_id}


class PendingBranchInfo(BaseModel):
    """Info about a pending (unmerged) fix branch."""

    branch_name: str
    repository_id: str
    repository_name: str
    issues_count: int
    issue_codes: list[str]
    created_at: datetime


class PendingBranchesResponse(BaseModel):
    """Response with pending fix branches."""

    has_pending: bool
    branches: list[PendingBranchInfo]


@router.get("/pending-branches/{repository_id}", response_model=PendingBranchesResponse)
def get_pending_branches(
    repository_id: str,
    db: Session = Depends(get_db),
):
    """
    Check if there are unmerged fix branches for a repository.

    Returns branches with resolved issues that haven't been merged yet.
    """
    # Get repo info
    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Find issues that are "resolved" with a fix_branch set (not merged yet)
    resolved_issues = db.query(Issue).filter(
        Issue.repository_id == repository_id,
        Issue.status == IssueStatus.RESOLVED.value,
        Issue.fix_branch.isnot(None),
    ).all()

    if not resolved_issues:
        return PendingBranchesResponse(has_pending=False, branches=[])

    # Group by branch
    branches_map: dict[str, list[Issue]] = {}
    for issue in resolved_issues:
        branch = issue.fix_branch
        if branch not in branches_map:
            branches_map[branch] = []
        branches_map[branch].append(issue)

    # Build response
    branches = []
    for branch_name, issues in branches_map.items():
        branches.append(PendingBranchInfo(
            branch_name=branch_name,
            repository_id=repository_id,
            repository_name=repo.name,
            issues_count=len(issues),
            issue_codes=[i.issue_code for i in issues],
            created_at=min(i.fixed_at for i in issues if i.fixed_at) or datetime.utcnow(),
        ))

    return PendingBranchesResponse(
        has_pending=len(branches) > 0,
        branches=branches,
    )


class MergeRequest(BaseModel):
    """Request to merge fix branch to main and push."""

    repository_id: str = Field(..., description="Repository ID")
    branch_name: str = Field(..., description="Branch name to merge (e.g., fix/<task_id>)")
    task_id: Optional[str] = Field(default=None, description="Task ID to update issues to merged")


@router.post("/merge")
async def merge_and_push(
    request: MergeRequest,
    db: Session = Depends(get_db),
):
    """
    Merge fix branch to main and push to GitHub.

    Uses Claude CLI to execute git commands:
    1. git checkout main
    2. git pull origin main
    3. git merge <branch>
    4. git push origin main
    """
    # Verify repository
    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    if not repo_path.exists():
        raise HTTPException(status_code=400, detail="Repository path not found")

    # Build prompt from agent file
    merge_prompt = _load_agent(GIT_MERGER_AGENT)
    merge_prompt = merge_prompt.replace("{branch_name}", request.branch_name)

    try:
        # Build environment with API key
        env = os.environ.copy()
        api_key = get_anthropic_api_key()
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key

        # Find Claude CLI
        cli_path = "/Users/niccolocalandri/.claude/local/claude"
        if not Path(cli_path).exists():
            cli_path = "claude"  # Fallback to PATH

        # Run Claude CLI
        process = await asyncio.create_subprocess_exec(
            cli_path,
            "--print",
            "--dangerously-skip-permissions",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(repo_path),
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=merge_prompt.encode()),
            timeout=120,
        )

        output = stdout.decode() if stdout else ""
        error = stderr.decode() if stderr else ""

        if process.returncode != 0:
            logger.error(f"Merge failed: {error}")
            raise HTTPException(
                status_code=500,
                detail=f"Merge failed: {error[:500]}",
            )

        # Extract commit SHA from output (Claude should report it)
        merge_commit = None
        for line in output.split("\n"):
            if "commit" in line.lower() and len(line) > 10:
                # Try to find a SHA-like string
                sha_match = re.search(r"[a-f0-9]{7,40}", line)
                if sha_match:
                    merge_commit = sha_match.group()
                    break

        logger.info(f"Merged {request.branch_name} to main: {merge_commit}")

        # Update all RESOLVED issues for this task to MERGED
        merged_count = 0
        if request.task_id:
            issues_to_merge = (
                db.query(Issue)
                .filter(
                    Issue.task_id == request.task_id,
                    Issue.status == IssueStatus.RESOLVED.value,
                )
                .all()
            )
            for issue in issues_to_merge:
                issue.status = IssueStatus.MERGED.value
                merged_count += 1
            db.commit()
            logger.info(f"Updated {merged_count} issues to MERGED status")

        return {
            "success": True,
            "status": "merged",
            "branch_name": request.branch_name,
            "merge_commit": merge_commit,
            "merged_issues_count": merged_count,
            "message": f"Branch {request.branch_name} merged to main successfully!",
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Merge operation timed out")
    except Exception as e:
        logger.exception("Merge failed")
        raise HTTPException(status_code=500, detail=str(e))
