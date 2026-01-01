"""LLM CLI exceptions."""


class LLMCLIError(Exception):
    """Base exception for LLM CLI operations."""

    pass


class ClaudeError(LLMCLIError):
    """Claude CLI error."""

    pass


class GeminiError(LLMCLIError):
    """Gemini CLI/SDK error."""

    pass


class GrokError(LLMCLIError):
    """Grok CLI error."""

    pass


class TimeoutError(LLMCLIError):
    """CLI operation timed out."""

    pass


class ConfigurationError(LLMCLIError):
    """Configuration or setup error."""

    pass
