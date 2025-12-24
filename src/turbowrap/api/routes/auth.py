"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr

from ..deps import get_current_user
from ..auth import cognito_login, get_user_info
from ...config import get_settings

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


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None, next: str | None = None):
    """Render login page."""
    settings = get_settings()

    # If already authenticated, redirect to home
    current_user = get_current_user(request)
    if current_user:
        return RedirectResponse(url=next or "/", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/login.html",
        {
            "request": request,
            "error": error,
            "next": next or "/",
        },
    )


@router.post("/auth/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
):
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
async def logout(request: Request):
    """Clear session cookie and redirect to login."""
    settings = get_settings()

    response = RedirectResponse(url="/login", status_code=302)

    # Delete cookies
    response.delete_cookie(settings.auth.session_cookie_name)
    response.delete_cookie(f"{settings.auth.session_cookie_name}_refresh")

    return response


@router.get("/auth/me", response_model=UserInfo)
async def me(current_user: dict = Depends(get_current_user)):
    """Get current user info (API endpoint)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return UserInfo(
        email=current_user.get("email"),
        username=current_user.get("username"),
        sub=current_user.get("sub"),
    )
