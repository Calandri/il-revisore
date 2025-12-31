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
import traceback
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import RLock
from typing import TYPE_CHECKING, Any

from turbowrap.utils.datetime_utils import format_iso, now_utc

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Types of operations that can be tracked."""

    FIX = "fix"
    REVIEW = "review"

    GIT_COMMIT = "git_commit"
    GIT_MERGE = "git_merge"
    GIT_PUSH = "git_push"
    GIT_PULL = "git_pull"
    GIT_CHECKOUT = "git_checkout"

    CLONE = "clone"
    SYNC = "sync"

    MERGE_AND_PUSH = "merge_and_push"
    OPEN_PR = "open_pr"

    DEPLOY = "deploy"
    PROMOTE = "promote"

    # Linear issue analysis
    LINEAR_CLARIFY = "linear_clarify"  # Phase 1: generate clarifying questions
    LINEAR_ANALYSIS = "linear_analysis"  # Phase 2: deep analysis with answers

    # Fix clarification and planning
    FIX_CLARIFICATION = "fix_clarification"  # Pre-fix clarification phase
    FIX_PLANNING = "fix_planning"  # Fix planning phase

    # Testing operations
    TEST_DISCOVERY = "test_discovery"  # Discovering tests in repo
    TEST_EXECUTION = "test_execution"  # Running tests
    TEST_ANALYSIS = "test_analysis"  # Analyzing test results
    REPO_TEST_ANALYSIS = "repo_test_analysis"  # Full repo test analysis
    TEST_ENHANCEMENT = "test_enhancement"  # Enhancing tests

    # Analysis operations
    MOCKUP = "mockup"  # Generating mockups
    ENDPOINT_DETECTION = "endpoint_detection"  # Detecting API endpoints
    README_ANALYSIS = "readme_analysis"  # Analyzing README
    EVALUATE = "evaluate"  # Code evaluation

    # Git operations (extended)
    GIT_RESOLVE = "git_resolve"  # Resolving git conflicts
    SMART_PUSH = "smart_push"  # Smart push with conflict handling

    # Fix operations (extended)
    COMPACTION = "compaction"  # Context compaction

    # Generic CLI task (for auto-tracking)
    CLI_TASK = "cli_task"


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
    OperationType.LINEAR_CLARIFY: "clarifying",
    OperationType.LINEAR_ANALYSIS: "analyzing issue",
    OperationType.FIX_CLARIFICATION: "clarifying fix for",
    OperationType.FIX_PLANNING: "planning fix for",
    # Testing operations
    OperationType.TEST_DISCOVERY: "discovering tests in",
    OperationType.TEST_EXECUTION: "running tests on",
    OperationType.TEST_ANALYSIS: "analyzing tests for",
    OperationType.REPO_TEST_ANALYSIS: "analyzing test suite in",
    OperationType.TEST_ENHANCEMENT: "enhancing tests for",
    # Analysis operations
    OperationType.MOCKUP: "generating mockup for",
    OperationType.ENDPOINT_DETECTION: "detecting endpoints in",
    OperationType.README_ANALYSIS: "analyzing README for",
    OperationType.EVALUATE: "evaluating code in",
    # Git operations (extended)
    OperationType.GIT_RESOLVE: "resolving conflicts in",
    OperationType.SMART_PUSH: "smart pushing to",
    # Fix operations (extended)
    OperationType.COMPACTION: "compacting context for",
    # Generic
    OperationType.CLI_TASK: "running task on",
}

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
    OperationType.LINEAR_CLARIFY: "amber",
    OperationType.LINEAR_ANALYSIS: "indigo",
    OperationType.FIX_CLARIFICATION: "teal",
    OperationType.FIX_PLANNING: "sky",
    # Testing operations
    OperationType.TEST_DISCOVERY: "lime",
    OperationType.TEST_EXECUTION: "green",
    OperationType.TEST_ANALYSIS: "emerald",
    OperationType.REPO_TEST_ANALYSIS: "teal",
    OperationType.TEST_ENHANCEMENT: "cyan",
    # Analysis operations
    OperationType.MOCKUP: "fuchsia",
    OperationType.ENDPOINT_DETECTION: "pink",
    OperationType.README_ANALYSIS: "amber",
    OperationType.EVALUATE: "indigo",
    # Git operations (extended)
    OperationType.GIT_RESOLVE: "orange",
    OperationType.SMART_PUSH: "yellow",
    # Fix operations (extended)
    OperationType.COMPACTION: "stone",
    # Generic
    OperationType.CLI_TASK: "slate",
}


@dataclass
class Operation:
    """
    A tracked operation.

    This is the unified data structure for all operations,
    flexible enough to handle fix, review, git, and deploy operations.
    """

    operation_id: str
    operation_type: OperationType
    status: str  # "in_progress", "completed", "failed", "cancelled"
    created_at: datetime = field(default_factory=now_utc)

    repository_id: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    user_name: str | None = None

    parent_session_id: str | None = None

    details: dict[str, Any] = field(default_factory=dict)

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
        end = self.completed_at or now_utc()
        # Handle naive/aware datetime mismatch (DB datetimes may be naive)
        start = self.created_at
        if start.tzinfo is None:
            from datetime import timezone

            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            from datetime import timezone

            end = end.replace(tzinfo=timezone.utc)
        return (end - start).total_seconds()

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
            "result": self.result,
            "started_at": format_iso(self.created_at) if self.created_at else None,
            "completed_at": format_iso(self.completed_at) if self.completed_at else None,
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

        tracker.complete(op.operation_id, result={"pushed": True})
        tracker.fail(op.operation_id, error="Authentication failed")
    """

    _instance: OperationTracker | None = None
    _lock = RLock()

    TTL_SECONDS = 3600

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
        self._subscribers: dict[str, list[Any]] = {}  # operation_id -> list of asyncio.Queue

    def _cleanup_expired(self) -> None:
        """Remove expired completed/failed operations."""
        now = now_utc()
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
        parent_session_id: str | None = None,
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
            parent_session_id: Parent session ID for hierarchical grouping
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
                parent_session_id=parent_session_id,
                details=details or {},
            )

            self._operations[op_id] = operation

            logger.info(
                f"[TRACKER] Registered {op_type.value}: {op_id} "
                f"(repo={repo_name}, branch={branch}, user={user})"
            )

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

            if op:
                # Update in-memory operation
                if status:
                    op.status = status
                if branch:
                    op.branch_name = branch
                if details:
                    op.details.update(details)

                if details:
                    self._persist_update(operation_id, {"details": op.details})

                return op
            # Operation not in memory - update directly in DB
            # This handles cases where server was restarted
            if details:
                self._persist_update_db_only(operation_id, details)
                logger.info(
                    f"[TRACKER] Updated operation in DB only: {operation_id[:8]} "
                    f"(not in memory)"
                )
                return None  # Still return None as we don't have in-memory object
            logger.warning(f"[TRACKER] Update failed: operation {operation_id} not found")
            return None

    def _persist_update_db_only(self, operation_id: str, details: dict[str, Any]) -> bool:
        """Update operation details directly in DB (merge with existing)."""
        try:
            from sqlalchemy.orm.attributes import flag_modified

            with self._db_session() as db:
                db_op = self._get_db_operation(db, operation_id)
                if db_op:
                    # Merge details - must use flag_modified for SQLAlchemy to detect change
                    existing_details = dict(db_op.details or {})
                    existing_details.update(details)
                    db_op.details = existing_details
                    flag_modified(db_op, "details")
                    logger.info(
                        f"[TRACKER-DB] Updated operation in DB: {operation_id[:8]} "
                        f"details={details}"
                    )
                    return True
                logger.warning(f"[TRACKER-DB] Update failed - operation not in DB: {operation_id}")
                return False
        except Exception as e:
            logger.error(f"[TRACKER-DB] Failed to update operation {operation_id}: {e}")
            return False

    def complete(
        self,
        operation_id: str,
        result: dict[str, Any] | None = None,
    ) -> Operation | None:
        """
        Mark operation as completed.

        Args:
            operation_id: Operation to complete
            result: Result data (will be merged with token/S3 data from details)

        Returns:
            Updated Operation or None if not found
        """
        with self._store_lock:
            op = self._operations.get(operation_id)
            if not op:
                # Fallback: complete directly in DB
                if self._persist_complete_db_only(operation_id, result):
                    logger.info(
                        f"[TRACKER] Completed operation in DB only: {operation_id[:8]} "
                        f"(not in memory)"
                    )
                else:
                    logger.warning(f"[TRACKER] Complete failed: operation {operation_id} not found")
                return None

            op.status = "completed"
            op.completed_at = now_utc()

            # This ensures data saved via update() is available in result for frontend
            merged_result = result.copy() if result else {}

            token_fields = [
                "total_input_tokens",
                "total_output_tokens",
                "total_cache_read_tokens",
                "total_cache_creation_tokens",
                "cost_usd",
                "models_used",
                "tools_used",
            ]
            for field_name in token_fields:
                if field_name not in merged_result and field_name in op.details:
                    merged_result[field_name] = op.details[field_name]

            s3_fields = ["s3_prompt_url", "s3_output_url"]
            for field_name in s3_fields:
                if field_name not in merged_result and field_name in op.details:
                    merged_result[field_name] = op.details[field_name]

            op.result = merged_result

            logger.info(
                f"[TRACKER] Completed {op.operation_type.value}: {operation_id} "
                f"(duration={op.duration_seconds:.1f}s)"
            )

            self._persist_complete(op)

            return op

    def _persist_complete_db_only(self, operation_id: str, result: dict[str, Any] | None) -> bool:
        """Complete operation directly in DB (fallback when not in memory)."""
        try:
            with self._db_session() as db:
                db_op = self._get_db_operation(db, operation_id)
                if db_op:
                    db_op.status = "completed"
                    db_op.completed_at = now_utc()
                    if db_op.started_at:
                        db_op.duration_seconds = (
                            db_op.completed_at - db_op.started_at
                        ).total_seconds()
                    db_op.result = result or {}
                    return True
                return False
        except Exception as e:
            logger.error(f"[TRACKER-DB] Failed to complete {operation_id}: {e}")
            return False

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
                # Fallback: fail directly in DB
                if self._persist_fail_db_only(operation_id, error):
                    logger.error(
                        f"[TRACKER] Failed operation in DB only: {operation_id[:8]} - {error}"
                    )
                else:
                    logger.warning(f"[TRACKER] Fail failed: operation {operation_id} not found")
                return None

            op.status = "failed"
            op.completed_at = now_utc()
            op.error = error

            logger.error(f"[TRACKER] Failed {op.operation_type.value}: {operation_id} - {error}")

            self._persist_fail(op)

            return op

    def _persist_fail_db_only(self, operation_id: str, error: str) -> bool:
        """Fail operation directly in DB (fallback when not in memory)."""
        try:
            with self._db_session() as db:
                db_op = self._get_db_operation(db, operation_id)
                if db_op:
                    db_op.status = "failed"
                    db_op.completed_at = now_utc()
                    if db_op.started_at:
                        db_op.duration_seconds = (
                            db_op.completed_at - db_op.started_at
                        ).total_seconds()
                    db_op.error = error
                    return True
                return False
        except Exception as e:
            logger.error(f"[TRACKER-DB] Failed to fail {operation_id}: {e}")
            return False

    def cancel(self, operation_id: str) -> Operation | None:
        """Mark operation as cancelled."""
        with self._store_lock:
            op = self._operations.get(operation_id)
            if not op:
                return None

            op.status = "cancelled"
            op.completed_at = now_utc()

            logger.info(f"[TRACKER] Cancelled {op.operation_type.value}: {operation_id}")

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

        Merges in-memory operations with DB operations (for server restart scenario).

        Args:
            op_type: Filter by operation type
            repo_id: Filter by repository ID

        Returns:
            List of active operations, sorted by creation time (newest first)
        """
        with self._store_lock:
            self._cleanup_expired()

            # Start with in-memory operations
            operations = [op for op in self._operations.values() if op.status == "in_progress"]
            seen_ids = {op.operation_id for op in operations}

            # Also load from DB (for server restart scenario)
            db_operations = self._load_active_from_db(op_type=op_type, repo_id=repo_id)
            for op in db_operations:
                if op.operation_id not in seen_ids:
                    operations.append(op)
                    # Also add to in-memory cache for future lookups
                    self._operations[op.operation_id] = op

            if op_type:
                operations = [op for op in operations if op.operation_type == op_type]

            if repo_id:
                operations = [op for op in operations if op.repository_id == repo_id]

            # Sort with fallback for None created_at
            operations.sort(key=lambda x: x.created_at or now_utc(), reverse=True)

            return operations

    def _load_active_from_db(
        self,
        op_type: OperationType | None = None,
        repo_id: str | None = None,
    ) -> list[Operation]:
        """Load active operations from database (fallback for server restart)."""
        try:
            with self._db_session() as db:
                from turbowrap.db.models.operation import Operation as OperationRecord

                query = db.query(OperationRecord).filter(OperationRecord.status == "in_progress")

                if op_type:
                    query = query.filter(OperationRecord.operation_type == op_type.value)
                if repo_id:
                    query = query.filter(OperationRecord.repository_id == repo_id)

                db_records = query.all()
                operations = []
                for rec in db_records:
                    op = Operation(
                        operation_id=rec.id,
                        operation_type=OperationType(rec.operation_type),
                        repository_id=rec.repository_id,
                        repository_name=rec.repository_name,
                        branch_name=rec.branch_name,
                        user_name=rec.user_name,
                        status=rec.status,
                        details=rec.details or {},
                        result=rec.result,
                        error=rec.error,
                        started_at=rec.started_at,
                        completed_at=rec.completed_at,
                        # duration_seconds is a computed property, not a field
                        created_at=rec.created_at or rec.started_at,
                        parent_session_id=rec.parent_session_id,
                    )
                    operations.append(op)
                return operations
        except Exception as e:
            logger.error(f"[TRACKER-DB] Failed to load active operations: {e}")
            return []

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

    # Pub/Sub Methods for SSE Streaming

    def subscribe(self, operation_id: str) -> Any:
        """
        Subscribe to operation events for SSE streaming.

        Args:
            operation_id: Operation to subscribe to

        Returns:
            asyncio.Queue to receive events from
        """
        import asyncio

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        with self._store_lock:
            if operation_id not in self._subscribers:
                self._subscribers[operation_id] = []
            self._subscribers[operation_id].append(queue)
            logger.debug(
                f"[TRACKER] Subscribed to {operation_id[:8]}, "
                f"total subscribers: {len(self._subscribers[operation_id])}"
            )
        return queue

    def unsubscribe(self, operation_id: str, queue: Any) -> None:
        """
        Unsubscribe from operation events.

        Args:
            operation_id: Operation to unsubscribe from
            queue: The queue that was returned from subscribe()
        """
        with self._store_lock:
            if operation_id in self._subscribers:
                try:
                    self._subscribers[operation_id].remove(queue)
                    logger.debug(
                        f"[TRACKER] Unsubscribed from {operation_id[:8]}, "
                        f"remaining: {len(self._subscribers[operation_id])}"
                    )
                    if not self._subscribers[operation_id]:
                        del self._subscribers[operation_id]
                except ValueError:
                    pass  # Queue not in list

    async def publish_event(
        self,
        operation_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> int:
        """
        Publish event to all subscribers of an operation.

        Args:
            operation_id: Operation to publish to
            event_type: Event type (e.g., "chunk", "status", "complete")
            data: Event data

        Returns:
            Number of subscribers that received the event
        """
        with self._store_lock:
            subscribers = self._subscribers.get(operation_id, [])
            if not subscribers:
                return 0

            event = {"type": event_type, "data": data}
            count = 0
            for queue in subscribers:
                try:
                    await queue.put(event)
                    count += 1
                except Exception as e:
                    logger.warning(f"[TRACKER] Failed to publish to subscriber: {e}")

            return count

    async def signal_completion(self, operation_id: str) -> None:
        """
        Signal to all subscribers that the operation has completed.

        Sends None to all subscriber queues to indicate end of stream.
        """
        with self._store_lock:
            subscribers = self._subscribers.get(operation_id, [])
            for queue in subscribers:
                try:
                    await queue.put(None)  # None signals completion
                except Exception:
                    pass

    def has_subscribers(self, operation_id: str) -> bool:
        """Check if an operation has any subscribers."""
        with self._store_lock:
            return bool(self._subscribers.get(operation_id))

    def subscriber_count(self, operation_id: str) -> int:
        """Get number of subscribers for an operation."""
        with self._store_lock:
            return len(self._subscribers.get(operation_id, []))

    # ─────────────────────────────────────────────────────────────────────────
    # Database Persistence Methods
    # ─────────────────────────────────────────────────────────────────────────

    @contextmanager
    def _db_session(self) -> Generator[Session, None, None]:
        """Context manager for database operations with auto-commit/rollback."""
        from turbowrap.db.session import get_session_local

        SessionLocal = get_session_local()
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _get_db_operation(self, db: Session, operation_id: str) -> Any:
        """Get DBOperation by ID. Returns None if not found."""
        from turbowrap.db.models import Operation as DBOperation

        return db.query(DBOperation).filter(DBOperation.id == operation_id).first()

    def _persist_register(self, operation: Operation) -> None:
        """Persist a new operation to database."""
        try:
            from turbowrap.db.models import Operation as DBOperation

            with self._db_session() as db:
                db_op = DBOperation(
                    id=operation.operation_id,
                    operation_type=operation.operation_type.value,
                    status=operation.status,
                    repository_id=operation.repository_id,
                    repository_name=operation.repository_name,
                    branch_name=operation.branch_name,
                    user_name=operation.user_name,
                    parent_session_id=operation.parent_session_id,
                    details=operation.details,
                    started_at=operation.created_at,
                )
                db.add(db_op)
            logger.info(f"[TRACKER-DB] Persisted operation: {operation.operation_id}")
        except Exception as e:
            logger.error(
                f"[TRACKER-DB] Failed to persist operation {operation.operation_id}: "
                f"{e}\n{traceback.format_exc()}"
            )

    def _persist_update(self, operation_id: str, updates: dict[str, Any]) -> None:
        """Update operation in database."""
        try:
            with self._db_session() as db:
                db_op = self._get_db_operation(db, operation_id)
                if db_op:
                    for key, value in updates.items():
                        if hasattr(db_op, key):
                            setattr(db_op, key, value)
                    logger.debug(f"[TRACKER-DB] Updated operation: {operation_id[:8]}")
                else:
                    logger.warning(
                        f"[TRACKER-DB] Update failed - operation not found in DB: {operation_id}"
                    )
        except Exception as e:
            logger.error(
                f"[TRACKER-DB] Failed to update operation {operation_id}: "
                f"{e}\n{traceback.format_exc()}"
            )

    def _persist_complete(self, operation: Operation) -> None:
        """Mark operation as completed in database."""
        try:
            with self._db_session() as db:
                db_op = self._get_db_operation(db, operation.operation_id)
                if db_op:
                    db_op.status = "completed"  # type: ignore[assignment]
                    db_op.completed_at = operation.completed_at  # type: ignore[assignment]
                    db_op.duration_seconds = operation.duration_seconds  # type: ignore[assignment]
                    db_op.result = operation.result  # type: ignore[assignment]
                    logger.info(f"[TRACKER-DB] Completed operation in DB: {operation.operation_id}")
                else:
                    logger.error(
                        f"[TRACKER-DB] Complete failed - operation not found: {operation.operation_id}"
                    )
        except Exception as e:
            logger.error(
                f"[TRACKER-DB] Failed to complete operation {operation.operation_id}: "
                f"{e}\n{traceback.format_exc()}"
            )

    def _persist_fail(self, operation: Operation) -> None:
        """Mark operation as failed in database."""
        try:
            with self._db_session() as db:
                db_op = self._get_db_operation(db, operation.operation_id)
                if db_op:
                    db_op.status = "failed"  # type: ignore[assignment]
                    db_op.completed_at = operation.completed_at  # type: ignore[assignment]
                    db_op.duration_seconds = operation.duration_seconds  # type: ignore[assignment]
                    db_op.error = operation.error  # type: ignore[assignment]
                    logger.info(f"[TRACKER-DB] Failed operation in DB: {operation.operation_id}")
                else:
                    logger.error(
                        f"[TRACKER-DB] Fail update failed - operation not found: {operation.operation_id}"
                    )
        except Exception as e:
            logger.error(
                f"[TRACKER-DB] Failed to mark operation {operation.operation_id} as failed: "
                f"{e}\n{traceback.format_exc()}"
            )

    def _persist_cancel(self, operation: Operation) -> None:
        """Mark operation as cancelled in database."""
        try:
            with self._db_session() as db:
                db_op = self._get_db_operation(db, operation.operation_id)
                if db_op:
                    db_op.status = "cancelled"  # type: ignore[assignment]
                    db_op.completed_at = operation.completed_at  # type: ignore[assignment]
                    db_op.duration_seconds = operation.duration_seconds  # type: ignore[assignment]
                    logger.debug(f"[TRACKER-DB] Cancelled operation: {operation.operation_id[:8]}")
        except Exception as e:
            logger.warning(f"[TRACKER-DB] Failed to cancel operation in DB: {e}")


def get_tracker() -> OperationTracker:
    """Get the global OperationTracker instance."""
    return OperationTracker()
