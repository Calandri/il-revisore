"""FastAPI application."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .deps import get_db
from .routes import repos_router, tasks_router, chat_router, status_router, web_router, settings_router, issues_router, fix_router, auth_router, users_router, thinking_router, relationships_router
from .middleware.auth import AuthMiddleware
from .websocket import ChatWebSocketHandler
from ..config import get_settings
from ..db.session import init_db

# Template and static directories
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


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
    app.include_router(users_router, prefix="/api")
    app.include_router(thinking_router, prefix="/api")
    app.include_router(relationships_router, prefix="/api")

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
