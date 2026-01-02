"""API dependencies."""

from collections.abc import Callable, Generator
from typing import Any

from fastapi import Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import (
    ChatSession,
    Feature,
    Issue,
    Mockup,
    Repository,
    Task,
    User,
    UserRepository,
    UserRole,
)
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

    return {
        "sub": claims.get("sub"),
        "email": email,
        "username": claims.get("username") or claims.get("cognito:username"),
    }


def require_auth(
    request: Request,
    current_user: dict[str, Any] | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Dependency that requires authentication.

    Raises HTTPException 401 if not authenticated.
    Also enriches user info with role from local database.
    Auto-provisions new users on first login.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    settings = get_settings()

    # Get cognito_sub from token claims
    cognito_sub = current_user.get("sub")
    if not cognito_sub:
        # Anonymous user (auth disabled) - treat as admin
        return {**current_user, "role": UserRole.ADMIN.value, "user_id": None}

    # Look up user in local DB for role
    user = db.query(User).filter(User.cognito_sub == cognito_sub).first()

    if not user:
        # Auto-provision new user on first login
        email = current_user.get("email", "")
        # Check if email matches any admin pattern from config
        admin_patterns = settings.auth.admin_email_patterns
        is_admin_email = email and any(
            pattern.lower() in email.lower() for pattern in admin_patterns
        )
        default_role = UserRole.ADMIN.value if is_admin_email else UserRole.CODER.value
        user = User(
            cognito_sub=cognito_sub,
            email=email,
            role=default_role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Return enriched user info
    return {
        **current_user,
        "user_id": user.id,
        "role": user.role,
        "is_admin": user.role == UserRole.ADMIN.value,
    }


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
# Role-Based Access Control (RBAC) Dependencies
# =============================================================================


def require_role(
    *allowed_roles: UserRole,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """
    Factory that creates a dependency requiring one of the specified roles.

    Usage:
        @router.post("/fix")
        async def start_fix(user: dict = Depends(require_role(UserRole.ADMIN, UserRole.CODER))):
            ...

    Args:
        allowed_roles: One or more UserRole values that are allowed

    Returns:
        A FastAPI dependency function
    """
    allowed_values = [r.value for r in allowed_roles]

    def dependency(
        current_user: dict[str, Any] = Depends(require_auth),
    ) -> dict[str, Any]:
        user_role = current_user.get("role")
        if user_role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Accesso riservato ai ruoli: {', '.join(allowed_values)}",
            )
        return current_user

    return dependency


# Convenience dependencies for common role combinations
require_coder = require_role(UserRole.ADMIN, UserRole.CODER)
require_mockupper = require_role(UserRole.ADMIN, UserRole.MOCKUPPER)
require_coder_or_mockupper = require_role(UserRole.ADMIN, UserRole.CODER, UserRole.MOCKUPPER)


def require_repo_access(
    repository_id: str = Path(..., description="Repository UUID"),
    current_user: dict[str, Any] = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Repository:
    """
    Dependency that requires user has access to the specified repository.

    - Admins have access to all repositories
    - Coders and Mockuppers only have access to assigned repositories

    Args:
        repository_id: The repository UUID from the path
        current_user: The authenticated user
        db: Database session

    Returns:
        The Repository object if access is granted

    Raises:
        HTTPException 404 if repository not found
        HTTPException 403 if user doesn't have access
    """
    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository non trovato",
        )

    # Admins have access to all repos
    if current_user.get("role") == UserRole.ADMIN.value:
        return repo

    # Check user-repository access
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso negato a questo repository",
        )

    access = (
        db.query(UserRepository)
        .filter(
            UserRepository.user_id == user_id,
            UserRepository.repository_id == repository_id,
        )
        .first()
    )

    if not access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai accesso a questo repository",
        )

    return repo


def get_accessible_repo_ids(
    current_user: dict[str, Any] = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[str] | None:
    """
    Get list of repository IDs the current user can access.

    - Admins can access all repositories (returns None = no filtering)
    - Coders and Mockuppers can only access assigned repositories

    Returns:
        None for admins (no filtering needed), list of repo IDs for others
    """
    # Admins see all repos - return None to signal "no filtering"
    if current_user.get("role") == UserRole.ADMIN.value:
        return None

    # Others see only assigned repos
    user_id = current_user.get("user_id")
    if not user_id:
        return []

    access = db.query(UserRepository.repository_id).filter(UserRepository.user_id == user_id).all()
    return [str(a.repository_id) for a in access]


def check_repo_access(
    repository_id: str,
    current_user: dict[str, Any],
    db: Session,
) -> bool:
    """
    Check if user has access to a specific repository.

    This is a utility function, not a FastAPI dependency.
    Use this when you need to check access without raising an exception.

    Args:
        repository_id: The repository UUID
        current_user: The authenticated user dict
        db: Database session

    Returns:
        True if user has access, False otherwise
    """
    # Admins have access to all repos
    if current_user.get("role") == UserRole.ADMIN.value:
        return True

    user_id = current_user.get("user_id")
    if not user_id:
        return False

    access = (
        db.query(UserRepository)
        .filter(
            UserRepository.user_id == user_id,
            UserRepository.repository_id == repository_id,
        )
        .first()
    )
    return access is not None


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
