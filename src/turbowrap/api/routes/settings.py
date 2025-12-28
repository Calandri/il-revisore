"""Settings routes."""

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...chat_cli import AgentInfo, get_agent_loader
from ...config import get_settings as get_config
from ...db.models import Setting
from ..deps import get_db
from ..schemas.settings import (
    GitHubTokenUpdate,
    LinearAPIKeyUpdate,
    LinearTeamIDUpdate,
    ModelUpdate,
    SettingsResponse,
)

router = APIRouter(prefix="/settings", tags=["settings"])

# Setting keys
GITHUB_TOKEN_KEY = "github_token"
LINEAR_API_KEY_KEY = "linear_api_key"
LINEAR_TEAM_ID_KEY = "linear_team_id"
CLAUDE_MODEL_KEY = "claude_model"
GEMINI_MODEL_KEY = "gemini_model"
GEMINI_PRO_MODEL_KEY = "gemini_pro_model"


def _get_setting(db: Session, key: str) -> Setting | None:
    """Get a setting by key."""
    return db.query(Setting).filter(Setting.key == key).first()


def _set_setting(
    db: Session,
    key: str,
    value: str | None,
    is_secret: str = "N",
    description: str | None = None,
) -> Setting:
    """Set a setting value."""
    setting = _get_setting(db, key)

    if setting:
        setting.value = value  # type: ignore[assignment]
        if description:
            setting.description = description  # type: ignore[assignment]
    else:
        setting = Setting(
            key=key,
            value=value,
            is_secret=is_secret,
            description=description,
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)
    return setting


@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    """Get all settings (secrets are masked)."""
    config = get_config()

    github_token = _get_setting(db, GITHUB_TOKEN_KEY)
    linear_api_key = _get_setting(db, LINEAR_API_KEY_KEY)
    linear_team_id = _get_setting(db, LINEAR_TEAM_ID_KEY)
    claude_model = _get_setting(db, CLAUDE_MODEL_KEY)
    gemini_model = _get_setting(db, GEMINI_MODEL_KEY)
    gemini_pro_model = _get_setting(db, GEMINI_PRO_MODEL_KEY)

    return SettingsResponse(
        github_token="***" if github_token and github_token.value else None,
        github_token_set=bool(github_token and github_token.value),
        # Linear Integration
        linear_api_key="***" if linear_api_key and linear_api_key.value else None,
        linear_api_key_set=bool(linear_api_key and linear_api_key.value),
        linear_team_id=(
            str(linear_team_id.value) if linear_team_id and linear_team_id.value else None
        ),
        # Models: DB overrides config defaults
        claude_model=(
            str(claude_model.value)
            if claude_model and claude_model.value
            else config.agents.claude_model
        ),
        gemini_model=(
            str(gemini_model.value)
            if gemini_model and gemini_model.value
            else config.agents.gemini_model
        ),
        gemini_pro_model=(
            str(gemini_pro_model.value)
            if gemini_pro_model and gemini_pro_model.value
            else config.agents.gemini_pro_model
        ),
    )


