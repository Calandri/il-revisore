"""Linear integration routes."""

import json
import logging
import shutil
import subprocess
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ...db.models import LinearIssue, LinearIssueRepositoryLink, Repository, Setting
from ...linear.analyzer import LinearIssueAnalyzer
from ...review.integrations.linear import LinearClient
from ..deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/linear", tags=["linear"])


# --- Schemas ---


class LinearIssueResponse(BaseModel):
    """Linear issue response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    linear_id: str
    linear_identifier: str
    linear_url: str
    linear_team_id: str
    linear_team_name: str | None = None
    title: str
    description: str | None = None
    improved_description: str | None = None
    assignee_name: str | None = None
    priority: int
    labels: list[dict[str, Any]] | None = None
    turbowrap_state: str
    linear_state_name: str | None = None
    is_active: bool
    analysis_summary: str | None = None
    analyzed_at: datetime | None = None
    user_answers: dict[str, Any] | None = None
    fix_commit_sha: str | None = None
    fix_branch: str | None = None
    repository_ids: list[str] = Field(default_factory=list)
    repository_names: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class LinearSyncRequest(BaseModel):
    """Request to sync issues from Linear."""

    team_id: str | None = Field(None, description="Team ID (uses settings if not provided)")
    limit: int = Field(100, ge=1, le=500)


class ImproveIssueRequest(BaseModel):
    """Request to improve issue with Claude."""

    issue_id: str


class ImproveIssuePhase2Request(BaseModel):
    """Request for Phase 2 analysis with user answers."""

    issue_id: str
    answers: dict[int, str] = Field(..., description="User answers keyed by question ID")


class LinkRepositoryRequest(BaseModel):
    """Request to link repository to issue."""

    issue_id: str
    repository_id: str
    link_source: str = "manual"


class FinalizeIssueRequest(BaseModel):
    """Request to finalize issue creation."""

    title: str
    description: str
    issue_type: str = Field(
        default="bug", description="Type of issue: bug, suggestion, or question"
    )
    figma_link: str | None = None
    website_link: str | None = None
    gemini_insights: str
    user_answers: dict[str, str] = Field(..., description="User answers keyed by question ID")
    temp_session_id: str
    team_id: str
    priority: int = Field(default=0, ge=0, le=4)
    assignee_id: str | None = None
    due_date: str | None = None  # ISO format date
    selected_element: dict[str, Any] | None = None  # Element selector info from widget

    model_config = {"extra": "ignore"}


# --- Helper Functions ---


def _get_linear_client(db: Session) -> LinearClient:
    """Get Linear client from settings."""
    setting = db.query(Setting).filter(Setting.key == "linear_api_key").first()
    if not setting or not setting.value:
        raise HTTPException(status_code=400, detail="Linear API key not configured")
    return LinearClient(api_key=str(setting.value))


def _get_team_id(db: Session, provided: str | None = None) -> str:
    """Get team ID from settings or param."""
    if provided:
        team_id = provided
    else:
        setting = db.query(Setting).filter(Setting.key == "linear_team_id").first()
        if not setting or not setting.value:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Linear team ID not configured. Please go to Settings and "
                    "configure your Linear Team ID (UUID format)."
                ),
            )
        team_id = str(setting.value)

    # Validate team ID format (should be UUID)
    if len(team_id) < 20:  # UUIDs are much longer
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid Team ID format: '{team_id}'. "
                f"Team ID must be a UUID (e.g., 'a1b2c3d4-...'). "
                f"You can find it in Linear Settings or by clicking on your team name."
            ),
        )

    return team_id


def _parse_repo_labels(labels: list[dict[str, Any]]) -> list[str]:
    """Extract repository names from labels.

    Looks for labels like:
    - repo:backend
    - repo:frontend
    - repository:my-app
    """
    repo_names = []
    for label in labels:
        name = label.get("name", "")
        if name.startswith("repo:"):
            repo_names.append(name[5:])  # Remove "repo:" prefix
        elif name.startswith("repository:"):
            repo_names.append(name[11:])  # Remove "repository:" prefix
    return repo_names


def _map_linear_state_to_turbowrap(state_name: str) -> str:
    """Map Linear state name to TurboWrap state."""
    state_mapping = {
        "triage": "analysis",
        "to do": "analysis",
        "in progress": "in_progress",
        "in review": "in_review",
        "done": "merged",
    }
    return state_mapping.get(state_name.lower(), "analysis")


# --- Routes ---


@router.get("/issues", response_model=list[LinearIssueResponse])
def list_linear_issues(
    state: str | None = Query(None, description="Filter by TurboWrap state"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[LinearIssueResponse]:
    """List Linear issues synced to TurboWrap."""
    query = db.query(LinearIssue).filter(LinearIssue.deleted_at.is_(None))

    if state:
        query = query.filter(LinearIssue.turbowrap_state == state)
    if is_active is not None:
        query = query.filter(LinearIssue.is_active == is_active)

    # Order by priority (urgent first) then created_at
    query = query.order_by(LinearIssue.priority.asc(), LinearIssue.created_at.desc())

    issues = query.offset(offset).limit(limit).all()

    # Enrich with repository info
    result: list[LinearIssueResponse] = []
    for issue in issues:
        # Get linked repositories
        links = (
            db.query(LinearIssueRepositoryLink)
            .filter(LinearIssueRepositoryLink.linear_issue_id == issue.id)
            .all()
        )

        repo_ids = [link.repository_id for link in links]
        repos = db.query(Repository).filter(Repository.id.in_(repo_ids)).all() if repo_ids else []

        issue_dict = LinearIssueResponse.model_validate(issue).model_dump()
        issue_dict["repository_ids"] = repo_ids
        issue_dict["repository_names"] = [r.name for r in repos]

        result.append(LinearIssueResponse(**issue_dict))

    return result


@router.post("/sync")
async def sync_linear_issues(
    request: LinearSyncRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Sync issues from Linear to TurboWrap."""
    try:
        client = _get_linear_client(db)
        team_id = _get_team_id(db, request.team_id)

        logger.info(f"Syncing Linear issues from team {team_id}")

        # Fetch issues from Linear
        try:
            issues, _ = await client.get_team_issues(
                team_id=team_id,
                limit=request.limit,
            )
        except Exception as e:
            logger.error(f"Failed to fetch issues from Linear: {e}")
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to fetch issues from Linear API: {str(e)}. "
                    f"Check your API key and Team ID."
                ),
            )

        synced_count = 0
        updated_count = 0
        converted_count = 0  # To Do → Triage conversions

        # Get cached state IDs from settings
        triage_state_setting = (
            db.query(Setting).filter(Setting.key == "linear_state_triage_id").first()
        )
        triage_state_id = str(triage_state_setting.value) if triage_state_setting else None

        for linear_issue in issues:
            linear_id = linear_issue["id"]
            state_name = linear_issue["state"]["name"]

            # Log all state names found for debugging
            logger.info(f"Found issue {linear_issue['identifier']} in state: '{state_name}'")

            # Filter: Only import Triage and To Do, ignore In Progress
            # Handle both "To Do" (with space) and "Todo" (without space)
            if state_name.lower() not in ["triage", "to do", "todo"]:
                logger.info(
                    f"⏭️  Skipping issue {linear_issue['identifier']} - "
                    f"state '{state_name}' not in [Triage, To Do, Todo]"
                )
                continue

            # Check if already exists
            existing = db.query(LinearIssue).filter(LinearIssue.linear_id == linear_id).first()

            # Extract labels
            labels_data = linear_issue.get("labels") or {}
            label_nodes = labels_data.get("nodes", [])
            labels: list[dict[str, Any]] = [
                {"name": label["name"], "color": label["color"]} for label in label_nodes
            ]
            repo_label_names = _parse_repo_labels(label_nodes)

            if existing:
                # Update existing
                existing.title = linear_issue["title"]
                existing.description = linear_issue.get("description")  # type: ignore[assignment]
                existing.priority = linear_issue.get("priority", 0)
                existing.labels = labels  # type: ignore[assignment]
                existing.linear_state_id = linear_issue["state"]["id"]
                existing.linear_state_name = linear_issue["state"]["name"]
                assignee_data = linear_issue.get("assignee") or {}
                existing.assignee_id = assignee_data.get("id")  # type: ignore[assignment]
                existing.assignee_name = assignee_data.get("name")  # type: ignore[assignment]
                existing.synced_at = datetime.utcnow()  # type: ignore[assignment]
                existing.updated_at = datetime.utcnow()  # type: ignore[assignment]

                issue_obj = existing
                updated_count += 1
            else:
                # Create new
                assignee_data = linear_issue.get("assignee") or {}
                issue_obj = LinearIssue(
                    linear_id=linear_id,
                    linear_identifier=linear_issue["identifier"],
                    linear_url=linear_issue["url"],
                    linear_team_id=linear_issue["team"]["id"],
                    linear_team_name=linear_issue["team"]["name"],
                    title=linear_issue["title"],
                    description=linear_issue.get("description"),
                    priority=linear_issue.get("priority", 0),
                    labels=labels,
                    linear_state_id=linear_issue["state"]["id"],
                    linear_state_name=linear_issue["state"]["name"],
                    assignee_id=assignee_data.get("id"),
                    assignee_name=assignee_data.get("name"),
                    turbowrap_state="analysis",  # Default initial state
                    synced_at=datetime.utcnow(),
                )
                db.add(issue_obj)
                db.flush()  # Get ID
                synced_count += 1

            # Convert "To Do" to "Triage" on Linear
            if state_name.lower() == "to do" and triage_state_id:
                try:
                    await client.update_issue_state(linear_id, triage_state_id)
                    issue_obj.linear_state_name = "Triage"  # type: ignore[assignment]
                    converted_count += 1
                    logger.info(f"Converted {linear_issue['identifier']} from To Do to Triage")
                except Exception as e:
                    logger.error(f"Failed to convert state for {linear_issue['identifier']}: {e}")

            # Link repositories based on labels (max 3)
            if repo_label_names:
                linked_count = 0
                for repo_name in repo_label_names[:3]:  # Max 3 repos
                    # Find repository by name (partial match)
                    repo = (
                        db.query(Repository).filter(Repository.name.ilike(f"%{repo_name}%")).first()
                    )

                    if repo:
                        # Create link if doesn't exist
                        existing_link = (
                            db.query(LinearIssueRepositoryLink)
                            .filter(
                                and_(
                                    LinearIssueRepositoryLink.linear_issue_id == issue_obj.id,
                                    LinearIssueRepositoryLink.repository_id == repo.id,
                                )
                            )
                            .first()
                        )

                        if not existing_link:
                            link = LinearIssueRepositoryLink(
                                linear_issue_id=issue_obj.id,
                                repository_id=repo.id,
                                link_source="label",
                                source_label=f"repo:{repo_name}",
                            )
                            db.add(link)
                            linked_count += 1

                if linked_count > 0:
                    logger.info(
                        f"Linked {linked_count} repositories to {linear_issue['identifier']}"
                    )

        db.commit()

        return {
            "status": "ok",
            "synced": synced_count,
            "updated": updated_count,
            "converted_to_triage": converted_count,
            "total": len(issues),
        }

    except HTTPException:
        # Re-raise HTTP exceptions (from _get_linear_client or _get_team_id)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during sync: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.post("/improve/phase1")
