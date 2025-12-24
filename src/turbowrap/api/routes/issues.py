"""Issue tracking routes."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from ..deps import get_db
from ...db.models import Issue, IssueStatus, Repository

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

    # Order by severity (CRITICAL first) and creation date
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
