"""Mockup schemas for API requests and responses."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DesignSystemEnum(str, Enum):
    """Design system options for mockups."""

    TAILWIND = "tailwind"
    BOOTSTRAP = "bootstrap"
    MATERIAL = "material"
    CUSTOM = "custom"


class ComponentTypeEnum(str, Enum):
    """Component type options for mockups."""

    PAGE = "page"
    COMPONENT = "component"
    MODAL = "modal"
    FORM = "form"
    TABLE = "table"
    CARD = "card"
    NAVBAR = "navbar"
    SIDEBAR = "sidebar"
    DASHBOARD = "dashboard"


class LLMTypeEnum(str, Enum):
    """LLM provider options."""

    CLAUDE = "claude"
    GEMINI = "gemini"
    GROK = "grok"


# =========================================================================
# MockupProject Schemas
# =========================================================================


class MockupProjectCreate(BaseModel):
    """Request to create a mockup project."""

    repository_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="Repository UUID to associate the project with",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Project name",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Project description",
    )
    design_system: DesignSystemEnum = Field(
        default=DesignSystemEnum.TAILWIND,
        description="Default design system for mockups in this project",
    )
    color: str = Field(
        default="#6366f1",
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Project color (hex)",
    )
    icon: str = Field(
        default="layout",
        max_length=50,
        description="Project icon name",
    )


class MockupProjectUpdate(BaseModel):
    """Request to update a mockup project."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Project name",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Project description",
    )
    design_system: DesignSystemEnum | None = Field(
        default=None,
        description="Default design system",
    )
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Project color (hex)",
    )
    icon: str | None = Field(
        default=None,
        max_length=50,
        description="Project icon name",
    )


class MockupProjectResponse(BaseModel):
    """Mockup project response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Project UUID")
    repository_id: str = Field(..., description="Associated repository UUID")
    name: str = Field(..., description="Project name")
    description: str | None = Field(default=None, description="Project description")
    design_system: str | None = Field(default=None, description="Default design system")
    color: str = Field(..., description="Project color")
    icon: str = Field(..., description="Project icon")
    mockup_count: int | None = Field(default=None, description="Number of mockups in project")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


# =========================================================================
# Mockup Schemas
# =========================================================================


class MockupCreate(BaseModel):
    """Request to create a mockup."""

    project_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="Project UUID to associate the mockup with",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Mockup name",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Mockup description",
    )
    component_type: ComponentTypeEnum | None = Field(
        default=None,
        description="Type of UI component",
    )
    llm_type: LLMTypeEnum = Field(
        default=LLMTypeEnum.CLAUDE,
        description="LLM to use for generation",
    )
    prompt: str = Field(
        ...,
        min_length=10,
        max_length=10000,
        description="Prompt describing what to create",
    )


class MockupUpdate(BaseModel):
    """Request to update a mockup."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Mockup name",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Mockup description",
    )
    component_type: ComponentTypeEnum | None = Field(
        default=None,
        description="Type of UI component",
    )


class MockupModifyRequest(BaseModel):
    """Request to modify an existing mockup."""

    modification_prompt: str = Field(
        ...,
        min_length=5,
        max_length=5000,
        description="Description of what to modify",
    )
    element_selector: str | None = Field(
        default=None,
        max_length=500,
        description="CSS selector of element to modify (from click-to-select)",
    )


class MockupResponse(BaseModel):
    """Mockup response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Mockup UUID")
    project_id: str = Field(..., description="Associated project UUID")
    name: str = Field(..., description="Mockup name")
    description: str | None = Field(default=None, description="Mockup description")
    component_type: str | None = Field(default=None, description="Component type")

    # LLM metadata
    llm_type: str = Field(..., description="LLM used for generation")
    llm_model: str | None = Field(default=None, description="Specific model used")
    tokens_in: int = Field(default=0, description="Input tokens used")
    tokens_out: int = Field(default=0, description="Output tokens used")

    # S3 URLs
    s3_html_url: str | None = Field(default=None, description="S3 URL for HTML")
    s3_css_url: str | None = Field(default=None, description="S3 URL for CSS")
    s3_js_url: str | None = Field(default=None, description="S3 URL for JS")
    s3_prompt_url: str | None = Field(default=None, description="S3 URL for prompt")

    # Versioning
    version: int = Field(default=1, description="Version number")
    parent_mockup_id: str | None = Field(default=None, description="Parent mockup UUID")

    # Timestamps
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class MockupContentResponse(BaseModel):
    """Response containing mockup HTML/CSS/JS content."""

    id: str = Field(..., description="Mockup UUID")
    name: str = Field(..., description="Mockup name")
    html: str | None = Field(default=None, description="HTML content")
    css: str | None = Field(default=None, description="CSS content (if separate)")
    js: str | None = Field(default=None, description="JavaScript content (if separate)")
    version: int = Field(default=1, description="Version number")


class MockupListResponse(BaseModel):
    """Paginated list of mockups."""

    items: list[MockupResponse] = Field(..., description="List of mockups")
    total: int = Field(..., description="Total number of mockups")
    page: int = Field(default=1, description="Current page")
    page_size: int = Field(default=20, description="Items per page")
    has_more: bool = Field(default=False, description="Whether there are more pages")


class MockupProjectListResponse(BaseModel):
    """Paginated list of mockup projects."""

    items: list[MockupProjectResponse] = Field(..., description="List of projects")
    total: int = Field(..., description="Total number of projects")


class MockupGenerateResponse(BaseModel):
    """Response from mockup generation."""

    success: bool = Field(..., description="Whether generation succeeded")
    mockup: MockupResponse | None = Field(default=None, description="Generated mockup")
    error: str | None = Field(default=None, description="Error message if failed")
