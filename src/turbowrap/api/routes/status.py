"""Status and health routes."""

import time
import platform
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import get_db
from ...config import get_settings
from ...core.task_queue import get_task_queue
from ...db.models import Repository, Task, ChatSession

router = APIRouter(prefix="/status", tags=["status"])

# Track server start time
SERVER_START_TIME = datetime.now()


class ServiceStatus(BaseModel):
    """Status of a single service."""
    name: str
    status: Literal["ok", "error", "unavailable"]
    message: str | None = None
    latency_ms: float | None = None
    model: str | None = None


class FullStatus(BaseModel):
    """Complete system status."""
    server: dict
    services: list[ServiceStatus]
    database: dict
    system: dict


@router.get("")
def health_check():
    """Basic health check."""
    return {
        "status": "ok",
        "service": "turbowrap",
        "version": "0.5.0",
        "uptime_seconds": (datetime.now() - SERVER_START_TIME).total_seconds(),
    }


@router.get("/agents")
def agents_status():
    """Check AI agent availability (config only)."""
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


@router.get("/ping/claude")
def ping_claude():
    """Ping Claude API with a minimal request."""
    settings = get_settings()

    if not settings.agents.anthropic_api_key:
        return ServiceStatus(
            name="claude",
            status="unavailable",
            message="API key not configured",
            model=settings.agents.claude_model
        )

    try:
        start = time.time()
        from ...llm import ClaudeClient
        client = ClaudeClient(max_tokens=100)
        response = client.generate("Say 'ok' in one word.")
        latency = (time.time() - start) * 1000

        return ServiceStatus(
            name="claude",
            status="ok",
            message=response[:50] if response else "Empty response",
            latency_ms=round(latency, 2),
            model=settings.agents.claude_model
        )
    except Exception as e:
        return ServiceStatus(
            name="claude",
            status="error",
            message=str(e)[:100],
            model=settings.agents.claude_model
        )


@router.get("/ping/gemini")
def ping_gemini():
    """Ping Gemini API with a minimal request."""
    settings = get_settings()

    if not settings.agents.effective_google_key:
        return ServiceStatus(
            name="gemini",
            status="unavailable",
            message="API key not configured",
            model=settings.agents.gemini_model
        )

    try:
        start = time.time()
        from ...llm import GeminiClient
        client = GeminiClient()
        response = client.generate("Say 'ok' in one word.")
        latency = (time.time() - start) * 1000

        return ServiceStatus(
            name="gemini",
            status="ok",
            message=response[:50] if response else "Empty response",
            latency_ms=round(latency, 2),
            model=settings.agents.gemini_model
        )
    except Exception as e:
        return ServiceStatus(
            name="gemini",
            status="error",
            message=str(e)[:100],
            model=settings.agents.gemini_model
        )


@router.get("/ping/all")
def ping_all_services():
    """Ping all AI services."""
    return {
        "claude": ping_claude(),
        "gemini": ping_gemini(),
    }


@router.get("/system")
def system_status():
    """Get system resource usage."""
    try:
        import psutil
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "python_version": platform.python_version(),
            "cpu": {
                "count": psutil.cpu_count(),
                "percent": psutil.cpu_percent(interval=0.1),
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
            },
        }
    except ImportError:
        return {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "python_version": platform.python_version(),
            "note": "Install psutil for detailed system metrics",
        }


@router.get("/queue")
def queue_status():
    """Get task queue status."""
    queue = get_task_queue()
    return queue.get_status()


@router.get("/reviews")
def active_reviews_status():
    """Get status of active background reviews."""
    from ..review_manager import get_review_manager

    manager = get_review_manager()
    sessions = manager.get_active_sessions()

    return {
        "active_count": len(sessions),
        "reviews": [
            {
                "task_id": s.task_id,
                "repository_id": s.repository_id,
                "started_at": s.started_at.isoformat(),
                "status": s.status,
                "events_buffered": len(s.events),
                "subscribers": len(s.subscribers),
            }
            for s in sessions
        ],
    }


