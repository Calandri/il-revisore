"""Hook registry system for event-driven architecture.

Provides a centralized hook system that allows registering and triggering
custom callbacks for events across the application.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class HookRegistry:
    """Registry for custom async hooks.

    Allows adding custom async callbacks for events and triggering them
    with arbitrary arguments. Multiple callbacks can be registered for
    the same event and will all be executed.

    Example:
        >>> registry = HookRegistry()
        >>> async def my_hook(message: str) -> None:
        ...     print(f"Event: {message}")
        >>> registry.register("message_sent", my_hook)
        >>> await registry.trigger("message_sent", message="hello")
    """

    def __init__(self) -> None:
        """Initialize the hook registry."""
        self._hooks: dict[str, list[Callable[..., Awaitable[Any]]]] = {}

    def register(self, event: str, callback: Callable[..., Awaitable[Any]]) -> None:
        """Register a hook callback for an event.

        Args:
            event: Event name (e.g., "message_sent", "response_complete")
            callback: Async function to call when event is triggered.
                     Function signature should match trigger() kwargs.

        Raises:
            TypeError: If callback is not awaitable
        """
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    async def trigger(self, event: str, **kwargs: Any) -> list[Any]:
        """Trigger all registered hooks for an event.

        Calls all registered callbacks for the event in order.
        If a callback raises an exception, it's logged and the error dict
        is added to results, but execution continues.

        Args:
            event: Event name
            **kwargs: Arguments to pass to all callbacks

        Returns:
            List of results from all callbacks, or error dicts if they failed
        """
        if event not in self._hooks:
            return []

        results: list[Any] = []
        for callback in self._hooks[event]:
            try:
                result = await callback(**kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Hook error for {event}: {e}", exc_info=True)
                results.append({"error": str(e)})

        return results


# Global registry instance
_hook_registry: HookRegistry = HookRegistry()


def get_hook_registry() -> HookRegistry:
    """Get the global hook registry.

    Returns:
        The global HookRegistry instance
    """
    return _hook_registry


def register_hook(event: str, callback: Callable[..., Awaitable[Any]]) -> None:
    """Register a hook callback on the global registry.

    Convenience function that registers on the global registry
    instead of needing to call get_hook_registry().register().

    Args:
        event: Event name
        callback: Async callback function
    """
    _hook_registry.register(event, callback)


async def trigger_hooks(event: str, **kwargs: Any) -> list[Any]:
    """Trigger all registered hooks for an event on the global registry.

    Convenience function for triggering hooks on the global registry.

    Args:
        event: Event name
        **kwargs: Arguments for hooks

    Returns:
        List of results from all callbacks
    """
    return await _hook_registry.trigger(event, **kwargs)


__all__ = [
    "HookRegistry",
    "get_hook_registry",
    "register_hook",
    "trigger_hooks",
]
