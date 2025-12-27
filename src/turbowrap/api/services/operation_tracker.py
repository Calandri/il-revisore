"""
Unified Operation Tracker - Track all long-running operations.

This module provides a thread-safe, singleton tracker for monitoring
all operations across the application: fix, review, git, clone, sync, deploy.

Design Principles:
- Single source of truth for all active operations
- Zero code duplication - one tracker for everything
- Backward compatible with existing IdempotencyStore pattern
- Real-time visibility into what's happening across all repos
- Dual storage: in-memory for fast access + DB for persistence/history
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Types of operations that can be tracked."""

    # AI-powered operations (long-running)
    FIX = "fix"
    REVIEW = "review"

    # Git write operations (medium duration)
    GIT_COMMIT = "git_commit"
    GIT_MERGE = "git_merge"
    GIT_PUSH = "git_push"
    GIT_PULL = "git_pull"

    # Repository operations (can be long for large repos)
    CLONE = "clone"
    SYNC = "sync"

    # Post-fix operations
    MERGE_AND_PUSH = "merge_and_push"
    OPEN_PR = "open_pr"

    # Deployment
    DEPLOY = "deploy"
    PROMOTE = "promote"

    # Generic CLI task (for auto-tracking)
    CLI_TASK = "cli_task"


# Human-readable labels for each operation type
OPERATION_LABELS: dict[OperationType, str] = {
    OperationType.FIX: "fixing issues on",
    OperationType.REVIEW: "reviewing",
    OperationType.GIT_MERGE: "merging into",
    OperationType.GIT_PUSH: "pushing to",
    OperationType.GIT_PULL: "pulling",
    OperationType.CLONE: "cloning",
    OperationType.SYNC: "syncing",
    OperationType.MERGE_AND_PUSH: "merging & pushing",
    OperationType.OPEN_PR: "opening PR for",
    OperationType.DEPLOY: "deploying",
    OperationType.PROMOTE: "promoting to production",
    OperationType.CLI_TASK: "running task on",
}

# Colors for frontend (Tailwind classes)
OPERATION_COLORS: dict[OperationType, str] = {
    OperationType.FIX: "violet",
    OperationType.REVIEW: "blue",
    OperationType.GIT_MERGE: "green",
    OperationType.GIT_PUSH: "orange",
    OperationType.GIT_PULL: "cyan",
    OperationType.CLONE: "gray",
    OperationType.SYNC: "yellow",
    OperationType.MERGE_AND_PUSH: "emerald",
    OperationType.OPEN_PR: "purple",
    OperationType.DEPLOY: "red",
    OperationType.PROMOTE: "rose",
    OperationType.CLI_TASK: "slate",
}


@dataclass
class Operation:
    """
    A tracked operation.

    This is the unified data structure for all operations,
    flexible enough to handle fix, review, git, and deploy operations.
    """

    # Core identity
    operation_id: str
    operation_type: OperationType
    status: str  # "in_progress", "completed", "failed", "cancelled"
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Context (common to all operations)
    repository_id: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    user_name: str | None = None

    # Operation-specific details (flexible dict)
    details: dict[str, Any] = field(default_factory=dict)

    # Completion data
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @property
    def label(self) -> str:
        """Human-readable label for this operation."""
        return OPERATION_LABELS.get(self.operation_type, self.operation_type.value)

    @property
    def color(self) -> str:
        """Color class for frontend."""
        return OPERATION_COLORS.get(self.operation_type, "gray")

    @property
    def duration_seconds(self) -> float | None:
        """Duration in seconds, if started."""
        if not self.created_at:
            return None
        end = self.completed_at or datetime.utcnow()
        return (end - self.created_at).total_seconds()

    @property
    def is_stale(self) -> bool:
        """True if operation has been running for >30 minutes."""
        if self.status != "in_progress":
            return False
        return (self.duration_seconds or 0) > 1800

    def to_dict(self) -> dict[str, Any]:
        """Convert to API response format."""
        return {
            "operation_id": self.operation_id,
            "type": self.operation_type.value,
            "label": self.label,
            "color": self.color,
            "status": self.status,
            "repository_id": self.repository_id,
            "repository_name": self.repository_name,
            "branch_name": self.branch_name,
            "user_name": self.user_name,
            "details": self.details,
            "started_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "is_stale": self.is_stale,
            "error": self.error,
        }


