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

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..services.operation_tracker import OperationType, get_tracker

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
    details: dict[str, Any] = {}
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

    response_ops = [
        OperationResponse(**op.to_dict())
        for op in operations
    ]

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


@router.delete("/{operation_id}")
async def cancel_operation(operation_id: str) -> dict[str, str]:
    """
    Cancel an operation.

    Note: This only marks the operation as cancelled in the tracker.
    The actual operation may continue running (e.g., a git push).
    For operations that support true cancellation (like fix sessions),
    use the dedicated cancel endpoint.
    """
    tracker = get_tracker()
    op = tracker.cancel(operation_id)

    if not op:
        return {"status": "not_found", "message": f"Operation {operation_id} not found"}

    return {
        "status": "cancelled",
        "message": f"Operation {operation_id} marked as cancelled",
        "type": op.operation_type.value,
    }
