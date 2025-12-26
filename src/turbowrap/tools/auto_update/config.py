"""Configuration for the auto-update module."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AutoUpdateSettings(BaseSettings):
    """Configuration for the auto-update workflow."""

    model_config = SettingsConfigDict(
        env_prefix="TURBOWRAP_AUTOUPDATE_",
        extra="ignore",
    )

    # S3 checkpoint storage
    s3_bucket: str = Field(default="turbowrap-thinking")
    s3_region: str = Field(default="eu-west-3")
    s3_prefix: str = Field(default="auto-update/")

    # LLM model settings
    analysis_model: str = Field(
        default="gemini-2.0-flash",
        description="Model for Step 1 analysis",
    )
    research_model: str = Field(
        default="gemini-2.0-flash",
        description="Model for Step 2 web research with grounding",
    )
    evaluation_model: str = Field(
        default="claude-opus-4-5-20251101",
        description="Model for Step 3 evaluation",
    )

    # Linear settings
    linear_team_id: str = Field(default="", description="Linear team ID for issue creation")
    linear_project_id: str = Field(default="", description="Optional Linear project ID")
    linear_label_ids: list[str] = Field(
        default_factory=list,
        description="Label IDs to add to created issues",
    )

    # Research queries
    competitor_queries: list[str] = Field(
        default_factory=lambda: [
            "AI code review tools 2025 features comparison",
            "developer productivity AI tools best practices",
            "code analysis automation emerging technologies",
            "GitHub Copilot alternatives code review",
            "Linear integration developer tools automation",
        ],
        description="Web search queries for competitor research",
    )

    # Workflow settings
    max_features_to_propose: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of features to propose",
    )
    min_priority_score: float = Field(
        default=30.0,
        ge=0,
        le=100,
        description="Minimum priority score to create an issue",
    )

    # Retry settings
    max_retries: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: int = Field(default=5, ge=1)


def get_autoupdate_settings() -> AutoUpdateSettings:
    """Get auto-update settings instance."""
    return AutoUpdateSettings()
