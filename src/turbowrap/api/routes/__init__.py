"""API routes."""

from .repos import router as repos_router
from .tasks import router as tasks_router
from .chat import router as chat_router
from .status import router as status_router
from .web import router as web_router
from .settings import router as settings_router
from .issues import router as issues_router

__all__ = [
    "repos_router",
    "tasks_router",
    "chat_router",
    "status_router",
    "web_router",
    "settings_router",
    "issues_router",
]
