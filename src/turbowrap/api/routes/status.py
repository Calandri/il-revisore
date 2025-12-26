"""Status and health routes."""

import asyncio
import json
import logging
import platform
import time
from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal
from weakref import WeakSet

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ...config import get_settings
from ...core.task_queue import get_task_queue
from ...db.models import ChatSession, Issue, LinearIssue, Repository, Task
from ..deps import get_db

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
        "version": "0.6.0",
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
            model=settings.agents.claude_model,
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
            model=settings.agents.claude_model,
        )
    except Exception as e:
        return ServiceStatus(
            name="claude", status="error", message=str(e)[:100], model=settings.agents.claude_model
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
            model=settings.agents.gemini_model,
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
            model=settings.agents.gemini_model,
        )
    except Exception as e:
        return ServiceStatus(
            name="gemini", status="error", message=str(e)[:100], model=settings.agents.gemini_model
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

    # CLI processes (claude/gemini)
    try:
        import psutil

        cli_processes = []
        now = time.time()

        for proc in psutil.process_iter(["name", "memory_percent", "cpu_percent"]):
            try:
                name = proc.info["name"].lower()
                if name in ("claude", "gemini", "node"):
                    cmdline_list = proc.cmdline()
                    cmdline = " ".join(cmdline_list).lower()
                    if "claude" in cmdline or "gemini" in cmdline:
                        # Get additional process info
                        cwd = None
                        try:
                            cwd = proc.cwd()
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            pass

                        elapsed_seconds = 0
                        try:
                            elapsed_seconds = int(now - proc.create_time())
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            pass

                        cpu = 0
                        try:
                            cpu = proc.cpu_percent(interval=None)
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            pass

                        status = "unknown"
                        try:
                            status = proc.status()
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            pass

                        # Extract repo name from cwd
                        repo_name = cwd.rstrip("/").split("/")[-1] if cwd else None

                        # Format elapsed time
                        if elapsed_seconds < 60:
                            elapsed_str = f"{elapsed_seconds}s"
                        elif elapsed_seconds < 3600:
                            elapsed_str = f"{elapsed_seconds // 60}m {elapsed_seconds % 60}s"
                        else:
                            elapsed_str = (
                                f"{elapsed_seconds // 3600}h {(elapsed_seconds % 3600) // 60}m"
                            )

                        # Extract meaningful cmdline info
                        cmdline_short = " ".join(cmdline_list[1:4]) if len(cmdline_list) > 1 else ""
                        if len(cmdline_short) > 60:
                            cmdline_short = cmdline_short[:57] + "..."

                        cli_processes.append(
                            {
                                "name": "claude" if "claude" in cmdline else "gemini",
                                "pid": proc.pid,
                                "memory_percent": round(proc.info["memory_percent"] or 0, 1),
                                "cpu_percent": round(cpu, 1),
                                "status": status,
                                "cwd": cwd,
                                "repo_name": repo_name,
                                "elapsed": elapsed_str,
                                "elapsed_seconds": elapsed_seconds,
                                "cmdline": cmdline_short,
                            }
                        )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        result["cli_processes"] = {
            "count": len(cli_processes),
            "processes": cli_processes[:10],
        }
    except Exception as e:
        result["cli_processes"] = {"count": 0, "error": str(e)[:50]}

    # Docker/Container build processes
    try:
        import psutil

        build_processes = []
        now = time.time()

        for proc in psutil.process_iter(["name", "memory_percent", "cpu_percent"]):
            try:
                name = proc.info["name"].lower()
                # Detect docker, docker-compose, buildx, podman, buildah
                if name in (
                    "docker",
                    "docker-compose",
                    "podman",
                    "buildah",
                    "buildx",
                    "containerd",
                ):
                    cmdline_list = proc.cmdline()
                    cmdline = " ".join(cmdline_list).lower()

                    # Check if it's a build operation
                    is_build = any(
                        kw in cmdline for kw in ["build", "push", "pull", "compose up", "run"]
                    )
                    if not is_build:
                        continue

                    # Get additional process info
                    cwd = None
                    try:
                        cwd = proc.cwd()
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    elapsed_seconds = 0
                    try:
                        elapsed_seconds = int(now - proc.create_time())
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    cpu = 0
                    try:
                        cpu = proc.cpu_percent(interval=None)
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    status = "unknown"
                    try:
                        status = proc.status()
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    # Determine operation type
                    if "build" in cmdline:
                        op_type = "build"
                    elif "push" in cmdline:
                        op_type = "push"
                    elif "pull" in cmdline:
                        op_type = "pull"
                    elif "compose up" in cmdline or "up -d" in cmdline:
                        op_type = "up"
                    elif "run" in cmdline:
                        op_type = "run"
                    else:
                        op_type = "other"

                    # Extract image/service name from cmdline
                    image_name = None
                    # Try to find -t flag for build
                    if "-t " in cmdline:
                        parts = cmdline.split("-t ")
                        if len(parts) > 1:
                            image_name = parts[1].split()[0].split(":")[0]
                    # Or look for Dockerfile context
                    elif "-f " in cmdline:
                        parts = cmdline.split("-f ")
                        if len(parts) > 1:
                            image_name = parts[1].split()[0]

                    # Extract repo/project name from cwd
                    project_name = cwd.rstrip("/").split("/")[-1] if cwd else None

                    # Format elapsed time
                    if elapsed_seconds < 60:
                        elapsed_str = f"{elapsed_seconds}s"
                    elif elapsed_seconds < 3600:
                        elapsed_str = f"{elapsed_seconds // 60}m {elapsed_seconds % 60}s"
                    else:
                        elapsed_str = (
                            f"{elapsed_seconds // 3600}h {(elapsed_seconds % 3600) // 60}m"
                        )

                    # Extract meaningful cmdline info
                    cmdline_short = " ".join(cmdline_list[:5]) if cmdline_list else ""
                    if len(cmdline_short) > 80:
                        cmdline_short = cmdline_short[:77] + "..."

                    build_processes.append(
                        {
                            "tool": name,  # docker, podman, etc
                            "operation": op_type,
                            "pid": proc.pid,
                            "memory_percent": round(proc.info["memory_percent"] or 0, 1),
                            "cpu_percent": round(cpu, 1),
                            "status": status,
                            "cwd": cwd,
                            "project_name": project_name,
                            "image_name": image_name,
                            "elapsed": elapsed_str,
                            "elapsed_seconds": elapsed_seconds,
                            "cmdline": cmdline_short,
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        result["build_processes"] = {
            "count": len(build_processes),
            "processes": build_processes[:10],
        }
    except Exception as e:
        result["build_processes"] = {"count": 0, "error": str(e)[:50]}

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
        "version": "0.6.0",
        "uptime_seconds": uptime,
        "uptime_human": format_uptime(uptime),
        "host": settings.server.host,
        "port": settings.server.port,
    }

    # Service status (config check, not live ping)
    services = []

    # Claude status
    if settings.agents.anthropic_api_key:
        services.append(
            ServiceStatus(
                name="claude",
                status="ok",
                message="API key configured",
                model=settings.agents.claude_model,
            )
        )
    else:
        services.append(
            ServiceStatus(name="claude", status="unavailable", message="API key not configured")
        )

    # Gemini status
    if settings.agents.effective_google_key:
        services.append(
            ServiceStatus(
                name="gemini",
                status="ok",
                message="API key configured",
                model=settings.agents.gemini_model,
            )
        )
    else:
        services.append(
            ServiceStatus(name="gemini", status="unavailable", message="API key not configured")
        )

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


@router.get("/active-development")
def get_active_development(db: Session = Depends(get_db)):
    """
    Get currently active development issues (both Linear and GitHub).

    Returns a unified list of active issues for the sidebar banner.
    """
    active_issues = []

    # Get active Linear issues
    linear_issues = (
        db.query(LinearIssue).filter(LinearIssue.is_active, LinearIssue.deleted_at.is_(None)).all()
    )

    for li in linear_issues:
        # Get repository names
        repo_names = []
        for link in li.repository_links:
            if link.repository:
                repo_names.append(link.repository.name)

        active_issues.append(
            {
                "type": "linear",
                "id": li.id,
                "identifier": li.linear_identifier,
                "title": li.title,
                "url": li.linear_url,
                "repository_names": repo_names[:3],  # Max 3
                "fix_branch": li.fix_branch,
                "fix_commit_sha": li.fix_commit_sha,
                "turbowrap_state": li.turbowrap_state,
            }
        )

    # Get active GitHub issues
    github_issues = db.query(Issue).filter(Issue.is_active, Issue.deleted_at.is_(None)).all()

    for gi in github_issues:
        active_issues.append(
            {
                "type": "github",
                "id": gi.id,
                "identifier": gi.issue_code,
                "title": gi.title,
                "url": None,  # GitHub issues don't have external URLs
                "repository_names": [gi.repository.name] if gi.repository else [],
                "fix_branch": gi.fix_branch,
                "fix_commit_sha": gi.fix_commit_sha,
                "status": gi.status,
                "severity": gi.severity,
            }
        )

    return active_issues


# =============================================================================
# Application Logs Streaming
# =============================================================================

# Global log buffer and subscribers
_log_buffer: deque = deque(maxlen=500)  # Keep last 500 logs
_log_subscribers: WeakSet = WeakSet()


class SSELogHandler(logging.Handler):
    """Custom log handler that stores logs for SSE streaming."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = {
                "content": self.format(record),
                "level": record.levelname,
                "timestamp": datetime.utcnow().isoformat(),
                "logger": record.name,
            }
            _log_buffer.append(log_entry)

            # Notify all subscribers
            for queue in list(_log_subscribers):
                try:
                    queue.put_nowait(log_entry)
                except Exception:
                    pass  # Queue full or closed
        except Exception:
            pass  # Never fail in log handler


def setup_sse_logging():
    """Setup SSE log handler on root logger."""
    handler = SSELogHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    # Add to root logger
    root_logger = logging.getLogger()
    # Check if already added
    for h in root_logger.handlers:
        if isinstance(h, SSELogHandler):
            return  # Already setup
    root_logger.addHandler(handler)


# Setup on module load
setup_sse_logging()


async def generate_app_logs(level: str = "all") -> AsyncIterator[dict]:
    """
    Generator that streams application logs via SSE.

    Args:
        level: Filter level - 'all', 'warning', 'error'
    """
    # Create a queue for this subscriber
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _log_subscribers.add(queue)

    try:
        # Send connected event
        yield {
            "event": "connected",
            "data": json.dumps(
                {
                    "message": "Connected to TurboWrap logs",
                    "container": "turbowrap-app",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ),
        }

        # Send buffered logs first (last 100)
        for log_entry in list(_log_buffer)[-100:]:
            if _should_include_log(log_entry, level):
                yield {
                    "event": "log",
                    "data": json.dumps(log_entry),
                }

        # Stream new logs
        while True:
            try:
                log_entry = await asyncio.wait_for(queue.get(), timeout=30.0)
                if _should_include_log(log_entry, level):
                    yield {
                        "event": "log",
                        "data": json.dumps(log_entry),
                    }
            except asyncio.TimeoutError:
                # Send keepalive
                yield {
                    "event": "ping",
                    "data": json.dumps({"timestamp": datetime.utcnow().isoformat()}),
                }

    except asyncio.CancelledError:
        raise
    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "message": f"Error streaming logs: {e}",
                    "level": "ERROR",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ),
        }
    finally:
        _log_subscribers.discard(queue)


def _should_include_log(log_entry: dict, level: str) -> bool:
    """Check if log entry should be included based on filter."""
    if level == "all":
        return True

    log_level = log_entry.get("level", "INFO").upper()

    if level.lower() == "error":
        return log_level in ("ERROR", "CRITICAL", "FATAL")
    if level.lower() == "warning":
        return log_level in ("WARNING", "WARN", "ERROR", "CRITICAL", "FATAL")

    return True


@router.get("/docker-logs/stream")
async def stream_app_logs(level: str = "all"):
    """
    Stream application logs via Server-Sent Events.

    Args:
        level: Filter level - 'all' (default), 'warning', or 'error'

    Returns:
        EventSourceResponse with log events

    Events:
        - connected: Connection established
        - log: Log line with content, level, timestamp
        - ping: Keepalive
        - error: Error message
    """
    return EventSourceResponse(generate_app_logs(level))
