"""Fix routes for issue remediation."""

import hashlib
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from turbowrap.api.deps import get_current_user, get_db
from turbowrap.api.services.operation_tracker import get_tracker
from turbowrap.api.services.pending_question_store import (
    ScopeViolationResponse,
    get_pending_question_store,
)
from turbowrap.db.models import Issue, IssueStatus, Repository
from turbowrap.fix import ClarificationAnswer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fix", tags=["fix"])

# Agent file path for merge (used by /merge endpoint)
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
GIT_MERGER_AGENT = AGENTS_DIR / "git_merger_gemini.md"


def _load_agent(agent_path: Path) -> str:
    """Load agent prompt from MD file, stripping frontmatter."""
    if not agent_path.exists():
        logger.warning(f"Agent file not found: {agent_path}")
        return ""

    content = agent_path.read_text(encoding="utf-8")

    if content.startswith("---"):
        import re

        end_match = re.search(r"\n---\n", content[3:])
        if end_match:
            content = content[3 + end_match.end() :]

    return content.strip()


# Idempotency tracking
IDEMPOTENCY_TTL_SECONDS = 3600  # 1 hour


@dataclass
class IdempotencyEntry:
    """Entry for tracking idempotent requests."""

    session_id: str
    status: str  # "in_progress", "completed", "failed"
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    repository_id: str | None = None
    repository_name: str | None = None
    task_id: str | None = None
    issue_count: int = 0
    issue_codes: list[str] = field(default_factory=list)
    issue_ids: list[str] = field(default_factory=list)
    user_name: str | None = None
    branch_name: str | None = None


