"""
Background review manager for persistent review execution.

Reviews run independently of client SSE connections, allowing:
- Page navigation without losing progress
- Reconnection to ongoing reviews
- Event history for late-joining clients
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, Awaitable
from collections import deque

from turbowrap.review.models.progress import ProgressEvent, ProgressEventType

logger = logging.getLogger(__name__)

# Maximum events to buffer per review (prevent memory issues)
MAX_EVENT_BUFFER = 500


@dataclass
class ReviewSession:
    """Tracks a running review session."""

    task_id: str
    repository_id: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    status: str = "running"  # running, completed, failed, cancelled

    # The asyncio task running the review
    task: Optional[asyncio.Task] = None

    # Buffer of progress events (for reconnection)
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENT_BUFFER))

    # Subscribers waiting for new events
    subscribers: list[asyncio.Queue] = field(default_factory=list)

    def add_event(self, event: ProgressEvent):
        """Add event to buffer and notify subscribers."""
        self.events.append(event)

        # Notify all subscribers
        for queue in self.subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Subscriber is slow, skip

    def subscribe(self) -> asyncio.Queue:
        """Create a new subscriber queue."""
        queue = asyncio.Queue(maxsize=100)
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Remove a subscriber queue."""
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def get_history(self) -> list[ProgressEvent]:
        """Get all buffered events."""
        return list(self.events)


class ReviewManager:
    """
    Singleton manager for background review execution.

    Reviews continue running even when clients disconnect.
    Clients can reconnect and receive event history + live updates.
    """

    _instance: Optional["ReviewManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._sessions: dict[str, ReviewSession] = {}
        self._initialized = True
        logger.info("ReviewManager initialized")

    def get_session(self, task_id: str) -> Optional[ReviewSession]:
        """Get a review session by task ID."""
        return self._sessions.get(task_id)

    def get_active_sessions(self) -> list[ReviewSession]:
        """Get all running review sessions."""
        return [s for s in self._sessions.values() if s.status == "running"]

    async def start_review(
        self,
        task_id: str,
        repository_id: str,
        review_coro: Callable[["ReviewSession"], Awaitable[None]],
    ) -> ReviewSession:
        """
        Start a new review in the background.

        Args:
            task_id: Unique task identifier
            repository_id: Repository being reviewed
            review_coro: Coroutine function that takes ReviewSession as argument

        Returns:
            ReviewSession for tracking/subscribing
        """
        # Check if already running
        if task_id in self._sessions:
            existing = self._sessions[task_id]
            if existing.status == "running":
                logger.warning(f"Review {task_id} already running")
                return existing

        # Create session
        session = ReviewSession(
            task_id=task_id,
            repository_id=repository_id,
        )

        # Wrapper to catch completion/errors
        async def run_with_tracking():
            try:
                await review_coro(session)  # Pass session directly!
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                logger.info(f"Review {task_id} completed")
            except asyncio.CancelledError:
                session.status = "cancelled"
                session.completed_at = datetime.utcnow()
                logger.info(f"Review {task_id} cancelled")
                raise
            except Exception as e:
                session.status = "failed"
                session.completed_at = datetime.utcnow()
                logger.error(f"Review {task_id} failed: {e}")
                # Send error event
                session.add_event(ProgressEvent(
                    type=ProgressEventType.REVIEW_ERROR,
                    error=str(e),
                    message=f"Review failed: {str(e)[:100]}",
                ))
            finally:
                # Send completion signal to all subscribers
                for queue in session.subscribers:
                    try:
                        queue.put_nowait(None)  # None signals completion
                    except asyncio.QueueFull:
                        pass

        # Start background task
        session.task = asyncio.create_task(run_with_tracking())
        self._sessions[task_id] = session

        logger.info(f"Started background review {task_id} for repo {repository_id}")
        return session

    def cancel_review(self, task_id: str) -> bool:
        """Cancel a running review."""
        session = self._sessions.get(task_id)
        if not session or session.status != "running":
            return False

        if session.task and not session.task.done():
            session.task.cancel()
            return True

        return False

    def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Remove old completed sessions to free memory."""
        now = datetime.utcnow()
        to_remove = []

        for task_id, session in self._sessions.items():
            if session.status != "running" and session.completed_at:
                age = (now - session.completed_at).total_seconds() / 3600
                if age > max_age_hours:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self._sessions[task_id]
            logger.info(f"Cleaned up old session {task_id}")


# Global singleton
def get_review_manager() -> ReviewManager:
    """Get the global ReviewManager instance."""
    return ReviewManager()
