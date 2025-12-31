"""Live View API routes.

Provides endpoints for:
- Listing frontend repositories with production links
- Checking iframe compatibility (X-Frame-Options)
- Managing screenshots for sites that block iframe embedding
- Creating issues/features from live view interactions
"""

import json
import logging
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import (
    Feature,
    FeatureRepository,
    FeatureRepositoryRole,
    FeatureStatus,
    Issue,
    IssueStatus,
    LiveViewScreenshot,
    Repository,
    RepositoryExternalLink,
    generate_uuid,
)
from ..deps import get_db, get_or_404

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/live-view", tags=["live-view"])


# =============================================================================
# Pydantic Schemas
# =============================================================================


class ProductionLinkInfo(BaseModel):
    """Production link information."""

    id: str
    url: str
    label: str | None


class LiveViewRepoResponse(BaseModel):
    """Repository with production link for live view."""

    id: str
    name: str
    slug: str
    repo_type: str
    production_link: ProductionLinkInfo


class IframeCheckRequest(BaseModel):
    """Request to check iframe compatibility."""

    url: str


class IframeCheckResponse(BaseModel):
    """Response from iframe compatibility check."""

    url: str
    can_embed: bool
    blocked_reason: str | None = None
    headers: dict[str, str] | None = None


class ScreenshotResponse(BaseModel):
    """Screenshot information."""

    id: str
    s3_url: str
    captured_at: str
    viewport_width: int
    viewport_height: int


class CaptureScreenshotRequest(BaseModel):
    """Request to capture a new screenshot."""

    external_link_id: str
    viewport_width: int = 1920
    viewport_height: int = 1080


class LiveViewActionRequest(BaseModel):
    """Request to create an issue/feature from live view."""

    repository_id: str
    action: str  # "create_issue", "create_feature", "send_to_chat"
    selector: str
    element_info: dict[str, str] | None = None
    title: str | None = None
    description: str | None = None


class LiveViewActionResponse(BaseModel):
    """Response from live view action."""

    action: str
    success: bool
    redirect: str | None = None
    command: str | None = None
    entity_id: str | None = None
    message: str | None = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/repos", response_model=list[LiveViewRepoResponse])
def list_live_view_repos(
    db: Session = Depends(get_db),
) -> list[LiveViewRepoResponse]:
    """List repositories with production links for live view.

    Only returns frontend and fullstack repositories that have
    a production external link configured.
    """
    # Query repos with production links
    repos_with_links = (
        db.query(Repository, RepositoryExternalLink)
        .join(
            RepositoryExternalLink,
            Repository.id == RepositoryExternalLink.repository_id,
        )
        .filter(
            Repository.repo_type.in_(["frontend", "fullstack"]),
            RepositoryExternalLink.link_type == "production",
        )
        .all()
    )

    return [
        LiveViewRepoResponse(
            id=repo.id,
            name=repo.name,
            slug=repo.slug,
            repo_type=repo.repo_type or "unknown",
            production_link=ProductionLinkInfo(
                id=link.id,
                url=link.url,
                label=link.label,
            ),
        )
        for repo, link in repos_with_links
    ]


@router.post("/{repo_id}/check-iframe", response_model=IframeCheckResponse)
async def check_iframe_compatibility(
    repo_id: str,
    request: IframeCheckRequest,
    db: Session = Depends(get_db),
) -> IframeCheckResponse:
    """Check if a URL can be embedded in an iframe.

    Checks X-Frame-Options and Content-Security-Policy headers
    to determine if the site blocks iframe embedding.
    """
    get_or_404(db, Repository, repo_id)  # Validate repo exists

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.head(request.url)

        headers = dict(response.headers)

        # Check X-Frame-Options
        x_frame = headers.get("x-frame-options", "").upper()
        if x_frame in ("DENY", "SAMEORIGIN"):
            return IframeCheckResponse(
                url=request.url,
                can_embed=False,
                blocked_reason=f"X-Frame-Options: {x_frame}",
                headers={"x-frame-options": x_frame},
            )

        # Check Content-Security-Policy frame-ancestors
        csp = headers.get("content-security-policy", "")
        if "frame-ancestors" in csp.lower():
            # Parse frame-ancestors directive
            if "'none'" in csp or "frame-ancestors 'self'" in csp.lower():
                return IframeCheckResponse(
                    url=request.url,
                    can_embed=False,
                    blocked_reason="CSP frame-ancestors blocks embedding",
                    headers={"content-security-policy": csp[:200]},
                )

        return IframeCheckResponse(
            url=request.url,
            can_embed=True,
            headers={
                "x-frame-options": x_frame or "(not set)",
            },
        )

    except httpx.TimeoutException:
        return IframeCheckResponse(
            url=request.url,
            can_embed=False,
            blocked_reason="Request timeout",
        )
    except httpx.RequestError as e:
        return IframeCheckResponse(
            url=request.url,
            can_embed=False,
            blocked_reason=f"Request failed: {e!s}",
        )


@router.get("/{repo_id}/screenshot", response_model=ScreenshotResponse | None)
def get_latest_screenshot(
    repo_id: str,
    external_link_id: str = Query(..., description="External link ID"),
    db: Session = Depends(get_db),
) -> ScreenshotResponse | None:
    """Get the latest screenshot for a repository's production link."""
    get_or_404(db, Repository, repo_id)  # Validate repo exists

    screenshot = (
        db.query(LiveViewScreenshot)
        .filter(
            LiveViewScreenshot.repository_id == repo_id,
            LiveViewScreenshot.external_link_id == external_link_id,
        )
        .order_by(LiveViewScreenshot.captured_at.desc())
        .first()
    )

    if not screenshot:
        return None

    return ScreenshotResponse(
        id=screenshot.id,
        s3_url=screenshot.s3_url,
        captured_at=screenshot.captured_at.isoformat(),
        viewport_width=screenshot.viewport_width,
        viewport_height=screenshot.viewport_height,
    )


