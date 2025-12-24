"""Web routes for HTML pages."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..deps import get_db
from ...db.models import Repository, ChatSession, Setting

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard page - lista repository."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/dashboard.html",
        {
            "request": request,
            "repos": repos,
            "active_page": "dashboard",
        }
    )


@router.get("/repos", response_class=HTMLResponse)
async def repos_page(request: Request, db: Session = Depends(get_db)):
    """Repository management page."""
    repos = db.query(Repository).all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/repos.html",
        {
            "request": request,
            "repos": repos,
            "active_page": "repos",
        }
    )


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, db: Session = Depends(get_db)):
    """Chat interface page."""
    sessions = (
        db.query(ChatSession)
        .order_by(ChatSession.updated_at.desc())
        .limit(20)
        .all()
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/chat.html",
        {
            "request": request,
            "sessions": sessions,
            "session": None,
            "messages": [],
            "active_page": "chat",
        }
    )


@router.get("/chat/{session_id}", response_class=HTMLResponse)
async def chat_session_page(
    request: Request,
    session_id: str,
    db: Session = Depends(get_db)
):
    """Specific chat session page."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    templates = request.app.state.templates

    if not session:
        return templates.TemplateResponse(
            "pages/chat.html",
            {
                "request": request,
                "sessions": [],
                "session": None,
                "messages": [],
                "active_page": "chat",
                "error": "Session not found",
            },
            status_code=404
        )

    return templates.TemplateResponse(
        "pages/chat.html",
        {
            "request": request,
            "session": session,
            "messages": session.messages,
            "active_page": "chat",
        }
    )


@router.get("/system-status", response_class=HTMLResponse)
async def status_page(request: Request):
    """System status monitoring page."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/status.html",
        {
            "request": request,
            "active_page": "status",
        }
    )


@router.get("/review", response_class=HTMLResponse)
async def review_page(request: Request, db: Session = Depends(get_db)):
    """Code review page with multi-agent streaming."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/review.html",
        {
            "request": request,
            "repos": repos,
            "active_page": "review",
        }
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """Settings page for configuring TurboWrap."""
    from ...config import get_settings as get_config

    config = get_config()

    # Get settings from DB
    github_token = db.query(Setting).filter(Setting.key == "github_token").first()
    claude_model = db.query(Setting).filter(Setting.key == "claude_model").first()
    gemini_model = db.query(Setting).filter(Setting.key == "gemini_model").first()
    gemini_pro_model = db.query(Setting).filter(Setting.key == "gemini_pro_model").first()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/settings.html",
        {
            "request": request,
            "active_page": "settings",
            "github_token_set": bool(github_token and github_token.value),
            # Models: DB value or config default
            "claude_model": claude_model.value if claude_model else config.agents.claude_model,
            "gemini_model": gemini_model.value if gemini_model else config.agents.gemini_model,
            "gemini_pro_model": gemini_pro_model.value if gemini_pro_model else config.agents.gemini_pro_model,
        }
    )


# HTMX Partial endpoints
@router.get("/htmx/repos", response_class=HTMLResponse)
async def htmx_repo_list(request: Request, db: Session = Depends(get_db)):
    """HTMX partial: repository list."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "components/repo_list.html",
        {"request": request, "repos": repos}
    )


@router.delete("/htmx/repos/{repo_id}", response_class=HTMLResponse)
async def htmx_delete_repo(request: Request, repo_id: str, db: Session = Depends(get_db)):
    """HTMX: delete a repository and return updated list."""
    import shutil
    from pathlib import Path

    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if repo:
        # Delete local files
        local_path = Path(repo.local_path)
        if local_path.exists():
            shutil.rmtree(local_path)
        # Delete from DB
        db.delete(repo)
        db.commit()

    # Return updated list
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "components/repo_list.html",
        {"request": request, "repos": repos}
    )
