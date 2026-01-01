"""Adapters for turbowrap-llm package integration.

Provides adapters that wrap TurboWrap's internal services to match
the Protocol interfaces expected by the turbowrap-llm package.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from turbowrap.api.services.operation_tracker import OperationTracker, OperationType

logger = logging.getLogger(__name__)


class TurboWrapTrackerAdapter:
    """Adapter that wraps TurboWrap's OperationTracker for turbowrap-llm.

    Converts the package's progress() calls to TurboWrap's register/update/complete/fail API.

    Usage:
        from turbowrap.api.services.operation_tracker import get_tracker, OperationType

        tracker = get_tracker()
        adapter = TurboWrapTrackerAdapter(
            tracker=tracker,
            operation_type=OperationType.FIX_CLARIFICATION,
            repo_id="abc-123",
            repo_name="my-repo",
            initial_details={
                "issue_codes": ["BE-001", "FE-003"],
                "issue_ids": ["uuid1", "uuid2"],
            },
        )

        cli = ClaudeCLI(tracker=adapter, ...)
    """

    def __init__(
        self,
        tracker: OperationTracker,
        operation_type: OperationType,
        *,
        repo_id: str | None = None,
        repo_name: str | None = None,
        branch: str | None = None,
        user: str | None = None,
        parent_session_id: str | None = None,
        initial_details: dict[str, Any] | None = None,
    ):
        """Initialize the adapter.

        Args:
            tracker: TurboWrap's OperationTracker instance.
            operation_type: Type of operation being tracked.
            repo_id: Repository ID.
            repo_name: Repository name.
            branch: Branch name.
            user: User who initiated the operation.
            parent_session_id: Parent session ID for hierarchical grouping.
            initial_details: Initial details to include when registering
                (e.g., issue_codes, issue_ids for frontend display).
        """
        self._tracker = tracker
        self._operation_type = operation_type
        self._repo_id = repo_id
        self._repo_name = repo_name
        self._branch = branch
        self._user = user
        self._parent_session_id = parent_session_id
        self._initial_details = initial_details or {}
        self._registered_ops: set[str] = set()

    async def progress(
        self,
        operation_id: str,
        status: str,
        *,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
        error: str | None = None,
        publish_delay_ms: int = 0,
    ) -> None:
        """Track operation progress (idempotent).

        Maps turbowrap-llm status values to TurboWrap tracker methods:
        - "running": register() or update()
        - "streaming": update() with details
        - "completed": complete()
        - "failed": fail()

        Args:
            operation_id: Unique operation identifier.
            status: Current status (running, streaming, completed, failed).
            session_id: CLI session ID.
            details: Additional details (tokens, cost, duration, etc.).
            error: Error message if status is "failed".
            publish_delay_ms: SSE publish delay (passed to tracker).
        """
        merged_details = details or {}
        if session_id:
            merged_details["session_id"] = session_id

        if status == "running":
            if operation_id not in self._registered_ops:
                # First time seeing this operation - register it
                # Include initial_details (issue_codes, issue_ids, etc.)
                register_details = {**self._initial_details, **merged_details}
                self._tracker.register(
                    op_type=self._operation_type,
                    operation_id=operation_id,
                    repo_id=self._repo_id,
                    repo_name=self._repo_name,
                    branch=self._branch,
                    user=self._user,
                    parent_session_id=self._parent_session_id,
                    details=register_details,
                )
                self._registered_ops.add(operation_id)
            else:
                # Already registered, just update
                self._tracker.update(operation_id, details=merged_details)

        elif status == "streaming":
            # Update with streaming details
            self._tracker.update(operation_id, details=merged_details)

        elif status == "completed":
            self._tracker.complete(operation_id, result=merged_details)
            self._registered_ops.discard(operation_id)

        elif status == "failed":
            self._tracker.fail(operation_id, error=error or "Unknown error")
            self._registered_ops.discard(operation_id)

        else:
            logger.warning(f"[LLM-ADAPTER] Unknown status: {status}")

        # Publish SSE event if requested
        if publish_delay_ms >= 0 and self._tracker.has_subscribers(operation_id):
            await self._tracker.publish_event(
                operation_id,
                event_type="progress",
                data={"status": status, "details": merged_details, "error": error},
            )
