"""Task routes."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from ..deps import get_db
from ..schemas.tasks import TaskCreate, TaskResponse, TaskQueueStatus
from ...core.repo_manager import RepoManager
from ...core.task_queue import get_task_queue, QueuedTask
from ...db.models import Task, Repository, Issue
from ...tasks import get_task_registry, TaskContext
from ...exceptions import TaskError
from ...review.models.progress import ProgressEvent, ProgressEventType

router = APIRouter(prefix="/tasks", tags=["tasks"])


def run_task_background(task_id: str, repo_path: str, task_type: str, config: dict):
    """Run task in background thread."""
    from ...db.session import get_session_local

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        registry = get_task_registry()
        task_instance = registry.create(task_type)

        if not task_instance:
            # Update task as failed
            db_task = db.query(Task).filter(Task.id == task_id).first()
            if db_task:
                db_task.status = "failed"
                db_task.error = f"Unknown task type: {task_type}"
                db.commit()
            return

        context = TaskContext(
            db=db,
            repo_path=Path(repo_path),
            config={**config, "task_id": task_id},
        )

        task_instance.execute(context)

    finally:
        db.close()
        # Mark as complete in queue
        queue = get_task_queue()
        queue.complete(task_id)


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    repository_id: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List tasks."""
    query = db.query(Task)

    if repository_id:
        query = query.filter(Task.repository_id == repository_id)
    if status:
        query = query.filter(Task.status == status)
    if task_type:
        query = query.filter(Task.type == task_type)

    tasks = query.order_by(Task.created_at.desc()).limit(limit).all()
    return tasks


@router.post("", response_model=TaskResponse)
def create_task(
    data: TaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create and queue a new task."""
    # Verify repository exists
    repo_manager = RepoManager(db)
    repo = repo_manager.get(data.repository_id)

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Verify task type
    registry = get_task_registry()
    if data.type not in registry.available_tasks:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task type: {data.type}. Available: {registry.available_tasks}"
        )

    # Create task record
    task = Task(
        repository_id=data.repository_id,
        type=data.type,
        status="pending",
        config=data.config,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Add to queue
    queue = get_task_queue()
    queued = QueuedTask(
        task_id=task.id,
        task_type=data.type,
        repository_id=data.repository_id,
        config=data.config,
    )
    queue.enqueue(queued)

    # Start background execution
    background_tasks.add_task(
        run_task_background,
        task.id,
        repo.local_path,
        data.type,
        data.config,
    )

    return task


@router.get("/queue", response_model=TaskQueueStatus)
def get_queue_status():
    """Get task queue status."""
    queue = get_task_queue()
    return queue.get_status()


@router.get("/types")
def list_task_types():
    """List available task types."""
    registry = get_task_registry()
    return registry.list_tasks()


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Get task details."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Cancel a pending task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status: {task.status}"
        )

    # Try to remove from queue
    queue = get_task_queue()
    cancelled = queue.cancel(task_id)

    if cancelled or task.status == "pending":
        task.status = "cancelled"
        db.commit()
        return {"status": "cancelled", "id": task_id}
    else:
        raise HTTPException(
            status_code=400,
            detail="Task is already running and cannot be cancelled"
        )


from pydantic import BaseModel, Field
from typing import Literal


class ReviewStreamRequest(BaseModel):
    """Request body for streaming review."""
    mode: Literal["initial", "diff"] = Field(
        default="initial",
        description="Review mode: 'initial' for STRUCTURE.md only, 'diff' for changed files"
    )
    challenger_enabled: bool = Field(
        default=True,
        description="Enable challenger validation loop"
    )
    include_functional: bool = Field(
        default=True,
        description="Include functional analyst reviewer"
    )


@router.post("/{repository_id}/review/stream")
async def stream_review(
    repository_id: str,
    request_body: ReviewStreamRequest = ReviewStreamRequest(),
    db: Session = Depends(get_db),
):
    """
    Start a review task and stream progress via SSE.

    Args:
        repository_id: Repository UUID
        mode: 'initial' (STRUCTURE.md architecture review) or 'diff' (changed files)

    Returns server-sent events with progress updates from all parallel reviewers.
    """
    # Verify repository exists
    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Create task record
    task = Task(
        repository_id=repository_id,
        type="review",
        status="running",
        config={
            "mode": request_body.mode,
            "challenger_enabled": request_body.challenger_enabled,
        },
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # Capture request options for use in async generator
    review_mode = request_body.mode
    challenger_enabled = request_body.challenger_enabled
    include_functional = request_body.include_functional

    async def generate() -> AsyncIterator[dict]:
        """Generate SSE events from review progress."""
        from ...review.orchestrator import Orchestrator
        from ...review.models.review import ReviewRequest, ReviewSource, ReviewOptions, ReviewMode

        # Queue for progress events
        event_queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

        async def progress_callback(event: ProgressEvent):
            """Callback to enqueue progress events."""
            await event_queue.put(event)

        async def run_review():
            """Run the review in background."""
            try:
                orchestrator = Orchestrator()

                request = ReviewRequest(
                    source=ReviewSource(directory=repo.local_path),
                    options=ReviewOptions(
                        mode=ReviewMode.INITIAL if review_mode == "initial" else ReviewMode.DIFF,
                        challenger_enabled=challenger_enabled,
                        include_functional=include_functional,
                    ),
                )

                report = await orchestrator.review(request, progress_callback)

                # Update task record
                task.status = "completed"
                task.result = report.model_dump()

                # Save issues to database for tracking
                for issue in report.issues:
                    db_issue = Issue(
                        task_id=task.id,
                        repository_id=repository_id,
                        issue_code=issue.id,  # e.g., BE-CRIT-001
                        severity=issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity),
                        category=issue.category.value if hasattr(issue.category, 'value') else str(issue.category),
                        rule=issue.rule,
                        file=issue.file,
                        line=issue.line,
                        title=issue.title,
                        description=issue.description,
                        current_code=issue.current_code,
                        suggested_fix=issue.suggested_fix,
                        references=issue.references if issue.references else None,
                        flagged_by=issue.flagged_by if issue.flagged_by else None,
                    )
                    db.add(db_issue)

                db.commit()

            except Exception as e:
                # Send error event
                await event_queue.put(ProgressEvent(
                    type=ProgressEventType.REVIEW_ERROR,
                    error=str(e),
                    message=f"Review failed: {str(e)[:100]}",
                ))

                task.status = "failed"
                task.error = str(e)
                db.commit()

            finally:
                # Signal completion
                await event_queue.put(None)

        # Start review task
        review_task = asyncio.create_task(run_review())

        # Emit initial event with task_id for cancellation support
        yield {
            "event": "task_started",
            "data": f'{{"task_id": "{task.id}"}}',
        }

        try:
            # Stream events until done
            while True:
                event = await event_queue.get()

                if event is None:
                    break

                yield event.to_sse()

        except asyncio.CancelledError:
            review_task.cancel()
            raise

    return EventSourceResponse(generate())
