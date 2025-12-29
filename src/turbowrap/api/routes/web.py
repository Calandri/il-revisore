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


@router.get("/issues/{issue_code}", response_class=HTMLResponse)
async def issue_detail_page(
    request: Request,
    issue_code: str,
    db: Session = Depends(get_db),
) -> Response:
    """Issue detail page - shows full issue info by issue_code."""
    from ...db.models import Issue

    # Find issue by issue_code
    issue = db.query(Issue).filter(Issue.issue_code == issue_code).first()
    if not issue:
        # Try to find by ID as fallback
        issue = db.query(Issue).filter(Issue.id == issue_code).first()

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


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)) -> Response:
    """Settings page for configuring TurboWrap."""
    from ...config import get_settings as get_config

    config = get_config()

    # Get settings from DB
    github_token = db.query(Setting).filter(Setting.key == "github_token").first()
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
    from ...db.models import TestSuite

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
        total_tests = 0
        passed = 0
        failed = 0

        if suite.runs:
            last_run = sorted(suite.runs, key=lambda r: r.created_at, reverse=True)[0]
            total_tests = last_run.total_tests or 0
            passed = last_run.passed or 0
            failed = last_run.failed or 0

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

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "components/test_suite_details.html",
        {
            "request": request,
            "suite": suite,
            "scan_result": scan_result,
            "repo_path": repo.local_path,
        },
    )


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
    db: Session = Depends(get_db),
) -> Response:
    """HTMX: trigger a test run for a suite."""
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
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Queue TestTask for background execution
    background_tasks.add_task(
        _execute_test_run,
        run_id=str(run.id),
        repo_path=repo.local_path,
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


async def _execute_test_run(run_id: str, repo_path: str) -> None:
    """Background task to execute a test run."""
    import logging
    from pathlib import Path

    from ...db.session import get_session_local
    from ...tasks import TaskContext, TestTask

    logger = logging.getLogger(__name__)

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        task = TestTask()
        context = TaskContext(
            db=db,
            repo_path=Path(repo_path),
            config={"run_id": run_id, "repository_id": ""},
        )
        result = await task.execute_async(context)
        logger.info(f"Test run {run_id} completed: {result.status}")
    except Exception as e:
        logger.exception(f"Test run {run_id} failed: {e}")
    finally:
        db.close()


@router.post("/htmx/tests/run-all/{repository_id}", response_class=HTMLResponse)
async def htmx_run_all_tests(
    request: Request,
    repository_id: str,
    background_tasks: BackgroundTasks,
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
