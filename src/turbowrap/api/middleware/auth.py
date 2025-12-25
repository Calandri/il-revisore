"""Authentication middleware."""

import logging
from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from ...config import get_settings
from ..auth import verify_token

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/login",
    "/auth/login",
    "/auth/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/health",
    "/api/status",  # ALB health check
}

# Path prefixes that don't require authentication
PUBLIC_PREFIXES = (
    "/static/",
    "/auth/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce authentication on protected routes.

    Redirects unauthenticated users to /login with a next parameter.
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # Skip if auth is disabled
        if not settings.auth.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip public paths
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # Skip public prefixes
        if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        # Check for valid session
        access_token = request.cookies.get(settings.auth.session_cookie_name)

        if not access_token:
            return self._redirect_to_login(request)

        # Verify token
        claims = verify_token(access_token)
        if not claims:
            logger.warning(f"Invalid token for path: {path}")
            return self._redirect_to_login(request)

        # User is authenticated, proceed
        return await call_next(request)

    def _redirect_to_login(self, request: Request) -> RedirectResponse:
        """Create redirect response to login page."""
        # Build next URL
        next_url = str(request.url.path)
        if request.url.query:
            next_url += f"?{request.url.query}"

        # URL encode the next parameter
        login_url = f"/login?next={quote(next_url)}"

        return RedirectResponse(url=login_url, status_code=302)
