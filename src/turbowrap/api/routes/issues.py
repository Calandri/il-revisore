"""Issue tracking routes."""

import json
import logging
from datetime import datetime
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from ..deps import get_db
from ...db.models import Issue, IssueStatus, Repository

logger = logging.getLogger(__name__)

# S3 bucket for fix logs
S3_BUCKET = "turbowrap-thinking"

router = APIRouter(prefix="/issues", tags=["issues"])


class IssueResponse(BaseModel):
    """Issue response schema."""

    id: str
    task_id: str
    repository_id: str
    issue_code: str
    severity: str
    category: str
    rule: Optional[str] = None
    file: str
    line: Optional[int] = None
    title: str
    description: str
    current_code: Optional[str] = None
    suggested_fix: Optional[str] = None
    references: Optional[list] = None
    flagged_by: Optional[list] = None
    status: str
    resolution_note: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Fix result fields (populated when resolved by fixer)
    fix_code: Optional[str] = None
    fix_explanation: Optional[str] = None
    fix_files_modified: Optional[list[str]] = None
    fix_commit_sha: Optional[str] = None
    fix_branch: Optional[str] = None
    fix_session_id: Optional[str] = None  # For S3 log retrieval
    fixed_at: Optional[datetime] = None
    fixed_by: Optional[str] = None

    class Config:
        from_attributes = True


class IssueUpdateRequest(BaseModel):
    """Request to update an issue."""

    status: Optional[str] = Field(
        None,
        description="New status: open, in_progress, resolved, ignored, duplicate"
    )
    resolution_note: Optional[str] = Field(
        None,
        description="Note explaining why issue was resolved/ignored"
    )


class IssueSummary(BaseModel):
    """Summary statistics for issues."""

    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    by_category: dict[str, int]


@router.get("", response_model=list[IssueResponse])
def list_issues(
    repository_id: Optional[str] = None,
    task_id: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = Query(default=None, description="Filter by status"),
    category: Optional[str] = None,
    file: Optional[str] = None,
    search: Optional[str] = Query(default=None, description="Search in title, description, file, issue_code"),
    order_by: Optional[str] = Query(default="severity", description="Order by: severity, updated_at, created_at"),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    List issues with optional filters.

    Filters:
    - repository_id: Filter by repository
    - task_id: Filter by task
    - severity: CRITICAL, HIGH, MEDIUM, LOW
    - status: open, in_progress, resolved, ignored, duplicate
    - category: security, performance, architecture, etc.
    - file: Filter by file path (partial match)
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
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Issue.title.ilike(search_term)) |
            (Issue.description.ilike(search_term)) |
            (Issue.file.ilike(search_term)) |
            (Issue.issue_code.ilike(search_term))
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
            else_=5
        )
        query = query.order_by(severity_order, Issue.created_at.desc())

    issues = query.offset(offset).limit(limit).all()
    return issues


@router.get("/summary", response_model=IssueSummary)
def get_issues_summary(
    repository_id: Optional[str] = None,
    status: Optional[str] = Query(default="open", description="Filter by status (default: open)"),
    db: Session = Depends(get_db),
):
    """Get summary statistics for issues."""
    query = db.query(Issue)

    if repository_id:
        query = query.filter(Issue.repository_id == repository_id)
    if status:
        query = query.filter(Issue.status == status)

    issues = query.all()

    by_severity = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_status = {"open": 0, "in_progress": 0, "resolved": 0, "ignored": 0, "duplicate": 0}
    by_category = {}

    for issue in issues:
        # Count by severity
        if issue.severity in by_severity:
            by_severity[issue.severity] += 1

        # Count by status
        if issue.status in by_status:
            by_status[issue.status] += 1

        # Count by category
        if issue.category not in by_category:
            by_category[issue.category] = 0
        by_category[issue.category] += 1

    return IssueSummary(
        total=len(issues),
        by_severity=by_severity,
        by_status=by_status,
        by_category=by_category,
    )


@router.get("/{issue_id}", response_model=IssueResponse)
def get_issue(
    issue_id: str,
    db: Session = Depends(get_db),
):
    """Get issue details."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.patch("/{issue_id}", response_model=IssueResponse)
def update_issue(
    issue_id: str,
    data: IssueUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Update issue status or resolution note.

    Valid status transitions:
    - open -> in_progress, resolved, ignored, duplicate
    - in_progress -> resolved, ignored, open
    - resolved -> open (reopen)
    - ignored -> open (reopen)
    """
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if data.status:
        valid_statuses = [s.value for s in IssueStatus]
        if data.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses}"
            )
        issue.status = data.status

        # Set resolved_at timestamp when marking as resolved
        if data.status in ("resolved", "ignored", "duplicate"):
            issue.resolved_at = datetime.utcnow()
        elif data.status == "open":
            issue.resolved_at = None

    if data.resolution_note is not None:
        issue.resolution_note = data.resolution_note

    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/resolve", response_model=IssueResponse)
def resolve_issue(
    issue_id: str,
    note: str = Query(default="", description="Resolution note"),
    db: Session = Depends(get_db),
):
    """Quick action to mark an issue as resolved."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.RESOLVED.value
    issue.resolved_at = datetime.utcnow()
    if note:
        issue.resolution_note = note

    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/ignore", response_model=IssueResponse)
def ignore_issue(
    issue_id: str,
    note: str = Query(default="", description="Reason for ignoring"),
    db: Session = Depends(get_db),
):
    """Quick action to mark an issue as ignored (false positive or won't fix)."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.IGNORED.value
    issue.resolved_at = datetime.utcnow()
    if note:
        issue.resolution_note = note

    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/reopen", response_model=IssueResponse)
def reopen_issue(
    issue_id: str,
    db: Session = Depends(get_db),
):
    """Reopen a resolved or ignored issue."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.OPEN.value
    issue.resolved_at = None

    db.commit()
    db.refresh(issue)
    return issue


class FixLogResponse(BaseModel):
    """Response with fix log data from S3."""

    session_id: str
    timestamp: str
    status: str
    branch_name: Optional[str] = None
    issues_requested: int
    issues_fixed: int
    claude_prompts: list[dict] = []  # [{type, batch, issues, prompt}]
    gemini_prompt: Optional[str] = None
    gemini_review: Optional[str] = None


@router.get("/{issue_id}/fix-log", response_model=FixLogResponse)
def get_issue_fix_log(
    issue_id: str,
    db: Session = Depends(get_db),
):
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
            detail="No fix log available for this issue (not fixed yet or missing session_id)"
        )

    # The S3 key format is: fix-logs/{date}/{session_id}.json
    # We need to find the log since we don't know the date
    # Try to find it by listing prefix with session_id

    s3_client = boto3.client("s3")

    try:
        # List all objects with the fix-logs prefix to find our session
        paginator = s3_client.get_paginator("list_objects_v2")
        session_id = issue.fix_session_id

        # Try fixed_at date first if available
        s3_key = None
        if issue.fixed_at:
            date_str = issue.fixed_at.strftime("%Y-%m-%d")
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
                status_code=404,
                detail=f"Fix log not found in S3 for session {session_id}"
            )

        # Fetch the log
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        log_data = json.loads(response["Body"].read().decode("utf-8"))

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
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching fix log from S3: {str(e)}"
        )
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for fix log: {e}")
        raise HTTPException(
            status_code=500,
            detail="Fix log file is corrupted"
        )
