"""Authentication middleware."""

import logging
from collections.abc import Awaitable, Callable
from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from ...config import get_settings
from ..auth import refresh_access_token, verify_token

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/login",
    "/forgot-password",
    "/reset-password",
    "/auth/login",
    "/auth/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/health",
    "/api/status",  # ALB health check
    "/api/deployments/status",  # Deployment status (public GitHub data)
    "/api/deployments/staging/status",  # Staging status (for promote button)
    "/api/errors",  # Error reporting (uses its own Bearer token auth)
    "/api/linear/create/analyze",  # Widget API (uses X-Widget-Key)
    "/api/linear/create/finalize",  # Widget API (uses X-Widget-Key)
}

# Path prefixes that don't require authentication
PUBLIC_PREFIXES = (
    "/static/",
    "/auth/",
    "/api/widget-chat/",  # Widget chat API (uses X-Widget-Key)
)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce authentication on protected routes.

    Redirects unauthenticated users to /login with a next parameter.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
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
        refresh_token = request.cookies.get(f"{settings.auth.session_cookie_name}_refresh")

        if not access_token:
            # No access token - try refresh if available
            if refresh_token:
                try:
                    new_tokens = refresh_access_token(refresh_token)
                    if new_tokens and new_tokens.get("access_token"):
                        logger.info(f"Refreshed expired token for path: {path}")
                        # Store new token in request state for downstream handlers
                        request.state.refreshed_access_token = new_tokens["access_token"]
                        # Proceed with request and set new cookie in response
                        refreshed_response: Response = await call_next(request)
                        refreshed_response.set_cookie(
                            key=settings.auth.session_cookie_name,
                            value=new_tokens["access_token"],
                            max_age=settings.auth.session_max_age,
                            httponly=True,
                            secure=settings.auth.secure_cookies,
                            samesite="lax",
                        )
                        return refreshed_response
                except Exception as e:
                    logger.error(f"Token refresh error: {e}")
            return self._redirect_to_login(request)

        # Verify token
        claims = verify_token(access_token)
        if not claims:
            # Token invalid/expired - try refresh
            if refresh_token:
                try:
                    new_tokens = refresh_access_token(refresh_token)
                    if new_tokens and new_tokens.get("access_token"):
                        logger.info(f"Refreshed invalid token for path: {path}")
                        # Store new token in request state for downstream handlers
                        request.state.refreshed_access_token = new_tokens["access_token"]
                        # Proceed with request and set new cookie in response
                        invalid_token_response: Response = await call_next(request)
                        invalid_token_response.set_cookie(
                            key=settings.auth.session_cookie_name,
                            value=new_tokens["access_token"],
                            max_age=settings.auth.session_max_age,
                            httponly=True,
                            secure=settings.auth.secure_cookies,
                            samesite="lax",
                        )
                        return invalid_token_response
                except Exception as e:
                    logger.error(f"Token refresh error: {e}")
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
