"""Feature tracking routes."""

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.models import (
    Feature,
    FeatureRepository,
    FeatureRepositoryRole,
    FeatureStatus,
    Repository,
    is_valid_feature_transition,
)
from ..deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/features", tags=["features"])


# =============================================================================
# Request/Response Schemas
# =============================================================================


class FeatureRepositoryResponse(BaseModel):
    """Feature-Repository link response."""

    id: str
    repository_id: str
    repository_name: str | None = None
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class FeatureResponse(BaseModel):
    """Feature response schema."""

    id: str
    linear_id: str | None = None
    linear_identifier: str | None = None
    linear_url: str | None = None
    status: str
    phase_started_at: datetime | None = None
    title: str
    description: str | None = None
    improved_description: str | None = None
    implementation_plan: list[dict[str, Any]] | None = None
    user_qa: list[dict[str, Any]] | None = None
    mockup_id: str | None = None
    figma_link: str | None = None
    attachments: list[dict[str, Any]] | None = None
    comments: list[dict[str, Any]] | None = None
    estimated_effort: int | None = None
    estimated_days: int | None = None
    fix_commit_sha: str | None = None
    fix_branch: str | None = None
    fix_explanation: str | None = None
    priority: int | None = None
    assignee_name: str | None = None
    created_at: datetime
    updated_at: datetime
    repositories: list[FeatureRepositoryResponse] = []

    class Config:
        from_attributes = True


class FeatureCreateRequest(BaseModel):
    """Request to create a feature."""

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    linear_id: str | None = Field(None, max_length=100)
    linear_identifier: str | None = Field(None, max_length=50)
    linear_url: str | None = Field(None, max_length=512)
    priority: int | None = Field(None, ge=1, le=4)
    repository_id: str | None = Field(None, description="Primary repository ID")


class FeatureUpdateRequest(BaseModel):
    """Request to update a feature."""

    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    improved_description: str | None = Field(None, max_length=10000)
    status: str | None = None
    implementation_plan: list[dict[str, Any]] | None = None
    figma_link: str | None = Field(None, max_length=512)
    priority: int | None = Field(None, ge=1, le=4)
    assignee_name: str | None = Field(None, max_length=255)
    estimated_effort: int | None = Field(None, ge=1, le=5)
    estimated_days: int | None = Field(None, ge=1)


class QAItemRequest(BaseModel):
    """Request to add a Q&A item."""

    question: str = Field(..., min_length=1, max_length=1000)
    why: str | None = Field(None, max_length=500)
    answer: str | None = Field(None, max_length=5000)


class CommentRequest(BaseModel):
    """Request to add a comment."""

    content: str = Field(..., min_length=1, max_length=5000)
    author: str = Field(default="system", max_length=100)
    comment_type: str = Field(default="comment", max_length=50)


class LinkRepositoryRequest(BaseModel):
    """Request to link a repository to a feature."""

    repository_id: str
    role: str = Field(default="secondary", description="primary, secondary, or shared")


class FeatureSummary(BaseModel):
    """Summary statistics for features."""

    total: int
    by_status: dict[str, int]
    by_priority: dict[int, int]


# =============================================================================
# Helper Functions
# =============================================================================


def _feature_to_response(feature: Feature) -> FeatureResponse:
    """Convert Feature model to response with repository info."""
    repo_links = []
    for link in feature.repository_links:
        repo_links.append(
            FeatureRepositoryResponse(
                id=link.id,
                repository_id=link.repository_id,
                repository_name=link.repository.name if link.repository else None,
                role=link.role,
                created_at=link.created_at,
            )
        )

    return FeatureResponse(
        id=feature.id,
        linear_id=feature.linear_id,
        linear_identifier=feature.linear_identifier,
        linear_url=feature.linear_url,
        status=feature.status,
        phase_started_at=feature.phase_started_at,
        title=feature.title,
        description=feature.description,
        improved_description=feature.improved_description,
        implementation_plan=feature.implementation_plan,
        user_qa=feature.user_qa,
        mockup_id=feature.mockup_id,
        figma_link=feature.figma_link,
        attachments=feature.attachments,
        comments=feature.comments,
        estimated_effort=feature.estimated_effort,
        estimated_days=feature.estimated_days,
        fix_commit_sha=feature.fix_commit_sha,
        fix_branch=feature.fix_branch,
        fix_explanation=feature.fix_explanation,
        priority=feature.priority,
        assignee_name=feature.assignee_name,
        created_at=feature.created_at,
        updated_at=feature.updated_at,
        repositories=repo_links,
    )


