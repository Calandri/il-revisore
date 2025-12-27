"""TurboWrap configuration with Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_DB_")

    url: str = Field(
        default="sqlite:///~/.turbowrap/turbowrap.db",
        description="Database URL (SQLite or PostgreSQL)",
    )
    echo: bool = Field(default=False, description="Echo SQL queries")
    pool_size: int = Field(default=5, ge=1, le=50, description="Connection pool size")
    pool_recycle: int = Field(default=3600, ge=60, description="Pool recycle time in seconds")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate database URL format."""
        if not (v.startswith("sqlite:") or v.startswith("postgresql:")):
            raise ValueError("Database URL must start with 'sqlite:' or 'postgresql:'")
        return v

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite."""
        return self.url.startswith("sqlite:")


class AgentSettings(BaseSettings):
    """AI Agent configuration."""

    model_config = SettingsConfigDict(env_prefix="", populate_by_name=True)

    gemini_model: str = Field(
        default="gemini-3-flash-preview",
        min_length=1,
        description="Gemini Flash model (fast analysis)",
    )
    gemini_pro_model: str = Field(
        default="gemini-3-pro-preview",
        min_length=1,
        description="Gemini Pro model (complex reasoning)",
    )
    claude_model: str = Field(
        default="claude-opus-4-5-20251101",
        min_length=1,
        description="Claude model name",
    )
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    github_token: str | None = Field(
        default=None, alias="GITHUB_TOKEN", description="GitHub token for private repositories"
    )

    @property
    def effective_google_key(self) -> str | None:
        """Get effective Google API key (prefers GOOGLE_API_KEY)."""
        return self.google_api_key or self.gemini_api_key

    @property
    def has_gemini(self) -> bool:
        """Check if Gemini is configured."""
        return self.effective_google_key is not None

    @property
    def has_claude(self) -> bool:
        """Check if Claude is configured."""
        return self.anthropic_api_key is not None


class TaskSettings(BaseSettings):
    """Task execution configuration."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_TASK_")

    max_workers: int = Field(default=3, ge=1, le=10, description="Max parallel workers")
    batch_size: int = Field(default=3, ge=1, le=10, description="Files per reviewer batch")
    timeout_seconds: int = Field(default=300, ge=30, le=3600, description="Task timeout")
    max_file_size: int = Field(default=6000, ge=100, le=50000, description="Max file chars")


class ServerSettings(BaseSettings):
    """API Server configuration."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_SERVER_")

    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    cors_origins: list[str] = Field(default=["*"], description="CORS allowed origins")
    debug: bool = Field(default=False, description="Debug mode")
    workers: int = Field(default=1, ge=1, le=16, description="Number of workers")


class AuthSettings(BaseSettings):
    """Authentication configuration for AWS Cognito."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_AUTH_")

    enabled: bool = Field(default=True, description="Enable authentication")
    cognito_region: str = Field(default="eu-west-1", description="AWS Cognito region")
    cognito_user_pool_id: str = Field(default="", description="Cognito User Pool ID")
    cognito_app_client_id: str = Field(default="", description="Cognito App Client ID")
    session_cookie_name: str = Field(default="turbowrap_session", description="Session cookie name")
    session_max_age: int = Field(
        default=86400 * 7, description="Session max age in seconds (7 days)"
    )
    secure_cookies: bool = Field(
        default=True, description="Use secure cookies (HTTPS only). Set to False for localhost dev."
    )


