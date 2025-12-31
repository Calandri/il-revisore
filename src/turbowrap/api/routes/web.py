"""Web routes for HTML pages."""

from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from ...db.models import Repository, Setting, Task
from ..deps import get_current_user, get_db

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)) -> Response:
    """Dashboard page - lista repository."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/dashboard.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "dashboard",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/repos", response_class=HTMLResponse)
async def repos_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Repository management page."""
    repos = db.query(Repository).all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/repos.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "repos",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> Response:
    """Chat CLI interface page - opens sidebar in page mode."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/chat.html",
            {
                "request": request,
                "active_page": "chat",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/chat/{session_id}", response_class=HTMLResponse)
async def chat_session_page(
    request: Request,
    session_id: str,
) -> Response:
    """Redirect old chat session URLs to main chat page."""
    return RedirectResponse(url="/chat", status_code=302)


@router.get("/system-status", response_class=HTMLResponse)
async def status_page(request: Request) -> Response:
    """System status monitoring page."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/status.html",
            {
                "request": request,
                "active_page": "status",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/review", response_class=HTMLResponse)
async def review_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Code review page with multi-agent streaming."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/review.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "review",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/tests", response_class=HTMLResponse)
async def tests_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Tests management page."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/tests.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "tests",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/issues", response_class=HTMLResponse)
async def issues_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Issues tracking page."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/issues.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "issues",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/panoramica", response_class=HTMLResponse)
async def panoramica_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Panoramica page - repository overview with KPIs, branches, and tasks."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/panoramica.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "panoramica",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/issues/{issue_id}", response_class=HTMLResponse)
async def issue_detail_page(
    request: Request,
    issue_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """Issue detail page - shows full issue info by ID (UUID only)."""
    from ...db.models import Issue

    # Find by ID (UUID) only - no fallback to issue_code to avoid ambiguity
    issue = db.query(Issue).filter(Issue.id == issue_id).first()

    if not issue:
        # Return 404 page
        return Response(
            content="<html><body><h1>Issue not found</h1><p>The issue code you requested does not exist.</p><a href='/issues'>Back to Issues</a></body></html>",
            status_code=404,
            media_type="text/html",
        )

    # Get repository info
    repository = db.query(Repository).filter(Repository.id == issue.repository_id).first()

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/issue_detail.html",
            {
                "request": request,
                "issue": issue,
                "repository": repository,
                "active_page": "issues",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/live-tasks", response_class=HTMLResponse)
async def live_tasks_page(request: Request) -> Response:
    """Live tasks page - shows active fix sessions."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/live_tasks.html",
            {
                "request": request,
                "active_page": "live_tasks",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/linear", response_class=HTMLResponse)
async def linear_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Linear issues page."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/linear_issues.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "linear",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/features", response_class=HTMLResponse)
async def features_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Features tracking page."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/features.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "features",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/features/{feature_id}", response_class=HTMLResponse)
async def feature_detail_page(
    request: Request,
    feature_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """Feature detail page - shows full feature info by ID."""
    from ...db.models import Feature

    feature = db.query(Feature).filter(Feature.id == feature_id).first()

    if not feature:
        return Response(
            content="<html><body><h1>Feature not found</h1><p>The feature you requested does not exist.</p><a href='/features'>Back to Features</a></body></html>",
            status_code=404,
            media_type="text/html",
        )

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/feature_detail.html",
            {
                "request": request,
                "feature": feature,
                "active_page": "features",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """File editor page."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/files.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "files",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request) -> Response:
    """Agents management page - view and edit AI agents."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/agents.html",
            {
                "request": request,
                "active_page": "agents",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Settings page for configuring TurboWrap."""
    from ...config import get_settings as get_config

    config = get_config()

    # Get settings from DB
    github_token = db.query(Setting).filter(Setting.key == "github_token").first()
    vercel_token = db.query(Setting).filter(Setting.key == "vercel_token").first()
    linear_api_key = db.query(Setting).filter(Setting.key == "linear_api_key").first()
    linear_team_id = db.query(Setting).filter(Setting.key == "linear_team_id").first()
    claude_model = db.query(Setting).filter(Setting.key == "claude_model").first()
    gemini_model = db.query(Setting).filter(Setting.key == "gemini_model").first()
    gemini_pro_model = db.query(Setting).filter(Setting.key == "gemini_pro_model").first()

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/settings.html",
            {
                "request": request,
                "active_page": "settings",
                "github_token_set": bool(github_token and github_token.value),
                # Vercel Integration
                "vercel_token_set": bool(vercel_token and vercel_token.value),
                # Linear Integration
                "linear_api_key_set": bool(linear_api_key and linear_api_key.value),
                "linear_team_id": linear_team_id.value if linear_team_id else "",
                # Models: DB value or config default
                "claude_model": claude_model.value if claude_model else config.agents.claude_model,
                "gemini_model": gemini_model.value if gemini_model else config.agents.gemini_model,
                "gemini_pro_model": (
                    gemini_pro_model.value if gemini_pro_model else config.agents.gemini_pro_model
                ),
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request) -> Response:
    """User management page (admin only)."""
    current_user = get_current_user(request)

    # Redirect se non admin
    if not current_user or not current_user.get("is_admin"):
        return RedirectResponse(url="/", status_code=302)

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/users.html",
            {
                "request": request,
                "active_page": "users",
                "current_user": current_user,
            },
        ),
    )


