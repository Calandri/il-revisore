"""FastAPI application."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db.session import init_db
from .deps import get_db
from .middleware.auth import AuthMiddleware
from .routes import (
    analysis_router,
    auth_router,
    chat_router,
    cli_chat_router,
    databases_router,
    deployments_router,
    endpoints_router,
    fix_router,
    git_router,
    github_router,
    issues_router,
    linear_router,
    operations_router,
    relationships_router,
    repos_router,
    settings_router,
    status_router,
    tasks_router,
    thinking_router,
    users_router,
    web_router,
)
from .websocket import ChatWebSocketHandler

# Template and static directories
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def configure_logging() -> None:
    """Configure logging for the application.

    Called inside create_app() so it works with uvicorn --reload.
    """
    # Reset root logger handlers to allow reconfiguration
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Configure base logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,  # Force reconfiguration even if already configured
    )

    # Set turbowrap loggers to INFO
    logging.getLogger("turbowrap").setLevel(logging.INFO)
    logging.getLogger("turbowrap.review").setLevel(logging.INFO)
    logging.getLogger("turbowrap.fix").setLevel(logging.INFO)

    # SECURITY: Silence AWS/boto loggers - they log secrets in DEBUG mode!
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)

    # Silence other noisy libraries
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sse_starlette").setLevel(logging.WARNING)


def _ensure_all_repos_exist_sync() -> None:
    """Check all repositories and re-clone any with missing local paths (sync version).

    This handles the case where local files were deleted (e.g., disk cleanup)
    but the database records still exist.
    """
    from ..core.repo_manager import RepoManager
    from ..db.models import Repository
    from ..db.session import get_session_local

    logger = logging.getLogger(__name__)
    logger.info("[STARTUP] Checking repository local paths...")

    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        # Check repos with active or error status (not deleted)
        repos = db.query(Repository).filter(Repository.status.in_(["active", "error"])).all()
        logger.info(f"[STARTUP] Found {len(repos)} repositories to check")

        missing_count = 0
        restored_count = 0
        failed_repos = []

        for repo in repos:
            local_path = Path(repo.local_path)
            if not local_path.exists() or not (local_path / ".git").exists():
                missing_count += 1
                logger.warning(f"[STARTUP] Missing repo: {repo.name} at {local_path}")

                try:
                    manager = RepoManager(db)
                    manager.ensure_repo_exists(str(repo.id))
                    restored_count += 1
                    logger.info(f"[STARTUP] Restored repo: {repo.name}")
                except Exception as e:
                    failed_repos.append(repo.name)
                    logger.error(f"[STARTUP] Failed to restore {repo.name}: {e}")

        if missing_count == 0:
            logger.info("[STARTUP] All repository paths OK")
        else:
            logger.info(
                f"[STARTUP] Repository check complete: "
                f"{missing_count} missing, {restored_count} restored, "
                f"{len(failed_repos)} failed"
            )
            if failed_repos:
                logger.warning(f"[STARTUP] Failed repos: {failed_repos}")

    finally:
        db.close()


async def _ensure_all_repos_exist_task() -> None:
    """Background task to restore missing repositories."""
    import asyncio

    logger = logging.getLogger(__name__)
    logger.info("[STARTUP] Starting background repo check task...")

    # Run sync function in thread pool to not block event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _ensure_all_repos_exist_sync)


async def _cleanup_stale_processes_task() -> None:
    """Background task to cleanup stale CLI processes."""
    import asyncio

    from ..chat_cli.process_manager import (
        CLEANUP_INTERVAL_SECONDS,
        STALE_PROCESS_HOURS,
        get_process_manager,
    )

    logger = logging.getLogger(__name__)
    logger.info(
        f"[CLEANUP] Started background task: checking every {CLEANUP_INTERVAL_SECONDS}s "
        f"for processes older than {STALE_PROCESS_HOURS}h"
    )

    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            manager = get_process_manager()
            terminated = await manager.cleanup_stale_processes()
            if terminated > 0:
                logger.info(f"[CLEANUP] Cleaned up {terminated} stale processes")
        except asyncio.CancelledError:
            logger.info("[CLEANUP] Background cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"[CLEANUP] Error in cleanup task: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    import asyncio

    from ..chat_cli.process_manager import get_process_manager

    logger = logging.getLogger(__name__)

    # Startup
    init_db()

    # Start background repo check task (non-blocking, repos may take time to clone)
    repo_check_task = asyncio.create_task(_ensure_all_repos_exist_task())

    # Start background cleanup task
    cleanup_task = asyncio.create_task(_cleanup_stale_processes_task())
    logger.info("[STARTUP] Background tasks started")

    yield

    # Shutdown
    repo_check_task.cancel()
    cleanup_task.cancel()
    try:
        await repo_check_task
    except asyncio.CancelledError:
        pass
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Terminate all remaining CLI processes
    manager = get_process_manager()
    terminated = await manager.terminate_all()
    if terminated > 0:
        logger.info(f"[SHUTDOWN] Terminated {terminated} CLI processes")


def create_app() -> FastAPI:
    """Create FastAPI application."""
    # Configure logging on every app creation (works with --reload)
    configure_logging()

    # Setup SSE log handler AFTER configure_logging to ensure it's not removed
    from .routes.status import setup_sse_logging

    setup_sse_logging()

    settings = get_settings()

    app = FastAPI(
        title="TurboWrap",
        description="AI-Powered Repository Orchestrator",
        version=__version__,
        lifespan=lifespan,
    )

    # Authentication middleware (must be added before CORS)
    app.add_middleware(AuthMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Templates and static files
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Include API routers with /api prefix
    app.include_router(repos_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(status_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(issues_router, prefix="/api")
    app.include_router(fix_router, prefix="/api")
    app.include_router(linear_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(thinking_router, prefix="/api")
    app.include_router(relationships_router, prefix="/api")
    app.include_router(analysis_router, prefix="/api")
    app.include_router(git_router, prefix="/api")
    app.include_router(github_router, prefix="/api")
    app.include_router(cli_chat_router, prefix="/api")
    app.include_router(deployments_router, prefix="/api")
    app.include_router(operations_router, prefix="/api")
    app.include_router(databases_router, prefix="/api")
    app.include_router(endpoints_router, prefix="/api")

    # Web routes (no prefix - these are the HTML pages)
    app.include_router(web_router)

    # Auth routes (login, logout, etc.)
    app.include_router(auth_router)

    # WebSocket endpoint
    @app.websocket("/chat/sessions/{session_id}/ws")
    async def websocket_chat(
        websocket: WebSocket,
        session_id: str,
        db: Session = Depends(get_db),
    ) -> None:
        """WebSocket endpoint for streaming chat."""
        handler = ChatWebSocketHandler(websocket, session_id, db)
        await handler.handle()

    return app


# Default app instance
app = create_app()