@router.put("/github-token")
def set_github_token(
    data: GitHubTokenUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Set GitHub token for private repositories."""
    _set_setting(
        db,
        key=GITHUB_TOKEN_KEY,
        value=data.token,
        is_secret="Y",
        description="GitHub personal access token for private repositories",
    )
    return {"status": "ok", "message": "GitHub token saved"}


@router.delete("/github-token")
def delete_github_token(db: Session = Depends(get_db)) -> dict[str, str]:
    """Delete GitHub token."""
    setting = _get_setting(db, GITHUB_TOKEN_KEY)
    if setting:
        db.delete(setting)
        db.commit()
    return {"status": "ok", "message": "GitHub token deleted"}


# Linear endpoints
@router.put("/linear-api-key")
def set_linear_api_key(
    data: LinearAPIKeyUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Set Linear API key for issue management."""
    _set_setting(
        db,
        key=LINEAR_API_KEY_KEY,
        value=data.api_key,
        is_secret="Y",
        description="Linear API key for issue tracking integration",
    )
    return {"status": "ok", "message": "Linear API key saved"}


@router.delete("/linear-api-key")
def delete_linear_api_key(db: Session = Depends(get_db)) -> dict[str, str]:
    """Delete Linear API key."""
    setting = _get_setting(db, LINEAR_API_KEY_KEY)
    if setting:
        db.delete(setting)
        db.commit()
    return {"status": "ok", "message": "Linear API key deleted"}


@router.put("/linear-team-id")
def set_linear_team_id(
    data: LinearTeamIDUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Set Linear team ID for default team."""
    _set_setting(
        db,
        key=LINEAR_TEAM_ID_KEY,
        value=data.team_id,
        description="Linear team ID (UUID) for default team",
    )
    return {"status": "ok", "message": "Linear team ID saved"}


def get_github_token(db: Session) -> str | None:
    """Get GitHub token from database.

    This is a utility function for use by other modules.
    """
    setting = _get_setting(db, GITHUB_TOKEN_KEY)
    return str(setting.value) if setting and setting.value else None


# Model endpoints
@router.put("/models/claude")
def set_claude_model(
    data: ModelUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Set Claude model name."""
    _set_setting(
        db,
        key=CLAUDE_MODEL_KEY,
        value=data.model,
        description="Claude model for code review",
    )
    return {"status": "ok", "model": data.model}


@router.put("/models/gemini")
def set_gemini_model(
    data: ModelUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Set Gemini Flash model name."""
    _set_setting(
        db,
        key=GEMINI_MODEL_KEY,
        value=data.model,
        description="Gemini Flash model for fast analysis",
    )
    return {"status": "ok", "model": data.model}


@router.put("/models/gemini-pro")
def set_gemini_pro_model(
    data: ModelUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Set Gemini Pro model name."""
    _set_setting(
        db,
        key=GEMINI_PRO_MODEL_KEY,
        value=data.model,
        description="Gemini Pro model for complex reasoning",
    )
    return {"status": "ok", "model": data.model}


def get_model_setting(db: Session, key: str, default: str) -> str:
    """Get model setting from DB or return default.

    This is a utility function for use by other modules.
    """
    setting = _get_setting(db, key)
    return str(setting.value) if setting and setting.value else default


# =============================================================================
# AGENTS ENDPOINTS
# =============================================================================


class AgentContentResponse(BaseModel):
    """Agent content with full details."""

    name: str
    description: str
    model: str
    version: str
    color: str
    tokens: int
    path: str
    raw_content: str  # Full file content (frontmatter + body)
    instructions: str  # Body only (markdown after frontmatter)


class AgentUpdateRequest(BaseModel):
    """Request to update an agent."""

    content: str  # Full file content to save


@router.get("/agents", response_model=list[AgentInfo])
def list_agents() -> list[AgentInfo]:
    """List all available agents."""
    loader = get_agent_loader()
    return loader.list_agents(reload=True)


@router.get("/agents/{name}", response_model=AgentContentResponse)
def get_agent(name: str) -> AgentContentResponse:
    """Get agent details including full content."""
    loader = get_agent_loader()
    agent = loader.get_agent(name)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Read raw content from file
    path = Path(agent.info["path"])
    raw_content = path.read_text(encoding="utf-8")

    return AgentContentResponse(
        name=agent.info["name"],
        description=agent.info["description"],
        model=agent.info["model"],
        version=agent.info["version"],
        color=agent.info["color"],
        tokens=agent.info["tokens"],
        path=agent.info["path"],
        raw_content=raw_content,
        instructions=agent.instructions,
    )


@router.put("/agents/{name}")
def update_agent(name: str, data: AgentUpdateRequest) -> dict[str, str]:
    """Update an agent's content."""
    loader = get_agent_loader()
    path = loader.get_agent_path(name)

    if not path:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Validate content has proper frontmatter
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, data.content, re.DOTALL)

    if not match:
        raise HTTPException(
            status_code=400,
            detail="Invalid format: content must have YAML frontmatter between --- delimiters",
        )

    # Validate YAML frontmatter
    try:
        metadata: dict[str, Any] = yaml.safe_load(match.group(1)) or {}
        if not metadata.get("name"):
            raise HTTPException(
                status_code=400,
                detail="Invalid frontmatter: 'name' field is required",
            )
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YAML frontmatter: {e}",
        )

    # Write content to file
    path.write_text(data.content, encoding="utf-8")

    # Clear cache to reload
    loader._cache.pop(name, None)

    return {"status": "ok", "message": f"Agent '{name}' updated successfully"}