@router.get("/databases", response_class=HTMLResponse)
async def databases_page(request: Request) -> Response:
    """Database viewer page - manage and visualize databases."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/databases.html",
            {
                "request": request,
                "active_page": "databases",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/endpoints", response_class=HTMLResponse)
async def endpoints_page(request: Request) -> Response:
    """Endpoint manager page - view and document API endpoints."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/endpoints.html",
            {
                "request": request,
                "active_page": "endpoints",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/mockups", response_class=HTMLResponse)
async def mockups_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Mockups page - generate and manage UI mockups with AI."""
    repos = db.query(Repository).filter(Repository.deleted_at.is_(None)).all()
    repos_data = [{"id": r.id, "name": r.name} for r in repos]

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/mockups.html",
            {
                "request": request,
                "repos": repos_data,
                "active_page": "mockups",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/mockup-deploy", response_class=HTMLResponse)
async def mockup_deploy_page(request: Request) -> Response:
    """Static mockup page for deployment UI redesign."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/mockup_deploy.html",
            {
                "request": request,
                "active_page": "mockup-deploy",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/live-view", response_class=HTMLResponse)
async def live_view_page(request: Request) -> Response:
    """Live View page - interact with production frontend sites."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/live_view.html",
            {
                "request": request,
                "active_page": "live-view",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/mockups/{mockup_id}/preview", response_class=HTMLResponse)
async def mockup_preview_page(
    request: Request,
    mockup_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """Full-page preview of a mockup (fetches HTML from S3 via boto3)."""
    from ...db.models import Mockup

    mockup = db.query(Mockup).filter(Mockup.id == mockup_id, Mockup.deleted_at.is_(None)).first()

    if not mockup:
        return Response(
            content="<html><body><h1>Mockup not found</h1></body></html>",
            status_code=404,
            media_type="text/html",
        )

    # If we have an S3 URL, fetch content from S3 using boto3
    if mockup.s3_html_url:
        try:
            import re

            import boto3

            from ...config import get_settings

            settings = get_settings()

            # Extract S3 key from URL
            # URL format: https://bucket.s3.region.amazonaws.com/key
            match = re.search(r"\.amazonaws\.com/(.+)$", mockup.s3_html_url)
            if match and settings.thinking.s3_bucket:
                s3_key = match.group(1)
                client = boto3.client("s3", region_name=settings.thinking.s3_region)
                response = client.get_object(
                    Bucket=settings.thinking.s3_bucket,
                    Key=s3_key,
                )
                html_content = response["Body"].read().decode("utf-8")
                return Response(content=html_content, media_type="text/html")
        except Exception as e:
            # Log error but fall through to placeholder
            import logging

            logging.getLogger(__name__).warning(f"Failed to fetch mockup from S3: {e}")

    # Fallback: placeholder for mockups still generating or with errors
    html_content = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{mockup.name} - Preview</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gradient-to-br from-indigo-50 to-violet-100 min-h-screen flex items-center justify-center">
    <div class="text-center p-8">
        <div class="w-20 h-20 mx-auto mb-6 bg-white rounded-2xl shadow-lg flex items-center justify-center">
            <svg class="w-10 h-10 text-indigo-500 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
        </div>
        <h1 class="text-2xl font-bold text-gray-800 mb-2">{mockup.name}</h1>
        <p class="text-indigo-600 font-medium">Generazione in corso...</p>
        <p class="text-gray-500 text-sm mt-4">{mockup.component_type or 'component'} • {mockup.llm_type}</p>
    </div>
</body>
</html>"""

    return Response(content=html_content, media_type="text/html")


# HTMX Partial endpoints
@router.get("/htmx/repos", response_class=HTMLResponse)
async def htmx_repo_list(request: Request, db: Session = Depends(get_db)) -> Response:
    """HTMX partial: repository list with last evaluation and git sync status."""
    import json
    from pathlib import Path

    from sqlalchemy import func

    from ...utils.git_utils import get_repo_status

    repos = db.query(Repository).filter(Repository.status != "deleted").all()

    # Get last completed review task with evaluation for each repo
    # Subquery to get max completed_at per repo
    subq = (
        db.query(Task.repository_id, func.max(Task.completed_at).label("last_completed"))
        .filter(Task.type == "review", Task.status == "completed")
        .group_by(Task.repository_id)
        .subquery()
    )

    # Join to get the actual task records
    last_tasks = (
        db.query(Task)
        .join(
            subq,
            (Task.repository_id == subq.c.repository_id)
            & (Task.completed_at == subq.c.last_completed),
        )
        .filter(Task.type == "review", Task.status == "completed")
        .all()
    )

    # Build repo_id -> evaluation dict
    evaluations: dict[str, Any] = {}
    for task in last_tasks:
        if task.result:
            try:
                result_value = cast(Any, task.result)
                result: dict[str, Any] = (
                    result_value if isinstance(result_value, dict) else json.loads(result_value)
                )
                eval_data = result.get("evaluation")
                if eval_data:
                    evaluations[str(task.repository_id)] = {
                        "evaluation": eval_data,
                        "task_id": task.id,
                        "completed_at": task.completed_at,
                    }
            except (json.JSONDecodeError, TypeError):
                pass

    # Get git sync status for each repo
    git_statuses: dict[str, dict[str, Any]] = {}
    for repo in repos:
        if repo.local_path and repo.status == "active":
            local_path = Path(repo.local_path)
            if local_path.exists():
                try:
                    status = get_repo_status(local_path)
                    git_statuses[str(repo.id)] = {
                        "ahead": status.ahead,
                        "behind": status.behind,
                        "is_clean": status.is_clean,
                    }
                except Exception:
                    # If git status fails, skip this repo
                    pass

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "components/repo_list.html",
            {
                "request": request,
                "repos": repos,
                "evaluations": evaluations,
                "git_statuses": git_statuses,
            },
        ),
    )


