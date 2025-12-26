"""API routes."""

from .analysis import router as analysis_router
from .auth import router as auth_router
from .chat import router as chat_router
from .fix import router as fix_router
from .git import router as git_router
from .issues import router as issues_router
from .linear import router as linear_router
from .relationships import router as relationships_router
from .repos import router as repos_router
from .settings import router as settings_router
from .status import router as status_router
from .tasks import router as tasks_router
from .thinking import router as thinking_router
from .users import router as users_router
from .web import router as web_router
from .cli_chat import router as cli_chat_router

__all__ = [
    "repos_router",
    "tasks_router",
    "chat_router",
    "status_router",
    "web_router",
    "settings_router",
    "issues_router",
    "fix_router",
    "linear_router",
    "auth_router",
    "users_router",
    "thinking_router",
    "relationships_router",
    "analysis_router",
    "git_router",
    "cli_chat_router",
]
