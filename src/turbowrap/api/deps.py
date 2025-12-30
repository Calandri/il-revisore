"""API dependencies."""

from collections.abc import Generator
from typing import Any

from fastapi import Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import ChatSession, Feature, Issue, Mockup, Repository, Task
from ..db.session import get_db as _get_db
from .auth import verify_token


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

    # Check for refreshed token from middleware first
    access_token = getattr(request.state, "refreshed_access_token", None)

    # Fall back to cookie
    if not access_token:
        access_token = request.cookies.get(settings.auth.session_cookie_name)

    if not access_token:
        return None

    # Verify token
    claims = verify_token(access_token)
    if not claims:
        return None

    # Return user info from claims
    email = claims.get("email") or claims.get("username")
    # Determina se admin (hardcoded per niccolo.calandri)
    is_admin = email and "niccolo.calandri" in email.lower()

    return {
        "sub": claims.get("sub"),
        "email": email,
        "username": claims.get("username") or claims.get("cognito:username"),
        "is_admin": is_admin,
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


def require_admin(
    current_user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """
    Dependency that requires admin privileges.

    Raises HTTPException 403 if not admin.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato agli amministratori",
        )
    return current_user


# =============================================================================
# Generic get_or_404 utility
# =============================================================================


def get_or_404(
    db: Session,
    model: Any,
    entity_id: str,
    error_message: str | None = None,
) -> Any:
    """Fetch entity by ID or raise 404.

    Args:
        db: Database session
        model: SQLAlchemy model class
        entity_id: Primary key ID to look up
        error_message: Optional custom error message

    Returns:
        The found entity

    Raises:
        HTTPException: 404 if entity not found
    """
    entity = db.query(model).filter(model.id == entity_id).first()
    if not entity:
        name = model.__name__.lower()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_message or f"{name.title()} not found",
        )
    return entity


# =============================================================================
# FastAPI dependencies for common entities
# =============================================================================


def get_repository(
    repository_id: str = Path(..., description="Repository UUID"),
    db: Session = Depends(get_db),
) -> Repository:
    """Dependency to fetch a repository by ID or raise 404."""
    return get_or_404(db, Repository, repository_id)


def get_issue(
    issue_id: str = Path(..., description="Issue UUID"),
    db: Session = Depends(get_db),
) -> Issue:
    """Dependency to fetch an issue by ID or raise 404."""
    return get_or_404(db, Issue, issue_id)


def get_task(
    task_id: str = Path(..., description="Task UUID"),
    db: Session = Depends(get_db),
) -> Task:
    """Dependency to fetch a task by ID or raise 404."""
    return get_or_404(db, Task, task_id)


def get_session(
    session_id: str = Path(..., description="Chat session UUID"),
    db: Session = Depends(get_db),
) -> ChatSession:
    """Dependency to fetch a chat session by ID or raise 404."""
    return get_or_404(db, ChatSession, session_id)


def get_feature(
    feature_id: str = Path(..., description="Feature UUID"),
    db: Session = Depends(get_db),
) -> Feature:
    """Dependency to fetch a feature by ID or raise 404."""
    return get_or_404(db, Feature, feature_id)


def get_mockup(
    mockup_id: str = Path(..., description="Mockup UUID"),
    db: Session = Depends(get_db),
) -> Mockup:
    """Dependency to fetch a mockup by ID or raise 404."""
    return get_or_404(db, Mockup, mockup_id)