class OperationTracker:
    """
    Singleton tracker for all operations.

    Thread-safe, with automatic cleanup of old entries.
    Provides a unified view of all active operations across the system.

    Usage:
        tracker = OperationTracker()

        # Register an operation
        op = tracker.register(
            op_type=OperationType.GIT_PUSH,
            repo_id="abc-123",
            repo_name="my-repo",
            branch="main",
            user="john",
            details={"remote": "origin"}
        )

        # Update during execution
        tracker.update(op.operation_id, branch="feature-x")

        # Complete or fail
        tracker.complete(op.operation_id, result={"pushed": True})
        # OR
        tracker.fail(op.operation_id, error="Authentication failed")
    """

    _instance: OperationTracker | None = None
    _lock = RLock()

    # Time-to-live for completed/failed operations (1 hour)
    TTL_SECONDS = 3600

    # Stale threshold (30 minutes)
    STALE_THRESHOLD_SECONDS = 1800

    def __new__(cls) -> OperationTracker:
        """Singleton pattern with double-checked locking."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init_store()
                    cls._instance = instance
        return cls._instance

    def _init_store(self) -> None:
        """Initialize the internal store."""
        self._operations: dict[str, Operation] = {}
        self._store_lock = RLock()

    def _cleanup_expired(self) -> None:
        """Remove expired completed/failed operations."""
        now = datetime.utcnow()
        expired_ids = []

        for op_id, op in self._operations.items():
            if op.status in ("completed", "failed", "cancelled"):
                if op.completed_at:
                    age = (now - op.completed_at).total_seconds()
                    if age > self.TTL_SECONDS:
                        expired_ids.append(op_id)

        for op_id in expired_ids:
            del self._operations[op_id]

        if expired_ids:
            logger.debug(f"Cleaned up {len(expired_ids)} expired operations")

    def register(
        self,
        op_type: OperationType,
        *,
        operation_id: str | None = None,
        repo_id: str | None = None,
        repo_name: str | None = None,
        branch: str | None = None,
        user: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> Operation:
        """
        Register a new operation.

        Args:
            op_type: Type of operation
            operation_id: Optional custom ID (auto-generated if not provided)
            repo_id: Repository ID
            repo_name: Repository name (for display)
            branch: Branch name
            user: User who initiated the operation
            details: Operation-specific details

        Returns:
            The created Operation instance
        """
        with self._store_lock:
            self._cleanup_expired()

            op_id = operation_id or str(uuid.uuid4())

            operation = Operation(
                operation_id=op_id,
                operation_type=op_type,
                status="in_progress",
                repository_id=repo_id,
                repository_name=repo_name,
                branch_name=branch,
                user_name=user,
                details=details or {},
            )

            self._operations[op_id] = operation

            logger.info(
                f"[TRACKER] Registered {op_type.value}: {op_id} "
                f"(repo={repo_name}, branch={branch}, user={user})"
            )

            # Persist to database (async-safe, non-blocking)
            self._persist_register(operation)

            return operation

    def update(
        self,
        operation_id: str,
        *,
        status: str | None = None,
        branch: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> Operation | None:
        """
        Update an existing operation.

        Args:
            operation_id: Operation to update
            status: New status (if changing)
            branch: Updated branch name
            details: Additional details to merge

        Returns:
            Updated Operation or None if not found
        """
        with self._store_lock:
            op = self._operations.get(operation_id)
            if not op:
                logger.warning(f"[TRACKER] Update failed: operation {operation_id} not found")
                return None

            if status:
                op.status = status
            if branch:
                op.branch_name = branch
            if details:
                op.details.update(details)

            # Persist details update to database
            if details:
                self._persist_update(operation_id, {"details": op.details})

            return op

    def complete(
        self,
        operation_id: str,
        result: dict[str, Any] | None = None,
    ) -> Operation | None:
        """
        Mark operation as completed.

        Args:
            operation_id: Operation to complete
            result: Result data

        Returns:
            Updated Operation or None if not found
        """
        with self._store_lock:
            op = self._operations.get(operation_id)
            if not op:
                logger.warning(f"[TRACKER] Complete failed: operation {operation_id} not found")
                return None

            op.status = "completed"
            op.completed_at = datetime.utcnow()
            op.result = result

            logger.info(
                f"[TRACKER] Completed {op.operation_type.value}: {operation_id} "
                f"(duration={op.duration_seconds:.1f}s)"
            )

            # Persist to database
            self._persist_complete(op)

            return op

    def fail(
        self,
        operation_id: str,
        error: str,
    ) -> Operation | None:
        """
        Mark operation as failed.

        Args:
            operation_id: Operation to fail
            error: Error message

        Returns:
            Updated Operation or None if not found
        """
        with self._store_lock:
            op = self._operations.get(operation_id)
            if not op:
                logger.warning(f"[TRACKER] Fail failed: operation {operation_id} not found")
                return None

            op.status = "failed"
            op.completed_at = datetime.utcnow()
            op.error = error

            logger.error(f"[TRACKER] Failed {op.operation_type.value}: {operation_id} - {error}")

            # Persist to database
            self._persist_fail(op)

            return op

    def cancel(self, operation_id: str) -> Operation | None:
        """Mark operation as cancelled."""
        with self._store_lock:
            op = self._operations.get(operation_id)
            if not op:
                return None

            op.status = "cancelled"
            op.completed_at = datetime.utcnow()

            logger.info(f"[TRACKER] Cancelled {op.operation_type.value}: {operation_id}")

            # Persist to database
            self._persist_cancel(op)

            return op

    def remove(self, operation_id: str) -> bool:
        """
        Remove an operation from tracking.

        Args:
            operation_id: Operation to remove

        Returns:
            True if removed, False if not found
        """
        with self._store_lock:
            if operation_id in self._operations:
                del self._operations[operation_id]
                logger.debug(f"[TRACKER] Removed operation: {operation_id}")
                return True
            return False

    def get(self, operation_id: str) -> Operation | None:
        """Get a specific operation by ID."""
        with self._store_lock:
            return self._operations.get(operation_id)

    def get_active(
        self,
        op_type: OperationType | None = None,
        repo_id: str | None = None,
    ) -> list[Operation]:
        """
        Get all active (in_progress) operations.

        Args:
            op_type: Filter by operation type
            repo_id: Filter by repository ID

        Returns:
            List of active operations, sorted by creation time (newest first)
        """
        with self._store_lock:
            self._cleanup_expired()

            operations = [op for op in self._operations.values() if op.status == "in_progress"]

            if op_type:
                operations = [op for op in operations if op.operation_type == op_type]

            if repo_id:
                operations = [op for op in operations if op.repository_id == repo_id]

            # Sort by creation time, newest first
            operations.sort(key=lambda x: x.created_at, reverse=True)

            return operations

    def get_all(
        self,
        include_completed: bool = False,
    ) -> list[Operation]:
        """
        Get all tracked operations.

        Args:
            include_completed: Include completed/failed operations

        Returns:
            List of operations
        """
        with self._store_lock:
            self._cleanup_expired()

            if include_completed:
                operations = list(self._operations.values())
            else:
                operations = [op for op in self._operations.values() if op.status == "in_progress"]

            operations.sort(key=lambda x: x.created_at, reverse=True)
            return operations

    def count_active(self, op_type: OperationType | None = None) -> int:
        """Count active operations, optionally filtered by type."""
        return len(self.get_active(op_type))

    def has_active(self, op_type: OperationType | None = None) -> bool:
        """Check if there are any active operations."""
        return self.count_active(op_type) > 0

    # =========================================================================
    # Database Persistence Methods
    # =========================================================================

    def _persist_register(self, operation: Operation) -> None:
        """Persist a new operation to database."""
        try:
            from turbowrap.db.models import Operation as DBOperation
            from turbowrap.db.session import get_session_local

            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                db_op = DBOperation(
                    id=operation.operation_id,
                    operation_type=operation.operation_type.value,
                    status=operation.status,
                    repository_id=operation.repository_id,
                    repository_name=operation.repository_name,
                    branch_name=operation.branch_name,
                    user_name=operation.user_name,
                    details=operation.details,
                    started_at=operation.created_at,
                )
                db.add(db_op)
                db.commit()
                logger.debug(f"[TRACKER-DB] Persisted operation: {operation.operation_id[:8]}")
            finally:
                db.close()
        except Exception as e:
            # Don't fail the operation if DB persistence fails
            logger.warning(f"[TRACKER-DB] Failed to persist operation: {e}")

    def _persist_update(self, operation_id: str, updates: dict[str, Any]) -> None:
        """Update operation in database."""
        try:
            from turbowrap.db.models import Operation as DBOperation
            from turbowrap.db.session import get_session_local

            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                db_op = db.query(DBOperation).filter(DBOperation.id == operation_id).first()
                if db_op:
                    for key, value in updates.items():
                        if hasattr(db_op, key):
                            setattr(db_op, key, value)
                    db.commit()
                    logger.debug(f"[TRACKER-DB] Updated operation: {operation_id[:8]}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[TRACKER-DB] Failed to update operation: {e}")

    def _persist_complete(self, operation: Operation) -> None:
        """Mark operation as completed in database."""
        try:
            from turbowrap.db.models import Operation as DBOperation
            from turbowrap.db.session import get_session_local

            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                db_op = db.query(DBOperation).filter(DBOperation.id == operation.operation_id).first()
                if db_op:
                    db_op.status = "completed"  # type: ignore[assignment]
                    db_op.completed_at = operation.completed_at  # type: ignore[assignment]
                    db_op.duration_seconds = operation.duration_seconds  # type: ignore[assignment]
                    db_op.result = operation.result  # type: ignore[assignment]
                    db.commit()
                    logger.debug(f"[TRACKER-DB] Completed operation: {operation.operation_id[:8]}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[TRACKER-DB] Failed to complete operation in DB: {e}")

    def _persist_fail(self, operation: Operation) -> None:
        """Mark operation as failed in database."""
        try:
            from turbowrap.db.models import Operation as DBOperation
            from turbowrap.db.session import get_session_local

            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                db_op = db.query(DBOperation).filter(DBOperation.id == operation.operation_id).first()
                if db_op:
                    db_op.status = "failed"  # type: ignore[assignment]
                    db_op.completed_at = operation.completed_at  # type: ignore[assignment]
                    db_op.duration_seconds = operation.duration_seconds  # type: ignore[assignment]
                    db_op.error = operation.error  # type: ignore[assignment]
                    db.commit()
                    logger.debug(f"[TRACKER-DB] Failed operation: {operation.operation_id[:8]}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[TRACKER-DB] Failed to mark operation as failed in DB: {e}")

    def _persist_cancel(self, operation: Operation) -> None:
        """Mark operation as cancelled in database."""
        try:
            from turbowrap.db.models import Operation as DBOperation
            from turbowrap.db.session import get_session_local

            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                db_op = db.query(DBOperation).filter(DBOperation.id == operation.operation_id).first()
                if db_op:
                    db_op.status = "cancelled"  # type: ignore[assignment]
                    db_op.completed_at = operation.completed_at  # type: ignore[assignment]
                    db_op.duration_seconds = operation.duration_seconds  # type: ignore[assignment]
                    db.commit()
                    logger.debug(f"[TRACKER-DB] Cancelled operation: {operation.operation_id[:8]}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[TRACKER-DB] Failed to cancel operation in DB: {e}")


# Convenience function for getting the singleton
def get_tracker() -> OperationTracker:
    """Get the global OperationTracker instance."""
    return OperationTracker()
