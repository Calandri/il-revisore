"""Prompt management for LLM clients."""

from pathlib import Path
from functools import lru_cache

from turbowrap.config import get_settings


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """Load prompt from agents directory.

    Args:
        name: Prompt name (without .md extension).
              Examples: "flash_analyzer", "reviewer_be", "reviewer_fe"

    Returns:
        Prompt content as string.

    Raises:
        FileNotFoundError: If prompt file doesn't exist.
    """
    settings = get_settings()
    prompt_path = settings.agents_dir / f"{name}.md"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    return prompt_path.read_text(encoding="utf-8")


def get_available_prompts() -> list[str]:
    """Get list of available prompt names.

    Returns:
        List of prompt names (without .md extension).
    """
    settings = get_settings()

    if not settings.agents_dir.exists():
        return []

    return [
        p.stem
        for p in settings.agents_dir.glob("*.md")
        if p.is_file()
    ]


def reload_prompts() -> None:
    """Clear prompt cache to reload from disk."""
    load_prompt.cache_clear()
