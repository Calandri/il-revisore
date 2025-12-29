"""API routes."""

from .analysis import router as analysis_router
from .auth import router as auth_router
from .chat import router as chat_router
from .cli_chat import router as cli_chat_router
from .databases import router as databases_router
from .deployments import router as deployments_router
from .endpoints import router as endpoints_router
from .features import router as features_router
from .fix import router as fix_router
from .git import router as git_router
from .github import router as github_router
from .issues import router as issues_router
from .linear import router as linear_router
from .mockups import router as mockups_router
from .operations import router as operations_router
from .relationships import router as relationships_router
from .repos import router as repos_router
from .settings import router as settings_router
from .status import router as status_router
from .tasks import router as tasks_router
from .thinking import router as thinking_router
from .users import router as users_router
from .web import router as web_router

__all__ = [
    "repos_router",
    "tasks_router",
    "chat_router",
    "status_router",
    "web_router",
    "settings_router",
    "issues_router",
    "features_router",
    "fix_router",
    "linear_router",
    "auth_router",
    "users_router",
    "thinking_router",
    "relationships_router",
    "analysis_router",
    "git_router",
    "github_router",
    "cli_chat_router",
    "deployments_router",
    "operations_router",
    "databases_router",
    "endpoints_router",
    "mockups_router",
]
