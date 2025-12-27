"""Authentication routes."""

from typing import Any, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr

from ...config import get_settings
from ..auth import cognito_confirm_forgot_password, cognito_forgot_password, cognito_login
from ..deps import get_current_user

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    """Login request body."""

    email: EmailStr
    password: str


class UserInfo(BaseModel):
    """User info response."""

    email: str | None
    username: str | None
    sub: str | None


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(
    request: Request,
    error: str | None = None,
    success: str | None = None,
    next: str | None = None,
) -> Response:
    """Render login page."""
    get_settings()

    # If already authenticated, redirect to home
    current_user = get_current_user(request)
    if current_user:
        return RedirectResponse(url=next or "/", status_code=302)

    templates = request.app.state.templates
    return cast(
        HTMLResponse,
        templates.TemplateResponse(
            "pages/login.html",
            {
                "request": request,
                "error": error,
                "success": success,
                "next": next or "/",
            },
        ),
    )


@router.post("/auth/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
) -> RedirectResponse:
    """
    Authenticate user with Cognito and set session cookie.

    Returns redirect to next URL on success, or login page with error.
    """
    settings = get_settings()

    # Authenticate with Cognito
    tokens = cognito_login(email, password)

    if not tokens:
        # Return to login with error
        return RedirectResponse(
            url=f"/login?error=Credenziali+non+valide&next={next}",
            status_code=302,
        )

    # Create redirect response
    redirect = RedirectResponse(url=next, status_code=302)

    # Set session cookie with access token
    redirect.set_cookie(
        key=settings.auth.session_cookie_name,
        value=tokens["access_token"],
        max_age=settings.auth.session_max_age,
        httponly=True,
        secure=settings.auth.secure_cookies,
        samesite="lax",
    )

    # Optionally store refresh token in separate cookie
    if tokens.get("refresh_token"):
        redirect.set_cookie(
            key=f"{settings.auth.session_cookie_name}_refresh",
            value=tokens["refresh_token"],
            max_age=settings.auth.session_max_age,
            httponly=True,
            secure=settings.auth.secure_cookies,
            samesite="lax",
        )

    return redirect


@router.post("/auth/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear session cookie and redirect to login."""
    settings = get_settings()

    response = RedirectResponse(url="/login", status_code=302)

    # Delete cookies
    response.delete_cookie(settings.auth.session_cookie_name)
    response.delete_cookie(f"{settings.auth.session_cookie_name}_refresh")

    return response


@router.get("/auth/me", response_model=UserInfo)
async def me(current_user: dict[str, Any] = Depends(get_current_user)) -> UserInfo:
    """Get current user info (API endpoint)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return UserInfo(
        email=current_user.get("email"),
        username=current_user.get("username"),
        sub=current_user.get("sub"),
    )


# =============================================================================
# Forgot Password Flow
# =============================================================================


@router.get("/forgot-password", response_class=HTMLResponse, response_model=None)
async def forgot_password_page(
    request: Request,
    error: str | None = None,
    success: str | None = None,
    email: str | None = None,
) -> Response:
    """Render forgot password page."""
    templates = request.app.state.templates
    return cast(
        HTMLResponse,
        templates.TemplateResponse(
            "pages/forgot-password.html",
            {
                "request": request,
                "error": error,
                "success": success,
                "email": email,
            },
        ),
    )


@router.post("/auth/forgot-password")
async def forgot_password(
    request: Request,
    email: str = Form(...),
) -> RedirectResponse:
    """Initiate forgot password flow - sends verification code."""
    success, message = cognito_forgot_password(email)

    if success:
        # Redirect to reset-password page with email pre-filled
        return RedirectResponse(
            url=f"/reset-password?email={quote(email)}&success={quote(message)}",
            status_code=302,
        )

    return RedirectResponse(
        url=f"/forgot-password?error={quote(message)}&email={quote(email)}",
        status_code=302,
    )


@router.get("/reset-password", response_class=HTMLResponse, response_model=None)
async def reset_password_page(
    request: Request,
    error: str | None = None,
    success: str | None = None,
    email: str | None = None,
) -> Response:
    """Render reset password page."""
    templates = request.app.state.templates
    return cast(
        HTMLResponse,
        templates.TemplateResponse(
            "pages/reset-password.html",
            {
                "request": request,
                "error": error,
                "success": success,
                "email": email,
            },
        ),
    )


@router.post("/auth/reset-password")
async def reset_password(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
) -> RedirectResponse:
    """Confirm password reset with verification code."""
    # Validate passwords match
    if password != confirm_password:
        return RedirectResponse(
            url=f"/reset-password?error={quote('Le password non coincidono')}&email={quote(email)}",
            status_code=302,
        )

    success, message = cognito_confirm_forgot_password(email, code, password)

    if success:
        # Password reset successful - redirect to login with success message
        return RedirectResponse(
            url=f"/login?success={quote(message)}",
            status_code=302,
        )

    return RedirectResponse(
        url=f"/reset-password?error={quote(message)}&email={quote(email)}",
        status_code=302,
    )