@router.post("/{repo_id}/screenshot", response_model=ScreenshotResponse)
async def capture_screenshot(
    repo_id: str,
    request: CaptureScreenshotRequest,
    db: Session = Depends(get_db),
) -> ScreenshotResponse:
    """Capture a new screenshot for a repository's production link.

    Uses Playwright to capture a full-page screenshot and uploads to S3.
    """
    from ..services.screenshot_service import ScreenshotService

    repo = get_or_404(db, Repository, repo_id)
    link = get_or_404(db, RepositoryExternalLink, request.external_link_id)

    if link.repository_id != repo_id:
        raise HTTPException(
            status_code=400,
            detail="External link does not belong to this repository",
        )

    # Capture screenshot
    service = ScreenshotService()
    try:
        s3_url = await service.capture_and_upload(
            url=link.url,
            repo_slug=repo.slug,
            viewport_width=request.viewport_width,
            viewport_height=request.viewport_height,
        )
    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Screenshot capture failed: {e!s}",
        )

    # Delete old screenshot for this link (keep only latest)
    db.query(LiveViewScreenshot).filter(
        LiveViewScreenshot.external_link_id == request.external_link_id,
    ).delete()

    # Save new screenshot
    screenshot = LiveViewScreenshot(
        id=generate_uuid(),
        repository_id=repo_id,
        external_link_id=request.external_link_id,
        s3_url=s3_url,
        captured_at=datetime.utcnow(),
        viewport_width=request.viewport_width,
        viewport_height=request.viewport_height,
    )
    db.add(screenshot)
    db.commit()
    db.refresh(screenshot)

    return ScreenshotResponse(
        id=screenshot.id,
        s3_url=screenshot.s3_url,
        captured_at=screenshot.captured_at.isoformat(),
        viewport_width=screenshot.viewport_width,
        viewport_height=screenshot.viewport_height,
    )


@router.post("/action", response_model=LiveViewActionResponse)
def handle_live_view_action(
    request: LiveViewActionRequest,
    db: Session = Depends(get_db),
) -> LiveViewActionResponse:
    """Handle an action from the live view (create issue, feature, or chat command).

    Actions:
    - create_issue: Creates a new bug issue from the selected element
    - create_feature: Creates a new feature request from the selected element
    - send_to_chat: Returns a chat command with context for the AI assistant
    """
    repo = get_or_404(db, Repository, request.repository_id)

    if request.action == "create_issue":
        # Generate issue code
        issue_code = f"LV-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Build description
        description = "## Element Details\n\n"
        description += f"**Selector:** `{request.selector}`\n\n"

        if request.element_info:
            description += "**Element Info:**\n```json\n"
            description += json.dumps(request.element_info, indent=2)
            description += "\n```\n\n"

        if request.description:
            description += f"## Description\n\n{request.description}\n\n"

        description += "\n---\n*Created from Live View*"

        issue = Issue(
            id=str(uuid.uuid4()),
            issue_code=issue_code,
            repository_id=request.repository_id,
            severity="MEDIUM",
            category="ui",
            rule="live_view",
            file=request.selector,
            title=request.title or f"UI Issue: {request.selector[:50]}",
            description=description,
            status=IssueStatus.OPEN.value,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        db.add(issue)
        db.commit()
        db.refresh(issue)

        logger.info(f"Created issue {issue_code} from Live View")

        return LiveViewActionResponse(
            action="create_issue",
            success=True,
            redirect=f"/issues/{issue.id}",
            entity_id=issue.id,
            message=f"Issue {issue_code} created",
        )

    if request.action == "create_feature":
        # Create feature
        feature = Feature(
            title=request.title or f"Feature: {request.selector[:50]}",
            description=request.description
            or f"Feature request from Live View.\n\nElement: `{request.selector}`",
            priority=3,
            status=FeatureStatus.ANALYSIS.value,
            phase_started_at=datetime.utcnow(),
        )

        db.add(feature)
        db.flush()

        # Link to repository
        feature_repo = FeatureRepository(
            feature_id=feature.id,
            repository_id=request.repository_id,
            role=FeatureRepositoryRole.PRIMARY.value,
        )
        db.add(feature_repo)
        db.commit()
        db.refresh(feature)

        logger.info(f"Created feature {feature.id} from Live View")

        return LiveViewActionResponse(
            action="create_feature",
            success=True,
            redirect=f"/features/{feature.id}",
            entity_id=feature.id,
            message="Feature created",
        )

    if request.action == "send_to_chat":
        # Build chat command with context
        element_desc = (
            request.element_info.get("text", request.selector)
            if request.element_info
            else request.selector
        )
        command = f'/live-context --repo "{repo.slug}" --selector "{request.selector}"'

        if request.description:
            command += f' --description "{request.description}"'

        return LiveViewActionResponse(
            action="send_to_chat",
            success=True,
            command=command,
            message=f"Ready to discuss: {element_desc[:50]}",
        )

    raise HTTPException(
        status_code=400,
        detail=f"Unknown action: {request.action}",
    )
