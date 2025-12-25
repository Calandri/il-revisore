"""Settings routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

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
        setting.value = value
        if description:
            setting.description = description
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
def get_settings(db: Session = Depends(get_db)):
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
        linear_team_id=linear_team_id.value if linear_team_id else None,
        # Models: DB overrides config defaults
        claude_model=claude_model.value if claude_model else config.agents.claude_model,
        gemini_model=gemini_model.value if gemini_model else config.agents.gemini_model,
        gemini_pro_model=gemini_pro_model.value if gemini_pro_model else config.agents.gemini_pro_model,
    )


@router.put("/github-token")
def set_github_token(
    data: GitHubTokenUpdate,
    db: Session = Depends(get_db),
):
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
def delete_github_token(db: Session = Depends(get_db)):
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
):
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
def delete_linear_api_key(db: Session = Depends(get_db)):
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
):
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
    return setting.value if setting else None


# Model endpoints
@router.put("/models/claude")
def set_claude_model(
    data: ModelUpdate,
    db: Session = Depends(get_db),
):
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
):
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
):
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
    return setting.value if setting and setting.value else default
