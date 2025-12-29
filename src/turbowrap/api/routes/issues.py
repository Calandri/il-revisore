"""Issue tracking routes."""

import json
import logging
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case
from sqlalchemy.orm import Session

from ...db.models import Issue, IssueStatus, is_valid_issue_transition
from ..deps import get_db

logger = logging.getLogger(__name__)

# S3 bucket for fix logs
S3_BUCKET = "turbowrap-thinking"

router = APIRouter(prefix="/issues", tags=["issues"])


class IssueComment(BaseModel):
    """Comment on an issue."""

    id: str
    author: str
    content: str
    created_at: str
    comment_type: str = "human"  # human, ai, system


class IssueAttachment(BaseModel):
    """Attachment on an issue."""

    filename: str
    s3_key: str
    file_type: str
    uploaded_at: str


class IssueResponse(BaseModel):
    """Issue response schema."""

    id: str
    task_id: str | None = None
    repository_id: str
    issue_code: str
    severity: str
    category: str
    rule: str | None = None
    file: str
    line: int | None = None
    end_line: int | None = None
    title: str
    description: str
    current_code: str | None = None
    suggested_fix: str | None = None
    references: list[Any] | None = None
    flagged_by: list[Any] | None = None
    status: str
    resolution_note: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Linear integration (NEW)
    linear_id: str | None = None
    linear_identifier: str | None = None  # e.g., "TEAM-123"
    linear_url: str | None = None

    # Discussion & Attachments (NEW)
    comments: list[IssueComment] | None = None
    attachments: list[IssueAttachment] | None = None

    # Phase tracking (NEW)
    phase_started_at: datetime | None = None
    is_active: bool = False
    is_viewed: bool = False  # Manual "reviewed" flag

    # Fix result fields (populated when resolved by fixer)
    fix_code: str | None = None
    fix_explanation: str | None = None
    fix_files_modified: list[str] | None = None
    fix_commit_sha: str | None = None
    fix_branch: str | None = None
    fix_session_id: str | None = None  # For S3 log retrieval
    fixed_at: datetime | None = None
    fixed_by: str | None = None

    # Effort estimation (populated by reviewer agent)
    estimated_effort: int | None = None  # 1-5 scale (1=trivial, 5=major)
    estimated_files_count: int | None = None

    class Config:
        from_attributes = True


class IssueUpdateRequest(BaseModel):
    """Request to update an issue."""

    status: str | None = Field(
        None, description="New status: open, in_progress, resolved, ignored, duplicate"
    )
    resolution_note: str | None = Field(
        None, description="Note explaining why issue was resolved/ignored"
    )


class IssueSummary(BaseModel):
    """Summary statistics for issues."""

    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    by_category: dict[str, int]
    linear_linked: int = 0  # Count of issues linked to Linear


class LinkLinearRequest(BaseModel):
    """Request to link an issue to Linear."""

    linear_identifier: str = Field(
        ..., description="Linear issue identifier (e.g., TEAM-123) or URL"
    )


class AddCommentRequest(BaseModel):
    """Request to add a comment to an issue."""

    content: str = Field(..., min_length=1, description="Comment content")
    author: str = Field(default="user", description="Comment author")
    comment_type: str = Field(default="human", description="Comment type: human, ai, system")


