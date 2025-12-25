"""Linear integration routes."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from sse_starlette.sse import EventSourceResponse

from ..deps import get_db
from ...db.models import LinearIssue, LinearIssueRepositoryLink, Repository, Setting
from ...review.integrations.linear import LinearClient
from ...linear.analyzer import LinearIssueAnalyzer

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
    linear_team_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    improved_description: Optional[str] = None
    assignee_name: Optional[str] = None
    priority: int
    labels: Optional[list] = None
    turbowrap_state: str
    linear_state_name: Optional[str] = None
    is_active: bool
    analysis_summary: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    user_answers: Optional[dict] = None
    fix_commit_sha: Optional[str] = None
    fix_branch: Optional[str] = None
    repository_ids: list[str] = Field(default_factory=list)
    repository_names: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class LinearSyncRequest(BaseModel):
    """Request to sync issues from Linear."""
    team_id: Optional[str] = Field(None, description="Team ID (uses settings if not provided)")
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


# --- Helper Functions ---

def _get_linear_client(db: Session) -> LinearClient:
    """Get Linear client from settings."""
    setting = db.query(Setting).filter(Setting.key == "linear_api_key").first()
    if not setting or not setting.value:
        raise HTTPException(status_code=400, detail="Linear API key not configured")
    return LinearClient(api_key=setting.value)


def _get_team_id(db: Session, provided: Optional[str] = None) -> str:
    """Get team ID from settings or param."""
    if provided:
        return provided
    setting = db.query(Setting).filter(Setting.key == "linear_team_id").first()
    if not setting or not setting.value:
        raise HTTPException(status_code=400, detail="Linear team ID not configured")
    return setting.value


def _parse_repo_labels(labels: list[dict]) -> list[str]:
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
    state: Optional[str] = Query(None, description="Filter by TurboWrap state"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
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
    result = []
    for issue in issues:
        # Get linked repositories
        links = db.query(LinearIssueRepositoryLink).filter(
            LinearIssueRepositoryLink.linear_issue_id == issue.id
        ).all()

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
):
    """Sync issues from Linear to TurboWrap."""
    client = _get_linear_client(db)
    team_id = _get_team_id(db, request.team_id)

    logger.info(f"Syncing Linear issues from team {team_id}")

    # Fetch issues from Linear
    issues, _ = await client.get_team_issues(
        team_id=team_id,
        limit=request.limit,
    )

    synced_count = 0
    updated_count = 0
    converted_count = 0  # To Do → Triage conversions

    # Get cached state IDs from settings
    triage_state_setting = db.query(Setting).filter(Setting.key == "linear_state_triage_id").first()
    triage_state_id = triage_state_setting.value if triage_state_setting else None

    for linear_issue in issues:
        linear_id = linear_issue["id"]
        state_name = linear_issue["state"]["name"]

        # Filter: Only import Triage and To Do, ignore In Progress
        if state_name.lower() not in ["triage", "to do"]:
            logger.debug(f"Skipping issue {linear_issue['identifier']} in state {state_name}")
            continue

        # Check if already exists
        existing = db.query(LinearIssue).filter(
            LinearIssue.linear_id == linear_id
        ).first()

        # Extract labels
        label_nodes = linear_issue.get("labels", {}).get("nodes", [])
        labels = [{"name": l["name"], "color": l["color"]} for l in label_nodes]
        repo_label_names = _parse_repo_labels(label_nodes)

        if existing:
            # Update existing
            existing.title = linear_issue["title"]
            existing.description = linear_issue.get("description")
            existing.priority = linear_issue.get("priority", 0)
            existing.labels = labels
            existing.linear_state_id = linear_issue["state"]["id"]
            existing.linear_state_name = linear_issue["state"]["name"]
            existing.assignee_id = linear_issue.get("assignee", {}).get("id")
            existing.assignee_name = linear_issue.get("assignee", {}).get("name")
            existing.synced_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()

            issue_obj = existing
            updated_count += 1
        else:
            # Create new
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
                assignee_id=linear_issue.get("assignee", {}).get("id"),
                assignee_name=linear_issue.get("assignee", {}).get("name"),
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
                issue_obj.linear_state_name = "Triage"
                converted_count += 1
                logger.info(f"Converted {linear_issue['identifier']} from To Do to Triage")
            except Exception as e:
                logger.error(f"Failed to convert state for {linear_issue['identifier']}: {e}")

        # Link repositories based on labels (max 3)
        if repo_label_names:
            linked_count = 0
            for repo_name in repo_label_names[:3]:  # Max 3 repos
                # Find repository by name (partial match)
                repo = db.query(Repository).filter(
                    Repository.name.ilike(f"%{repo_name}%")
                ).first()

                if repo:
                    # Create link if doesn't exist
                    existing_link = db.query(LinearIssueRepositoryLink).filter(
                        and_(
                            LinearIssueRepositoryLink.linear_issue_id == issue_obj.id,
                            LinearIssueRepositoryLink.repository_id == repo.id,
                        )
                    ).first()

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
                logger.info(f"Linked {linked_count} repositories to {linear_issue['identifier']}")

    db.commit()

    return {
        "status": "ok",
        "synced": synced_count,
        "updated": updated_count,
        "converted_to_triage": converted_count,
        "total": len(issues),
    }


@router.post("/improve/phase1")
async def improve_issue_phase1(
    request: ImproveIssueRequest,
    db: Session = Depends(get_db),
):
    """Phase 1: Generate clarifying questions for issue analysis."""
    issue = db.query(LinearIssue).filter(LinearIssue.id == request.issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if issue is in correct state
    if issue.turbowrap_state not in ["analysis", "repo_link"]:
        raise HTTPException(
            status_code=400,
            detail=f"Issue must be in 'analysis' or 'repo_link' state, currently in '{issue.turbowrap_state}'"
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
):
    """Phase 2: Deep analysis with user answers (SSE streaming)."""
    issue = db.query(LinearIssue).filter(LinearIssue.id == request.issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if issue is in correct state
    if issue.turbowrap_state not in ["analysis", "repo_link"]:
        raise HTTPException(
            status_code=400,
            detail=f"Issue must be in 'analysis' or 'repo_link' state, currently in '{issue.turbowrap_state}'"
        )

    client = _get_linear_client(db)
    analyzer = LinearIssueAnalyzer(client)

    async def event_generator():
        """Stream analysis progress via SSE."""
        try:
            async for message in analyzer.analyze_phase2_with_answers(issue, request.answers):
                if message == "COMPLETE":
                    # Update database with analysis results
                    issue.improved_description = analyzer.last_improved_description
                    issue.analysis_summary = analyzer.last_analysis_summary
                    issue.user_answers = request.answers  # Store as JSON
                    issue.analyzed_at = datetime.utcnow()
                    issue.analyzed_by = "claude_opus"

                    # Transition state: analysis → repo_link
                    if issue.turbowrap_state == "analysis":
                        issue.turbowrap_state = "repo_link"

                    issue.updated_at = datetime.utcnow()
                    db.commit()

                    # Update Linear state: Triage → To Do
                    todo_state_setting = db.query(Setting).filter(
                        Setting.key == "linear_state_todo_id"
                    ).first()

                    if todo_state_setting and todo_state_setting.value:
                        try:
                            await client.update_issue_state(issue.linear_id, todo_state_setting.value)
                            issue.linear_state_name = "To Do"
                            db.commit()
                            logger.info(f"Updated Linear state to To Do for {issue.linear_identifier}")
                        except Exception as e:
                            logger.error(f"Failed to update Linear state: {e}")

                    # Auto-link repositories from analyzer recommendations
                    if analyzer.last_repository_recommendations:
                        linked_count = 0
                        for repo_name in analyzer.last_repository_recommendations[:3]:
                            # Find repository by name (partial match)
                            repo = db.query(Repository).filter(
                                Repository.name.ilike(f"%{repo_name}%")
                            ).first()

                            if repo:
                                # Create link if doesn't exist
                                existing_link = db.query(LinearIssueRepositoryLink).filter(
                                    and_(
                                        LinearIssueRepositoryLink.linear_issue_id == issue.id,
                                        LinearIssueRepositoryLink.repository_id == repo.id,
                                    )
                                ).first()

                                if not existing_link:
                                    # Check max 3 repos constraint
                                    current_count = db.query(LinearIssueRepositoryLink).filter(
                                        LinearIssueRepositoryLink.linear_issue_id == issue.id
                                    ).count()

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
                            logger.info(f"Auto-linked {linked_count} repositories from Claude analysis")

                    yield {
                        "event": "complete",
                        "data": json.dumps({
                            "status": "complete",
                            "improved_description": analyzer.last_improved_description[:500],  # Preview
                            "repository_count": len(analyzer.last_repository_recommendations),
                        })
                    }
                else:
                    # Progress message
                    yield {
                        "event": "progress",
                        "data": json.dumps({"message": message})
                    }

        except Exception as e:
            logger.error(f"Phase 2 analysis failed: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }

    return EventSourceResponse(event_generator())


@router.post("/link-repository")
def link_repository(
    request: LinkRepositoryRequest,
    db: Session = Depends(get_db),
):
    """Manually link a repository to a Linear issue."""
    issue = db.query(LinearIssue).filter(LinearIssue.id == request.issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Check if link exists
    existing = db.query(LinearIssueRepositoryLink).filter(
        and_(
            LinearIssueRepositoryLink.linear_issue_id == issue.id,
            LinearIssueRepositoryLink.repository_id == repo.id,
        )
    ).first()

    if existing:
        return {"status": "ok", "message": "Link already exists"}

    # Check max 3 repos constraint
    link_count = db.query(LinearIssueRepositoryLink).filter(
        LinearIssueRepositoryLink.linear_issue_id == issue.id
    ).count()

    if link_count >= 3:
        raise HTTPException(
            status_code=400,
            detail="Maximum 3 repositories per issue. Remove an existing link first."
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
):
    """Mark issue as active and ready for development.

    Enforces single-active-issue constraint.
    """
    issue = db.query(LinearIssue).filter(LinearIssue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if issue has repository links
    links = db.query(LinearIssueRepositoryLink).filter(
        LinearIssueRepositoryLink.linear_issue_id == issue_id
    ).count()

    if links == 0:
        raise HTTPException(
            status_code=400,
            detail="Issue must be linked to at least one repository before development"
        )

    # Check if another issue is active
    active_issue = db.query(LinearIssue).filter(
        and_(
            LinearIssue.is_active == True,
            LinearIssue.id != issue_id,
        )
    ).first()

    if active_issue:
        raise HTTPException(
            status_code=409,
            detail=f"Another issue is already active: {active_issue.linear_identifier}"
        )

    # Mark as active and in_progress
    issue.is_active = True
    issue.turbowrap_state = "in_progress"
    issue.updated_at = datetime.utcnow()
    db.commit()

    # Update Linear state to "In Progress"
    client = _get_linear_client(db)
    inprogress_state_setting = db.query(Setting).filter(
        Setting.key == "linear_state_inprogress_id"
    ).first()

    if inprogress_state_setting and inprogress_state_setting.value:
        try:
            await client.update_issue_state(issue.linear_id, inprogress_state_setting.value)
            logger.info(f"Updated Linear state to In Progress for {issue.linear_identifier}")
        except Exception as e:
            logger.error(f"Failed to update Linear state: {e}")

    return {"status": "ok", "message": "Issue marked as active"}


@router.get("/settings/states")
async def get_linear_states(
    db: Session = Depends(get_db),
):
    """Get workflow states from Linear (for setup)."""
    client = _get_linear_client(db)
    team_id = _get_team_id(db)

    states = await client.get_workflow_states(team_id)

    return {"states": states}