@router.get("/live")
def live_status():
    """
    Get real-time system status for frontend polling.

    Returns CPU, memory, and active review information.
    Designed for lightweight polling (every 2-5 seconds).
    """
    from ..review_manager import get_review_manager

    result = {
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": (datetime.now() - SERVER_START_TIME).total_seconds(),
    }

    # System metrics
    try:
        import psutil

        # CPU (non-blocking, uses last interval)
        cpu_percent = psutil.cpu_percent(interval=None)
        if cpu_percent == 0.0:
            # First call returns 0, do a quick measure
            cpu_percent = psutil.cpu_percent(interval=0.1)

        memory = psutil.virtual_memory()

        result["system"] = {
            "cpu_percent": round(cpu_percent, 1),
            "cpu_count": psutil.cpu_count(),
            "memory_percent": round(memory.percent, 1),
            "memory_used_gb": round((memory.total - memory.available) / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
        }
    except ImportError:
        result["system"] = {"error": "psutil not installed"}

    # Active reviews
    try:
        manager = get_review_manager()
        sessions = manager.get_active_sessions()
        result["reviews"] = {
            "active": len(sessions),
            "tasks": [
                {
                    "task_id": s.task_id,
                    "repository_id": s.repository_id,
                    "status": s.status,
                    "events": len(s.events),
                }
                for s in sessions
            ],
        }
    except Exception as e:
        result["reviews"] = {"error": str(e)[:100]}

    # Task queue
    try:
        queue = get_task_queue()
        q_status = queue.get_status()
        result["queue"] = {
            "pending": q_status.get("pending", 0),
            "processing": q_status.get("processing", 0),
        }
    except Exception as e:
        result["queue"] = {"error": str(e)[:100]}

    return result


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

    total_sessions = db.query(ChatSession).count()

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
        "chat_sessions": total_sessions,
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


@router.get("/full", response_model=FullStatus)
def full_status(db: Session = Depends(get_db)):
    """Get complete system status with all checks."""
    settings = get_settings()

    # Server info
    uptime = (datetime.now() - SERVER_START_TIME).total_seconds()
    server = {
        "status": "ok",
        "version": "0.5.0",
        "uptime_seconds": uptime,
        "uptime_human": format_uptime(uptime),
        "host": settings.server.host,
        "port": settings.server.port,
    }

    # Service status (config check, not live ping)
    services = []

    # Claude status
    if settings.agents.anthropic_api_key:
        services.append(ServiceStatus(
            name="claude",
            status="ok",
            message="API key configured",
            model=settings.agents.claude_model
        ))
    else:
        services.append(ServiceStatus(
            name="claude",
            status="unavailable",
            message="API key not configured"
        ))

    # Gemini status
    if settings.agents.effective_google_key:
        services.append(ServiceStatus(
            name="gemini",
            status="ok",
            message="API key configured",
            model=settings.agents.gemini_model
        ))
    else:
        services.append(ServiceStatus(
            name="gemini",
            status="unavailable",
            message="API key not configured"
        ))

    # Database stats
    try:
        total_repos = db.query(Repository).count()
        total_tasks = db.query(Task).count()
        total_sessions = db.query(ChatSession).count()
        database = {
            "status": "ok",
            "repositories": total_repos,
            "tasks": total_tasks,
            "chat_sessions": total_sessions,
        }
    except Exception as e:
        database = {
            "status": "error",
            "message": str(e)[:100],
        }

    # System resources
    try:
        import psutil
        memory = psutil.virtual_memory()
        system = {
            "platform": platform.system(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": memory.percent,
            "memory_available_gb": round(memory.available / (1024**3), 2),
        }
    except ImportError:
        system = {
            "platform": platform.system(),
            "note": "psutil not installed",
        }

    return FullStatus(
        server=server,
        services=services,
        database=database,
        system=system,
    )


def format_uptime(seconds: float) -> str:
    """Format uptime in human-readable string."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}m")

    return " ".join(parts)
