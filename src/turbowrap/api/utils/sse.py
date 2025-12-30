"""SSE (Server-Sent Events) utility functions.

Provides centralized formatting for SSE events to eliminate duplicated code.
"""

import json
from typing import Any


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format SSE event with type and JSON data.

    Args:
        event_type: The SSE event type (e.g., "progress", "error", "done")
        data: Dictionary to serialize as JSON in the data field

    Returns:
        Formatted SSE event string with double newline terminator
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def sse_error(message: str) -> str:
    """Format SSE error event.

    Args:
        message: Error message to include

    Returns:
        Formatted SSE error event string
    """
    return sse_event("error", {"error": message})


def sse_progress(message: str, **extra: Any) -> str:
    """Format SSE progress event.

    Args:
        message: Progress message
        **extra: Additional key-value pairs to include in the data

    Returns:
        Formatted SSE progress event string
    """
    data = {"message": message, **extra}
    return sse_event("progress", data)


def sse_ping() -> str:
    """Format SSE keepalive ping.

    Returns:
        SSE comment line for keepalive
    """
    return ": keepalive\n\n"


def sse_done(data: dict[str, Any] | None = None) -> str:
    """Format SSE done/complete event.

    Args:
        data: Optional data to include in the done event

    Returns:
        Formatted SSE done event string
    """
    return sse_event("done", data or {})
