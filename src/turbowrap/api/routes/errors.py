"""Error reporting routes for TurboWrap clients.

This module provides an API endpoint for external applications to report
errors, which are then stored as issues in the TurboWrap database.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.models import Issue, Repository, Setting
from ..deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["errors"])


# --- Schemas ---


class ErrorDetail(BaseModel):
    """Error detail information."""

    message: str
    type: str = "Error"
    code: str | None = None


class ErrorReportRequest(BaseModel):
    """Request body for reporting an error."""

    turbo_error: bool = True
    repository_id: str = Field(..., description="Repository UUID")
    command: str = Field(..., description="Operation that failed")
    severity: str = Field(default="error", description="warning, error, or critical")
    error: ErrorDetail
    context: dict[str, Any] = Field(default_factory=dict)
    traceback: str | None = None
    timestamp: str | None = None


class ErrorReportResponse(BaseModel):
    """Response after error is reported."""

    success: bool
    issue_id: str
    issue_code: int
    message: str


# --- Auth ---


def _validate_api_key(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """Validate the API key from Authorization header.

    For now, we use a global API key stored in settings.
    Future: support per-repository API keys.

    Returns:
        The validated API key.

    Raises:
        HTTPException: If key is missing or invalid.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
        )

    # Extract Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Use 'Bearer <token>'",
        )

    token = parts[1]

    # Get global API key from settings
    setting = db.query(Setting).filter(Setting.key == "errors_api_key").first()

    if not setting or not setting.value:
        # If no key is configured, allow any non-empty token (for development)
        logger.warning("[Errors API] No errors_api_key configured, accepting any token")
        return token

    # Validate token
    if token != setting.value:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )

    return token


# --- Routes ---


@router.post(
    "/errors",
    response_model=ErrorReportResponse,
    status_code=201,
    summary="Report an error from an external application",
)
async def report_error(
    request: ErrorReportRequest,
    api_key: str = Depends(_validate_api_key),
    db: Session = Depends(get_db),
) -> ErrorReportResponse:
    """Receive error reports from TurboWrap clients and create issues.

    This endpoint is called by applications using the turbowrap-errors package
    to report runtime errors. Each error is stored as an issue in the database,
    linked to the specified repository.

    Authentication:
        - Bearer token in Authorization header
        - Token must match the `errors_api_key` setting

    Request Headers:
        - Authorization: Bearer <api_key>
        - X-TurboWrap-Repo-ID: <repository_id> (optional, can also be in body)
    """
    # Validate repository exists
    repo = db.query(Repository).filter(Repository.id == request.repository_id).first()
    if not repo:
        raise HTTPException(
            status_code=404,
            detail=f"Repository not found: {request.repository_id}",
        )

    # Get next issue code for this repo
    max_code = (
        db.query(Issue)
        .filter(Issue.repository_id == request.repository_id)
        .order_by(Issue.issue_code.desc())
        .first()
    )
    next_code = (max_code.issue_code + 1) if max_code else 1

    # Build issue title and description
    severity_emoji = {
        "warning": "⚠️",
        "error": "❌",
        "critical": "🚨",
    }.get(request.severity, "❌")

    title = f"{severity_emoji} {request.command}: {request.error.message[:80]}"
    if len(request.error.message) > 80:
        title += "..."

    # Build description
    description_parts = [
        "## Error Details\n",
        f"- **Command:** {request.command}",
        f"- **Severity:** {request.severity}",
        f"- **Error Type:** {request.error.type}",
    ]

    if request.error.code:
        description_parts.append(f"- **Error Code:** {request.error.code}")

    description_parts.append(f"\n### Message\n```\n{request.error.message}\n```")

    if request.context:
        description_parts.append(f"\n### Context\n```json\n{_format_json(request.context)}\n```")

    if request.traceback:
        description_parts.append(f"\n### Stack Trace\n```\n{request.traceback}\n```")

    if request.timestamp:
        description_parts.append(f"\n---\n*Reported at: {request.timestamp}*")

    description = "\n".join(description_parts)

    # Create issue
    issue = Issue(
        repository_id=request.repository_id,
        issue_code=next_code,
        type="runtime_error",
        category="error",
        severity=request.severity,
        title=title,
        description=description,
        file_path=request.context.get("path"),
        raw_data={
            "source": "turbowrap_errors",
            "command": request.command,
            "error": request.error.model_dump(),
            "context": request.context,
            "traceback": request.traceback,
            "reported_at": request.timestamp,
        },
        status="open",
    )

    db.add(issue)
    db.commit()
    db.refresh(issue)

    logger.info(f"[Errors API] Created issue #{next_code} for repo {repo.name}: {request.command}")

    return ErrorReportResponse(
        success=True,
        issue_id=issue.id,
        issue_code=next_code,
        message=f"Error reported as issue #{next_code}",
    )


def _format_json(obj: dict[str, Any]) -> str:
    """Format dict as pretty JSON string."""
    import json

    return json.dumps(obj, indent=2, default=str)
