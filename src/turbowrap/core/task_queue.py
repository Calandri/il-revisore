"""Task queue management."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

# Default timeout for zombie detection (30 minutes)
DEFAULT_ZOMBIE_TIMEOUT_SECONDS = 1800


@dataclass
class QueuedTask:
    """Task in the queue."""

    task_id: str
    task_type: str
    repository_id: str
    config: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = field(default=None)  # When processing started


class TaskQueue:
    """Simple in-memory task queue.

    Thread-safe queue for managing pending tasks.
    For production, consider using Redis or Celery.
    """

    def __init__(self, max_size: int = 100):
        """Initialize queue.

        Args:
            max_size: Maximum queue size.
        """
        self._queue: deque[QueuedTask] = deque(maxlen=max_size)
        self._lock = Lock()
        self._processing: dict[str, QueuedTask] = {}

    def enqueue(self, task: QueuedTask) -> None:
        """Add task to queue.

        Args:
            task: Task to enqueue.
        """
        with self._lock:
            # Insert based on priority (higher priority first)
            inserted = False
            for i, existing in enumerate(self._queue):
                if task.priority > existing.priority:
                    self._queue.insert(i, task)
                    inserted = True
                    break

            if not inserted:
                self._queue.append(task)

    def dequeue(self) -> QueuedTask | None:
        """Get next task from queue.

        Returns:
            Next task or None if empty.
        """
        with self._lock:
            if not self._queue:
                return None

            task = self._queue.popleft()
            task.started_at = datetime.utcnow()  # Track when processing started
            self._processing[task.task_id] = task
            return task

    def complete(self, task_id: str) -> None:
        """Mark task as completed.

        Args:
            task_id: Task ID to complete.
        """
        with self._lock:
            self._processing.pop(task_id, None)

    def fail(self, task_id: str) -> None:
        """Mark task as failed.

        Args:
            task_id: Task ID that failed.
        """
        with self._lock:
            self._processing.pop(task_id, None)

    def cancel(self, task_id: str) -> bool:
        """Cancel a task.

        Args:
            task_id: Task ID to cancel.

        Returns:
            True if cancelled, False if not found.
        """
        with self._lock:
            # Check processing
            if task_id in self._processing:
                return False  # Can't cancel running task

            # Check queue
            for i, task in enumerate(self._queue):
                if task.task_id == task_id:
                    del self._queue[i]
                    return True

            return False

    def get_status(self) -> dict[str, Any]:
        """Get queue status.

        Returns:
            Status dictionary.
        """
        with self._lock:
            return {
                "pending": len(self._queue),
                "processing": len(self._processing),
                "pending_tasks": [
                    {"id": t.task_id, "type": t.task_type, "priority": t.priority}
                    for t in self._queue
                ],
                "processing_tasks": [
                    {"id": t.task_id, "type": t.task_type} for t in self._processing.values()
                ],
            }

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        with self._lock:
            return len(self._queue) == 0

    def size(self) -> int:
        """Get queue size."""
        with self._lock:
            return len(self._queue)

    def get_zombie_tasks(
        self, timeout_seconds: int = DEFAULT_ZOMBIE_TIMEOUT_SECONDS
    ) -> list[QueuedTask]:
        """Find tasks that have been processing for too long (zombies).

        A zombie task is one that started processing but never completed,
        likely due to a crash, timeout, or other failure without cleanup.

        Args:
            timeout_seconds: Consider a task zombie after this many seconds.
                            Default is 30 minutes.

        Returns:
            List of zombie QueuedTask objects.
        """
        with self._lock:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=timeout_seconds)
            zombies = []

            for task in self._processing.values():
                if task.started_at and task.started_at < cutoff:
                    zombies.append(task)

            return zombies

    def cleanup_zombie_tasks(
        self,
        timeout_seconds: int = DEFAULT_ZOMBIE_TIMEOUT_SECONDS,
        requeue: bool = False,
    ) -> list[str]:
        """Find and remove zombie tasks from processing.

        Args:
            timeout_seconds: Consider a task zombie after this many seconds.
            requeue: If True, put zombie tasks back in the queue for retry.
                    If False, just remove them from processing.

        Returns:
            List of task IDs that were cleaned up.
        """
        with self._lock:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=timeout_seconds)
            zombie_ids = []

            # Find zombies
            for task_id, task in list(self._processing.items()):
                if task.started_at and task.started_at < cutoff:
                    zombie_ids.append(task_id)

            # Clean up zombies
            for task_id in zombie_ids:
                task = self._processing.pop(task_id)
                if requeue:
                    # Reset started_at and put back in queue
                    task.started_at = None
                    task.priority += 1  # Slightly higher priority for retry
                    self._queue.appendleft(task)

            return zombie_ids

    def get_task_age(self, task_id: str) -> timedelta | None:
        """Get how long a task has been processing.

        Args:
            task_id: Task ID to check.

        Returns:
            Time since task started processing, or None if not found.
        """
        with self._lock:
            task = self._processing.get(task_id)
            if task and task.started_at:
                return datetime.utcnow() - task.started_at
            return None


# Global queue instance
_task_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    """Get global task queue instance."""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue
