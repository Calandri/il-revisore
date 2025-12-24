"""TurboWrap configuration with Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, SecretStr
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
        default="gemini-2.0-flash",
        min_length=1,
        description="Gemini Flash model (fast analysis)",
    )
    gemini_pro_model: str = Field(
        default="gemini-3-pro-preview",
        min_length=1,
        description="Gemini Pro model (complex reasoning)",
    )
    claude_model: str = Field(
        default="claude-opus-4-20250514",
        min_length=1,
        description="Claude model name",
    )
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")

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


class Settings(BaseSettings):
    """Main TurboWrap settings."""

    model_config = SettingsConfigDict(
        env_prefix="TURBOWRAP_",
        env_nested_delimiter="__",
        extra="ignore"
    )

    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)
    tasks: TaskSettings = Field(default_factory=TaskSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)

    # Paths
    repos_dir: Path = Field(
        default=Path.home() / ".turbowrap" / "repos",
        description="Directory for cloned repositories"
    )
    agents_dir: Path = Field(
        default=Path(__file__).parent.parent.parent / "agents",
        description="Directory for agent prompt files"
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level"
    )

    def ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.repos_dir.mkdir(parents=True, exist_ok=True)

        # Ensure SQLite directory exists
        if self.database.url.startswith("sqlite"):
            db_path = self.database.url.replace("sqlite:///", "")
            db_path = Path(db_path).expanduser()
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
