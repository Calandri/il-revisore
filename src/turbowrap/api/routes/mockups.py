"""Mockup management API routes."""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...db.models import Mockup, MockupProject, MockupStatus, Repository
from ..deps import get_db
from ..schemas.mockups import (
    MockupContentResponse,
    MockupCreate,
    MockupFailRequest,
    MockupGenerateResponse,
    MockupInitRequest,
    MockupInitResponse,
    MockupListResponse,
    MockupModifyRequest,
    MockupProjectCreate,
    MockupProjectListResponse,
    MockupProjectResponse,
    MockupProjectUpdate,
    MockupResponse,
    MockupSaveRequest,
    MockupSaveResponse,
    MockupUpdate,
)
from ..services.mockup_service import get_mockup_service

router = APIRouter(prefix="/mockups", tags=["mockups"])
logger = logging.getLogger(__name__)


# =========================================================================
# MockupProject Endpoints
# =========================================================================


@router.get("/projects", response_model=MockupProjectListResponse)
async def list_projects(
    repository_id: str | None = None,
    db: Session = Depends(get_db),
) -> MockupProjectListResponse:
    """List all mockup projects, optionally filtered by repository."""
    query = db.query(MockupProject).filter(MockupProject.deleted_at.is_(None))

    if repository_id:
        query = query.filter(MockupProject.repository_id == repository_id)

    projects = query.order_by(MockupProject.created_at.desc()).all()

    # Get mockup counts for each project
    items = []
    for project in projects:
        mockup_count = (
            db.query(func.count(Mockup.id))
            .filter(
                Mockup.project_id == project.id,
                Mockup.deleted_at.is_(None),
            )
            .scalar()
        )

        items.append(
            MockupProjectResponse(
                id=project.id,
                repository_id=project.repository_id,
                name=project.name,
                description=project.description,
                design_system=project.design_system,
                color=project.color,
                icon=project.icon,
                mockup_count=mockup_count,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )

    return MockupProjectListResponse(
        items=items,
        total=len(items),
    )


@router.post("/projects", response_model=MockupProjectResponse, status_code=201)
async def create_project(
    request: MockupProjectCreate,
    db: Session = Depends(get_db),
) -> MockupProjectResponse:
    """Create a new mockup project."""
    # Verify repository exists
    repo = (
        db.query(Repository)
        .filter(
            Repository.id == request.repository_id,
            Repository.deleted_at.is_(None),
        )
        .first()
    )

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    project = MockupProject(
        repository_id=request.repository_id,
        name=request.name,
        description=request.description,
        design_system=request.design_system.value if request.design_system else "tailwind",
        color=request.color,
        icon=request.icon,
    )

    db.add(project)
    db.commit()
    db.refresh(project)

    logger.info(f"Created mockup project: {project.name} ({project.id})")

    return MockupProjectResponse(
        id=project.id,
        repository_id=project.repository_id,
        name=project.name,
        description=project.description,
        design_system=project.design_system,
        color=project.color,
        icon=project.icon,
        mockup_count=0,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("/projects/{project_id}", response_model=MockupProjectResponse)
async def get_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> MockupProjectResponse:
    """Get a mockup project by ID."""
    project = (
        db.query(MockupProject)
        .filter(
            MockupProject.id == project_id,
            MockupProject.deleted_at.is_(None),
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mockup_count = (
        db.query(func.count(Mockup.id))
        .filter(
            Mockup.project_id == project.id,
            Mockup.deleted_at.is_(None),
        )
        .scalar()
    )

    return MockupProjectResponse(
        id=project.id,
        repository_id=project.repository_id,
        name=project.name,
        description=project.description,
        design_system=project.design_system,
        color=project.color,
        icon=project.icon,
        mockup_count=mockup_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.put("/projects/{project_id}", response_model=MockupProjectResponse)
async def update_project(
    project_id: str,
    request: MockupProjectUpdate,
    db: Session = Depends(get_db),
) -> MockupProjectResponse:
    """Update a mockup project."""
    project = (
        db.query(MockupProject)
        .filter(
            MockupProject.id == project_id,
            MockupProject.deleted_at.is_(None),
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if request.name is not None:
        project.name = request.name
    if request.description is not None:
        project.description = request.description
    if request.design_system is not None:
        project.design_system = request.design_system.value
    if request.color is not None:
        project.color = request.color
    if request.icon is not None:
        project.icon = request.icon

    project.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(project)

    mockup_count = (
        db.query(func.count(Mockup.id))
        .filter(
            Mockup.project_id == project.id,
            Mockup.deleted_at.is_(None),
        )
        .scalar()
    )

    return MockupProjectResponse(
        id=project.id,
        repository_id=project.repository_id,
        name=project.name,
        description=project.description,
        design_system=project.design_system,
        color=project.color,
        icon=project.icon,
        mockup_count=mockup_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Soft delete a mockup project and all its mockups."""
    project = (
        db.query(MockupProject)
        .filter(
            MockupProject.id == project_id,
            MockupProject.deleted_at.is_(None),
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Soft delete all mockups in the project
    db.query(Mockup).filter(
        Mockup.project_id == project_id,
        Mockup.deleted_at.is_(None),
    ).update({"deleted_at": datetime.utcnow()})

    # Soft delete the project
    project.soft_delete()
    db.commit()

    logger.info(f"Deleted mockup project: {project.name} ({project.id})")


# =========================================================================
# Mockup Endpoints
# =========================================================================


@router.get("", response_model=MockupListResponse)
async def list_mockups(
    project_id: str | None = None,
    repository_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
) -> MockupListResponse:
    """List mockups with optional filters."""
    query = db.query(Mockup).filter(Mockup.deleted_at.is_(None))

    if project_id:
        query = query.filter(Mockup.project_id == project_id)

    if repository_id:
        # Filter by repository through project
        query = query.join(MockupProject).filter(MockupProject.repository_id == repository_id)

    total = query.count()
    offset = (page - 1) * page_size

    mockups = query.order_by(Mockup.created_at.desc()).offset(offset).limit(page_size).all()

    items = [MockupResponse.model_validate(m) for m in mockups]

    return MockupListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(items)) < total,
    )


@router.post("", response_model=MockupGenerateResponse, status_code=201)
async def create_mockup(
    request: MockupCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MockupGenerateResponse:
    """Create and generate a new mockup."""
    # Verify project exists
    project = (
        db.query(MockupProject)
        .filter(
            MockupProject.id == request.project_id,
            MockupProject.deleted_at.is_(None),
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create mockup record
    mockup = Mockup(
        project_id=request.project_id,
        name=request.name,
        description=request.description,
        component_type=request.component_type.value if request.component_type else None,
        llm_type=request.llm_type.value,
        prompt_used=request.prompt,
    )

    db.add(mockup)
    db.commit()
    db.refresh(mockup)

    # Generate mockup using service
    service = get_mockup_service(db)
    design_system = project.design_system or "tailwind"

    result = await service.generate_mockup(
        mockup=mockup,
        prompt=request.prompt,
        design_system=design_system,
    )

    if result.success:
        # Update mockup with generation results
        mockup.s3_html_url = result.s3_html_url
        mockup.s3_prompt_url = result.s3_prompt_url
        mockup.tokens_in = result.tokens_in
        mockup.tokens_out = result.tokens_out
        mockup.llm_model = result.llm_model
        mockup.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(mockup)

        logger.info(f"Generated mockup: {mockup.name} ({mockup.id})")

        return MockupGenerateResponse(
            success=True,
            mockup=MockupResponse.model_validate(mockup),
        )
    # Delete the failed mockup record
    mockup.soft_delete()
    db.commit()

    logger.warning(f"Failed to generate mockup: {result.error}")

    return MockupGenerateResponse(
        success=False,
        error=result.error,
    )


@router.get("/{mockup_id}", response_model=MockupResponse)
async def get_mockup(
    mockup_id: str,
    db: Session = Depends(get_db),
) -> MockupResponse:
    """Get a mockup by ID."""
    mockup = (
        db.query(Mockup)
        .filter(
            Mockup.id == mockup_id,
            Mockup.deleted_at.is_(None),
        )
        .first()
    )

    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    return MockupResponse.model_validate(mockup)


@router.get("/{mockup_id}/content", response_model=MockupContentResponse)
async def get_mockup_content(
    mockup_id: str,
    db: Session = Depends(get_db),
) -> MockupContentResponse:
    """Get the HTML/CSS/JS content of a mockup from S3."""
    mockup = (
        db.query(Mockup)
        .filter(
            Mockup.id == mockup_id,
            Mockup.deleted_at.is_(None),
        )
        .first()
    )

    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    service = get_mockup_service(db)

    # Fetch content from S3
    html = await service._fetch_from_s3(mockup.s3_html_url) if mockup.s3_html_url else None
    css = await service._fetch_from_s3(mockup.s3_css_url) if mockup.s3_css_url else None
    js = await service._fetch_from_s3(mockup.s3_js_url) if mockup.s3_js_url else None

    return MockupContentResponse(
        id=mockup.id,
        name=mockup.name,
        html=html,
        css=css,
        js=js,
        version=mockup.version,
    )


@router.post("/{mockup_id}/modify", response_model=MockupGenerateResponse)
async def modify_mockup(
    mockup_id: str,
    request: MockupModifyRequest,
    db: Session = Depends(get_db),
) -> MockupGenerateResponse:
    """Create a modified version of an existing mockup."""
    parent_mockup = (
        db.query(Mockup)
        .filter(
            Mockup.id == mockup_id,
            Mockup.deleted_at.is_(None),
        )
        .first()
    )

    if not parent_mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    # Create new version
    new_mockup = Mockup(
        project_id=parent_mockup.project_id,
        name=f"{parent_mockup.name} (v{parent_mockup.version + 1})",
        description=parent_mockup.description,
        component_type=parent_mockup.component_type,
        llm_type=parent_mockup.llm_type,
        prompt_used=request.modification_prompt,
        version=parent_mockup.version + 1,
        parent_mockup_id=parent_mockup.id,
    )

    db.add(new_mockup)
    db.commit()
    db.refresh(new_mockup)

    # Modify mockup using service
    service = get_mockup_service(db)

    result = await service.modify_mockup(
        mockup=new_mockup,
        modification_prompt=request.modification_prompt,
        element_selector=request.element_selector,
        current_html=None,  # Will be fetched from parent's S3 URL
    )

    # Fetch parent HTML for modification
    parent_html = (
        await service._fetch_from_s3(parent_mockup.s3_html_url)
        if parent_mockup.s3_html_url
        else None
    )

    if parent_html:
        result = await service.modify_mockup(
            mockup=new_mockup,
            modification_prompt=request.modification_prompt,
            element_selector=request.element_selector,
            current_html=parent_html,
        )

        if result.success:
            # Update mockup with generation results
            new_mockup.s3_html_url = result.s3_html_url
            new_mockup.s3_prompt_url = result.s3_prompt_url
            new_mockup.tokens_in = result.tokens_in
            new_mockup.tokens_out = result.tokens_out
            new_mockup.llm_model = result.llm_model
            new_mockup.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(new_mockup)

            logger.info(f"Modified mockup: {new_mockup.name} ({new_mockup.id})")

            return MockupGenerateResponse(
                success=True,
                mockup=MockupResponse.model_validate(new_mockup),
            )

    # Failed - delete the new mockup
    new_mockup.soft_delete()
    db.commit()

    return MockupGenerateResponse(
        success=False,
        error=result.error if result else "Could not fetch parent mockup content",
    )


@router.put("/{mockup_id}", response_model=MockupResponse)
async def update_mockup(
    mockup_id: str,
    request: MockupUpdate,
    db: Session = Depends(get_db),
) -> MockupResponse:
    """Update mockup metadata (not content)."""
    mockup = (
        db.query(Mockup)
        .filter(
            Mockup.id == mockup_id,
            Mockup.deleted_at.is_(None),
        )
        .first()
    )

    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    if request.name is not None:
        mockup.name = request.name
    if request.description is not None:
        mockup.description = request.description
    if request.component_type is not None:
        mockup.component_type = request.component_type.value

    mockup.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(mockup)

    return MockupResponse.model_validate(mockup)


@router.delete("/{mockup_id}", status_code=204)
async def delete_mockup(
    mockup_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Soft delete a mockup."""
    mockup = (
        db.query(Mockup)
        .filter(
            Mockup.id == mockup_id,
            Mockup.deleted_at.is_(None),
        )
        .first()
    )

    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    mockup.soft_delete()
    db.commit()

    logger.info(f"Deleted mockup: {mockup.name} ({mockup.id})")


# =========================================================================
# LLM Tool Endpoints (init_mockup / save_mockup)
# =========================================================================


@router.post("/init", response_model=MockupInitResponse, status_code=201)
async def init_mockup(
    request: MockupInitRequest,
    db: Session = Depends(get_db),
) -> MockupInitResponse:
    """Initialize a mockup placeholder with 'generating' status.

    Used by LLM tools to create a mockup record before generating content.
    The UI shows this as a loading/in-progress state.

    Returns the mockup_id to use with save_mockup when generation is complete.
    """
    # Verify project exists
    project = (
        db.query(MockupProject)
        .filter(
            MockupProject.id == request.project_id,
            MockupProject.deleted_at.is_(None),
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create mockup with 'generating' status
    mockup = Mockup(
        project_id=request.project_id,
        name=request.name,
        description=request.description,
        component_type=request.component_type.value if request.component_type else None,
        llm_type=request.llm_type.value,
        status=MockupStatus.GENERATING.value,
        chat_session_id=request.chat_session_id,
    )

    db.add(mockup)
    db.commit()
    db.refresh(mockup)

    logger.info(f"Initialized mockup: {mockup.name} ({mockup.id}) - generating")

    return MockupInitResponse(
        mockup_id=mockup.id,
        status=MockupStatus.GENERATING.value,
        message=f"Mockup '{mockup.name}' initialized. Generate the HTML and call save_mockup with mockup_id='{mockup.id}' when done.",
    )


@router.put("/{mockup_id}/save", response_model=MockupSaveResponse)
async def save_mockup(
    mockup_id: str,
    request: MockupSaveRequest,
    db: Session = Depends(get_db),
) -> MockupSaveResponse:
    """Save HTML content to a mockup and mark as completed.

    Used by LLM tools to save the generated content.
    The HTML is uploaded to S3 and the mockup status changes to 'completed'.
    """
    mockup = (
        db.query(Mockup)
        .filter(
            Mockup.id == mockup_id,
            Mockup.deleted_at.is_(None),
        )
        .first()
    )

    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    # Get mockup service for S3 upload
    service = get_mockup_service(db)

    try:
        # Upload HTML to S3
        s3_result = await service._save_to_s3(mockup.id, request.html_content)

        # Update mockup record
        mockup.s3_html_url = s3_result.get("html")
        mockup.status = MockupStatus.COMPLETED.value
        mockup.tokens_in = request.tokens_in or 0
        mockup.tokens_out = request.tokens_out or 0
        mockup.llm_model = request.llm_model
        mockup.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(mockup)

        logger.info(f"Saved mockup: {mockup.name} ({mockup.id}) - completed")

        return MockupSaveResponse(
            success=True,
            mockup_id=mockup.id,
            status=MockupStatus.COMPLETED.value,
            s3_html_url=mockup.s3_html_url,
            preview_url=f"/mockups/{mockup.id}/preview",
            message=f"Mockup '{mockup.name}' saved successfully! View it at /mockups",
        )

    except Exception as e:
        logger.error(f"Failed to save mockup {mockup_id}: {e}")

        # Mark as failed
        mockup.status = MockupStatus.FAILED.value
        mockup.error_message = str(e)
        mockup.updated_at = datetime.utcnow()
        db.commit()

        return MockupSaveResponse(
            success=False,
            mockup_id=mockup.id,
            status=MockupStatus.FAILED.value,
            s3_html_url=None,
            preview_url=f"/mockups/{mockup.id}/preview",
            message=f"Failed to save mockup: {e}",
        )


@router.put("/{mockup_id}/fail", response_model=MockupSaveResponse)
async def fail_mockup(
    mockup_id: str,
    request: MockupFailRequest,
    db: Session = Depends(get_db),
) -> MockupSaveResponse:
    """Mark a mockup as failed.

    Used by LLM tools when generation fails for any reason.
    """
    mockup = (
        db.query(Mockup)
        .filter(
            Mockup.id == mockup_id,
            Mockup.deleted_at.is_(None),
        )
        .first()
    )

    if not mockup:
        raise HTTPException(status_code=404, detail="Mockup not found")

    mockup.status = MockupStatus.FAILED.value
    mockup.error_message = request.error_message
    mockup.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(mockup)

    logger.warning(f"Mockup failed: {mockup.name} ({mockup.id}) - {request.error_message}")

    return MockupSaveResponse(
        success=False,
        mockup_id=mockup.id,
        status=MockupStatus.FAILED.value,
        s3_html_url=None,
        preview_url=f"/mockups/{mockup.id}/preview",
        message=f"Mockup marked as failed: {request.error_message}",
    )
