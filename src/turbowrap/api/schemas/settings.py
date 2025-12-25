"""Settings schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class SettingUpdate(BaseModel):
    """Request to update a setting."""

    value: str | None = Field(default=None, description="Setting value")


class SettingResponse(BaseModel):
    """Setting response."""

    key: str = Field(..., description="Setting key")
    value: str | None = Field(default=None, description="Setting value (masked if secret)")
    is_secret: bool = Field(default=False, description="Whether value is secret")
    description: str | None = Field(default=None, description="Setting description")
    updated_at: datetime | None = Field(default=None, description="Last update")


class SettingsResponse(BaseModel):
    """All settings response."""

    github_token: str | None = Field(default=None, description="GitHub token (masked)")
    github_token_set: bool = Field(default=False, description="Whether GitHub token is configured")

    # Linear Integration
    linear_api_key: str | None = Field(default=None, description="Linear API key (masked)")
    linear_api_key_set: bool = Field(default=False, description="Whether Linear API key is configured")
    linear_team_id: str | None = Field(default=None, description="Linear team ID")

    # AI Models
    claude_model: str | None = Field(default=None, description="Claude model name")
    gemini_model: str | None = Field(default=None, description="Gemini Flash model name")
    gemini_pro_model: str | None = Field(default=None, description="Gemini Pro model name")


class GitHubTokenUpdate(BaseModel):
    """Request to update GitHub token."""

    token: str = Field(..., min_length=1, description="GitHub personal access token")


class LinearAPIKeyUpdate(BaseModel):
    """Request to update Linear API key."""

    api_key: str = Field(..., min_length=1, description="Linear API key")


class LinearTeamIDUpdate(BaseModel):
    """Request to update Linear team ID."""

    team_id: str = Field(..., min_length=1, description="Linear team ID (UUID)")


class ModelUpdate(BaseModel):
    """Request to update an AI model setting."""

    model: str = Field(..., min_length=1, description="Model name/ID")
