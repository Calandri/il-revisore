"""FastAPI application."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.session import init_db
from .deps import get_db
from .middleware.auth import AuthMiddleware
from .routes import (
    analysis_router,
    auth_router,
    chat_router,
    cli_chat_router,
    fix_router,
    git_router,
    issues_router,
    linear_router,
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


async def _cleanup_stale_processes_task():
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
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    import asyncio

    from ..chat_cli.process_manager import get_process_manager

    logger = logging.getLogger(__name__)

    # Startup
    init_db()

    # Start background cleanup task
    cleanup_task = asyncio.create_task(_cleanup_stale_processes_task())
    logger.info("[STARTUP] Background process cleanup task started")

    yield

    # Shutdown
    cleanup_task.cancel()
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

    settings = get_settings()

    app = FastAPI(
        title="TurboWrap",
        description="AI-Powered Repository Orchestrator",
        version="0.3.0",
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
    app.include_router(cli_chat_router, prefix="/api")

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
    ):
        """WebSocket endpoint for streaming chat."""
        handler = ChatWebSocketHandler(websocket, session_id, db)
        await handler.handle()

    return app


# Default app instance
app = create_app()
