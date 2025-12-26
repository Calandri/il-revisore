"""
Unified progress callback types for TurboWrap orchestrators.

Provides:
- Generic ProgressCallback type alias
- BaseProgressEvent with common fields
- ProgressEmitter helper class
- Typed callbacks for specific orchestrators
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Generic progress event type
TProgressEvent = TypeVar("TProgressEvent", bound=BaseModel)

# Generic progress callback type
ProgressCallback = Callable[[TProgressEvent], Awaitable[None]]


class BaseProgressEvent(BaseModel):
    """
    Base class for all progress events.

    Provides common fields shared by all orchestrator progress events.
    Specific orchestrators extend this with additional fields.
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: str | None = Field(default=None, description="Human-readable status message")
    error: str | None = Field(default=None, description="Error message if failed")
    log_level: str | None = Field(default=None, description="Log level: INFO, WARNING, ERROR")

    # Streaming content (for real-time updates)
    content: str | None = Field(default=None, description="Streaming content chunk")

    def to_sse(self) -> dict[str, str]:
        """Convert to SSE format for streaming."""
        event_type = getattr(self, "type", None)
        if event_type and hasattr(event_type, "value"):
            event_name = event_type.value
        else:
            event_name = "progress"

        return {
            "event": event_name,
            "data": self.model_dump_json(exclude_none=True),
        }


class ProgressEmitter:
    """
    Helper class for emitting progress events with common patterns.

    Provides factory methods for common event types across orchestrators.
    Handles callback errors gracefully to prevent workflow interruption.
    """

    def __init__(self, callback: Callable[[BaseModel], Awaitable[None]] | None = None):
        """
        Initialize progress emitter.

        Args:
            callback: Optional async callback to receive events
        """
        self._callback = callback

    def set_callback(self, callback: Callable[[BaseModel], Awaitable[None]] | None) -> None:
        """Set or update the callback."""
        self._callback = callback

    async def emit(self, event: BaseModel) -> None:
        """
        Emit a progress event safely.

        Catches and logs any callback errors to prevent workflow interruption.

        Args:
            event: Progress event to emit
        """
        if self._callback:
            try:
                await self._callback(event)
            except Exception as e:
                logger.error(f"Error emitting progress event: {e}")

    async def emit_log(
        self,
        level: str,
        message: str,
        event_class: type[BaseModel],
        event_type: Enum,
        **extra_fields: Any,
    ) -> None:
        """
        Emit a log-style event for UI toast notifications.

        Args:
            level: Log level (INFO, WARNING, ERROR)
            message: Log message
            event_class: Pydantic model class for the event
            event_type: Event type enum value
            **extra_fields: Additional fields for the event
        """
        event = event_class(
            type=event_type,
            log_level=level,
            message=message,
            **extra_fields,
        )
        await self.emit(event)


# Import specific progress types for convenience re-exports
# These are imported lazily to avoid circular imports
def get_review_progress_types() -> dict[str, Any]:
    """Get review progress event types (lazy import)."""
    from turbowrap.review.models.progress import (
        REVIEWER_DISPLAY_NAMES,
        ReviewerState,
        ReviewProgress,
        get_reviewer_display_name,
    )
    from turbowrap.review.models.progress import ProgressEvent as ReviewProgressEvent
    from turbowrap.review.models.progress import ProgressEventType as ReviewProgressEventType

    return {
        "ReviewProgressEvent": ReviewProgressEvent,
        "ReviewProgressEventType": ReviewProgressEventType,
        "ReviewerState": ReviewerState,
        "ReviewProgress": ReviewProgress,
        "get_reviewer_display_name": get_reviewer_display_name,
        "REVIEWER_DISPLAY_NAMES": REVIEWER_DISPLAY_NAMES,
    }


def get_fix_progress_types() -> dict[str, Any]:
    """Get fix progress event types (lazy import)."""
    from turbowrap.fix.models import FixEventType, FixProgressEvent

    return {
        "FixProgressEvent": FixProgressEvent,
        "FixEventType": FixEventType,
    }


# Type aliases for specific orchestrators
# Import the actual types from the respective modules when needed:
#   from turbowrap.review.models.progress import ProgressEvent as ReviewProgressEvent
#   from turbowrap.fix.models import FixProgressEvent
# Then define: ReviewProgressCallback = Callable[[ReviewProgressEvent], Awaitable[None]]

# Simple tuple callback for auto-update (legacy format)
AutoUpdateProgressCallback = Callable[[str, int, str], Awaitable[None]]

# Checkpoint callback type (from review orchestrator)
# Args: reviewer_name, status, issues, satisfaction, iterations, model_usage, started_at
CheckpointCallback = Callable[
    [str, str, list[Any], float, int, list[dict[str, Any]], datetime],
    Awaitable[None],
]
