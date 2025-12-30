"""
Unified Operations API - Single endpoint for all active operations.

This provides a unified view of everything happening across the system:
- Fix sessions
- Code reviews
- Git operations (merge, push, pull)
- Clone/sync operations
- Deployments

The frontend polls this single endpoint to show the Live Tasks banner.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..services.operation_tracker import OperationType, get_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operations", tags=["operations"])


class OperationResponse(BaseModel):
    """Response model for a single operation."""

    operation_id: str
    type: str
    label: str
    color: str
    status: str
    repository_id: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    user_name: str | None = None
    parent_session_id: str | None = None
    details: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    is_stale: bool = False
    error: str | None = None


class ActiveOperationsResponse(BaseModel):
    """Response for active operations list."""

    operations: list[OperationResponse]
    count: int
    has_stale: bool


@router.get("/active", response_model=ActiveOperationsResponse)
async def list_active_operations(
    type: OperationType | None = Query(None, description="Filter by operation type"),
    repo_id: str | None = Query(None, description="Filter by repository ID"),
) -> ActiveOperationsResponse:
    """
    Get all active operations.

    Returns a unified list of all in-progress operations across the system.
    This is the single endpoint polled by the Live Tasks banner and page.

    Supports filtering by:
    - type: Operation type (fix, review, git_merge, etc.)
    - repo_id: Repository ID
    """
    tracker = get_tracker()
    operations = tracker.get_active(op_type=type, repo_id=repo_id)

    # Debug logging (polling happens every 5s, keep at DEBUG to avoid noise)
    logger.debug(f"[OPERATIONS] Active operations: {len(operations)}")
    for op in operations:
        logger.debug(f"  - {op.operation_id[:8]}: {op.operation_type.value} ({op.status})")

    response_ops = [OperationResponse(**op.to_dict()) for op in operations]

    return ActiveOperationsResponse(
        operations=response_ops,
        count=len(response_ops),
        has_stale=any(op.is_stale for op in response_ops),
    )


@router.get("/count")
async def count_active_operations(
    type: OperationType | None = Query(None, description="Filter by operation type"),
) -> dict[str, int]:
    """
    Quick count of active operations.

    Lightweight endpoint for badge counts.
    """
    tracker = get_tracker()
    count = tracker.count_active(type)
    return {"count": count}


@router.get("/types")
async def list_operation_types() -> dict[str, list[dict[str, str]]]:
    """
    List all available operation types with their labels and colors.

    Useful for frontend to build dynamic UI.
    """
    from ..services.operation_tracker import OPERATION_COLORS, OPERATION_LABELS

    types = [
        {
            "type": op_type.value,
            "label": OPERATION_LABELS.get(op_type, op_type.value),
            "color": OPERATION_COLORS.get(op_type, "gray"),
        }
        for op_type in OperationType
    ]

    return {"types": types}


class OperationHistoryResponse(BaseModel):
    """Response for operation history."""

    operations: list[OperationResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


@router.get("/history", response_model=OperationHistoryResponse)
async def list_operation_history(
    status: str | None = Query(None, description="Filter by status (completed, failed, cancelled)"),
    type: str | None = Query(None, description="Filter by operation type"),
    repo_id: str | None = Query(None, description="Filter by repository ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
) -> OperationHistoryResponse:
    """
    Get operation history from database.

    Returns paginated list of completed, failed, or cancelled operations.
    For live/in_progress operations, use /active endpoint.
    """
    from sqlalchemy import desc

    from ...db.models import Operation as DBOperation
    from ...db.session import get_session_local

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        query = db.query(DBOperation)

        # Apply filters
        if status:
            query = query.filter(DBOperation.status == status)
        else:
            # By default, exclude in_progress (those are in /active)
            query = query.filter(DBOperation.status != "in_progress")

        if type:
            query = query.filter(DBOperation.operation_type == type)

        if repo_id:
            query = query.filter(DBOperation.repository_id == repo_id)

        # Get total count
        total = query.count()

        # Paginate and order by started_at descending
        operations = (
            query.order_by(desc(DBOperation.started_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        response_ops = [OperationResponse(**op.to_dict()) for op in operations]

        return OperationHistoryResponse(
            operations=response_ops,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )

    finally:
        db.close()


@router.get("/stats")
async def get_operation_stats(
    days: int = Query(7, ge=1, le=90, description="Number of days to include"),
) -> dict[str, Any]:
    """
    Get operation statistics for the specified time period.

    Returns counts by status, type, and daily breakdown.
    """
    from datetime import timedelta

    from sqlalchemy import func

    from ...db.models import Operation as DBOperation
    from ...db.session import get_session_local

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        since = datetime.utcnow() - timedelta(days=days)

        # Count by status
        status_counts = dict(
            db.query(DBOperation.status, func.count(DBOperation.id))
            .filter(DBOperation.started_at >= since)
            .group_by(DBOperation.status)
            .all()
        )

        # Count by type
        type_counts = dict(
            db.query(DBOperation.operation_type, func.count(DBOperation.id))
            .filter(DBOperation.started_at >= since)
            .group_by(DBOperation.operation_type)
            .all()
        )

        # Average duration by type (completed only)
        avg_durations = dict(
            db.query(DBOperation.operation_type, func.avg(DBOperation.duration_seconds))
            .filter(
                DBOperation.started_at >= since,
                DBOperation.status == "completed",
                DBOperation.duration_seconds.isnot(None),
            )
            .group_by(DBOperation.operation_type)
            .all()
        )

        # Total operations
        total = (
            db.query(func.count(DBOperation.id)).filter(DBOperation.started_at >= since).scalar()
        )

        return {
            "period_days": days,
            "total_operations": total or 0,
            "by_status": status_counts,
            "by_type": type_counts,
            "avg_duration_seconds": {
                k: round(v, 2) if v else None for k, v in avg_durations.items()
            },
        }

    finally:
        db.close()


@router.post("/{operation_id}/complete")
async def complete_operation(operation_id: str) -> dict[str, str]:
    """
    Manually mark an operation as completed.

    Use this when an operation is stuck in 'in_progress' but has actually finished.
    This updates the tracker AND resets any stuck issues if it's a fix operation.
    """
    from sqlalchemy.orm import Session

    from ...db.models import Issue, IssueStatus
    from ...db.session import get_session_local
    from ..services.operation_tracker import OperationType

    tracker = get_tracker()

    # Get operation details before completing
    op = next((o for o in tracker.get_active() if o.operation_id == operation_id), None)

    if not op:
        return {"status": "not_found", "message": f"Operation {operation_id} not found"}

    # If it's a fix operation, reset any stuck in_progress issues
    reset_count = 0
    if op.operation_type == OperationType.FIX:
        SessionLocal = get_session_local()
        db: Session = SessionLocal()
        try:
            repo_id = op.repository_id

            if repo_id:
                # Find and reset stuck issues
                stuck_issues = (
                    db.query(Issue)
                    .filter(
                        Issue.repository_id == repo_id,
                        Issue.status == IssueStatus.IN_PROGRESS.value,
                    )
                    .all()
                )

                for issue in stuck_issues:
                    issue.status = IssueStatus.OPEN.value  # type: ignore[assignment]
                    issue.resolution_note = "Manually reset from stuck in_progress"  # type: ignore[assignment]
                    reset_count += 1

                if reset_count > 0:
                    db.commit()
                    logger.info(f"Reset {reset_count} stuck issues for operation {operation_id}")
        except Exception as e:
            logger.error(f"Error resetting issues for operation {operation_id}: {e}")
        finally:
            db.close()

    # Mark as completed in tracker
    tracker.complete(
        operation_id,
        result={"manually_completed": True, "issues_reset": reset_count},
    )

    return {
        "status": "completed",
        "message": f"Operation {operation_id} marked as completed, reset {reset_count} issues",
        "type": op.operation_type.value,
        "issues_reset": str(reset_count),
    }


@router.delete("/{operation_id}")
async def cancel_operation(operation_id: str) -> dict[str, str]:
    """
    Cancel an operation.

    Note: This only marks the operation as cancelled in the tracker.
    The actual operation may continue running (e.g., a git push).
    For operations that support true cancellation (like fix sessions),
    use the dedicated cancel endpoint.
    """
    logger.info(f"[OPERATIONS] Cancel request for operation: {operation_id}")

    try:
        tracker = get_tracker()
        op = tracker.cancel(operation_id)

        if not op:
            logger.warning(f"[OPERATIONS] Operation not found: {operation_id}")
            raise HTTPException(
                status_code=404,
                detail=f"Operation {operation_id} not found in tracker",
            )

        logger.info(f"[OPERATIONS] Cancelled operation: {operation_id}")
        return {
            "status": "cancelled",
            "message": f"Operation {operation_id} marked as cancelled",
            "type": op.operation_type.value,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[OPERATIONS] Error cancelling operation {operation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/issues/reset-stuck")
async def reset_stuck_issues(
    repository_id: str | None = Query(None, description="Filter by repository ID"),
) -> dict[str, Any]:
    """
    Reset issues stuck in 'in_progress' status to 'open'.

    Use this to cleanup after crashed or interrupted fix sessions.

    Args:
        repository_id: Optional filter to reset only issues from a specific repository.
                      If not provided, resets ALL stuck issues (use with caution).
    """
    from ...db.models import Issue, IssueStatus
    from ...db.session import get_session_local

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        query = db.query(Issue).filter(Issue.status == IssueStatus.IN_PROGRESS.value)

        # Filter by repository if provided
        if repository_id:
            query = query.filter(Issue.repository_id == repository_id)

        stuck_issues = query.all()

        reset_count = 0
        for issue in stuck_issues:
            issue.status = IssueStatus.OPEN.value  # type: ignore[assignment]
            issue.resolution_note = "Reset from stuck in_progress"  # type: ignore[assignment]
            reset_count += 1

        if reset_count > 0:
            db.commit()

        scope_msg = f" for repository {repository_id}" if repository_id else " (all repositories)"
        return {
            "status": "success",
            "message": f"Reset {reset_count} stuck issues{scope_msg}",
            "count": reset_count,
            "repository_id": repository_id,
        }

    except Exception as e:
        logger.error(f"Error resetting stuck issues: {e}")
        return {
            "status": "error",
            "message": str(e),
            "count": 0,
        }
    finally:
        db.close()


@router.get("/{operation_id}/prompt")
async def get_operation_prompt(operation_id: str) -> dict[str, Any]:
    """
    Get the prompt content for an operation.

    Fetches from S3 if s3_prompt_url is available, otherwise returns prompt_preview.
    """
    import traceback

    try:
        tracker = get_tracker()
        s3_url = None
        preview = None

        # Check active operations
        op = next((o for o in tracker.get_active() if o.operation_id == operation_id), None)

        # If not active, check history
        if not op:
            from ...db.models import Operation as DBOperation
            from ...db.session import get_session_local

            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                # Note: DB uses 'id', API uses 'operation_id'
                db_op = db.query(DBOperation).filter(DBOperation.id == operation_id).first()
                if db_op and db_op.details:
                    details = db_op.details if isinstance(db_op.details, dict) else {}
                    s3_url = details.get("s3_prompt_url")
                    preview = details.get("prompt_preview")
                else:
                    return {"status": "not_found", "content": f"Operation {operation_id} not found"}
            finally:
                db.close()
        else:
            details = op.details or {}
            s3_url = details.get("s3_prompt_url")
            preview = details.get("prompt_preview")
            logger.debug(
                f"[PROMPT] Operation {operation_id[:8]} details: s3_url={s3_url}, "
                f"preview_len={len(preview) if preview else 0}"
            )

        # Handle S3 URLs (both legacy s3:// and pre-signed HTTPS)
        if s3_url:
            try:
                import httpx

                # Pre-signed HTTPS URL - fetch directly
                if s3_url.startswith("https://"):
                    logger.info("[PROMPT] Fetching from pre-signed URL")
                    async with httpx.AsyncClient() as client:
                        response = await client.get(s3_url, timeout=30)
                        response.raise_for_status()
                        content = response.text
                    logger.info(
                        f"[PROMPT] Pre-signed URL fetch successful, content_len={len(content)}"
                    )
                    return {
                        "status": "ok",
                        "source": "s3_presigned",
                        "s3_url": s3_url,
                        "content": content,
                    }

                # Legacy s3:// URL - fetch via boto3
                if s3_url.startswith("s3://"):
                    from ...utils.aws_clients import get_s3_client

                    parts = s3_url.replace("s3://", "").split("/", 1)
                    bucket = parts[0]
                    key = parts[1] if len(parts) > 1 else ""

                    logger.info(f"[PROMPT] Fetching from S3: bucket={bucket}, key={key}")
                    s3 = get_s3_client()
                    response = s3.get_object(Bucket=bucket, Key=key)
                    content = response["Body"].read().decode("utf-8")
                    logger.info(f"[PROMPT] S3 fetch successful, content_len={len(content)}")

                    return {
                        "status": "ok",
                        "source": "s3",
                        "s3_url": s3_url,
                        "content": content,
                    }

            except Exception as e:
                logger.warning(f"Failed to fetch prompt from S3 ({s3_url}): {e}")
                return {
                    "status": "error",
                    "source": "s3",
                    "s3_url": s3_url,
                    "error": str(e),
                    "content": preview or f"S3 fetch failed: {e}",
                }

        # Fallback to preview
        if preview:
            return {
                "status": "ok",
                "source": "preview",
                "content": preview,
            }

        # No prompt available
        return {
            "status": "no_prompt",
            "source": "none",
            "content": f"No prompt available for operation {operation_id[:8]}. S3 URL not set.",
        }

    except Exception as e:
        logger.error(f"[PROMPT] Unhandled error for {operation_id}: {e}\n{traceback.format_exc()}")
        return {
            "status": "error",
            "source": "exception",
            "error": str(e),
            "content": f"Error: {e}",
        }


@router.get("/{operation_id}/output")
async def get_operation_output(operation_id: str) -> dict[str, Any]:
    """
    Get the output content for an operation.

    Fetches from S3 if s3_output_url is available.
    """

    tracker = get_tracker()

    # Check active operations
    op = next((o for o in tracker.get_active() if o.operation_id == operation_id), None)

    # Build details from operation or DB
    details: dict[str, Any] = {}
    result: dict[str, Any] = {}

    if not op:
        from ...db.models import Operation as DBOperation
        from ...db.session import get_session_local

        SessionLocal = get_session_local()
        db = SessionLocal()
        try:
            # Note: DB uses 'id', API uses 'operation_id'
            db_op = db.query(DBOperation).filter(DBOperation.id == operation_id).first()
            if db_op:
                details = db_op.details if isinstance(db_op.details, dict) else {}
                result = db_op.result if isinstance(db_op.result, dict) else {}
            else:
                return {"status": "not_found", "content": None}
        finally:
            db.close()
    else:
        details = op.details or {}
        result = op.result or {}

    # Try s3_output_url from result first, then details
    s3_url = result.get("s3_output_url") or details.get("s3_output_url")

    if s3_url:
        try:
            import httpx

            # Pre-signed HTTPS URL - fetch directly
            if s3_url.startswith("https://"):
                async with httpx.AsyncClient() as client:
                    response = await client.get(s3_url, timeout=30)
                    response.raise_for_status()
                    content = response.text
                return {
                    "status": "ok",
                    "source": "s3_presigned",
                    "s3_url": s3_url,
                    "content": content,
                }

            # Legacy s3:// URL - fetch via boto3
            if s3_url.startswith("s3://"):
                from ...utils.aws_clients import get_s3_client

                parts = s3_url.replace("s3://", "").split("/", 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ""

                s3 = get_s3_client()
                response = s3.get_object(Bucket=bucket, Key=key)
                content = response["Body"].read().decode("utf-8")

                return {
                    "status": "ok",
                    "source": "s3",
                    "s3_url": s3_url,
                    "content": content,
                }

        except Exception as e:
            logger.warning(f"Failed to fetch output from S3: {e}")

    return {
        "status": "pending",
        "source": "none",
        "content": "Output not yet available",
    }


@router.get("/{operation_id}/stream")
async def stream_operation_output(operation_id: str) -> EventSourceResponse:
    """
    Stream live output for an operation via SSE.

    This endpoint allows the frontend to subscribe to real-time output
    from an operation (fix, review, etc.) as it runs.

    Events:
    - connected: Connection established
    - chunk: Output chunk {content: "..."}
    - status: Status update {status: "running"|"complete"|"failed"}
    - complete: Operation finished {success: bool}
    - thinking: Extended thinking content (Claude)
    - tool_call: Tool invocation info
    - ping: Keepalive (every 30s)
    """
    tracker = get_tracker()

    async def generate() -> AsyncGenerator[dict[str, str], None]:
        # Find operation in tracker
        op = next((o for o in tracker.get_active() if o.operation_id == operation_id), None)

        # Also check for recently completed operations
        if not op:
            op = tracker.get(operation_id)

        if not op:
            yield {
                "event": "error",
                "data": json.dumps({"error": "Operation not found", "operation_id": operation_id}),
            }
            return

        # Send connected event with operation info
        yield {
            "event": "connected",
            "data": json.dumps(
                {
                    "operation_id": operation_id,
                    "type": op.operation_type.value,
                    "status": op.status,
                    "repository_name": op.repository_name,
                }
            ),
        }

        # If operation already completed, send final status and return
        if op.status in ("completed", "failed", "cancelled"):
            yield {
                "event": "complete",
                "data": json.dumps(
                    {
                        "status": op.status,
                        "result": op.result,
                        "error": op.error,
                    }
                ),
            }
            return

        # Subscribe to operation events
        queue = tracker.subscribe(operation_id)

        try:
            while True:
                try:
                    # Wait for event with timeout for keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=30)

                    if event is None:
                        # None signals operation completion
                        # Get final status
                        final_op = tracker.get(operation_id)
                        yield {
                            "event": "complete",
                            "data": json.dumps(
                                {
                                    "status": final_op.status if final_op else "unknown",
                                    "result": final_op.result if final_op else None,
                                    "error": final_op.error if final_op else None,
                                }
                            ),
                        }
                        break

                    # Forward event to client
                    yield {
                        "event": event["type"],
                        "data": json.dumps(event["data"]),
                    }

                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    yield {"event": "ping", "data": "{}"}

                    # Check if operation is still active
                    current_op = tracker.get(operation_id)
                    if current_op and current_op.status != "in_progress":
                        yield {
                            "event": "complete",
                            "data": json.dumps(
                                {
                                    "status": current_op.status,
                                    "result": current_op.result,
                                    "error": current_op.error,
                                }
                            ),
                        }
                        break

        except asyncio.CancelledError:
            logger.debug(f"[STREAM] Client disconnected from {operation_id[:8]}")
        finally:
            tracker.unsubscribe(operation_id, queue)
            logger.debug(f"[STREAM] Cleaned up subscription for {operation_id[:8]}")

    return EventSourceResponse(generate(), ping=15)
