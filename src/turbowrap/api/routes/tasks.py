"""Task routes."""

from datetime import datetime
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..deps import get_db
from ..schemas.tasks import TaskCreate, TaskResponse, TaskQueueStatus
from ...core.repo_manager import RepoManager
from ...core.task_queue import get_task_queue, QueuedTask
from ...db.models import Task
from ...tasks import get_task_registry, TaskContext
from ...exceptions import TaskError

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