class LogsSettings(BaseSettings):
    """CloudWatch logs configuration."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_LOGS_")

    enabled: bool = Field(default=True, description="Enable CloudWatch logs fetching")
    region: str = Field(default="eu-west-1", description="AWS region for CloudWatch")
    log_group: str = Field(
        default="/aws/lambda/oasi-api",
        description="CloudWatch log group name",
    )
    default_minutes: int = Field(
        default=30, ge=1, le=1440, description="Default time range in minutes"
    )
    max_events: int = Field(default=500, ge=10, le=5000, description="Maximum log events to fetch")


class ChallengerSettings(BaseSettings):
    """Challenger loop configuration."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_CHALLENGER_")

    enabled: bool = Field(default=True, description="Enable challenger loop")
    reviewer_model: str = Field(
        default="claude-opus-4-5-20251101", description="Model for the primary reviewer"
    )
    challenger_model: str = Field(
        default="gemini-3-flash-preview", description="Model for the challenger"
    )
    satisfaction_threshold: float = Field(
        default=50.0, ge=0, le=100, description="Required satisfaction score (0-100)"
    )
    max_iterations: int = Field(default=3, ge=1, le=10, description="Maximum challenger iterations")
    min_improvement_threshold: float = Field(
        default=2.0, ge=0, le=100, description="Minimum % improvement per iteration"
    )
    stagnation_window: int = Field(
        default=2, ge=1, le=5, description="Iterations to detect stagnation"
    )
    forced_acceptance_threshold: float = Field(
        default=90.0, ge=0, le=100, description="Accept if above this after max iterations"
    )


class FixChallengerSettings(BaseSettings):
    """Fix challenger configuration."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_FIX_CHALLENGER_")

    enabled: bool = Field(default=True, description="Enable fix challenger")
    model: str = Field(
        default="gemini-3-pro-preview",
        description="Model for fix evaluation (Pro for better reasoning)",
    )
    satisfaction_threshold: float = Field(
        default=95.0, ge=0, le=100, description="Required satisfaction score to approve fix (0-100)"
    )
    max_iterations: int = Field(
        default=2, ge=1, le=5, description="Maximum fix refinement iterations"
    )
    thinking_budget: int = Field(
        default=10000,
        ge=0,
        le=24576,
        description="Token budget for Gemini thinking mode (0 to disable)",
    )


class ThinkingSettings(BaseSettings):
    """Extended thinking configuration for Claude Opus."""

    model_config = SettingsConfigDict(env_prefix="TURBOWRAP_THINKING_")

    enabled: bool = Field(default=True, description="Enable extended thinking")
    budget_tokens: int = Field(
        default=8000,
        ge=1000,
        le=50000,
        description="Base token budget for thinking (1k-50k). Orchestrator increases for heavy issues.",
    )
    s3_bucket: str = Field(
        default="turbowrap-thinking",
        description="S3 bucket for storing thinking logs and review checkpoints (10-day retention)",
    )
    s3_region: str = Field(default="eu-west-3", description="AWS region for S3 bucket")
    stream_to_websocket: bool = Field(
        default=True, description="Stream thinking to WebSocket clients"
    )


class Settings(BaseSettings):
    """Main TurboWrap settings."""

    model_config = SettingsConfigDict(
        env_prefix="TURBOWRAP_", env_nested_delimiter="__", extra="ignore"
    )

    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)
    tasks: TaskSettings = Field(default_factory=TaskSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    challenger: ChallengerSettings = Field(default_factory=ChallengerSettings)
    fix_challenger: FixChallengerSettings = Field(default_factory=FixChallengerSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    thinking: ThinkingSettings = Field(default_factory=ThinkingSettings)
    logs: LogsSettings = Field(default_factory=LogsSettings)

    # Paths
    repos_dir: Path = Field(
        default=Path.home() / ".turbowrap" / "repos",
        description="Directory for cloned repositories",
    )
    agents_dir: Path = Field(
        default=Path(__file__).parent.parent.parent / "agents",
        description="Directory for agent prompt files",
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Logging level"
    )

    def ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.repos_dir.mkdir(parents=True, exist_ok=True)

        # Ensure SQLite directory exists
        if self.database.url.startswith("sqlite"):
            db_path_str = self.database.url.replace("sqlite:///", "")
            db_path = Path(db_path_str).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Get cached global settings instance.

    Returns:
        Settings instance (cached).
    """
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings() -> None:
    """Reset cached settings (useful for testing)."""
    get_settings.cache_clear()
