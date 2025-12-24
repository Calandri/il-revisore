"""Web routes for HTML pages."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..deps import get_db, get_current_user
from ...db.models import Repository, ChatSession, Setting
from ...utils.git_utils import smart_push_with_conflict_resolution
from ...utils.aws_secrets import get_anthropic_api_key

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
            "current_user": get_current_user(request),
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
            "current_user": get_current_user(request),
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
            "current_user": get_current_user(request),
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
    current_user = get_current_user(request)

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
                "current_user": current_user,
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
            "current_user": current_user,
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
            "current_user": get_current_user(request),
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
            "current_user": get_current_user(request),
        }
    )


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    """Task history page."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/tasks.html",
        {
            "request": request,
            "active_page": "tasks",
            "current_user": get_current_user(request),
        }
    )


@router.get("/issues", response_class=HTMLResponse)
async def issues_page(request: Request, db: Session = Depends(get_db)):
    """Issues tracking page."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/issues.html",
        {
            "request": request,
            "repos": repos,
            "active_page": "issues",
            "current_user": get_current_user(request),
        }
    )


@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request, db: Session = Depends(get_db)):
    """File editor page."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/files.html",
        {
            "request": request,
            "repos": repos,
            "active_page": "files",
            "current_user": get_current_user(request),
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
            "current_user": get_current_user(request),
        }
    )


@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    """User management page (admin only)."""
    current_user = get_current_user(request)

    # Redirect se non admin
    if not current_user or not current_user.get("is_admin"):
        return RedirectResponse(url="/", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "pages/users.html",
        {
            "request": request,
            "active_page": "users",
            "current_user": current_user,
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


@router.post("/htmx/repos/{repo_id}/sync", response_class=HTMLResponse)
async def htmx_sync_repo(request: Request, repo_id: str, db: Session = Depends(get_db)):
    """HTMX: sync a repository and return updated list."""
    from ...core.repo_manager import RepoManager

    manager = RepoManager(db)
    try:
        manager.sync(repo_id)
    except Exception as e:
        # Log error but continue to return updated list
        print(f"Sync error: {e}")

    # Return updated list
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "components/repo_list.html",
        {"request": request, "repos": repos}
    )


@router.post("/htmx/repos/{repo_id}/push", response_class=HTMLResponse)
async def htmx_push_repo(request: Request, repo_id: str, db: Session = Depends(get_db)):
    """HTMX: push repository changes with automatic conflict resolution via Claude CLI."""
    import json
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)
    push_message = None
    push_error = None

    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if repo and repo.local_path:
        try:
            api_key = get_anthropic_api_key()
            result = await smart_push_with_conflict_resolution(
                Path(repo.local_path),
                message="Update via TurboWrap",
                api_key=api_key,
            )
            if result.get("claude_resolved"):
                push_message = f"✅ Push completato - Claude ha risolto i conflitti per {repo.name}"
            else:
                push_message = f"✅ Push completato per {repo.name}"
            logger.info(push_message)
        except Exception as e:
            push_error = f"❌ Push fallito per {repo.name}: {str(e)}"
            logger.error(push_error)
    else:
        push_error = "❌ Repository non trovata"

    # Return updated list with HX-Trigger for toast notification
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        "components/repo_list.html",
        {"request": request, "repos": repos}
    )

    # Add HX-Trigger header for toast notification
    if push_message:
        response.headers["HX-Trigger"] = json.dumps({"showToast": {"message": push_message, "type": "success"}})
    elif push_error:
        response.headers["HX-Trigger"] = json.dumps({"showToast": {"message": push_error, "type": "error"}})

    return response
