"""Prompt management for LLM clients."""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from turbowrap.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CachedPrompt:
    """Cached prompt with metadata for invalidation."""

    content: str
    mtime: float  # File modification time when loaded
    path: Path


class PromptCache:
    """Thread-safe prompt cache with automatic invalidation.

    Caches prompts and automatically reloads them when the source file
    has been modified.
    """

    def __init__(self, max_size: int = 32):
        """Initialize cache.

        Args:
            max_size: Maximum number of prompts to cache.
        """
        self._cache: dict[str, CachedPrompt] = {}
        self._lock = threading.RLock()
        self._max_size = max_size

    def get(self, name: str) -> str:
        """Get prompt, loading or reloading as needed.

        Args:
            name: Prompt name (without .md extension).

        Returns:
            Prompt content.

        Raises:
            FileNotFoundError: If prompt file doesn't exist.
        """
        settings = get_settings()
        prompt_path = settings.agents_dir / f"{name}.md"

        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        current_mtime = prompt_path.stat().st_mtime

        with self._lock:
            # Check if we have a valid cached version
            cached = self._cache.get(name)
            if cached and cached.mtime >= current_mtime:
                logger.debug(f"Prompt cache hit: {name}")
                return cached.content

            # Load or reload the prompt
            if cached:
                logger.info(f"Prompt cache invalidated (file changed): {name}")
            else:
                logger.debug(f"Loading prompt: {name}")

            content = prompt_path.read_text(encoding="utf-8")

            # Evict oldest if at capacity
            if len(self._cache) >= self._max_size and name not in self._cache:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Evicted oldest prompt from cache: {oldest_key}")

            self._cache[name] = CachedPrompt(
                content=content,
                mtime=current_mtime,
                path=prompt_path,
            )

            return content

    def clear(self) -> int:
        """Clear all cached prompts.

        Returns:
            Number of entries cleared.
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared {count} prompts from cache")
            return count


# Global cache instance
_prompt_cache = PromptCache()


def load_prompt(name: str) -> str:
    """Load prompt from agents directory.

    Uses a smart cache that automatically invalidates when the source
    file has been modified.

    Args:
        name: Prompt name (without .md extension).
              Examples: "flash_analyzer", "reviewer_be", "reviewer_fe"

    Returns:
        Prompt content as string.

    Raises:
        FileNotFoundError: If prompt file doesn't exist.
    """
    return _prompt_cache.get(name)


def get_available_prompts() -> list[str]:
    """Get list of available prompt names.

    Returns:
        List of prompt names (without .md extension).
    """
    settings = get_settings()

    if not settings.agents_dir.exists():
        return []

    return [p.stem for p in settings.agents_dir.glob("*.md") if p.is_file()]


def reload_prompts() -> int:
    """Clear prompt cache to reload all prompts from disk.

    Returns:
        Number of prompts that were cleared from cache.
    """
    return _prompt_cache.clear()