@router.post("/htmx/repos", response_class=HTMLResponse)
async def htmx_add_repo(
    request: Request,
    url: str = Form(...),
    branch: str = Form("main"),
    workspace_path: str | None = Form(None),
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: add a new repository and return updated list.

    For monorepos, workspace_path limits operations to a subfolder.
    """
    import json
    import logging

    from ...core.repo_manager import RepoManager

    logger = logging.getLogger(__name__)
    clone_error: str | None = None

    manager = RepoManager(db)
    try:
        # Normalize empty string to None
        ws_path = workspace_path.strip() if workspace_path else None
        manager.clone(url, branch, workspace_path=ws_path)
    except Exception as e:
        logger.error(f"Clone error for {url}: {e}")
        clone_error = str(e)

    # Return updated list
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        "components/repo_list.html", {"request": request, "repos": repos}
    )

    # Send toast notification on error
    if clone_error:
        response.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": f"Clone fallito: {clone_error}", "type": "error"}}
        )

    return cast(Response, response)


@router.delete("/htmx/repos/{repo_id}", response_class=HTMLResponse)
async def htmx_delete_repo(
    request: Request, repo_id: str, db: Session = Depends(get_db)
) -> Response:
    """HTMX: delete a repository and return updated list."""
    import shutil
    from pathlib import Path

    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if repo:
        # Delete local files
        local_path = Path(str(repo.local_path))
        if local_path.exists():
            shutil.rmtree(local_path)
        # Delete from DB
        db.delete(repo)
        db.commit()

    # Return updated list
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "components/repo_list.html", {"request": request, "repos": repos}
        ),
    )


@router.post("/htmx/repos/{repo_id}/sync", response_class=HTMLResponse)
async def htmx_sync_repo(request: Request, repo_id: str, db: Session = Depends(get_db)) -> Response:
    """HTMX: sync a repository and return updated list."""
    from ...core.repo_manager import RepoManager

    manager = RepoManager(db)
    sync_error = None
    try:
        manager.sync(repo_id)
    except Exception as e:
        # Capture error for UI display
        error_str = str(e)
        print(f"Sync error: {error_str}")
        # Check for token expiration
        if "TOKEN_EXPIRED" in error_str:
            sync_error = "token_expired"
        else:
            sync_error = error_str

    # Return updated list with optional error
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        "components/repo_list.html",
        {"request": request, "repos": repos, "sync_error": sync_error},
    )
    # Add HX-Trigger header for toast notification
    if sync_error:
        import json

        trigger_data = {"showSyncError": {"error": sync_error}}
        response.headers["HX-Trigger"] = json.dumps(trigger_data)
    return cast(Response, response)


@router.post("/htmx/repos/{repo_id}/reclone", response_class=HTMLResponse)
async def htmx_reclone_repo(
    request: Request, repo_id: str, db: Session = Depends(get_db)
) -> Response:
    """HTMX: force reclone a repository (delete local + fresh clone)."""
    import logging
    import shutil
    from pathlib import Path

    from ...core.repo_manager import RepoManager

    logger = logging.getLogger(__name__)
    repo = db.query(Repository).filter(Repository.id == repo_id).first()

    sync_error = None
    if repo:
        try:
            local_path = Path(str(repo.local_path))

            # Delete local directory if exists
            if local_path.exists():
                logger.info(f"[RECLONE] Removing local directory: {local_path}")
                shutil.rmtree(local_path)

            # Use sync which calls ensure_repo_exists to reclone
            manager = RepoManager(db)
            manager.sync(repo_id)
            logger.info(f"[RECLONE] Successfully recloned: {repo.name}")
        except Exception as e:
            error_str = str(e)
            logger.error(f"[RECLONE] Failed for {repo.name}: {error_str}")
            # Mark as error
            repo.status = "error"  # type: ignore[assignment]
            db.commit()
            # Check for token expiration
            if "TOKEN_EXPIRED" in error_str:
                sync_error = "token_expired"
            else:
                sync_error = error_str

    # Return updated list with optional error
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        "components/repo_list.html",
        {"request": request, "repos": repos, "evaluations": {}, "sync_error": sync_error},
    )
    # Add HX-Trigger header for toast notification
    if sync_error:
        import json

        trigger_data = {"showSyncError": {"error": sync_error}}
        response.headers["HX-Trigger"] = json.dumps(trigger_data)
    return cast(Response, response)


# =============================================================================
# HTMX Routes for Tests
# =============================================================================


@router.get("/htmx/tests/suites", response_class=HTMLResponse)
async def htmx_test_suites(
    request: Request,
    repository_id: str,
    type: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX partial: test suites list for a repository."""
    from datetime import datetime, timedelta

    from ...db.models import TestRun, TestSuite

    # Auto-cleanup: Mark runs stuck for >10 minutes as "error"
    stale_threshold = datetime.utcnow() - timedelta(minutes=10)
    stale_runs = (
        db.query(TestRun)
        .filter(
            TestRun.repository_id == repository_id,
            TestRun.status.in_(["pending", "running"]),
            TestRun.created_at < stale_threshold,
        )
        .all()
    )
    for run in stale_runs:
        run.status = "error"
        run.error_message = "Timeout: run bloccato per più di 10 minuti"
        run.completed_at = datetime.utcnow()
    if stale_runs:
        db.commit()

    query = db.query(TestSuite).filter(
        TestSuite.repository_id == repository_id,
        TestSuite.deleted_at.is_(None),
    )

    if type and type != "all":
        # Map 'ai' to the actual type values
        if type == "ai":
            query = query.filter(TestSuite.type.in_(["ai_analysis", "ai_generation"]))
        else:
            query = query.filter(TestSuite.type == type)

    suites = query.order_by(TestSuite.name).all()

    # Build suite data with run stats
    suites_data = []
    for suite in suites:
        runs_count = len(suite.runs) if suite.runs else 0
        last_run = None
        passed = 0
        failed = 0

        if suite.runs:
            last_run = sorted(suite.runs, key=lambda r: r.created_at, reverse=True)[0]
            passed = last_run.passed or 0
            failed = last_run.failed or 0

        # Use test_count from scanner as fallback if no runs or run has 0 tests
        total_tests = (
            last_run.total_tests if last_run and last_run.total_tests else (suite.test_count or 0)
        )

        suites_data.append(
            {
                "id": suite.id,
                "name": suite.name,
                "path": suite.path,
                "type": suite.type,
                "framework": suite.framework,
                "command": suite.command,
                "runs_count": runs_count,
                "total_tests": total_tests,
                "passed": passed,
                "failed": failed,
                "last_run_status": last_run.status if last_run else None,
                "last_run_at": last_run.created_at if last_run else None,
                "duration_seconds": last_run.duration_seconds if last_run else None,
            }
        )

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "components/test_suites_list.html",
            {
                "request": request,
                "suites": suites_data,
                "repository_id": repository_id,
            },
        ),
    )


@router.get("/htmx/tests/summary", response_class=HTMLResponse)
async def htmx_test_summary(
    request: Request,
    repository_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX partial: test summary stats for a repository."""
    from ...db.models import TestRun, TestSuite

    suites = (
        db.query(TestSuite)
        .filter(
            TestSuite.repository_id == repository_id,
            TestSuite.deleted_at.is_(None),
        )
        .all()
    )

    # Get recent runs
    recent_runs = (
        db.query(TestRun)
        .filter(TestRun.repository_id == repository_id)
        .order_by(TestRun.created_at.desc())
        .limit(10)
        .all()
    )

    # Calculate stats
    total_passed = sum(r.passed or 0 for r in recent_runs)
    total_failed = sum(r.failed or 0 for r in recent_runs)
    total_tests = sum(r.total_tests or 0 for r in recent_runs)
    pass_rate = round((total_passed / total_tests * 100), 1) if total_tests > 0 else 0
    ai_suites = len([s for s in suites if s.type in ("ai_analysis", "ai_generation")])

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "components/test_summary_stats.html",
            {
                "request": request,
                "passed": total_passed,
                "failed": total_failed,
                "pass_rate": pass_rate,
                "ai_suites": ai_suites,
                "total_suites": len(suites),
            },
        ),
    )


@router.get("/htmx/tests/runs", response_class=HTMLResponse)
async def htmx_test_runs(
    request: Request,
    repository_id: str | None = None,
    suite_id: str | None = None,
    limit: int = 10,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX partial: recent test runs."""
    from ...db.models import TestRun

    query = db.query(TestRun)

    if repository_id:
        query = query.filter(TestRun.repository_id == repository_id)
    if suite_id:
        query = query.filter(TestRun.suite_id == suite_id)

    runs = query.order_by(TestRun.created_at.desc()).limit(limit).all()

    runs_data = []
    for run in runs:
        runs_data.append(
            {
                "id": run.id,
                "suite_name": run.suite.name if run.suite else "Unknown",
                "status": run.status,
                "total_tests": run.total_tests or 0,
                "passed": run.passed or 0,
                "failed": run.failed or 0,
                "duration_seconds": run.duration_seconds,
                "created_at": run.created_at,
                "pass_rate": run.pass_rate,
            }
        )

    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "components/test_runs_list.html",
            {
                "request": request,
                "runs": runs_data,
            },
        ),
    )


