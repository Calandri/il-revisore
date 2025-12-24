"""Task queue management."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any


@dataclass
class QueuedTask:
    """Task in the queue."""
    task_id: str
    task_type: str
    repository_id: str
    config: dict = field(default_factory=dict)
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


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
                    {"id": t.task_id, "type": t.task_type}
                    for t in self._processing.values()
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


# Global queue instance
_task_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    """Get global task queue instance."""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue
