"""
File watcher service - real-time file change detection using watchdog.

Provides a singleton service that watches a repository directory and
broadcasts file change events to SSE subscribers.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class FileChangeHandler(FileSystemEventHandler):
    """Handler that receives watchdog events and broadcasts them."""

    def __init__(self, service: FileWatcherService, repo_id: str) -> None:
        super().__init__()
        self.service = service
        self.repo_id = repo_id
        # Debounce: track recent events to avoid duplicates
        self._recent_events: dict[str, float] = {}
        self._debounce_seconds = 0.5

    def _should_ignore(self, path: str) -> bool:
        """Check if this path should be ignored."""
        # Ignore hidden files/folders (except .env, etc.)
        parts = Path(path).parts
        for part in parts:
            if part.startswith(".") and part not in (".env", ".envrc"):
                return True
        # Ignore common temp files
        if path.endswith((".pyc", ".pyo", ".swp", ".swo", "~", ".tmp")):
            return True
        return "__pycache__" in path

    def _debounce(self, path: str) -> bool:
        """Return True if event should be processed (not debounced)."""
        import time

        now = time.time()
        last_time = self._recent_events.get(path, 0)
        if now - last_time < self._debounce_seconds:
            return False
        self._recent_events[path] = now
        # Cleanup old entries
        cutoff = now - 5.0
        self._recent_events = {k: v for k, v in self._recent_events.items() if v > cutoff}
        return True

    def _emit_event(self, action: str, path: str, dest_path: str | None = None) -> None:
        """Emit file change event."""
        if self._should_ignore(path):
            return
        if not self._debounce(path):
            return

        event_data = {
            "action": action,
            "path": path,
            "dest_path": dest_path,
            "repo_id": self.repo_id,
        }
        logger.debug(f"[FileWatcher] {action}: {path}")
        self.service._broadcast(event_data)

    # File events
    def on_created(self, event: FileCreatedEvent | DirCreatedEvent) -> None:
        if not event.is_directory:
            self._emit_event("created", str(event.src_path))

    def on_deleted(self, event: FileDeletedEvent | DirDeletedEvent) -> None:
        if not event.is_directory:
            self._emit_event("deleted", str(event.src_path))

    def on_modified(self, event: FileModifiedEvent | DirModifiedEvent) -> None:
        if not event.is_directory:
            self._emit_event("modified", str(event.src_path))

    def on_moved(self, event: FileMovedEvent | DirMovedEvent) -> None:
        if not event.is_directory:
            dest = str(event.dest_path) if event.dest_path else None
            self._emit_event("moved", str(event.src_path), dest)


class FileWatcherService:
    """Singleton service for watching file changes in repositories.

    Manages a watchdog observer that watches the current repository and
    broadcasts file change events to SSE subscribers.

    Usage:
        service = FileWatcherService.get_instance()
        service.switch_repo(repo_id, repo_path)
        queue = service.subscribe()
        # ... receive events from queue ...
        service.unsubscribe(queue)
    """

    _instance: FileWatcherService | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the service (private - use get_instance())."""
        self._current_repo_id: str | None = None
        self._current_repo_path: Path | None = None
        self._observer: Any = None  # Observer type not recognized by mypy
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get_instance(cls) -> FileWatcherService:
        """Get the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def current_repo_id(self) -> str | None:
        """Get the currently watched repository ID."""
        return self._current_repo_id

    @property
    def subscriber_count(self) -> int:
        """Get the number of active subscribers."""
        return len(self._subscribers)

    def switch_repo(self, repo_id: str | None, repo_path: str | None) -> bool:
        """Switch to watching a different repository.

        Args:
            repo_id: Repository ID (or None to stop watching).
            repo_path: Local path to repository (or None to stop watching).

        Returns:
            True if switch was successful.
        """
        # No change needed
        if repo_id == self._current_repo_id:
            return True

        # Stop current observer
        self._stop_observer()

        if repo_id is None or repo_path is None:
            self._current_repo_id = None
            self._current_repo_path = None
            logger.info("[FileWatcher] Stopped watching (no repo)")
            return True

        # Start new observer
        path = Path(repo_path)
        if not path.exists():
            logger.warning(f"[FileWatcher] Path does not exist: {repo_path}")
            return False

        self._current_repo_id = repo_id
        self._current_repo_path = path
        self._start_observer()

        logger.info(f"[FileWatcher] Now watching repo {repo_id}: {repo_path}")
        return True

    def _start_observer(self) -> None:
        """Start the watchdog observer for current repo."""
        if self._observer is not None:
            self._stop_observer()

        if self._current_repo_path is None or self._current_repo_id is None:
            return

        try:
            self._observer = Observer()
            handler = FileChangeHandler(self, self._current_repo_id)
            self._observer.schedule(
                handler,
                str(self._current_repo_path),
                recursive=True,
            )
            self._observer.start()
            logger.info(f"[FileWatcher] Observer started for {self._current_repo_path}")
        except Exception as e:
            logger.error(f"[FileWatcher] Failed to start observer: {e}")
            self._observer = None

    def _stop_observer(self) -> None:
        """Stop the current watchdog observer."""
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception as e:
                logger.warning(f"[FileWatcher] Error stopping observer: {e}")
            finally:
                self._observer = None

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to file change events.

        Returns:
            Queue that will receive file change events.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        logger.debug(f"[FileWatcher] New subscriber, total: {len(self._subscribers)}")
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe from file change events.

        Args:
            queue: Queue to remove from subscribers.
        """
        if queue in self._subscribers:
            self._subscribers.remove(queue)
            logger.debug(f"[FileWatcher] Subscriber removed, total: {len(self._subscribers)}")

    def _broadcast(self, event: dict[str, Any]) -> None:
        """Broadcast event to all subscribers.

        Called from watchdog handler thread, so we need to be thread-safe.
        """
        dead_subscribers = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead_subscribers.append(queue)

        # Remove dead subscribers
        for queue in dead_subscribers:
            self._subscribers.remove(queue)

    def get_status(self) -> dict[str, Any]:
        """Get current watcher status."""
        return {
            "repo_id": self._current_repo_id,
            "repo_path": str(self._current_repo_path) if self._current_repo_path else None,
            "observer_running": self._observer is not None and self._observer.is_alive(),
            "subscriber_count": len(self._subscribers),
        }
