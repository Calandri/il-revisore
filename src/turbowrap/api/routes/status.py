"""Status and health routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import get_db
from ...config import get_settings
from ...core.task_queue import get_task_queue
from ...db.models import Repository, Task

router = APIRouter(prefix="/status", tags=["status"])


@router.get("")
def health_check():
    """Basic health check."""
    return {
        "status": "ok",
        "service": "turbowrap",
        "version": "0.3.0",
    }


@router.get("/agents")
def agents_status():
    """Check AI agent availability."""
    settings = get_settings()

    gemini_ok = bool(settings.agents.effective_google_key)
    claude_ok = bool(settings.agents.anthropic_api_key)

    return {
        "gemini": {
            "available": gemini_ok,
            "model": settings.agents.gemini_model,
        },
        "claude": {
            "available": claude_ok,
            "model": settings.agents.claude_model,
        },
    }


@router.get("/queue")
def queue_status():
    """Get task queue status."""
    queue = get_task_queue()
    return queue.get_status()


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get overall statistics."""
    total_repos = db.query(Repository).count()
    active_repos = db.query(Repository).filter(Repository.status == "active").count()

    total_tasks = db.query(Task).count()
    pending_tasks = db.query(Task).filter(Task.status == "pending").count()
    running_tasks = db.query(Task).filter(Task.status == "running").count()
    completed_tasks = db.query(Task).filter(Task.status == "completed").count()
    failed_tasks = db.query(Task).filter(Task.status == "failed").count()

    return {
        "repositories": {
            "total": total_repos,
            "active": active_repos,
        },
        "tasks": {
            "total": total_tasks,
            "pending": pending_tasks,
            "running": running_tasks,
            "completed": completed_tasks,
            "failed": failed_tasks,
        },
    }


@router.get("/config")
def get_config():
    """Get non-sensitive configuration."""
    settings = get_settings()

    return {
        "repos_dir": str(settings.repos_dir),
        "agents_dir": str(settings.agents_dir),
        "task_settings": {
            "max_workers": settings.tasks.max_workers,
            "batch_size": settings.tasks.batch_size,
            "timeout_seconds": settings.tasks.timeout_seconds,
        },
        "server": {
            "host": settings.server.host,
            "port": settings.server.port,
        },
    }