class IdempotencyStore:
    """Thread-safe store for idempotency tracking.

    Prevents duplicate fix requests for the same set of issues.
    Uses an idempotency key based on issue IDs or a client-provided header.
    """

    def __init__(self) -> None:
        self._store: dict[str, IdempotencyEntry] = {}
        self._lock = threading.RLock()

    def generate_key(
        self,
        repository_id: str,
        task_id: str,
        issue_ids: list[str],
        client_key: str | None = None,
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

        sorted_ids = sorted(issue_ids)
        data = f"{repository_id}:{task_id}:{','.join(sorted_ids)}"
        return f"auto:{hashlib.sha256(data.encode()).hexdigest()[:16]}"

    def check_and_register(
        self,
        key: str,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, IdempotencyEntry | None]:
        """Check if request is duplicate and register if not.

        Args:
            key: Idempotency key.
            session_id: New session ID.
            metadata: Optional metadata dict with repository_id, repository_name,
                      task_id, issue_count, issue_codes, user_name.

        Returns:
            Tuple of (is_duplicate, existing_entry).
            If is_duplicate is True, existing_entry contains the prior request.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=IDEMPOTENCY_TTL_SECONDS)
        metadata = metadata or {}

        with self._lock:
            expired_keys = [k for k, v in self._store.items() if v.created_at < cutoff]
            for k in expired_keys:
                del self._store[k]

            # Check for existing entry
            existing = self._store.get(key)
            if existing:
                if existing.status == "in_progress":
                    logger.info(f"Duplicate fix request blocked (in progress): {key}")
                    return True, existing
                if existing.created_at > cutoff:
                    logger.info(f"Duplicate fix request detected (recent): {key}")
                    return True, existing

            self._store[key] = IdempotencyEntry(
                session_id=session_id,
                status="in_progress",
                repository_id=metadata.get("repository_id"),
                repository_name=metadata.get("repository_name"),
                task_id=metadata.get("task_id"),
                issue_count=metadata.get("issue_count", 0),
                issue_codes=metadata.get("issue_codes", []),
                issue_ids=metadata.get("issue_ids", []),
                user_name=metadata.get("user_name"),
            )
            return False, None

    def update_branch_name(self, key: str, branch_name: str) -> None:
        """Update branch name for a session.

        Args:
            key: Idempotency key.
            branch_name: Branch name to set.
        """
        with self._lock:
            if key in self._store:
                self._store[key].branch_name = branch_name

    def update_status(
        self,
        key: str,
        status: str,
        result: dict[str, Any] | None = None,
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


_idempotency_store = IdempotencyStore()


class FixStartRequest(BaseModel):
    """Request to start fixing issues."""

    repository_id: str = Field(..., description="Repository ID")
    task_id: str = Field(..., description="Task ID that found the issues")
    issue_ids: list[str] = Field(..., min_length=1, description="Issue IDs to fix")

    use_existing_branch: bool = Field(
        default=False,
        description="If True, use existing branch instead of creating new one from main",
    )
    existing_branch_name: str | None = Field(
        default=None,
        description="Name of existing branch to use (required if use_existing_branch=True)",
    )

    # Force restart - bypasses idempotency check for stuck sessions
    force: bool = Field(
        default=False,
        description=(
            "Force restart even if a session is already in progress (use when session is stuck)"
        ),
    )

    user_notes: str | None = Field(
        default=None,
        description="Optional user notes with additional context or instructions for the fixer",
    )

    # Session from pre-fix clarification phase
    clarify_session_id: str | None = Field(
        default=None,
        description="Session ID from pre-fix clarification phase (for resume with context)",
    )

    # Master TODO path from planning phase
    master_todo_path: str | None = Field(
        default=None,
        description="Path to master_todo.json from planning phase (for step-by-step execution)",
    )


# Pre-fix Clarification Models
class PreFixClarifyQuestion(BaseModel):
    """Question from pre-fix clarification phase."""

    id: str = Field(..., description="Question ID (e.g., 'q1', 'q2')")
    question: str = Field(..., description="The question text")
    context: str | None = Field(default=None, description="Why this information is needed")


class PreFixClarifyQuestionGroup(BaseModel):
    """Questions grouped by issue."""

    issue_code: str = Field(..., description="Issue code (e.g., BE-001)")
    questions: list[PreFixClarifyQuestion] = Field(default_factory=list)


class PreFixClarifyRequest(BaseModel):
    """Request for pre-fix clarification."""

    repository_id: str = Field(..., description="Repository ID")
    issue_ids: list[str] = Field(..., min_length=1, description="Issue IDs to analyze")
    session_id: str | None = Field(
        default=None, description="Session ID for resume (from previous clarify call)"
    )
    answers: dict[str, str] | None = Field(
        default=None, description="Answers to previous questions (key=question_id, value=answer)"
    )
    previous_questions: list[PreFixClarifyQuestion] | None = Field(
        default=None, description="Previous questions for context in resume"
    )


class PreFixClarifyResponse(BaseModel):
    """Response from pre-fix clarification."""

    has_questions: bool = Field(..., description="Whether there are questions")
    questions: list[PreFixClarifyQuestion] = Field(
        default_factory=list, description="Questions for the user (flat list)"
    )
    questions_by_issue: list[PreFixClarifyQuestionGroup] = Field(
        default_factory=list, description="Questions grouped by issue"
    )
    message: str = Field(..., description="AI message explaining the analysis")
    session_id: str = Field(..., description="Session ID for resume")
    ready_to_fix: bool = Field(..., description="Whether ready to proceed with fix")


# Planning Phase Models (for POST /fix/plan)
class FixPlanRequest(BaseModel):
    """Request for fix planning phase."""

    repository_id: str = Field(..., description="Repository ID")
    issue_ids: list[str] = Field(..., min_length=1, description="Issue IDs to plan")
    clarify_session_id: str = Field(
        ..., description="Session ID from clarification phase (required)"
    )


class FixPlanStepInfo(BaseModel):
    """Info about an execution step in the plan."""

    step: int = Field(..., description="Step number (1-based)")
    issue_codes: list[str] = Field(..., description="Issue codes in this step")
    reason: str | None = Field(default=None, description="Why grouped together")


class FixPlanResponse(BaseModel):
    """Response from fix planning phase."""

    session_id: str = Field(..., description="Fix session ID")
    master_todo_path: str = Field(..., description="Path to master_todo.json")
    issue_count: int = Field(..., description="Number of issues planned")
    step_count: int = Field(..., description="Number of execution steps")
    execution_steps: list[FixPlanStepInfo] = Field(..., description="Summary of execution steps")
    ready_to_execute: bool = Field(default=True, description="Whether ready to execute fixes")


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
    line: int | None
    title: str
    description: str
    status: str
    created_at: datetime

    fix_code: str | None = None
    fix_explanation: str | None = None
    fix_files_modified: list[str] | None = None
    fix_commit_sha: str | None = None
    fix_branch: str | None = None
    fixed_at: datetime | None = None
    fixed_by: str | None = None

    class Config:
        from_attributes = True


class IssueUpdateRequest(BaseModel):
    """Request to update issue status."""

    status: str = Field(..., description="New status")
    resolution_note: str | None = Field(default=None, description="Resolution note")


@router.get("/issues/{repository_id}", response_model=list[IssueListResponse])
def list_issues(
    repository_id: str,
    status: str | None = None,
    severity: str | None = None,
    task_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[IssueListResponse]:
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

    issues: list[Issue] = query.order_by(Issue.severity, Issue.created_at.desc()).all()
    return issues  # type: ignore[return-value]


@router.patch("/issues/{issue_id}")
def update_issue(
    issue_id: str,
    data: IssueUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update issue status."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    valid_statuses = [s.value for s in IssueStatus]
    if data.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Valid: {valid_statuses}",
        )

    issue.status = data.status  # type: ignore[assignment]
    if data.resolution_note:
        issue.resolution_note = data.resolution_note  # type: ignore[assignment]

    if data.status == IssueStatus.RESOLVED.value:
        issue.resolved_at = datetime.utcnow()  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)

    return {"status": "updated", "issue_id": issue_id, "new_status": data.status}


@router.post("/clarify", response_model=PreFixClarifyResponse)
async def clarify_before_fix(
    request: PreFixClarifyRequest,
    db: Session = Depends(get_db),
) -> PreFixClarifyResponse:
    """
    Pre-fix clarification phase with OPUS.

    Call this before /start to let OPUS analyze the issues and ask questions.
    Loop until ready_to_fix=true, then proceed to /start with clarify_session_id.

    Flow:
    1. First call: OPUS analyzes issues, may ask questions
    2. If has_questions=true: show questions to user, get answers
    3. Call again with session_id + answers
    4. Repeat until ready_to_fix=true
    5. Call /start with clarify_session_id for context preservation
    """
    from turbowrap.api.services.fix_clarify_service import (
        ClarifyQuestion,
        FixClarifyService,
    )

    # Load repository
    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Load issues
    issues = db.query(Issue).filter(Issue.id.in_(request.issue_ids)).all()
    if not issues:
        raise HTTPException(status_code=404, detail="No issues found")

    # Convert request questions to service format
    previous_questions: list[ClarifyQuestion] | None = None
    if request.previous_questions:
        previous_questions = [
            ClarifyQuestion(id=q.id, question=q.question, context=q.context)
            for q in request.previous_questions
        ]

    # Run clarification service
    try:
        service = FixClarifyService(repo, db)
        result = await service.clarify(
            issues=issues,
            session_id=request.session_id,
            answers=request.answers,
            previous_questions=previous_questions,
        )
    except Exception as e:
        logger.exception(f"Clarification failed: {e}")
        raise HTTPException(status_code=500, detail=f"Clarification failed: {e}")

    # Convert service result to response model
    return PreFixClarifyResponse(
        has_questions=result.has_questions,
        questions=[
            PreFixClarifyQuestion(id=q.id, question=q.question, context=q.context)
            for q in result.questions
        ],
        questions_by_issue=[
            PreFixClarifyQuestionGroup(
                issue_code=g.issue_code,
                questions=[
                    PreFixClarifyQuestion(id=q.id, question=q.question, context=q.context)
                    for q in g.questions
                ],
            )
            for g in result.questions_by_issue
        ],
        message=result.message,
        session_id=result.session_id,
        ready_to_fix=result.ready_to_fix,
    )


@router.post("/plan", response_model=FixPlanResponse)
async def create_fix_plan(
    request: FixPlanRequest,
    db: Session = Depends(get_db),
) -> FixPlanResponse:
    """
    Create execution plan for fixing issues.

    Called after clarification is complete (ready_to_fix=true).
    Generates:
    - Master TODO with execution steps
    - Individual Issue TODOs with context and plan

    Flow:
    1. Resume clarify session
    2. Run planner to analyze issues and generate TODO files
    3. Save TODO files locally and to S3
    4. Return plan summary
    """
    from turbowrap.api.services.fix_plan_service import FixPlanService

    # Load repository
    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Load issues
    issues = db.query(Issue).filter(Issue.id.in_(request.issue_ids)).all()
    if not issues:
        raise HTTPException(status_code=404, detail="No issues found")

    # Run planning service
    try:
        service = FixPlanService(repo, db)
        result = await service.create_plan(
            issues=issues,
            clarify_session_id=request.clarify_session_id,
        )
    except Exception as e:
        logger.exception(f"[PLAN] Planning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Planning failed: {e}")

    # Convert service result to response model
    return FixPlanResponse(
        session_id=result.session_id,
        master_todo_path=result.master_todo_path,
        issue_count=result.issue_count,
        step_count=result.step_count,
        execution_steps=[
            FixPlanStepInfo(
                step=s.step,
                issue_codes=s.issue_codes,
                reason=s.reason,
            )
            for s in result.execution_steps
        ],
        ready_to_execute=result.ready_to_execute,
    )


@router.post("/start", response_model=None)
async def start_fix(
    request: FixStartRequest,
    db: Session = Depends(get_db),
    current_user: dict[str, Any] | None = Depends(get_current_user),
    x_idempotency_key: str | None = Header(
        default=None,
        description="Optional client-provided idempotency key. "
        "If not provided, a key is generated from issue IDs.",
    ),
) -> EventSourceResponse | dict[str, Any]:
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
    from ..services.fix_session_service import DuplicateSessionError, get_fix_session_service

    # Extract user name for session display
    user_name = None
    if current_user:
        user_name = current_user.get("username") or current_user.get("email") or "unknown"

    service = get_fix_session_service(db)

    try:
        session_info, duplicate_response = service.validate_and_prepare(
            repository_id=request.repository_id,
            task_id=request.task_id,
            issue_ids=request.issue_ids,
            use_existing_branch=request.use_existing_branch,
            existing_branch_name=request.existing_branch_name,
            client_idempotency_key=x_idempotency_key,
            force=request.force,
            user_name=user_name,
            user_notes=request.user_notes,
            clarify_session_id=request.clarify_session_id,
            master_todo_path=request.master_todo_path,
        )

        # Handle duplicate request (already processed)
        if duplicate_response:
            return duplicate_response

        assert session_info is not None

        # Update FIX wrapper phase to "fixing"
        if request.clarify_session_id:
            tracker = get_tracker()
            updated = tracker.update(
                request.clarify_session_id,
                details={"phase": "fixing"},
            )
            if not updated:
                logger.warning(
                    f"[START] FIX wrapper operation not found: {request.clarify_session_id}"
                )

        return EventSourceResponse(service.execute_fixes(session_info))

    except DuplicateSessionError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Fix session already in progress for these issues",
                "session_id": e.session_id,
                "status": e.status,
                "started_at": e.created_at.isoformat(),
                "hint": "Use force=true to restart if the session is stuck",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/clarification/answer")
async def submit_clarification(data: ClarificationAnswerRequest) -> dict[str, str]:
    """
    Submit answer to a clarification question.

    This unblocks the fix process waiting for user input.
    """
    question_id = data.question_id
    store = get_pending_question_store()

    if not store.has_pending_clarification(question_id):
        raise HTTPException(
            status_code=404,
            detail="No pending clarification with this ID",
        )

    answer = ClarificationAnswer(
        question_id=question_id,
        answer=data.answer,
    )

    store.resolve_clarification(question_id, answer)

    return {"status": "received", "question_id": question_id}


class ScopeResponseRequest(BaseModel):
    """Request body for scope violation response."""

    allow: bool = Field(..., description="Whether to allow the paths and continue")


@router.post("/sessions/{session_id}/scope-response")
async def respond_to_scope_violation(
    session_id: str,
    data: ScopeResponseRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Respond to a scope violation prompt.

    When the fix orchestrator detects files modified outside the workspace scope,
    it sends a FIX_SCOPE_VIOLATION_PROMPT event via SSE and waits for user response.
    This endpoint allows the user to:
    - allow=True: Add the paths to the repository's allowed_extra_paths and continue
    - allow=False: Cancel the fix and revert all changes
    """
    question_id = f"scope_{session_id}"
    store = get_pending_question_store()

    if not store.has_pending_scope_violation(question_id):
        raise HTTPException(
            status_code=404,
            detail="No pending scope violation for this session",
        )

    pending = store.get_scope_violation(question_id) or {}
    response = ScopeViolationResponse(
        allow=data.allow,
        paths=pending.get("dirs", []),
    )

    store.resolve_scope_violation(question_id, response)
    store.remove_scope_violation(question_id)

    return {
        "status": "received",
        "session_id": session_id,
        "allow": data.allow,
        "paths": response.paths,
    }


STALE_SESSION_TIMEOUT_SECONDS = 30 * 60


class ActiveSessionInfo(BaseModel):
    """Info about an active fix session."""

    session_id: str
    status: str
    started_at: datetime
    is_stale: bool  # True if session is older than STALE_SESSION_TIMEOUT
    repository_id: str | None = None
    repository_name: str | None = None
    task_id: str | None = None
    branch_name: str | None = None
    user_name: str | None = None
    issue_count: int = 0
    issue_codes: list[str] = []
    issue_ids: list[str] = []


class ActiveSessionsResponse(BaseModel):
    """Response with active fix sessions."""

    sessions: list[ActiveSessionInfo]
    total: int


@router.get("/sessions/active", response_model=ActiveSessionsResponse)
def list_active_sessions() -> ActiveSessionsResponse:
    """
    List all active (in_progress) fix sessions.

    Sessions older than 30 minutes are marked as stale.
    Includes metadata for banner display: repo, branch, user, issues.
    """
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=STALE_SESSION_TIMEOUT_SECONDS)

    sessions = []
    with _idempotency_store._lock:
        for _key, entry in _idempotency_store._store.items():
            if entry.status == "in_progress":
                sessions.append(
                    ActiveSessionInfo(
                        session_id=entry.session_id,
                        status=entry.status,
                        started_at=entry.created_at,
                        is_stale=entry.created_at < stale_cutoff,
                        repository_id=entry.repository_id,
                        repository_name=entry.repository_name,
                        task_id=entry.task_id,
                        branch_name=entry.branch_name,
                        user_name=entry.user_name,
                        issue_count=entry.issue_count,
                        issue_codes=entry.issue_codes,
                        issue_ids=entry.issue_ids,
                    )
                )

    return ActiveSessionsResponse(sessions=sessions, total=len(sessions))


