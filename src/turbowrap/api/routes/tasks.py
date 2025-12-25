"""Task routes."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import AsyncIterator

logger = logging.getLogger(__name__)

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

# Global registry for running review tasks (for cancellation)
_running_reviews: dict[str, asyncio.Task] = {}


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


@router.get("/{task_id}/progress")
def get_task_progress(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Get task progress details.

    Returns progress percentage, elapsed time, and estimated remaining time.
    Useful for polling task status during execution.
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Calculate elapsed time
    elapsed = None
    if task.started_at:
        if task.completed_at:
            elapsed = (task.completed_at - task.started_at).total_seconds()
        else:
            elapsed = (datetime.utcnow() - task.started_at).total_seconds()

    # Estimate remaining time
    estimated_remaining = None
    progress = task.progress or 0

    if elapsed and progress > 0 and progress < 100:
        time_per_percent = elapsed / progress
        remaining_percent = 100 - progress
        estimated_remaining = round(time_per_percent * remaining_percent, 1)

    return {
        "task_id": task.id,
        "status": task.status,
        "progress": {
            "percentage": progress,
            "message": task.progress_message,
            "elapsed_seconds": round(elapsed, 1) if elapsed else None,
            "estimated_remaining_seconds": estimated_remaining,
        },
        "is_complete": task.status in ("completed", "failed", "cancelled"),
    }


@router.get("/{task_id}/evaluation")
def get_task_evaluation(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Get evaluation metrics from a completed review task.

    Returns the RepositoryEvaluation scores (0-100) for:
    - functionality
    - code_quality
    - comment_quality
    - architecture_quality
    - effectiveness
    - code_duplication
    - overall_score (weighted average)
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task not completed")

    if not task.result:
        raise HTTPException(status_code=404, detail="No result available")

    # Extract evaluation from the stored result
    result = task.result if isinstance(task.result, dict) else json.loads(task.result)
    evaluation = result.get("evaluation")

    if not evaluation:
        raise HTTPException(status_code=404, detail="No evaluation available")

    return evaluation


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Cancel a pending or running task."""
    from ..review_manager import get_review_manager

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status: {task.status}"
        )

    # Try to remove from queue (for pending tasks)
    queue = get_task_queue()
    cancelled = queue.cancel(task_id)

    if cancelled or task.status == "pending":
        task.status = "cancelled"
        db.commit()
        return {"status": "cancelled", "id": task_id}

    # Try to cancel via ReviewManager
    manager = get_review_manager()
    if manager.cancel_review(task_id):
        task.status = "cancelled"
        task.completed_at = datetime.utcnow()
        db.commit()
        return {"status": "cancelled", "id": task_id}

    # Fallback: check old registry (for backwards compatibility)
    if task_id in _running_reviews:
        review_task = _running_reviews[task_id]
        if not review_task.done():
            review_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(review_task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        _running_reviews.pop(task_id, None)

        task.status = "cancelled"
        task.completed_at = datetime.utcnow()
        db.commit()
        return {"status": "cancelled", "id": task_id}

    # Task running but not in registries
    task.status = "cancelled"
    task.completed_at = datetime.utcnow()
    db.commit()
    return {"status": "cancelled", "id": task_id, "note": "Task marked as cancelled"}


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

    The review runs in the background and persists across client disconnections.
    Clients can reconnect and receive event history + live updates.

    Args:
        repository_id: Repository UUID
        mode: 'initial' (STRUCTURE.md architecture review) or 'diff' (changed files)

    Returns server-sent events with progress updates from all parallel reviewers.
    """
    from ..review_manager import get_review_manager
    from ...review.orchestrator import Orchestrator
    from ...review.models.review import ReviewRequest, ReviewRequestSource, ReviewOptions, ReviewMode

    # Verify repository exists
    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    manager = get_review_manager()

    # Check for existing running review for this repo
    existing_session = None
    for session in manager.get_active_sessions():
        if session.repository_id == repository_id:
            existing_session = session
            break

    if existing_session:
        # Reconnect to existing review
        task_id = existing_session.task_id
        session = existing_session
    else:
        # Create new task record
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
        task_id = task.id

        # Capture request options
        review_mode = request_body.mode
        challenger_enabled = request_body.challenger_enabled
        include_functional = request_body.include_functional
        local_path = repo.local_path

        # Create the review coroutine
        async def run_review(session):
            """Run the review in background."""
            from ...db.session import get_session_local
            SessionLocal = get_session_local()
            review_db = SessionLocal()

            try:
                orchestrator = Orchestrator()

                async def progress_callback(event: ProgressEvent):
                    """Callback to add events to session."""
                    session.add_event(event)

                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(directory=local_path),
                    options=ReviewOptions(
                        mode=ReviewMode.INITIAL if review_mode == "initial" else ReviewMode.DIFF,
                        challenger_enabled=challenger_enabled,
                        include_functional=include_functional,
                    ),
                )

                report = await orchestrator.review(request, progress_callback)

                # Update task record in new session
                db_task = review_db.query(Task).filter(Task.id == task_id).first()
                if db_task:
                    db_task.status = "completed"
                    db_task.result = report.model_dump(mode="json")
                    db_task.completed_at = datetime.utcnow()

                    # Save issues to database for tracking
                    for issue in report.issues:
                        db_issue = Issue(
                            task_id=task_id,
                            repository_id=repository_id,
                            issue_code=issue.id,
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
                            # Effort estimation for fix batching
                            estimated_effort=issue.estimated_effort,
                            estimated_files_count=issue.estimated_files_count,
                        )
                        review_db.add(db_issue)

                    review_db.commit()

            except asyncio.CancelledError:
                db_task = review_db.query(Task).filter(Task.id == task_id).first()
                if db_task:
                    db_task.status = "cancelled"
                    db_task.completed_at = datetime.utcnow()
                    review_db.commit()
                raise

            except Exception as e:
                session.add_event(ProgressEvent(
                    type=ProgressEventType.REVIEW_ERROR,
                    error=str(e),
                    message=f"Review failed: {str(e)[:100]}",
                ))

                db_task = review_db.query(Task).filter(Task.id == task_id).first()
                if db_task:
                    db_task.status = "failed"
                    db_task.error = str(e)
                    db_task.completed_at = datetime.utcnow()
                    review_db.commit()

            finally:
                review_db.close()

        # Start background review (session passed directly by manager)
        session = await manager.start_review(
            task_id=task_id,
            repository_id=repository_id,
            review_coro=run_review,
        )

    # Generator for SSE streaming
    async def generate() -> AsyncIterator[dict]:
        """Generate SSE events from review progress."""

        # Subscribe to session events
        queue = session.subscribe()

        try:
            # Emit task_started with task_id
            yield {
                "event": "task_started",
                "data": f'{{"task_id": "{task_id}", "reconnected": {str(existing_session is not None).lower()}}}',
            }

            # Replay event history for reconnecting clients
            for event in session.get_history():
                yield event.to_sse()

            # If already completed, signal done
            if session.status != "running":
                return

            # Stream live events until done
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    if event is None:
                        break

                    yield event.to_sse()

                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield {"event": "ping", "data": "{}"}

        except asyncio.CancelledError:
            # Client disconnected - DON'T cancel the review!
            pass

        finally:
            # Unsubscribe (review continues running)
            session.unsubscribe(queue)

    return EventSourceResponse(generate())


class RestartReviewerRequest(BaseModel):
    """Request body for restarting a single reviewer."""
    challenger_enabled: bool = Field(
        default=True,
        description="Enable challenger validation loop"
    )


@router.post("/{task_id}/review/restart/{reviewer_name}")
async def restart_reviewer(
    task_id: str,
    reviewer_name: str,
    request_body: RestartReviewerRequest = RestartReviewerRequest(),
    db: Session = Depends(get_db),
):
    """
    Restart a single reviewer for an existing review task.

    This endpoint allows restarting a stuck or failed reviewer without
    re-running the entire review. It will:
    1. Delete existing issues from this reviewer
    2. Re-run the reviewer with challenger loop
    3. Save new issues to the database
    4. Stream progress via SSE

    Args:
        task_id: The existing review task ID
        reviewer_name: The reviewer to restart (reviewer_be, reviewer_fe, analyst_func)

    Returns server-sent events with progress updates.
    """
    from ..review_manager import get_review_manager
    from ...review.orchestrator import Orchestrator
    from ...review.challenger_loop import ChallengerLoop
    from ...review.reviewers.base import ReviewContext
    from ...review.models.review import ReviewRequest, ReviewRequestSource, ReviewOptions, ReviewMode
    from ...review.models.progress import ProgressEvent, ProgressEventType, get_reviewer_display_name

    # Validate reviewer name (support both old and new naming conventions)
    valid_reviewers = [
        "reviewer_be", "reviewer_be_architecture", "reviewer_be_quality",
        "reviewer_fe", "reviewer_fe_architecture", "reviewer_fe_quality",
        "analyst_func"
    ]
    if reviewer_name not in valid_reviewers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid reviewer: {reviewer_name}. Must be one of: {valid_reviewers}"
        )

    # Get task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get repository
    repo = db.query(Repository).filter(Repository.id == task.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    manager = get_review_manager()
    display_name = get_reviewer_display_name(reviewer_name)

    # Create the restart coroutine
    async def run_reviewer_restart(session):
        """Run single reviewer restart in background."""
        logger.info(f"[RESTART] run_reviewer_restart called with session={session}")
        from ...db.session import get_session_local
        SessionLocal = get_session_local()
        restart_db = SessionLocal()

        try:
            logger.info(f"[RESTART] Starting restart for {reviewer_name}")
            # Emit started event
            session.add_event(ProgressEvent(
                type=ProgressEventType.REVIEWER_STARTED,
                reviewer_name=reviewer_name,
                reviewer_display_name=display_name,
                message=f"Restarting {display_name}...",
            ))

            # Build review context
            local_path = repo.local_path
            review_mode = task.config.get("mode", "initial") if task.config else "initial"
            challenger_enabled = request_body.challenger_enabled

            request = ReviewRequest(
                type="directory",
                source=ReviewRequestSource(directory=local_path),
                options=ReviewOptions(
                    mode=ReviewMode.INITIAL if review_mode == "initial" else ReviewMode.DIFF,
                    challenger_enabled=challenger_enabled,
                ),
            )

            # Prepare context (similar to orchestrator._prepare_context)
            context = ReviewContext(request=request)
            context.repo_path = Path(local_path)

            # Scan directory for files to review
            exclude_dirs = {
                ".git", "node_modules", "__pycache__", ".venv", "venv",
                ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
                "coverage", ".tox", "htmlcov",
            }
            text_extensions = {
                ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
                ".html", ".css", ".scss", ".less", ".json", ".yaml", ".yml",
                ".md", ".txt", ".rst", ".sh", ".bash", ".zsh",
                ".sql", ".graphql", ".prisma", ".env", ".toml", ".ini", ".cfg",
                ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cpp", ".h",
                ".rb", ".php", ".ex", ".exs", ".erl", ".hs", ".ml", ".scala",
            }
            files = []
            for path in context.repo_path.rglob("*"):
                if path.is_file() and path.suffix.lower() in text_extensions:
                    rel_path = path.relative_to(context.repo_path)
                    if any(part in exclude_dirs for part in rel_path.parts):
                        continue
                    files.append(str(rel_path))
            context.files = files[:100]  # Limit to 100 files
            logger.info(f"[RESTART] Found {len(context.files)} files to review")

            # Check and regenerate stale STRUCTURE.md files
            from ...tools.structure_generator import StructureGenerator

            generator = StructureGenerator(context.repo_path)
            stale_dirs = generator.check_stale_structures()

            if stale_dirs:
                logger.info(f"[RESTART] Found {len(stale_dirs)} stale STRUCTURE.md files, regenerating...")
                regenerated = generator.regenerate_stale(verbose=False)
                logger.info(f"[RESTART] Regenerated {len(regenerated)} STRUCTURE.md files")

            # Load STRUCTURE.md files
            structure_files = list(context.repo_path.rglob("STRUCTURE.md"))
            for structure_file in structure_files:
                rel_path = structure_file.relative_to(context.repo_path)
                if any(part in exclude_dirs for part in rel_path.parts):
                    continue
                try:
                    content = structure_file.read_text(encoding="utf-8")
                    context.structure_docs[str(rel_path)] = content
                except Exception:
                    pass

            # Create progress callbacks
            async def on_iteration(iteration: int, satisfaction: float, issues_count: int):
                session.add_event(ProgressEvent(
                    type=ProgressEventType.REVIEWER_ITERATION,
                    reviewer_name=reviewer_name,
                    reviewer_display_name=display_name,
                    iteration=iteration,
                    max_iterations=5,
                    satisfaction_score=satisfaction,
                    issues_found=issues_count,
                    message=f"Iteration {iteration}: {satisfaction:.1f}% satisfaction",
                ))

            async def on_content(content: str):
                session.add_event(ProgressEvent(
                    type=ProgressEventType.REVIEWER_STREAMING,
                    reviewer_name=reviewer_name,
                    reviewer_display_name=display_name,
                    content=content,
                ))

            # Run challenger loop
            loop = ChallengerLoop()
            result = await loop.run(
                context,
                reviewer_name,
                on_iteration_callback=on_iteration,
                on_content_callback=on_content,
            )

            # Delete old issues from this reviewer
            old_issues = (
                restart_db.query(Issue)
                .filter(
                    Issue.task_id == task_id,
                    Issue.flagged_by.contains([reviewer_name])
                )
                .all()
            )
            for old_issue in old_issues:
                restart_db.delete(old_issue)

            # Save new issues
            for issue in result.final_review.issues:
                db_issue = Issue(
                    task_id=task_id,
                    repository_id=task.repository_id,
                    issue_code=issue.id,
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
                    flagged_by=issue.flagged_by if issue.flagged_by else [reviewer_name],
                    # Effort estimation for fix batching
                    estimated_effort=issue.estimated_effort,
                    estimated_files_count=issue.estimated_files_count,
                )
                restart_db.add(db_issue)

            restart_db.commit()

            # Emit completed
            session.add_event(ProgressEvent(
                type=ProgressEventType.REVIEWER_COMPLETED,
                reviewer_name=reviewer_name,
                reviewer_display_name=display_name,
                iteration=result.iterations,
                satisfaction_score=result.final_satisfaction,
                issues_found=len(result.final_review.issues),
                message=f"{display_name} restarted successfully with {len(result.final_review.issues)} issues",
                model_usage=[m.model_dump() for m in result.final_review.model_usage],
            ))

        except Exception as e:
            import traceback
            logger.error(f"[RESTART] Exception in run_reviewer_restart: {e}")
            logger.error(f"[RESTART] Traceback: {traceback.format_exc()}")
            session.add_event(ProgressEvent(
                type=ProgressEventType.REVIEWER_ERROR,
                reviewer_name=reviewer_name,
                reviewer_display_name=display_name,
                error=str(e),
                message=f"{display_name} restart failed: {str(e)[:100]}",
            ))

        finally:
            restart_db.close()

    # Use a new session ID for this restart
    restart_session_id = f"{task_id}_restart_{reviewer_name}_{datetime.utcnow().strftime('%H%M%S')}"

    # Start background reviewer restart (session passed directly by manager)
    session = await manager.start_review(
        task_id=restart_session_id,
        repository_id=task.repository_id,
        review_coro=run_reviewer_restart,
    )

    # Generator for SSE streaming
    async def generate() -> AsyncIterator[dict]:
        """Generate SSE events from reviewer restart progress."""
        queue = session.subscribe()

        try:
            yield {
                "event": "restart_started",
                "data": f'{{"task_id": "{task_id}", "reviewer": "{reviewer_name}"}}',
            }

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    if event is None:
                        break

                    yield event.to_sse()

                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}

        except asyncio.CancelledError:
            pass

        finally:
            session.unsubscribe(queue)

    return EventSourceResponse(generate())