# =============================================================================
# Routes
# =============================================================================


@router.get("", response_model=list[FeatureResponse])
def list_features(
    repository_id: str | None = None,
    status: str | None = Query(default=None, description="Filter by status"),
    priority: int | None = Query(default=None, ge=1, le=4),
    linear_identifier: str | None = None,
    search: str | None = Query(default=None, description="Search in title, description"),
    order_by: str | None = Query(
        default="priority", description="Order by: priority, updated_at, created_at, status"
    ),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[FeatureResponse]:
    """
    List features with optional filters.

    Filters:
    - repository_id: Filter by linked repository
    - status: analysis, design, development, review, merged, on_hold, cancelled
    - priority: 1 (Urgent), 2 (High), 3 (Normal), 4 (Low)
    - linear_identifier: Filter by Linear issue ID (e.g., "TEAM-123")
    - search: Search in title and description
    """
    query = db.query(Feature).filter(Feature.deleted_at.is_(None))

    if repository_id:
        query = query.join(FeatureRepository).filter(
            FeatureRepository.repository_id == repository_id
        )
    if status:
        query = query.filter(Feature.status == status)
    if priority:
        query = query.filter(Feature.priority == priority)
    if linear_identifier:
        query = query.filter(Feature.linear_identifier == linear_identifier)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Feature.title.ilike(search_term)) | (Feature.description.ilike(search_term))
        )

    # Ordering
    if order_by == "updated_at":
        query = query.order_by(Feature.updated_at.desc())
    elif order_by == "created_at":
        query = query.order_by(Feature.created_at.desc())
    elif order_by == "status":
        query = query.order_by(Feature.status, Feature.priority, Feature.created_at.desc())
    else:
        # Default: priority first, then creation date
        query = query.order_by(Feature.priority, Feature.created_at.desc())

    features = query.offset(offset).limit(limit).all()
    return [_feature_to_response(f) for f in features]


@router.get("/summary", response_model=FeatureSummary)
def get_features_summary(
    repository_id: str | None = None,
    db: Session = Depends(get_db),
) -> FeatureSummary:
    """Get summary statistics for features."""
    query = db.query(Feature).filter(Feature.deleted_at.is_(None))

    if repository_id:
        query = query.join(FeatureRepository).filter(
            FeatureRepository.repository_id == repository_id
        )

    features = query.all()

    by_status: dict[str, int] = {s.value: 0 for s in FeatureStatus}
    by_priority: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

    for feature in features:
        status_val = str(feature.status)
        if status_val in by_status:
            by_status[status_val] += 1

        priority_val = feature.priority or 3
        if priority_val in by_priority:
            by_priority[priority_val] += 1

    return FeatureSummary(
        total=len(features),
        by_status=by_status,
        by_priority=by_priority,
    )