@router.delete("/sessions/{session_id}")
def cancel_session(session_id: str) -> dict[str, str]:
    """
    Cancel a stuck fix session by session ID.

    Use this when a session is stuck in 'in_progress' and needs to be cleared.
    """
    removed = False
    with _idempotency_store._lock:
        keys_to_remove = []
        for key, entry in _idempotency_store._store.items():
            if entry.session_id == session_id:
                keys_to_remove.append(key)
                removed = True

        for key in keys_to_remove:
            del _idempotency_store._store[key]
            logger.info(f"Cancelled fix session: {session_id} (key: {key})")

    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found or already completed",
        )

    return {"status": "cancelled", "session_id": session_id}


@router.delete("/sessions/stale")
def clear_stale_sessions() -> dict[str, Any]:
    """
    Clear all stale (stuck) fix sessions.

    Removes sessions that have been in_progress for more than 30 minutes.
    """
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=STALE_SESSION_TIMEOUT_SECONDS)

    cleared = []
    with _idempotency_store._lock:
        keys_to_remove = []
        for key, entry in _idempotency_store._store.items():
            if entry.status == "in_progress" and entry.created_at < stale_cutoff:
                keys_to_remove.append(key)
                cleared.append(entry.session_id)

        for key in keys_to_remove:
            del _idempotency_store._store[key]
            logger.info(f"Cleared stale session (key: {key})")

    return {
        "status": "cleared",
        "cleared_count": len(cleared),
        "cleared_sessions": cleared,
    }


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
) -> PendingBranchesResponse:
    """
    Check if there are unmerged fix branches for a repository.

    Returns branches with resolved issues that haven't been merged yet.
    """
    # Get repo info
    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    resolved_issues = (
        db.query(Issue)
        .filter(
            Issue.repository_id == repository_id,
            Issue.status == IssueStatus.RESOLVED.value,
            Issue.fix_branch.isnot(None),
        )
        .all()
    )

    if not resolved_issues:
        return PendingBranchesResponse(has_pending=False, branches=[])

    branches_map: dict[str, list[Issue]] = {}
    for issue in resolved_issues:
        branch = str(issue.fix_branch)  # Cast Column[str] to str
        if branch not in branches_map:
            branches_map[branch] = []
        branches_map[branch].append(issue)

    # Build response
    branches = []
    repo_name = str(repo.name)  # Cast Column[str] to str
    for branch_name, issues in branches_map.items():
        fixed_times = [cast(datetime, i.fixed_at) for i in issues if i.fixed_at]
        created_at = min(fixed_times) if fixed_times else datetime.utcnow()
        branches.append(
            PendingBranchInfo(
                branch_name=branch_name,
                repository_id=repository_id,
                repository_name=repo_name,
                issues_count=len(issues),
                issue_codes=[str(i.issue_code) for i in issues],
                created_at=created_at,
            )
        )

    return PendingBranchesResponse(
        has_pending=len(branches) > 0,
        branches=branches,
    )


