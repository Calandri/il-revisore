"""TurboWrap custom exceptions."""


class TurboWrapError(Exception):
    """Base exception for TurboWrap."""

    pass


class ConfigError(TurboWrapError):
    """Configuration error."""

    pass


class RepositoryError(TurboWrapError):
    """Repository operation error."""

    pass


class CloneError(RepositoryError):
    """Failed to clone repository."""

    pass


class SyncError(RepositoryError):
    """Failed to sync repository."""

    pass


class TaskError(TurboWrapError):
    """Task execution error."""

    pass


class AgentError(TurboWrapError):
    """Agent communication error."""

    pass


class GeminiError(AgentError):
    """Gemini API error."""

    pass


class ClaudeError(AgentError):
    """Claude API error."""

    pass


class DatabaseError(TurboWrapError):
    """Database operation error."""

    pass