@router.post("", response_model=FeatureResponse, status_code=201)
def create_feature(
    data: FeatureCreateRequest,
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """Create a new feature."""
    # Check for duplicate linear_id
    if data.linear_id:
        existing = (
            db.query(Feature)
            .filter(Feature.linear_id == data.linear_id, Feature.deleted_at.is_(None))
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409, detail=f"Feature with linear_id {data.linear_id} already exists"
            )

    feature = Feature(
        title=data.title,
        description=data.description,
        linear_id=data.linear_id,
        linear_identifier=data.linear_identifier,
        linear_url=data.linear_url,
        priority=data.priority or 3,
        status=FeatureStatus.ANALYSIS.value,
        phase_started_at=datetime.utcnow(),
    )

    db.add(feature)
    db.flush()  # Get the ID

    # Link primary repository if provided
    if data.repository_id:
        repo = db.query(Repository).filter(Repository.id == data.repository_id).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")

        link = FeatureRepository(
            feature_id=feature.id,
            repository_id=data.repository_id,
            role=FeatureRepositoryRole.PRIMARY.value,
        )
        db.add(link)

    db.commit()
    db.refresh(feature)

    return _feature_to_response(feature)


@router.get("/{feature_id}", response_model=FeatureResponse)
def get_feature(
    feature_id: str,
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """Get feature details."""
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    return _feature_to_response(feature)


@router.patch("/{feature_id}", response_model=FeatureResponse)
def update_feature(
    feature_id: str,
    data: FeatureUpdateRequest,
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """
    Update feature details.

    Valid status transitions:
    - analysis -> design, development, on_hold, cancelled
    - design -> development, analysis, on_hold, cancelled
    - development -> review, design, on_hold, cancelled
    - review -> merged, development, cancelled
    - on_hold -> analysis, design, development, cancelled
    """
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    # Validate status transition
    if data.status:
        valid_statuses = [s.value for s in FeatureStatus]
        if data.status not in valid_statuses:
            raise HTTPException(
                status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}"
            )

        current_status = FeatureStatus(str(feature.status))
        new_status = FeatureStatus(data.status)
        if not is_valid_feature_transition(current_status, new_status):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition: {current_status.value} -> {new_status.value}",
            )

        feature.status = data.status
        feature.phase_started_at = datetime.utcnow()

    # Update other fields
    if data.title is not None:
        feature.title = data.title
    if data.description is not None:
        feature.description = data.description
    if data.improved_description is not None:
        feature.improved_description = data.improved_description
    if data.implementation_plan is not None:
        feature.implementation_plan = data.implementation_plan
    if data.figma_link is not None:
        feature.figma_link = data.figma_link
    if data.priority is not None:
        feature.priority = data.priority
    if data.assignee_name is not None:
        feature.assignee_name = data.assignee_name
    if data.estimated_effort is not None:
        feature.estimated_effort = data.estimated_effort
    if data.estimated_days is not None:
        feature.estimated_days = data.estimated_days

    db.commit()
    db.refresh(feature)

    return _feature_to_response(feature)


@router.delete("/{feature_id}", status_code=204)
def delete_feature(
    feature_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Soft delete a feature."""
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    feature.soft_delete()
    db.commit()


# =============================================================================
# Q&A Routes
# =============================================================================


@router.post("/{feature_id}/qa", response_model=FeatureResponse)
def add_qa_item(
    feature_id: str,
    data: QAItemRequest,
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """Add a Q&A item to a feature."""
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    qa_list = feature.user_qa or []
    qa_item = {
        "id": str(uuid4()),
        "question": data.question,
        "why": data.why,
        "answer": data.answer,
        "asked_at": datetime.utcnow().isoformat(),
    }
    qa_list.append(qa_item)
    feature.user_qa = qa_list

    db.commit()
    db.refresh(feature)

    return _feature_to_response(feature)


@router.patch("/{feature_id}/qa/{qa_id}", response_model=FeatureResponse)
def update_qa_answer(
    feature_id: str,
    qa_id: str,
    answer: str = Query(..., description="Answer to the question"),
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """Update the answer for a Q&A item."""
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    qa_list = feature.user_qa or []
    found = False
    for qa in qa_list:
        if qa.get("id") == qa_id:
            qa["answer"] = answer
            qa["answered_at"] = datetime.utcnow().isoformat()
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Q&A item not found")

    feature.user_qa = qa_list
    db.commit()
    db.refresh(feature)

    return _feature_to_response(feature)


# =============================================================================
# Comments Routes
# =============================================================================


@router.post("/{feature_id}/comments", response_model=FeatureResponse)
def add_comment(
    feature_id: str,
    data: CommentRequest,
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """Add a comment to a feature."""
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    comments_list = feature.comments or []
    comment = {
        "id": str(uuid4()),
        "author": data.author,
        "content": data.content,
        "type": data.comment_type,
        "created_at": datetime.utcnow().isoformat(),
    }
    comments_list.append(comment)
    feature.comments = comments_list

    db.commit()
    db.refresh(feature)

    return _feature_to_response(feature)


# =============================================================================
# Repository Link Routes
# =============================================================================


@router.post("/{feature_id}/repos", response_model=FeatureResponse)
def link_repository(
    feature_id: str,
    data: LinkRepositoryRequest,
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """Link a repository to a feature."""
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    # Check repository exists
    repo = db.query(Repository).filter(Repository.id == data.repository_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Check for duplicate link
    existing = (
        db.query(FeatureRepository)
        .filter(
            FeatureRepository.feature_id == feature_id,
            FeatureRepository.repository_id == data.repository_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="Repository is already linked to this feature"
        )

    # Validate role
    valid_roles = [r.value for r in FeatureRepositoryRole]
    if data.role not in valid_roles:
        raise HTTPException(
            status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}"
        )

    # If setting as primary, demote existing primary to secondary
    if data.role == FeatureRepositoryRole.PRIMARY.value:
        existing_primary = (
            db.query(FeatureRepository)
            .filter(
                FeatureRepository.feature_id == feature_id,
                FeatureRepository.role == FeatureRepositoryRole.PRIMARY.value,
            )
            .first()
        )
        if existing_primary:
            existing_primary.role = FeatureRepositoryRole.SECONDARY.value

    link = FeatureRepository(
        feature_id=feature_id,
        repository_id=data.repository_id,
        role=data.role,
    )
    db.add(link)
    db.commit()
    db.refresh(feature)

    return _feature_to_response(feature)


@router.delete("/{feature_id}/repos/{repository_id}", status_code=204)
def unlink_repository(
    feature_id: str,
    repository_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Unlink a repository from a feature."""
    link = (
        db.query(FeatureRepository)
        .filter(
            FeatureRepository.feature_id == feature_id,
            FeatureRepository.repository_id == repository_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Repository link not found")

    db.delete(link)
    db.commit()


@router.patch("/{feature_id}/repos/{repository_id}", response_model=FeatureResponse)
def update_repository_role(
    feature_id: str,
    repository_id: str,
    role: str = Query(..., description="New role: primary, secondary, shared"),
    db: Session = Depends(get_db),
) -> FeatureResponse:
    """Update the role of a linked repository."""
    feature = (
        db.query(Feature)
        .filter(Feature.id == feature_id, Feature.deleted_at.is_(None))
        .first()
    )
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    link = (
        db.query(FeatureRepository)
        .filter(
            FeatureRepository.feature_id == feature_id,
            FeatureRepository.repository_id == repository_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Repository link not found")

    valid_roles = [r.value for r in FeatureRepositoryRole]
    if role not in valid_roles:
        raise HTTPException(
            status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}"
        )

    # If setting as primary, demote existing primary
    if role == FeatureRepositoryRole.PRIMARY.value:
        existing_primary = (
            db.query(FeatureRepository)
            .filter(
                FeatureRepository.feature_id == feature_id,
                FeatureRepository.role == FeatureRepositoryRole.PRIMARY.value,
                FeatureRepository.id != link.id,
            )
            .first()
        )
        if existing_primary:
            existing_primary.role = FeatureRepositoryRole.SECONDARY.value

    link.role = role
    db.commit()
    db.refresh(feature)

    return _feature_to_response(feature)
