"""Settings routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ..schemas.settings import SettingsResponse, GitHubTokenUpdate, ModelUpdate
from ...db.models import Setting
from ...config import get_settings as get_config

router = APIRouter(prefix="/settings", tags=["settings"])

# Setting keys
GITHUB_TOKEN_KEY = "github_token"
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
    claude_model = _get_setting(db, CLAUDE_MODEL_KEY)
    gemini_model = _get_setting(db, GEMINI_MODEL_KEY)
    gemini_pro_model = _get_setting(db, GEMINI_PRO_MODEL_KEY)

    return SettingsResponse(
        github_token="***" if github_token and github_token.value else None,
        github_token_set=bool(github_token and github_token.value),
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
