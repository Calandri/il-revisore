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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    init_db()
    yield
    # Shutdown
    pass


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
