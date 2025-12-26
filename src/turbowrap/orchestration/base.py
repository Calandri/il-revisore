"""
Base orchestrator abstract class for TurboWrap.

Provides a common foundation for all orchestrators with:
- Unified settings access
- Progress event emission helpers
- Run ID generation
- Common lifecycle hooks
"""

import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from turbowrap.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Generic type for progress events
TProgressEvent = TypeVar("TProgressEvent", bound=BaseModel)
# Generic type for result
TResult = TypeVar("TResult", bound=BaseModel)

# Generic progress callback type
ProgressCallback = Callable[[TProgressEvent], Awaitable[None]]


class BaseOrchestrator(ABC, Generic[TProgressEvent, TResult]):
    """
    Abstract base class for all TurboWrap orchestrators.

    Provides:
    - Unified settings access
    - Progress event emission helpers
    - Run ID generation
    - Common lifecycle hooks

    Subclasses must implement the `run()` method.

    Example:
        class MyOrchestrator(BaseOrchestrator[MyProgressEvent, MyResult]):
            async def run(self, request: MyRequest) -> MyResult:
                self._mark_started()
                await self.emit(MyProgressEvent(type="started"))
                # ... do work ...
                return MyResult(...)
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        run_id: str | None = None,
        id_prefix: str = "run",
    ):
        """
        Initialize orchestrator.

        Args:
            repo_path: Repository path (optional, defaults to cwd)
            run_id: Explicit run ID (auto-generated if not provided)
            id_prefix: Prefix for auto-generated run IDs
        """
        self.settings: Settings = get_settings()
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        self.run_id = run_id or f"{id_prefix}_{uuid.uuid4().hex[:12]}"
        self._progress_callback: Callable[[TProgressEvent], Awaitable[None]] | None = None
        self._started_at: datetime | None = None

    @abstractmethod
    async def run(self, **kwargs: Any) -> TResult:
        """
        Execute the orchestrator's main workflow.

        Must be implemented by subclasses.

        Returns:
            Result of the orchestration
        """
        ...

    def set_progress_callback(
        self, callback: Callable[[TProgressEvent], Awaitable[None]] | None
    ) -> None:
        """
        Set the progress callback for event emission.

        Args:
            callback: Async callback function to receive progress events
        """
        self._progress_callback = callback

    async def emit(self, event: TProgressEvent) -> None:
        """
        Emit a progress event to the callback.

        Safely handles callback errors to prevent workflow interruption.

        Args:
            event: Progress event to emit
        """
        if self._progress_callback:
            try:
                await self._progress_callback(event)
            except Exception as e:
                logger.error(f"Error emitting progress event: {e}")

    async def emit_log(
        self,
        level: str,
        message: str,
        event_factory: Callable[..., TProgressEvent],
        **extra_fields: Any,
    ) -> None:
        """
        Emit a log-style progress event (for UI toast notifications).

        This is a convenience method for emitting log events that appear
        as toast notifications in the UI.

        Args:
            level: Log level (INFO, WARNING, ERROR)
            message: Log message
            event_factory: Factory function to create the progress event
            **extra_fields: Additional fields for the event
        """
        event = event_factory(
            log_level=level,
            message=message,
            **extra_fields,
        )
        await self.emit(event)

    @property
    def duration_seconds(self) -> float:
        """
        Get elapsed time since start.

        Returns:
            Elapsed seconds, or 0.0 if not started
        """
        if self._started_at is None:
            return 0.0
        return (datetime.utcnow() - self._started_at).total_seconds()

    def _mark_started(self) -> None:
        """Mark the start time of the workflow."""
        self._started_at = datetime.utcnow()

    def _generate_run_id(self, prefix: str = "run") -> str:
        """
        Generate a new unique run ID.

        Args:
            prefix: Prefix for the run ID

        Returns:
            Unique run ID string
        """
        return f"{prefix}_{uuid.uuid4().hex[:12]}"