@router.get("", response_model=list[IssueResponse])
def list_issues(
    repository_id: str | None = None,
    task_id: str | None = None,
    severity: str | None = None,
    status: str | None = Query(default=None, description="Filter by status"),
    category: str | None = None,
    file: str | None = None,
    linear_linked: str | None = Query(
        default=None, description="Filter by Linear link: 'linked', 'unlinked', or None for all"
    ),
    search: str | None = Query(
        default=None, description="Search in title, description, file, issue_code"
    ),
    order_by: str | None = Query(
        default="severity", description="Order by: severity, updated_at, created_at"
    ),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Issue]:
    """
    List issues with optional filters.

    Filters:
    - repository_id: Filter by repository
    - task_id: Filter by task
    - severity: CRITICAL, HIGH, MEDIUM, LOW
    - status: open, in_progress, resolved, ignored, duplicate
    - category: security, performance, architecture, etc.
    - file: Filter by file path (partial match)
    - linear_linked: 'linked' or 'unlinked'
    - order_by: severity (default), updated_at, created_at
    """
    query = db.query(Issue)

    if repository_id:
        query = query.filter(Issue.repository_id == repository_id)
    if task_id:
        query = query.filter(Issue.task_id == task_id)
    if severity:
        query = query.filter(Issue.severity == severity.upper())
    if status:
        query = query.filter(Issue.status == status)
    if category:
        query = query.filter(Issue.category == category)
    if file:
        query = query.filter(Issue.file.contains(file))
    if linear_linked == "linked":
        query = query.filter(Issue.linear_id.isnot(None))
    elif linear_linked == "unlinked":
        query = query.filter(Issue.linear_id.is_(None))
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Issue.title.ilike(search_term))
            | (Issue.description.ilike(search_term))
            | (Issue.file.ilike(search_term))
            | (Issue.issue_code.ilike(search_term))
        )

    # Order by selected criteria
    if order_by == "updated_at":
        query = query.order_by(Issue.updated_at.desc())
    elif order_by == "created_at":
        query = query.order_by(Issue.created_at.desc())
    else:
        # Default: order by severity (CRITICAL first) and creation date
        severity_order = case(
            (Issue.severity == "CRITICAL", 1),
            (Issue.severity == "HIGH", 2),
            (Issue.severity == "MEDIUM", 3),
            (Issue.severity == "LOW", 4),
            else_=5,
        )
        query = query.order_by(severity_order, Issue.created_at.desc())

    issues: list[Issue] = query.offset(offset).limit(limit).all()
    return issues


@router.get("/summary", response_model=IssueSummary)
def get_issues_summary(
    repository_id: str | None = None,
    status: str | None = Query(default="open", description="Filter by status (default: open)"),
    db: Session = Depends(get_db),
) -> IssueSummary:
    """Get summary statistics for issues."""
    query = db.query(Issue)

    if repository_id:
        query = query.filter(Issue.repository_id == repository_id)
    if status:
        query = query.filter(Issue.status == status)

    issues: list[Issue] = query.all()

    by_severity: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_status: dict[str, int] = {
        "open": 0,
        "in_progress": 0,
        "resolved": 0,
        "ignored": 0,
        "duplicate": 0,
    }
    by_category: dict[str, int] = {}

    linear_linked_count = 0
    for issue in issues:
        # Count by severity - cast to str for type safety
        severity_val = str(issue.severity)
        if severity_val in by_severity:
            by_severity[severity_val] += 1

        # Count by status - cast to str for type safety
        status_val = str(issue.status)
        if status_val in by_status:
            by_status[status_val] += 1

        # Count by category - cast to str for type safety
        category_val = str(issue.category)
        if category_val not in by_category:
            by_category[category_val] = 0
        by_category[category_val] += 1

        # Count Linear linked
        if issue.linear_id:
            linear_linked_count += 1

    return IssueSummary(
        total=len(issues),
        by_severity=by_severity,
        by_status=by_status,
        by_category=by_category,
        linear_linked=linear_linked_count,
    )


@router.get("/{issue_id}", response_model=IssueResponse)
def get_issue(
    issue_id: str,
    db: Session = Depends(get_db),
) -> Issue:
    """Get issue details."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.patch("/{issue_id}", response_model=IssueResponse)
def update_issue(
    issue_id: str,
    data: IssueUpdateRequest,
    force: bool = Query(default=False, description="Force status change, bypass validation"),
    db: Session = Depends(get_db),
) -> Issue:
    """
    Update issue status or resolution note.

    Valid status transitions:
    - open -> in_progress, resolved, ignored, duplicate
    - in_progress -> resolved, ignored, open
    - resolved -> open (reopen)
    - ignored -> open (reopen)

    Use force=true to bypass transition validation (dangerous).
    """
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if data.status:
        valid_statuses = [s.value for s in IssueStatus]
        if data.status not in valid_statuses:
            raise HTTPException(
                status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}"
            )

        # Validate state transition (skip if force=true)
        if not force:
            current_status = IssueStatus(str(issue.status))
            new_status = IssueStatus(data.status)
            if not is_valid_issue_transition(current_status, new_status):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status transition: {current_status.value} → {new_status.value}",
                )

        issue.status = data.status  # type: ignore[assignment]

        # Set resolved_at timestamp when marking as resolved
        if data.status in ("resolved", "ignored", "duplicate"):
            issue.resolved_at = datetime.utcnow()  # type: ignore[assignment]
        elif data.status == "open":
            issue.resolved_at = None  # type: ignore[assignment]

    if data.resolution_note is not None:
        issue.resolution_note = data.resolution_note  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/resolve", response_model=IssueResponse)
def resolve_issue(
    issue_id: str,
    note: str = Query(default="", description="Resolution note"),
    db: Session = Depends(get_db),
) -> Issue:
    """Quick action to mark an issue as merged (closed)."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.MERGED.value  # type: ignore[assignment]
    issue.resolved_at = datetime.utcnow()  # type: ignore[assignment]
    if note:
        issue.resolution_note = note  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/ignore", response_model=IssueResponse)
