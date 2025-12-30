"""Pydantic schemas for TurboWrap error responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error information."""

    message: str = Field(..., description="Human-readable error message")
    code: str | None = Field(None, description="Machine-readable error code")
    type: str = Field("Error", description="Exception type name")


class TurboErrorResponse(BaseModel):
    """Standardized error response format for TurboWrap.

    This schema ensures consistent error responses that the frontend
    TurboWrapError handler can parse and display appropriately.
    """

    turbo_error: bool = Field(
        True,
        description="Flag indicating this is a TurboWrap error response",
    )
    command: str | None = Field(
        None,
        description="Name of the operation that failed",
    )
    severity: str = Field(
        "error",
        description="Error severity: 'warning', 'error', or 'critical'",
    )
    error: ErrorDetail = Field(..., description="Error details")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context for debugging",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the error occurred",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "turbo_error": True,
                "command": "Fetch User",
                "severity": "error",
                "error": {
                    "message": "User not found",
                    "code": "USER_404",
                    "type": "NotFoundError",
                },
                "context": {"user_id": "123"},
                "timestamp": "2024-12-30T12:00:00Z",
            }
        }
    }
