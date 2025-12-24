"""Fix routes for issue remediation."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from turbowrap.api.deps import get_db
from turbowrap.db.models import Issue, IssueStatus, Repository, Task
from turbowrap.fix import (
    ClarificationAnswer,
    ClarificationQuestion,
    FixEventType,
    FixOrchestrator,
    FixProgressEvent,
    FixRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fix", tags=["fix"])

# Store for pending clarifications (session_id -> Question)
_pending_clarifications: dict[str, ClarificationQuestion] = {}
_clarification_answers: dict[str, asyncio.Future] = {}


class FixStartRequest(BaseModel):
    """Request to start fixing issues."""

    repository_id: str = Field(..., description="Repository ID")
    task_id: str = Field(..., description="Task ID that found the issues")
    issue_ids: list[str] = Field(..., min_length=1, description="Issue IDs to fix")


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
):
    """
    Start fixing issues with SSE streaming.

    Fixes are applied serially. Each fix includes:
    1. Validation that issue is still applicable
    2. Analysis for clarification needs
    3. Fix generation with Claude
    4. File modification and commit
    """
    # Verify repository
    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Verify task
    task = db.query(Task).filter(Task.id == request.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Load issues
    issues = (
        db.query(Issue)
        .filter(Issue.id.in_(request.issue_ids))
        .filter(Issue.repository_id == request.repository_id)
        .all()
    )

    if not issues:
        raise HTTPException(status_code=404, detail="No valid issues found")

    # Order issues by the requested order
    issue_order = {id: i for i, id in enumerate(request.issue_ids)}
    issues = sorted(issues, key=lambda x: issue_order.get(x.id, 999))

    # Capture for closure
    repo_path = Path(repo.local_path)
    fix_request = FixRequest(
        repository_id=request.repository_id,
        task_id=request.task_id,
        issue_ids=[i.id for i in issues],
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

        async def answer_provider(question: ClarificationQuestion) -> ClarificationAnswer:
            """Get answer from user via SSE interaction."""
            if not session_id:
                raise RuntimeError("No session ID available")

            # Store pending question
            _pending_clarifications[question.id] = question

            # Create future for answer
            answer_future: asyncio.Future = asyncio.Future()
            _clarification_answers[question.id] = answer_future

            try:
                # Wait for answer (with timeout)
                answer = await asyncio.wait_for(answer_future, timeout=300)  # 5 min
                return answer
            except asyncio.TimeoutError:
                return ClarificationAnswer(
                    question_id=question.id,
                    answer="Proceed with default approach",
                )
            finally:
                _pending_clarifications.pop(question.id, None)
                _clarification_answers.pop(question.id, None)

        async def run_fix():
            """Run fix in background."""
            try:
                orchestrator = FixOrchestrator(repo_path=repo_path)
                result = await orchestrator.fix_issues(
                    request=fix_request,
                    issues=issues,
                    emit=progress_callback,
                    answer_provider=answer_provider,
                )

                # Update issue statuses in database
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
                        elif issue_result.status.value == "failed":
                            db_issue.resolution_note = f"Fix failed: {issue_result.error}"
                db.commit()

            except Exception as e:
                logger.exception("Fix session error")
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