@router.post("/htmx/tests/suites", response_class=HTMLResponse)
async def htmx_create_test_suite(
    request: Request,
    repository_id: str = Form(...),
    name: str = Form(...),
    path: str = Form(...),
    type: str = Form("classic"),
    framework: str = Form(...),
    command: str = Form(None),
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: create a new test suite."""
    import json

    from ...db.models import TestSuite

    # Validate
    if not name or not path or not framework:
        return Response(
            content="<div class='text-red-500'>Nome, path e framework sono obbligatori</div>",
            status_code=400,
        )

    # Check for duplicate
    existing = (
        db.query(TestSuite)
        .filter(
            TestSuite.repository_id == repository_id,
            TestSuite.name == name,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if existing:
        return Response(
            content=f"<div class='text-red-500'>Test suite '{name}' già esistente</div>",
            status_code=400,
        )

    suite = TestSuite(
        repository_id=repository_id,
        name=name,
        path=path,
        type=type,
        framework=framework,
        command=command if command else None,
        is_auto_discovered=False,
    )
    db.add(suite)
    db.commit()

    # Return updated list
    templates = request.app.state.templates
    response = templates.TemplateResponse(
        "components/test_suites_list.html",
        {
            "request": request,
            "suites": [],  # Will be re-fetched via HTMX
            "repository_id": repository_id,
        },
    )
    response.headers["HX-Trigger"] = json.dumps(
        {
            "showToast": {"message": f"Test suite '{name}' creato", "type": "success"},
            "closeModal": True,
            "refreshSuites": True,
        }
    )
    return cast(Response, response)


@router.delete("/htmx/tests/suites/{suite_id}", response_class=HTMLResponse)
async def htmx_delete_test_suite(
    request: Request,
    suite_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: delete a test suite."""
    import json

    from ...db.models import TestSuite

    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        return Response(
            content="<div class='text-red-500'>Suite non trovata</div>", status_code=404
        )

    suite_name = suite.name
    suite.soft_delete()
    db.commit()

    response = Response(content="")
    response.headers["HX-Trigger"] = json.dumps(
        {
            "showToast": {"message": f"Test suite '{suite_name}' eliminato", "type": "success"},
            "refreshSuites": True,
        }
    )
    return response


@router.post("/htmx/tests/suites/{suite_id}/cancel", response_class=HTMLResponse)
async def htmx_cancel_stuck_run(
    request: Request,
    suite_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: cancel stuck test runs for a suite."""
    import json
    from datetime import datetime

    from ...db.models import TestRun, TestSuite

    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        return Response(
            content="<div class='text-red-500'>Suite non trovata</div>", status_code=404
        )

    # Find and cancel all pending/running runs
    stuck_runs = (
        db.query(TestRun)
        .filter(
            TestRun.suite_id == suite_id,
            TestRun.status.in_(["pending", "running"]),
        )
        .all()
    )

    cancelled_count = len(stuck_runs)
    for run in stuck_runs:
        run.status = "error"
        run.error_message = "Cancellato manualmente dall'utente"
        run.completed_at = datetime.utcnow()

    if stuck_runs:
        db.commit()

    response = Response(content="")
    response.headers["HX-Trigger"] = json.dumps(
        {
            "showToast": {
                "message": f"Cancellati {cancelled_count} run bloccati"
                if cancelled_count
                else "Nessun run da cancellare",
                "type": "success" if cancelled_count else "info",
            },
            "refreshSuites": True,
        }
    )
    return response


@router.get("/htmx/tests/suites/{suite_id}/details", response_class=HTMLResponse)
async def htmx_get_suite_details(
    request: Request,
    suite_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: get test suite details with scanned tests."""
    from pathlib import Path

    from ...db.models import Repository, TestSuite
    from ...tasks.test_scanner import scan_test_suite

    suite = (
        db.query(TestSuite).filter(TestSuite.id == suite_id, TestSuite.deleted_at.is_(None)).first()
    )
    if not suite:
        return Response(
            content="<div class='text-red-500'>Suite non trovata</div>", status_code=404
        )

    repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
    if not repo or not repo.local_path:
        return Response(
            content="<div class='text-red-500'>Repository non trovata</div>", status_code=404
        )

    # Scan the test files
    scan_result = scan_test_suite(
        repo_path=Path(repo.local_path),
        suite_path=suite.path,
        framework=suite.framework,
    )

    # Update test_count in suite if scan was successful
    if scan_result.success and scan_result.total_tests > 0:
        suite.test_count = scan_result.total_tests
        db.commit()

    templates = request.app.state.templates

    # Render main content
    main_content = templates.get_template("components/test_suite_details.html").render(
        request=request,
        suite=suite,
        scan_result=scan_result,
        repo_path=repo.local_path,
    )

    # SEMPRE render AI analysis OOB (reset o mostra analisi esistente)
    # Se la suite non ha analisi, il template mostra l'empty state
    ai_content = templates.get_template("components/test_ai_analysis.html").render(
        request=request,
        suite=suite,
        analysis=suite.ai_analysis,  # None se non esiste
    )
    oob_content = f'<div id="suite-ai-analysis" hx-swap-oob="innerHTML">{ai_content}</div>'
    return Response(content=main_content + oob_content, media_type="text/html")


@router.get("/htmx/tests/file/{suite_id}", response_class=HTMLResponse)
async def htmx_get_test_file_code(
    request: Request,
    suite_id: str,
    file_path: str,
    line: int = 1,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: get source code for a test file."""
    from pathlib import Path

    from ...db.models import Repository, TestSuite

    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        return Response(
            content="<div class='text-red-500'>Suite non trovata</div>", status_code=404
        )

    repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
    if not repo or not repo.local_path:
        return Response(
            content="<div class='text-red-500'>Repository non trovata</div>", status_code=404
        )

    full_path = Path(repo.local_path) / file_path
    if not full_path.exists():
        return Response(content="<div class='text-red-500'>File non trovato</div>", status_code=404)

    try:
        content = full_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        total_lines = len(lines)
    except Exception as e:
        return Response(content=f"<div class='text-red-500'>Errore: {e}</div>", status_code=500)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "components/test_file_code.html",
        {
            "request": request,
            "file_path": file_path,
            "content": content,
            "lines": lines,
            "total_lines": total_lines,
            "highlight_line": line,
            "framework": suite.framework,
        },
    )


@router.post("/htmx/tests/run/{suite_id}", response_class=HTMLResponse)
async def htmx_run_test_suite(
    request: Request,
    suite_id: str,
    background_tasks: BackgroundTasks,
    database_connection_id: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: trigger a test run for a suite using Gemini CLI."""
    import json

    from ...db.models import Repository, TestRun, TestSuite

    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        return Response(
            content="<div class='text-red-500'>Suite non trovata</div>", status_code=404
        )

    repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
    if not repo:
        return Response(
            content="<div class='text-red-500'>Repository non trovata</div>", status_code=404
        )

    # Create pending run
    run = TestRun(
        suite_id=suite.id,
        repository_id=suite.repository_id,
        status="pending",
        database_connection_id=database_connection_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Queue GeminiCLI test execution in background
    background_tasks.add_task(
        _execute_test_run,
        run_id=str(run.id),
        repo_name=str(repo.name),
        repo_path=str(repo.local_path),
        suite_path=str(suite.path),
        framework=str(suite.framework),
        custom_command=suite.command,
        database_connection_id=database_connection_id,
    )

    response = Response(content="")
    response.headers["HX-Trigger"] = json.dumps(
        {
            "showToast": {"message": f"Test '{suite.name}' avviato", "type": "success"},
            "refreshSuites": True,
            "refreshRuns": True,
        }
    )
    return response


async def _execute_test_run(
    run_id: str,
    repo_name: str,
    repo_path: str,
    suite_path: str,
    framework: str,
    custom_command: str | None,
    database_connection_id: str | None,
) -> None:
    """Background task to execute a test run using Gemini CLI."""
    import base64
    import logging
    import re
    from datetime import datetime
    from pathlib import Path

    from cryptography.fernet import Fernet

    from ...db.models import DatabaseConnection, TestRun
    from ...db.session import get_session_local
    from ...llm.gemini import GeminiCLI
    from ...review.reviewers.utils.json_extraction import parse_llm_json

    logger = logging.getLogger(__name__)
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        # Get the test run and update status
        test_run = db.query(TestRun).filter(TestRun.id == run_id).first()
        if not test_run:
            logger.error(f"TestRun {run_id} not found")
            return

        test_run.status = "running"
        test_run.started_at = datetime.utcnow()
        db.commit()

        # Build DATABASE_URL if connection provided
        database_url = None
        if database_connection_id:
            db_conn = (
                db.query(DatabaseConnection)
                .filter(DatabaseConnection.id == database_connection_id)
                .first()
            )
            if db_conn:
                password = None
                if db_conn.encrypted_password:
                    from ...core.config import settings

                    fernet_key = getattr(settings, "ENCRYPTION_KEY", None)
                    if fernet_key:
                        try:
                            fernet = Fernet(fernet_key.encode())
                            password = fernet.decrypt(db_conn.encrypted_password.encode()).decode()
                        except Exception:
                            try:
                                password = base64.b64decode(
                                    db_conn.encrypted_password.encode()
                                ).decode()
                            except Exception:
                                pass

                if db_conn.db_type == "sqlite":
                    database_url = f"sqlite:///{db_conn.database}"
                elif db_conn.db_type in ("mysql", "mariadb"):
                    auth = f"{db_conn.username}:{password}@" if db_conn.username else ""
                    host = f"{db_conn.host}:{db_conn.port}" if db_conn.port else db_conn.host
                    database_url = f"mysql://{auth}{host}/{db_conn.database}"
                elif db_conn.db_type == "postgresql":
                    auth = f"{db_conn.username}:{password}@" if db_conn.username else ""
                    host = f"{db_conn.host}:{db_conn.port}" if db_conn.port else db_conn.host
                    database_url = f"postgresql://{auth}{host}/{db_conn.database}"

        # Load agent prompt
        agent_path = Path(__file__).parents[4] / "agents" / "test_runner.md"
        agent_content = ""
        if agent_path.exists():
            agent_content = agent_path.read_text()

        # Build prompt
        db_context = ""
        if database_url:
            masked_url = re.sub(r":([^@]+)@", ":***@", database_url)
            db_context = f"""
## Database Configuration
Set DATABASE_URL before running: export DATABASE_URL="{database_url}"
(Masked: {masked_url})
"""

        prompt = f"""
{agent_content}

## Test Suite to Run
- Repository: {repo_name}
- Suite Path: {suite_path}
- Framework: {framework}
- Custom Command: {custom_command or "None - use framework default"}
- Repository Path: {repo_path}
{db_context}

Run the tests and return JSON with test counts and status.
"""

        # Run Gemini CLI
        cli = GeminiCLI(
            working_dir=Path(repo_path),
            model="flash",
            timeout=300,
            auto_accept=True,
        )

        result = await cli.run(
            prompt=prompt,
            operation_type="test_execution",
            repo_name=repo_name,
            track_operation=True,
        )

        # Parse result
        test_run.completed_at = datetime.utcnow()
        if test_run.started_at:
            test_run.duration_seconds = (
                test_run.completed_at - test_run.started_at
            ).total_seconds()

        if not result.success:
            test_run.status = "error"
            test_run.error_message = result.error
            db.commit()
            logger.error(f"Test run failed: {result.error}")
            return

        json_data = parse_llm_json(result.output)

        if json_data:
            test_run.status = json_data.get("status", "error")
            test_run.total_tests = json_data.get("total_tests", 0)
            test_run.passed = json_data.get("passed", 0)
            test_run.failed = json_data.get("failed", 0)
            test_run.skipped = json_data.get("skipped", 0)
            test_run.errors = json_data.get("errors", 0)
            test_run.report_data = json_data
            test_run.error_message = json_data.get("error_message")
            logger.info(f"Test run completed: {test_run.passed}/{test_run.total_tests} passed")
        else:
            test_run.status = "error"
            test_run.error_message = "Could not parse test results"
            test_run.report_data = {"raw_output": result.output[:5000]}
            logger.error("Could not parse test results from Gemini output")

        db.commit()

    except Exception as e:
        logger.exception(f"Test run {run_id} failed: {e}")
        try:
            test_run = db.query(TestRun).filter(TestRun.id == run_id).first()
            if test_run:
                test_run.status = "error"
                test_run.error_message = str(e)
                test_run.completed_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/htmx/tests/run-all/{repository_id}", response_class=HTMLResponse)
async def htmx_run_all_tests(
    request: Request,
    repository_id: str,
    background_tasks: BackgroundTasks,
    database_connection_id: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: run all test suites for a repository."""
    import json

    from ...db.models import Repository, TestRun, TestSuite

    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        response = Response(content="")
        response.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Repository non trovata", "type": "error"}}
        )
        return response

    suites = (
        db.query(TestSuite)
        .filter(
            TestSuite.repository_id == repository_id,
            TestSuite.deleted_at.is_(None),
        )
        .all()
    )

    if not suites:
        response = Response(content="")
        response.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Nessun test suite trovato", "type": "warning"}}
        )
        return response

    # Create runs for all suites and queue execution
    run_ids = []
    for suite in suites:
        run = TestRun(
            suite_id=suite.id,
            repository_id=repository_id,
            status="pending",
            database_connection_id=database_connection_id,
        )
        db.add(run)
        db.flush()  # Get the ID
        run_ids.append(str(run.id))

    db.commit()

    # Queue all test runs for background execution
    for run_id in run_ids:
        background_tasks.add_task(
            _execute_test_run,
            run_id=run_id,
            repo_path=repo.local_path,
        )

    response = Response(content="")
    response.headers["HX-Trigger"] = json.dumps(
        {
            "showToast": {"message": f"Avviati {len(suites)} test suite", "type": "success"},
            "closeModal": True,
            "refreshSuites": True,
            "refreshRuns": True,
        }
    )
    return response


@router.post("/htmx/tests/discover/{repository_id}", response_class=HTMLResponse)
async def htmx_discover_tests(
    request: Request,
    repository_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: auto-discover test suites in a repository using Gemini CLI."""
    import json

    from ...db.models import Repository
    from ..services.operation_tracker import OperationTracker

    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo:
        response = Response(content="")
        response.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Repository non trovata", "type": "error"}}
        )
        return response

    if not repo.local_path:
        response = Response(content="")
        response.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "Repository non ha un path locale", "type": "error"}}
        )
        return response

    # Check if there's already an active operation for this repository
    tracker = OperationTracker()
    active_ops = tracker.get_active(repo_id=repository_id)
    cli_ops = [op for op in active_ops if op.operation_type in ("cli_task", "test_discovery")]
    if cli_ops:
        response = Response(content="")
        response.headers["HX-Trigger"] = json.dumps(
            {
                "showToast": {
                    "message": "Discovery già in corso per questa repository",
                    "type": "warning",
                }
            }
        )
        return response

    # Queue discovery in background
    background_tasks.add_task(
        _execute_test_discovery,
        repository_id=repository_id,
        repo_name=repo.name,
        repo_path=repo.local_path,
    )

    response = Response(content="")
    response.headers["HX-Trigger"] = json.dumps(
        {
            "showToast": {"message": "Discovery avviato...", "type": "info"},
        }
    )
    return response


async def _execute_test_discovery(repository_id: str, repo_name: str, repo_path: str) -> None:
    """Background task to execute test discovery."""
    import logging
    from pathlib import Path

    from ...db.session import get_session_local
    from ...tasks.test_discovery import discover_and_save_tests

    logger = logging.getLogger(__name__)
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        result = await discover_and_save_tests(
            repo_path=Path(repo_path),
            repo_name=repo_name,
            repository_id=repository_id,
            db_session=db,
        )
        if result.success:
            logger.info(f"Test discovery completed: {len(result.suites)} suites found")
        else:
            logger.error(f"Test discovery failed: {result.error}")
    except Exception as e:
        logger.exception(f"Test discovery failed: {e}")
    finally:
        db.close()


@router.post("/htmx/tests/analyze/{suite_id}", response_class=HTMLResponse)
async def htmx_analyze_test_suite(
    request: Request,
    suite_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: analyze a test suite using Gemini CLI.

    Uses the test_analyzer.md agent to analyze the test suite and save results.
    """
    import logging
    from datetime import datetime
    from pathlib import Path

    from ...db.models import Repository, TestSuite
    from ...llm.gemini import GeminiCLI
    from ...review.reviewers.utils.json_extraction import parse_llm_json

    logger = logging.getLogger(__name__)

    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        return Response(
            content="<div class='text-red-500 p-4'>Suite non trovata</div>", status_code=404
        )

    repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
    if not repo or not repo.local_path:
        return Response(
            content="<div class='text-red-500 p-4'>Repository non trovata</div>", status_code=404
        )

    repo_path = Path(repo.local_path)
    suite_path = repo_path / suite.path

    # Load agent prompt
    agent_path = Path(__file__).parents[4] / "agents" / "test_analyzer.md"
    if not agent_path.exists():
        return Response(
            content="<div class='text-red-500 p-4'>Agent file not found</div>", status_code=500
        )

    agent_content = agent_path.read_text()
    # Remove YAML frontmatter
    if agent_content.startswith("---"):
        parts = agent_content.split("---", 2)
        if len(parts) >= 3:
            agent_content = parts[2].strip()

    # Gather test files to analyze
    test_files = []
    if suite_path.exists():
        patterns = ["test_*.py", "*_test.py", "*.spec.ts", "*.test.ts", "*.test.tsx"]
        for pattern in patterns:
            test_files.extend(suite_path.rglob(pattern))

    # Build context for the agent
    test_files_content = []
    for tf in test_files[:10]:  # Limit to first 10 files
        try:
            content = tf.read_text(encoding="utf-8")
            rel_path = tf.relative_to(repo_path)
            test_files_content.append(f"## File: {rel_path}\n```\n{content[:5000]}\n```")
        except Exception:
            pass

    # Build prompt
    prompt = f"""
{agent_content}

## Context

- Repository: {repo.name}
- Test Suite Path: {suite.path}
- Framework: {suite.framework}

## Test Files to Analyze

{chr(10).join(test_files_content) if test_files_content else "No test files found - use tools to explore."}

Now analyze this test suite and return the JSON response.
"""

    try:
        # Run Gemini CLI
        cli = GeminiCLI(
            working_dir=repo_path,
            model="flash",  # gemini-3-flash-preview
            timeout=120,
            auto_accept=True,
        )

        result = await cli.run(
            prompt=prompt,
            operation_type="test_analysis",
            repo_name=repo.name,
            track_operation=True,
        )

        if not result.success:
            logger.error(f"Test analysis failed: {result.error}")
            return Response(
                content=f"<div class='text-red-500 p-4'>Analisi fallita: {result.error}</div>",
                status_code=500,
            )

        # Parse JSON from output using centralized utility
        json_data = parse_llm_json(result.output)
        if not json_data:
            logger.error(f"Could not parse JSON from output: {result.output[:500]}")
            return Response(
                content="<div class='text-red-500 p-4'>Impossibile estrarre JSON dalla risposta</div>",
                status_code=500,
            )

        # Add timestamp
        json_data["analyzed_at"] = datetime.utcnow().isoformat()

        # Save to database
        suite.ai_analysis = json_data
        db.commit()
        db.refresh(suite)

        logger.info(f"Test analysis completed for suite {suite.name}: {json_data.get('test_type')}")

        # Return analysis component
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "components/test_ai_analysis.html",
            {
                "request": request,
                "suite": suite,
                "analysis": json_data,
            },
        )

    except Exception as e:
        logger.exception(f"Test analysis error: {e}")
        return Response(
            content=f"<div class='text-red-500 p-4'>Errore: {str(e)}</div>",
            status_code=500,
        )


@router.post("/htmx/tests/analyze-repo/{repository_id}", response_class=HTMLResponse)
async def htmx_analyze_repo_tests(
    request: Request,
    repository_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: analyze ALL test suites in a repository using Gemini CLI.

    Aggregates test files from all suites and provides a repo-level analysis.
    Uses the same test_analyzer.md agent but with different context.
    """
    import logging
    from datetime import datetime
    from pathlib import Path

    from ...db.models import Repository, TestSuite
    from ...llm.gemini import GeminiCLI
    from ...review.reviewers.utils.json_extraction import parse_llm_json

    logger = logging.getLogger(__name__)

    repo = db.query(Repository).filter(Repository.id == repository_id).first()
    if not repo or not repo.local_path:
        return Response(
            content="<div class='text-red-500 p-4'>Repository non trovata</div>", status_code=404
        )

    # Get all test suites for this repo
    suites = (
        db.query(TestSuite)
        .filter(
            TestSuite.repository_id == repository_id,
            TestSuite.deleted_at.is_(None),
        )
        .all()
    )

    if not suites:
        return Response(
            content="<div class='text-amber-500 p-4'>Nessuna test suite trovata. Usa Auto-Discovery per trovare i test.</div>",
            status_code=200,
        )

    repo_path = Path(repo.local_path)

    # Load agent prompt
    agent_path = Path(__file__).parents[4] / "agents" / "test_analyzer.md"
    if not agent_path.exists():
        return Response(
            content="<div class='text-red-500 p-4'>Agent file not found</div>", status_code=500
        )

    agent_content = agent_path.read_text()
    # Remove YAML frontmatter
    if agent_content.startswith("---"):
        parts = agent_content.split("---", 2)
        if len(parts) >= 3:
            agent_content = parts[2].strip()

    # Gather test files from ALL suites
    all_test_files = []
    suite_info = []
    for suite in suites:
        suite_path = repo_path / suite.path
        suite_files = []
        if suite_path.exists():
            patterns = ["test_*.py", "*_test.py", "*.spec.ts", "*.test.ts", "*.test.tsx"]
            for pattern in patterns:
                suite_files.extend(suite_path.rglob(pattern))
        all_test_files.extend(suite_files)
        suite_info.append(
            f"- {suite.name} ({suite.framework}): {suite.path} - {len(suite_files)} files"
        )

    # Build context for the agent - limit to 15 files across all suites
    test_files_content = []
    for tf in all_test_files[:15]:
        try:
            content = tf.read_text(encoding="utf-8")
            rel_path = tf.relative_to(repo_path)
            test_files_content.append(f"## File: {rel_path}\n```\n{content[:4000]}\n```")
        except Exception:
            pass

    # Build prompt - emphasize REPO-level analysis
    prompt = f"""
{agent_content}

## Context - REPOSITORY-LEVEL ANALYSIS

This is a **repository-level analysis** covering ALL test suites in the repository.
You should provide an aggregated view of test quality across the entire codebase.

- Repository: {repo.name}
- Total Test Suites: {len(suites)}
- Total Test Files: {len(all_test_files)}

### Test Suites in this Repository:
{chr(10).join(suite_info)}

## Test Files to Analyze (sample from all suites)

{chr(10).join(test_files_content) if test_files_content else "No test files found - use tools to explore."}

Now analyze ALL these test suites together and return the JSON response.
Focus on:
1. Overall test coverage and quality across the entire repo
2. Consistency between different test suites
3. Common patterns and anti-patterns
4. Suggestions that apply to the whole codebase
"""

    try:
        # Run Gemini CLI
        cli = GeminiCLI(
            working_dir=repo_path,
            model="flash",
            timeout=180,  # Longer timeout for repo-level
            auto_accept=True,
        )

        result = await cli.run(
            prompt=prompt,
            operation_type="repo_test_analysis",
            repo_name=repo.name,
            track_operation=True,
        )

        if not result.success:
            logger.error(f"Repo test analysis failed: {result.error}")
            return Response(
                content=f"<div class='text-red-500 p-4'>Analisi fallita: {result.error}</div>",
                status_code=500,
            )

        # Parse JSON from output using centralized utility
        json_data = parse_llm_json(result.output)
        if not json_data:
            logger.error(f"Could not parse JSON from output: {result.output[:500]}")
            return Response(
                content="<div class='text-red-500 p-4'>Impossibile estrarre JSON dalla risposta</div>",
                status_code=500,
            )

        # Add repo-level metadata
        json_data["analyzed_at"] = datetime.utcnow().isoformat()
        json_data["total_suites"] = len(suites)
        json_data["total_files"] = len(all_test_files)
        json_data["suites_analyzed"] = [s.name for s in suites]

        # Save to repository
        repo.test_analysis = json_data
        db.commit()
        db.refresh(repo)

        logger.info(f"Repo test analysis completed for {repo.name}: {json_data.get('test_type')}")

        # Return analysis component (reuse same template)
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "components/test_ai_analysis.html",
            {
                "request": request,
                "analysis": json_data,
                "is_repo_level": True,
            },
        )

    except Exception as e:
        logger.exception(f"Repo test analysis error: {e}")
        return Response(
            content=f"<div class='text-red-500 p-4'>Errore: {str(e)}</div>",
            status_code=500,
        )


@router.get("/htmx/tests/develop/{suite_id}", response_class=HTMLResponse)
async def htmx_develop_tests(
    request: Request,
    suite_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: redirect to chat for interactive test development.

    Opens the chat page with context about the test suite for AI-guided development.
    """
    from urllib.parse import quote

    from ...db.models import Repository, TestSuite

    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        return Response(
            content="<div class='text-red-500 p-4'>Suite non trovata</div>", status_code=404
        )

    repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
    if not repo:
        return Response(
            content="<div class='text-red-500 p-4'>Repository non trovata</div>", status_code=404
        )

    # Build initial message for chat
    initial_message = f"""Aiutami a sviluppare nuovi test per la suite "{suite.name}" nel path {suite.path}.

Framework: {suite.framework}
Repository: {repo.name}

Analizza i test esistenti e proponi nuovi test case che potrebbero migliorare la copertura. Fammi domande per capire meglio cosa testare."""

    # Redirect to chat with context
    response = Response(content="")
    response.headers["HX-Redirect"] = (
        f"/chat?repo_id={repo.id}&initial_message={quote(initial_message)}"
    )
    return response


@router.post("/htmx/tests/enhance/{suite_id}", response_class=HTMLResponse)
async def htmx_enhance_test(
    request: Request,
    suite_id: str,
    file_path: str = Form(...),
    test_name: str = Form(...),
    test_line: int = Form(...),
    class_name: str = Form(None),
    suggestions: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: enhance a single test using Claude CLI (Opus).

    Uses the test_enhancer.md agent to improve the test based on user suggestions.
    """
    import json
    import logging
    import re
    from pathlib import Path

    from ...db.models import Repository, TestSuite
    from ...llm.claude_cli import ClaudeCLI

    logger = logging.getLogger(__name__)

    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        return Response(
            content="<div class='text-red-500 p-4'>Suite non trovata</div>", status_code=404
        )

    repo = db.query(Repository).filter(Repository.id == suite.repository_id).first()
    if not repo or not repo.local_path:
        return Response(
            content="<div class='text-red-500 p-4'>Repository non trovata</div>", status_code=404
        )

    repo_path = Path(repo.local_path)
    full_file_path = repo_path / file_path

    if not full_file_path.exists():
        return Response(
            content="<div class='text-red-500 p-4'>File test non trovato</div>", status_code=404
        )

    # Read test file content
    try:
        test_file_content = full_file_path.read_text(encoding="utf-8")
    except Exception as e:
        return Response(
            content=f"<div class='text-red-500 p-4'>Errore lettura file: {e}</div>",
            status_code=500,
        )

    # Load agent prompt
    agent_path = Path(__file__).parents[4] / "agents" / "test_enhancer.md"
    if not agent_path.exists():
        return Response(
            content="<div class='text-red-500 p-4'>Agent file not found</div>", status_code=500
        )

    agent_content = agent_path.read_text()
    # Remove YAML frontmatter
    if agent_content.startswith("---"):
        parts = agent_content.split("---", 2)
        if len(parts) >= 3:
            agent_content = parts[2].strip()

    # Build prompt
    test_identifier = f"{class_name}.{test_name}" if class_name else test_name
    prompt = f"""
{agent_content}

## Context

- Repository: {repo.name}
- Test Framework: {suite.framework}
- File Path: {file_path}
- Test Name: {test_identifier}
- Test Line: {test_line}

## Original Test Code

```{suite.framework if suite.framework == 'pytest' else 'typescript'}
{test_file_content}
```

## User Suggestions

{suggestions if suggestions.strip() else "No specific suggestions provided. Apply general best practice improvements."}

Now enhance this test and return the JSON response with the improved code.
"""

    try:
        # Run Claude CLI with Opus
        cli = ClaudeCLI(
            working_dir=repo_path,
            model="opus",
            timeout=180,  # Opus may take longer
            skip_permissions=True,
        )

        result = await cli.run(
            prompt=prompt,
            operation_type="test_enhancement",
            repo_name=repo.name,
            track_operation=True,
        )

        if not result.success:
            logger.error(f"Test enhancement failed: {result.error}")
            return Response(
                content=f"<div class='text-red-500 p-4'>Enhancement fallito: {result.error}</div>",
                status_code=500,
            )

        # Parse JSON from output
        output = result.output
        json_data = None

        # Try to extract JSON from output
        try:
            json_data = json.loads(output.strip())
        except json.JSONDecodeError:
            # Look for JSON in markdown code block
            json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", output)
            if json_match:
                try:
                    json_data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

            # Look for raw JSON
            if not json_data:
                json_match = re.search(r"\{[\s\S]*\"enhanced_code\"[\s\S]*\}", output)
                if json_match:
                    try:
                        json_data = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass

        if not json_data:
            logger.error(f"Could not parse JSON from output: {output[:500]}")
            return Response(
                content="<div class='text-red-500 p-4'>Impossibile estrarre JSON dalla risposta</div>",
                status_code=500,
            )

        logger.info(f"Test enhanced: {test_name} with {json_data.get('new_test_count', 0)} tests")

        # Return enhanced test component
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "components/test_enhanced_result.html",
            {
                "request": request,
                "result": json_data,
                "test_name": test_name,
                "file_path": file_path,
                "framework": suite.framework,
            },
        )

    except Exception as e:
        logger.exception(f"Test enhancement error: {e}")
        return Response(
            content=f"<div class='text-red-500 p-4'>Errore: {str(e)}</div>",
            status_code=500,
        )


@router.get("/readme-mockup", response_class=HTMLResponse)
async def readme_mockup_page(request: Request) -> Response:
    """README UI mockup page - static demo with sample data."""
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/readme_mockup.html",
            {
                "request": request,
                "active_page": "readme",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.get("/readme", response_class=HTMLResponse)
async def readme_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """README UI page - dynamic documentation for repositories."""
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    return cast(
        Response,
        templates.TemplateResponse(
            "pages/readme.html",
            {
                "request": request,
                "repos": repos,
                "active_page": "readme",
                "current_user": get_current_user(request),
            },
        ),
    )


@router.post("/htmx/repos/{repo_id}/push", response_class=HTMLResponse)
async def htmx_push_repo(request: Request, repo_id: str, db: Session = Depends(get_db)) -> Response:
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
            # Use new Agentic Smart Push (Gemini Flash)
            from ...utils.git_utils import smart_push

            result = await smart_push(
                Path(str(repo.local_path)),
                commit_message="Update via TurboWrap",
            )

            if result.success:
                if result.ai_resolved:
                    push_message = f"Push completato (AI resolved) per {repo.name}"
                else:
                    push_message = f"Push completato per {repo.name}"
                logger.info(push_message)
            else:
                push_error = f"Push fallito: {result.message}"
                if result.output:
                    logger.error(f"Push output: {result.output}")

        except Exception as e:
            push_error = f"Push fallito per {repo.name}: {str(e)}"
            logger.error(push_error)
    else:
        push_error = "Repository non trovata"

    # Return updated list with HX-Trigger for toast notification
    repos = db.query(Repository).filter(Repository.status != "deleted").all()
    templates = request.app.state.templates
    response = cast(
        Response,
        templates.TemplateResponse(
            "components/repo_list.html", {"request": request, "repos": repos}
        ),
    )

    # Add HX-Trigger header for toast notification
    if push_message:
        response.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": push_message, "type": "success"}}
        )
    elif push_error:
        response.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": push_error, "type": "error"}}
        )

    return response
