"""Environment configuration utilities."""

import os

from ..config import get_settings


def build_env_with_api_keys() -> dict[str, str]:
    """Build environment dict with API keys from centralized config.

    Ensures API keys are available to CLI subprocesses regardless
    of whether they're set as env vars or only in .env/config.
    Supports both Claude and Gemini APIs.

    Returns:
        Environment dict with API keys set
    """
    settings = get_settings()
    env = os.environ.copy()

    # Anthropic API key for Claude CLI
    if settings.agents.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = settings.agents.anthropic_api_key

    # Google/Gemini API key for Gemini CLI
    # Set both for compatibility (some tools use GOOGLE_API_KEY, others GEMINI_API_KEY)
    effective_key = settings.agents.effective_google_key
    if effective_key:
        env["GEMINI_API_KEY"] = effective_key
        env["GOOGLE_API_KEY"] = effective_key

    return env


__all__ = ["build_env_with_api_keys"]
