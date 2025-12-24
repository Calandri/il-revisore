"""API dependencies."""

from typing import Any, Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db.session import get_db as _get_db
from ..config import get_settings
from .auth import verify_token, get_user_info


def get_db() -> Generator[Session, None, None]:
    """Database session dependency."""
    yield from _get_db()


def get_current_user(request: Request) -> dict[str, Any] | None:
    """
    Get current authenticated user from session cookie.

    Returns:
        User info dict or None if not authenticated
    """
    settings = get_settings()

    # Skip auth if disabled
    if not settings.auth.enabled:
        return {"email": "anonymous@local", "username": "anonymous"}

    # Get access token from cookie
    access_token = request.cookies.get(settings.auth.session_cookie_name)
    if not access_token:
        return None

    # Verify token
    claims = verify_token(access_token)
    if not claims:
        return None

    # Return user info from claims
    return {
        "sub": claims.get("sub"),
        "email": claims.get("email") or claims.get("username"),
        "username": claims.get("username") or claims.get("cognito:username"),
    }


def require_auth(
    request: Request,
    current_user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Dependency that requires authentication.

    Raises HTTPException 401 if not authenticated.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return current_user