async def improve_issue_phase1(
    request: ImproveIssueRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phase 1: Generate clarifying questions for issue analysis."""
    issue = db.query(LinearIssue).filter(LinearIssue.id == request.issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if issue is in correct state
    if issue.turbowrap_state not in ["analysis", "repo_link"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Issue must be in 'analysis' or 'repo_link' state, "
                f"currently in '{issue.turbowrap_state}'"
            ),
        )

    client = _get_linear_client(db)
    analyzer = LinearIssueAnalyzer(client)

    try:
        questions = await analyzer.analyze_phase1_questions(issue)
        return {"questions": questions, "count": len(questions)}
    except Exception as e:
        logger.error(f"Phase 1 analysis failed for {issue.linear_identifier}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/improve/phase2")
async def improve_issue_phase2(
    request: ImproveIssuePhase2Request,
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """Phase 2: Deep analysis with user answers (SSE streaming)."""
    issue = db.query(LinearIssue).filter(LinearIssue.id == request.issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if issue is in correct state
    if issue.turbowrap_state not in ["analysis", "repo_link"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Issue must be in 'analysis' or 'repo_link' state, "
                f"currently in '{issue.turbowrap_state}'"
            ),
        )

    client = _get_linear_client(db)
    analyzer = LinearIssueAnalyzer(client)

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        """Stream analysis progress via SSE."""
        try:
            async for message in analyzer.analyze_phase2_with_answers(issue, request.answers):
                if message == "COMPLETE":
                    # Update database with analysis results
                    issue.improved_description = analyzer.last_improved_description  # type: ignore[assignment]
                    issue.analysis_summary = analyzer.last_analysis_summary  # type: ignore[assignment]
                    issue.user_answers = request.answers  # type: ignore[assignment]
                    issue.analyzed_at = datetime.utcnow()  # type: ignore[assignment]
                    issue.analyzed_by = "claude_opus"  # type: ignore[assignment]

                    # Transition state: analysis → repo_link
                    if issue.turbowrap_state == "analysis":
                        issue.turbowrap_state = "repo_link"  # type: ignore[assignment]

                    issue.updated_at = datetime.utcnow()  # type: ignore[assignment]
                    db.commit()

                    # Update Linear state: Triage → To Do
                    todo_state_setting = (
                        db.query(Setting).filter(Setting.key == "linear_state_todo_id").first()
                    )

                    if todo_state_setting and todo_state_setting.value:
                        try:
                            await client.update_issue_state(
                                str(issue.linear_id), str(todo_state_setting.value)
                            )
                            issue.linear_state_name = "To Do"  # type: ignore[assignment]
                            db.commit()
                            logger.info(
                                f"Updated Linear state to To Do for {issue.linear_identifier}"
                            )
                        except Exception as e:
                            logger.error(f"Failed to update Linear state: {e}")

                    # Auto-link repositories from analyzer recommendations
                    if analyzer.last_repository_recommendations:
                        linked_count = 0
                        for repo_name in analyzer.last_repository_recommendations[:3]:
                            # Find repository by name (partial match)
                            repo = (
                                db.query(Repository)
                                .filter(Repository.name.ilike(f"%{repo_name}%"))
                                .first()
                            )

                            if repo:
                                # Create link if doesn't exist
                                existing_link = (
                                    db.query(LinearIssueRepositoryLink)
                                    .filter(
                                        and_(
                                            LinearIssueRepositoryLink.linear_issue_id == issue.id,
                                            LinearIssueRepositoryLink.repository_id == repo.id,
                                        )
                                    )
                                    .first()
                                )

                                if not existing_link:
                                    # Check max 3 repos constraint
                                    current_count = (
                                        db.query(LinearIssueRepositoryLink)
                                        .filter(
                                            LinearIssueRepositoryLink.linear_issue_id == issue.id
                                        )
                                        .count()
                                    )

                                    if current_count < 3:
                                        link = LinearIssueRepositoryLink(
                                            linear_issue_id=issue.id,
                                            repository_id=repo.id,
                                            link_source="claude_analysis",
                                            confidence_score=90.0,  # High confidence from analysis
                                        )
                                        db.add(link)
                                        linked_count += 1
                                        db.commit()

                        if linked_count > 0:
                            logger.info(
                                f"Auto-linked {linked_count} repositories from Claude analysis"
                            )

                    improved_desc = analyzer.last_improved_description
                    preview = improved_desc[:500] if improved_desc else ""
                    yield {
                        "event": "complete",
                        "data": json.dumps(
                            {
                                "status": "complete",
                                "improved_description": preview,
                                "repository_count": len(analyzer.last_repository_recommendations),
                            }
                        ),
                    }
                else:
                    # Progress message
                    yield {"event": "progress", "data": json.dumps({"message": message})}

        except Exception as e:
            logger.error(f"Phase 2 analysis failed: {e}")
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())


@router.post("/link-repository")
def link_repository(
    request: LinkRepositoryRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Manually link a repository to a Linear issue."""
    issue = db.query(LinearIssue).filter(LinearIssue.id == request.issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Check if link exists
    existing = (
        db.query(LinearIssueRepositoryLink)
        .filter(
            and_(
                LinearIssueRepositoryLink.linear_issue_id == issue.id,
                LinearIssueRepositoryLink.repository_id == repo.id,
            )
        )
        .first()
    )

    if existing:
        return {"status": "ok", "message": "Link already exists"}

    # Check max 3 repos constraint
    link_count = (
        db.query(LinearIssueRepositoryLink)
        .filter(LinearIssueRepositoryLink.linear_issue_id == issue.id)
        .count()
    )

    if link_count >= 3:
        raise HTTPException(
            status_code=400,
            detail="Maximum 3 repositories per issue. Remove an existing link first.",
        )

    link = LinearIssueRepositoryLink(
        linear_issue_id=issue.id,
        repository_id=repo.id,
        link_source=request.link_source,
    )
    db.add(link)
    db.commit()

    return {"status": "ok", "message": f"Linked to {repo.name}"}


@router.post("/start-development/{issue_id}")
async def start_development(
    issue_id: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Mark issue as active and ready for development.

    Enforces single-active-issue constraint.
    """
    issue = db.query(LinearIssue).filter(LinearIssue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if issue has repository links
    links = (
        db.query(LinearIssueRepositoryLink)
        .filter(LinearIssueRepositoryLink.linear_issue_id == issue_id)
        .count()
    )

    if links == 0:
        raise HTTPException(
            status_code=400,
            detail="Issue must be linked to at least one repository before development",
        )

    # Check if another issue is active
    active_issue = (
        db.query(LinearIssue)
        .filter(
            and_(
                LinearIssue.is_active,
                LinearIssue.id != issue_id,
            )
        )
        .first()
    )

    if active_issue:
        raise HTTPException(
            status_code=409,
            detail=f"Another issue is already active: {active_issue.linear_identifier}",
        )

    # Mark as active and in_progress
    issue.is_active = True  # type: ignore[assignment]
    issue.turbowrap_state = "in_progress"  # type: ignore[assignment]
    issue.updated_at = datetime.utcnow()  # type: ignore[assignment]
    db.commit()

    # Update Linear state to "In Progress"
    client = _get_linear_client(db)
    inprogress_state_setting = (
        db.query(Setting).filter(Setting.key == "linear_state_inprogress_id").first()
    )

    if inprogress_state_setting and inprogress_state_setting.value:
        try:
            await client.update_issue_state(
                str(issue.linear_id), str(inprogress_state_setting.value)
            )
            logger.info(f"Updated Linear state to In Progress for {issue.linear_identifier}")
        except Exception as e:
            logger.error(f"Failed to update Linear state: {e}")

    return {"status": "ok", "message": "Issue marked as active"}


@router.get("/teams")
async def get_linear_teams(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get all teams accessible with configured API key."""
    try:
        client = _get_linear_client(db)
        teams = await client.get_teams()

        return {"teams": teams}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch teams: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch teams from Linear: {str(e)}")


@router.get("/users")
async def get_linear_users(
    team_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get all users from Linear workspace."""
    try:
        client = _get_linear_client(db)
        users = await client.get_users(team_id)

        return {"users": users}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch users: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch users from Linear: {str(e)}")


@router.get("/settings/states")
async def get_linear_states(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get workflow states from Linear (for setup)."""
    client = _get_linear_client(db)
    team_id = _get_team_id(db)

    states = await client.get_workflow_states(team_id)

    return {"states": states}


# --- Issue Creation Workflow ---


@router.post("/create/analyze")
async def analyze_for_creation(
    title: str = Form(...),
    description: str = Form(...),
    issue_type: str = Form("bug"),
    figma_link: str = Form(None),
    website_link: str = Form(None),
    screenshots: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """Step 2: Analyze screenshots with Gemini + generate questions with Claude (SSE streaming)."""

    # Read screenshots first (can only be done once)
    screenshots_data: list[tuple[str, bytes]] = []
    for file in screenshots:
        content = await file.read()
        screenshots_data.append(
            (file.filename or f"screenshot_{len(screenshots_data)}.png", content)
        )

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        try:
            # Create temporary directory for screenshots
            session_id = str(uuid.uuid4())
            temp_dir = Path("/tmp/turbowrap_screenshots") / session_id
            temp_dir.mkdir(parents=True, exist_ok=True)

            yield {
                "event": "log",
                "data": json.dumps({"message": f"📁 Sessione {session_id[:8]}..."}),
            }

            # Save screenshots
            screenshot_paths: list[str] = []
            for filename, content in screenshots_data:
                path = temp_dir / filename
                with open(path, "wb") as f:
                    f.write(content)
                screenshot_paths.append(str(path))

            if screenshot_paths:
                yield {
                    "event": "log",
                    "data": json.dumps(
                        {"message": f"💾 Salvati {len(screenshot_paths)} screenshot"}
                    ),
                }

            # Gemini analysis
            gemini_insights = ""
            if screenshot_paths:
                yield {
                    "event": "log",
                    "data": json.dumps({"message": "🔮 Gemini sta analizzando gli screenshot..."}),
                }

                try:
                    from ...config import get_settings
                    from ...llm import GeminiProClient

                    # Load and format prompt template
                    settings = get_settings()
                    prompt_path = settings.agents_dir / "prompts" / "screenshot_analysis.md"
                    prompt_template = prompt_path.read_text(encoding="utf-8")
                    formatted_prompt = prompt_template.format(
                        title=title,
                        description=description,
                        figma_link=figma_link or "N/A",
                        website_link=website_link or "N/A",
                    )

                    gemini = GeminiProClient()
                    gemini_insights = gemini.analyze_images(formatted_prompt, screenshot_paths)

                    yield {
                        "event": "log",
                        "data": json.dumps(
                            {"message": f"✅ Gemini completato ({len(gemini_insights)} caratteri)"}
                        ),
                    }
                except Exception as e:
                    yield {
                        "event": "log",
                        "data": json.dumps({"message": f"❌ Gemini fallito: {str(e)}"}),
                    }
                    gemini_insights = f"Screenshot analysis failed: {str(e)}"

            # Claude question generation
            yield {
                "event": "log",
                "data": json.dumps({"message": "🤖 Claude sta generando le domande..."}),
            }

            # Map issue_type to Italian label
            issue_type_labels = {
                "bug": "Bug Report",
                "suggestion": "Suggerimento/Feature Request",
                "question": "Domanda/Dubbio",
            }
            issue_type_label = issue_type_labels.get(issue_type, issue_type)

            prompt_content = f"""Genera 3-4 domande (massimo 4) per chiarire questa issue Linear. Sii conciso e fai solo domande essenziali.

Tipo: {issue_type_label}
Titolo: {title}
Descrizione: {description}
Figma: {figma_link or "N/A"}
Sito: {website_link or "N/A"}

Analisi Gemini:
{gemini_insights if gemini_insights else "Nessuno screenshot fornito"}

Output JSON: {{"questions": [{{"id": 1, "question": "...", "why": "..."}}]}}
"""

            try:
                result = subprocess.run(
                    ["claude", "--agent", "agents/linear_question_generator.md"],
                    input=prompt_content,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode != 0:
                    raise Exception(f"Claude CLI failed: {result.stderr[:200]}")

                output = result.stdout.strip()

                # Extract JSON from markdown if needed
                json_str = output
                if "```json" in output:
                    start = output.find("```json") + 7
                    end = output.find("```", start)
                    json_str = output[start:end].strip()
                elif "```" in output:
                    start = output.find("```") + 3
                    end = output.find("```", start)
                    json_str = output[start:end].strip()

                questions_data = json.loads(json_str)
                questions = questions_data.get("questions", [])

                yield {
                    "event": "log",
                    "data": json.dumps({"message": f"✅ Claude generato {len(questions)} domande"}),
                }

                # Send final result
                yield {
                    "event": "complete",
                    "data": json.dumps(
                        {
                            "gemini_insights": gemini_insights,
                            "questions": questions,
                            "temp_session_id": session_id,
                            "screenshot_count": len(screenshot_paths),
                        }
                    ),
                }

            except Exception as e:
                yield {"event": "error", "data": json.dumps({"error": str(e)})}

        except Exception as e:
            logger.error(f"[create/analyze] Unexpected error: {e}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())


@router.post("/create/finalize")
async def finalize_creation(
    request: FinalizeIssueRequest, db: Session = Depends(get_db)
) -> EventSourceResponse:
    """Step 3: Generate final description + create issue (SSE streaming).

    Takes user answers and generates complete issue description with Claude,
    then creates the issue on Linear.

    SSE Events:
    - progress: {"message": "..."}
    - complete: {"identifier": "...", "url": "..."}
    - error: {"error": "..."}
    """

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        try:
            # Step 1: Claude description finalization
            logger.info(f"[create/finalize] Starting finalization for '{request.title}'")
            yield {
                "event": "progress",
                "data": json.dumps({"message": "Generando descrizione con Claude..."}),
            }

            answers_text = "\n".join([f"{k}: {v}" for k, v in request.user_answers.items()])

            # Map issue_type to Italian label
            issue_type_labels = {
                "bug": "🐛 Bug Report",
                "suggestion": "💡 Feature Request / Suggerimento",
                "question": "❓ Domanda / Dubbio",
            }
            issue_type_label = issue_type_labels.get(request.issue_type, request.issue_type)

            prompt_content = f"""Genera descrizione completa per issue Linear.

Tipo: {issue_type_label}
Titolo: {request.title}
Descrizione iniziale: {request.description}
Figma: {request.figma_link or "N/A"}
Sito: {request.website_link or "N/A"}

Analisi Gemini:
{request.gemini_insights}

Risposte utente:
{answers_text}

Genera descrizione markdown con sezione iniziale che indica il tipo ({issue_type_label}), poi:
1. Problema/Richiesta
2. Acceptance Criteria
3. Approccio Tecnico (se applicabile)
4. Rischi
"""

            try:
                logger.info("[create/finalize] Running Claude finalizer")
                result = subprocess.run(
                    ["claude", "--agent", "agents/linear_finalizer.md"],
                    input=prompt_content,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )

                final_desc = result.stdout.strip()
                logger.info(f"[create/finalize] Generated description ({len(final_desc)} chars)")

            except subprocess.TimeoutExpired:
                logger.error("[create/finalize] Claude finalizer timed out")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": "Description generation timed out"}),
                }
                return
            except Exception as e:
                logger.error(f"[create/finalize] Claude finalizer failed: {e}")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": f"Description generation failed: {str(e)}"}),
                }
                return

            # Add links to description
            if request.figma_link:
                final_desc += f"\n\n**Figma**: {request.figma_link}"
            if request.website_link:
                final_desc += f"\n\n**Sito**: {request.website_link}"

            # Step 1.5: Auto-detect repository
            detected_repo_name: str | None = None
            yield {
                "event": "progress",
                "data": json.dumps({"message": "Rilevando repository coinvolto..."}),
            }

            try:
                # Get available repositories
                repos = db.query(Repository).filter(Repository.deleted_at.is_(None)).all()
                repo_names = [r.name for r in repos]

                if repo_names:
                    detect_prompt = (
                        f"""Analizza questa issue e identifica quale """
                        f"""repository è coinvolto.

Titolo: {request.title}
Descrizione: {request.description}
Analisi Gemini: {request.gemini_insights[:500]}
Risposte utente: {answers_text[:500]}

Repository disponibili:
{chr(10).join(f"- {name}" for name in repo_names)}

Rispondi SOLO con il nome esatto del repository coinvolto, oppure "NONE" """
                        f"""se non puoi determinarlo con certezza.
Non aggiungere spiegazioni, solo il nome del repository."""
                    )

                    result = subprocess.run(
                        ["claude", "--model", "claude-sonnet-4-5-20250929"],
                        input=detect_prompt,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    if result.returncode == 0:
                        detected = result.stdout.strip()
                        if detected and detected != "NONE" and detected in repo_names:
                            detected_repo_name = detected
                            logger.info(
                                f"[create/finalize] Auto-detected repository: {detected_repo_name}"
                            )
                            yield {
                                "event": "progress",
                                "data": json.dumps(
                                    {"message": f"📦 Repository rilevato: {detected_repo_name}"}
                                ),
                            }
                        else:
                            logger.info(
                                f"[create/finalize] No repository detected (response: {detected})"
                            )
                    else:
                        logger.warning(
                            f"[create/finalize] Repository detection failed: {result.stderr[:200]}"
                        )

            except Exception as e:
                logger.warning(f"[create/finalize] Repository auto-detection failed: {e}")
                # Non fatal, prosegue senza repo

            # Step 2: Create issue on Linear
            yield {
                "event": "progress",
                "data": json.dumps({"message": "Creando issue su Linear..."}),
            }

            try:
                client = _get_linear_client(db)
                logger.info(f"[create/finalize] Creating issue on Linear (team: {request.team_id})")

                issue = await client.create_issue(
                    team_id=request.team_id,
                    title=request.title,
                    description=final_desc,
                    priority=request.priority,
                    assignee_id=request.assignee_id,
                    due_date=request.due_date,
                )

                logger.info(f"[create/finalize] Issue created: {issue['identifier']}")

            except Exception as e:
                logger.error(f"[create/finalize] Linear issue creation failed: {e}")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": f"Linear issue creation failed: {str(e)}"}),
                }
                return

            # Step 3: Save to database
            yield {"event": "progress", "data": json.dumps({"message": "Salvando in database..."})}

            try:
                db_issue = LinearIssue(
                    linear_id=issue["id"],
                    linear_identifier=issue["identifier"],
                    linear_url=issue["url"],
                    linear_team_id=issue["team"]["id"],
                    linear_team_name=issue["team"]["name"],
                    title=request.title,
                    description=request.description,
                    improved_description=final_desc,
                    turbowrap_state="repo_link",  # Skip analysis step
                    analyzed_by="gemini_claude",
                    analyzed_at=datetime.utcnow(),
                    user_answers=request.user_answers,  # Store user answers
                    priority=request.priority,
                )
                db.add(db_issue)
                db.commit()
                db.refresh(db_issue)  # Refresh to get ID

                logger.info(f"[create/finalize] Saved to database: {db_issue.id}")

                # Link detected repository
                if detected_repo_name:
                    try:
                        repo = (
                            db.query(Repository)
                            .filter(
                                Repository.name == detected_repo_name,
                                Repository.deleted_at.is_(None),
                            )
                            .first()
                        )

                        if repo:
                            link = LinearIssueRepositoryLink(
                                linear_issue_id=db_issue.id,
                                repository_id=repo.id,
                                link_source="claude_analysis",
                                confidence_score=95.0,  # High confidence from Claude
                            )
                            db.add(link)
                            db.commit()
                            logger.info(
                                f"[create/finalize] Linked repository: {detected_repo_name}"
                            )

                            # Update state to in_progress since repo is linked
                            db_issue.turbowrap_state = "repo_link"  # type: ignore[assignment]
                            db.commit()

                            yield {
                                "event": "progress",
                                "data": json.dumps(
                                    {"message": f"✅ Repository collegato: {detected_repo_name}"}
                                ),
                            }
                    except Exception as e:
                        logger.warning(f"[create/finalize] Failed to link repository: {e}")
                        # Non fatal, issue was created successfully

            except Exception as e:
                logger.error(f"[create/finalize] Database save failed: {e}")
                # Issue was created on Linear but not saved locally - log for manual recovery
                logger.critical(
                    f"[create/finalize] ORPHANED ISSUE: {issue['identifier']} at {issue['url']}"
                )
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"error": f"Database save failed: {str(e)}", "linear_url": issue["url"]}
                    ),
                }
                return

            # Step 4: Cleanup temporary files
            temp_dir = Path("/tmp/turbowrap_screenshots") / request.temp_session_id
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"[create/finalize] Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"[create/finalize] Failed to cleanup temp dir: {e}")

            # Complete
            yield {
                "event": "complete",
                "data": json.dumps(
                    {"identifier": issue["identifier"], "url": issue["url"], "id": db_issue.id}
                ),
            }

        except Exception as e:
            logger.error(f"[create/finalize] Unexpected error: {e}")
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())