def ignore_issue(
    issue_id: str,
    note: str = Query(default="", description="Reason for ignoring"),
    db: Session = Depends(get_db),
) -> Issue:
    """Quick action to mark an issue as ignored (false positive or won't fix)."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.IGNORED.value  # type: ignore[assignment]
    issue.resolved_at = datetime.utcnow()  # type: ignore[assignment]
    if note:
        issue.resolution_note = note  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/reopen", response_model=IssueResponse)
def reopen_issue(
    issue_id: str,
    db: Session = Depends(get_db),
) -> Issue:
    """Reopen a resolved or ignored issue."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.OPEN.value  # type: ignore[assignment]
    issue.resolved_at = None  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/toggle-viewed", response_model=IssueResponse)
def toggle_issue_viewed(
    issue_id: str,
    viewed: bool = Query(default=True, description="Set viewed status"),
    db: Session = Depends(get_db),
) -> Issue:
    """Toggle the is_viewed flag on an issue (manual triage marker)."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.is_viewed = viewed  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)
    return issue


class FixLogResponse(BaseModel):
    """Response with fix log data from S3."""

    session_id: str
    timestamp: str
    status: str
    branch_name: str | None = None
    issues_requested: int
    issues_fixed: int
    claude_prompts: list[dict[str, Any]] = []  # [{type, batch, issues, prompt}]
    gemini_prompt: str | None = None
    gemini_review: str | None = None


@router.get("/{issue_id}/fix-log", response_model=FixLogResponse)
def get_issue_fix_log(
    issue_id: str,
    db: Session = Depends(get_db),
) -> FixLogResponse:
    """
    Get the fix log for an issue from S3.

    Returns prompts sent to Claude CLI and Gemini CLI during the fix session.
    Only available for issues that have been fixed (have fix_session_id).
    """
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if not issue.fix_session_id:
        raise HTTPException(
            status_code=404,
            detail="No fix log available for this issue (not fixed yet or missing session_id)",
        )

    # The S3 key format is: fix-logs/{date}/{session_id}.json
    # We need to find the log since we don't know the date
    # Try to find it by listing prefix with session_id

    s3_client = boto3.client("s3")

    try:
        # List all objects with the fix-logs prefix to find our session
        paginator = s3_client.get_paginator("list_objects_v2")
        session_id = str(issue.fix_session_id)

        # Try fixed_at date first if available
        s3_key: str | None = None
        if issue.fixed_at:
            fixed_at_dt: datetime = issue.fixed_at  # type: ignore[assignment]
            date_str = fixed_at_dt.strftime("%Y-%m-%d")
            s3_key = f"fix-logs/{date_str}/{session_id}.json"
            try:
                s3_client.head_object(Bucket=S3_BUCKET, Key=s3_key)
            except ClientError:
                s3_key = None

        # If not found by date, search all fix-logs
        if not s3_key:
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="fix-logs/"):
                for obj in page.get("Contents", []):
                    if session_id in obj["Key"]:
                        s3_key = obj["Key"]
                        break
                if s3_key:
                    break

        if not s3_key:
            raise HTTPException(
                status_code=404, detail=f"Fix log not found in S3 for session {session_id}"
            )

        # Fetch the log
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        log_data: dict[str, Any] = json.loads(response["Body"].read().decode("utf-8"))

        return FixLogResponse(
            session_id=log_data.get("session_id", session_id),
            timestamp=log_data.get("timestamp", ""),
            status=log_data.get("status", "unknown"),
            branch_name=log_data.get("branch_name"),
            issues_requested=log_data.get("issues_requested", 0),
            issues_fixed=log_data.get("issues_fixed", 0),
            claude_prompts=log_data.get("claude_prompts", []),
            gemini_prompt=log_data.get("gemini_prompt"),
            gemini_review=log_data.get("gemini_review"),
        )

    except ClientError as e:
        logger.error(f"S3 error fetching fix log: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching fix log from S3: {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for fix log: {e}")
        raise HTTPException(status_code=500, detail="Fix log file is corrupted")


# =============================================================================
# LINEAR INTEGRATION ENDPOINTS
# =============================================================================


@router.post("/{issue_id}/link-linear", response_model=IssueResponse)
def link_issue_to_linear(
    issue_id: str,
    data: LinkLinearRequest,
    db: Session = Depends(get_db),
) -> Issue:
    """
    Link an issue to a Linear issue.

    Accepts either:
    - Linear identifier (e.g., "TEAM-123")
    - Linear URL (e.g., "https://linear.app/team/issue/TEAM-123")
    """
    import re
    import uuid

    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    linear_input = data.linear_identifier.strip()

    # Extract identifier from URL if provided
    url_match = re.search(r"linear\.app/[^/]+/issue/([A-Z]+-\d+)", linear_input)
    if url_match:
        linear_identifier = url_match.group(1)
        linear_url = linear_input
    elif re.match(r"^[A-Z]+-\d+$", linear_input):
        linear_identifier = linear_input
        linear_url = None  # Could be constructed if we knew the team slug
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid Linear identifier. Use format 'TEAM-123' or a Linear URL",
        )

    # Generate a Linear-compatible UUID if not syncing from Linear API
    # In a real implementation, you'd fetch this from Linear API
    linear_id = str(uuid.uuid4())

    issue.linear_id = linear_id  # type: ignore[assignment]
    issue.linear_identifier = linear_identifier  # type: ignore[assignment]
    if linear_url:
        issue.linear_url = linear_url  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)

    logger.info(f"Linked issue {issue_id} to Linear {linear_identifier}")
    return issue


@router.delete("/{issue_id}/link-linear", response_model=IssueResponse)
def unlink_issue_from_linear(
    issue_id: str,
    db: Session = Depends(get_db),
) -> Issue:
    """Remove Linear link from an issue."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if not issue.linear_id:
        raise HTTPException(status_code=400, detail="Issue is not linked to Linear")

    issue.linear_id = None  # type: ignore[assignment]
    issue.linear_identifier = None  # type: ignore[assignment]
    issue.linear_url = None  # type: ignore[assignment]

    db.commit()
    db.refresh(issue)

    logger.info(f"Unlinked issue {issue_id} from Linear")
    return issue