class MergeRequest(BaseModel):
    """Request to merge fix branch to main and push."""

    repository_id: str = Field(..., description="Repository ID")
    branch_name: str = Field(..., description="Branch name to merge (e.g., fix/<task_id>)")
    task_id: str | None = Field(default=None, description="Task ID to update issues to merged")


@router.post("/merge")
async def merge_and_push(
    request: MergeRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Merge fix branch to main and push to GitHub.

    Uses Gemini CLI Flash to:
    1. Checkout main, pull, merge, push
    2. Automatically resolve conflicts if any
    """
    from ...llm.gemini import GeminiCLI

    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = Path(repo.local_path)
    if not repo_path.exists():
        raise HTTPException(status_code=400, detail="Repository path not found")

    merge_prompt = _load_agent(GIT_MERGER_AGENT)
    merge_prompt = merge_prompt.replace("{branch_name}", request.branch_name)

    # Run Gemini CLI Flash
    gemini = GeminiCLI(
        working_dir=repo_path,
        model="flash",
        timeout=300,
        s3_prefix="git-merge",
    )

    logger.info(f"[MERGE] Starting merge for branch: {request.branch_name} on repo: {repo.name}")

    result = await gemini.run(
        prompt=merge_prompt,
        context_id=f"merge-{request.branch_name}-{datetime.now().strftime('%H%M%S')}",
        # Explicit tracking parameters
        operation_type="git_merge",
        repo_name=str(repo.name) if repo.name else "unknown",
    )

    logger.info(f"[MERGE] Completed: success={result.success}")

    if not result.success:
        logger.error(f"Merge failed: {result.error}")
        raise HTTPException(status_code=500, detail=result.error or "Merge failed")

    # Extract commit SHA from output
    merge_commit = None
    for line in result.output.split("\n"):
        if "commit" in line.lower():
            sha_match = re.search(r"[a-f0-9]{7,40}", line)
            if sha_match:
                merge_commit = sha_match.group()
                break

    logger.info(f"Merged {request.branch_name} to main: {merge_commit}")

    # Update issues to MERGED status
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
            issue.status = IssueStatus.MERGED.value  # type: ignore[assignment]
            merged_count += 1
        db.commit()

    return {
        "success": True,
        "status": "merged",
        "branch_name": request.branch_name,
        "merge_commit": merge_commit,
        "merged_issues_count": merged_count,
        "message": f"Branch {request.branch_name} merged to main!",
    }


class OpenPRRequest(BaseModel):
    """Request to open a PR for review."""

    repository_id: str = Field(..., description="Repository ID")
    branch_name: str = Field(..., description="Branch name to create PR from")
    task_id: str | None = Field(default=None, description="Task ID to get fixed issues")


@router.post("/open-pr")
async def open_pull_request(
    request: OpenPRRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Open a PR on GitHub for the fix branch.

    Creates a PR with:
    - Title: "TurboWrap Fixes: <branch_name>"
    - Body: List of fixed issues from the task
    """
    from turbowrap.review.integrations.github import GitHubClient

    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not repo.url:
        raise HTTPException(status_code=400, detail="Repository URL not configured")

    # Get fixed issues for PR body
    fixed_issues = []
    if request.task_id:
        issues = (
            db.query(Issue)
            .filter(
                Issue.task_id == request.task_id,
                Issue.status == IssueStatus.RESOLVED.value,
            )
            .all()
        )
        fixed_issues = [f"- [{i.issue_code}] {i.title}" for i in issues]

    # Build PR title and body
    pr_title = f"TurboWrap Fixes: {request.branch_name}"
    pr_body = "## Fixed Issues\n\n"
    if fixed_issues:
        pr_body += "\n".join(fixed_issues)
    else:
        pr_body += "_No issues tracked_"
    pr_body += "\n\n---\n_Created by TurboWrap_"

    try:
        github = GitHubClient()
        result = github.create_pull_request(
            repo_url=repo.url,
            branch_name=request.branch_name,
            title=pr_title,
            body=pr_body,
        )

        logger.info(f"PR created: {result['url']}")

        return {
            "success": True,
            "pr_url": result["url"],
            "pr_number": result["number"],
            "message": f"PR #{result['number']} created successfully!",
        }

    except Exception as e:
        logger.exception("Failed to create PR")
        raise HTTPException(status_code=500, detail=str(e))
