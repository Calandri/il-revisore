"""Chat schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChatRole = Literal["user", "assistant", "system"]
SessionStatus = Literal["active", "archived"]


class ChatSessionCreate(BaseModel):
    """Request to create a chat session."""

    repository_id: str | None = Field(
        default=None,
        description="Associated repository UUID",
    )
    task_id: str | None = Field(
        default=None,
        description="Associated task UUID",
    )
    title: str | None = Field(
        default=None,
        max_length=255,
        description="Session title",
    )


class ChatSessionResponse(BaseModel):
    """Chat session response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Session UUID")
    repository_id: str | None = Field(default=None, description="Associated repository")
    task_id: str | None = Field(default=None, description="Associated task")
    title: str | None = Field(default=None, description="Session title")
    status: SessionStatus = Field(..., description="Session status")
    message_count: int = Field(default=0, ge=0, description="Number of messages")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class ChatMessageCreate(BaseModel):
    """Request to send a chat message."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=50000,
        description="Message content",
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate and clean message content."""
        return v.strip()


class ChatMessageResponse(BaseModel):
    """Chat message response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Message UUID")
    session_id: str = Field(..., description="Parent session UUID")
    role: ChatRole = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata (tokens, agent type, etc.)",
    )
    created_at: datetime = Field(..., description="Creation timestamp")


class WebSocketMessage(BaseModel):
    """WebSocket message format."""

    type: Literal["message", "ping", "pong", "error", "generating", "message_received"] = Field(
        ..., description="Message type"
    )
    content: str | None = Field(default=None, description="Message content")
    role: ChatRole | None = Field(default=None, description="Message role")
    message_id: str | None = Field(default=None, description="Message ID")
    error: str | None = Field(default=None, description="Error message")