# =============================================================================
# COMMENTS ENDPOINTS
# =============================================================================


@router.post("/{issue_id}/comments", response_model=IssueResponse)
def add_comment_to_issue(
    issue_id: str,
    data: AddCommentRequest,
    db: Session = Depends(get_db),
) -> Issue:
    """Add a comment to an issue."""
    import uuid

    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Initialize comments list if None
    comments = issue.comments or []

    # Create new comment
    new_comment = {
        "id": str(uuid.uuid4()),
        "author": data.author,
        "content": data.content,
        "created_at": datetime.utcnow().isoformat(),
        "type": data.comment_type,
    }
    comments.append(new_comment)

    issue.comments = comments  # type: ignore[assignment]
    db.commit()
    db.refresh(issue)

    logger.info(f"Added comment to issue {issue_id} by {data.author}")
    return issue


@router.delete("/{issue_id}/comments/{comment_id}", response_model=IssueResponse)
def delete_comment_from_issue(
    issue_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
) -> Issue:
    """Delete a comment from an issue."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    comments = issue.comments or []

    # Find and remove the comment
    original_length = len(comments)
    comments = [c for c in comments if c.get("id") != comment_id]

    if len(comments) == original_length:
        raise HTTPException(status_code=404, detail="Comment not found")

    issue.comments = comments  # type: ignore[assignment]
    db.commit()
    db.refresh(issue)

    logger.info(f"Deleted comment {comment_id} from issue {issue_id}")
    return issue
