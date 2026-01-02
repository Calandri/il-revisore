"""CLI Chat API Schemas.

Pydantic models for CLI-based chat API endpoints.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Type aliases
CLITypeEnum = Literal["claude", "gemini"]
SessionStatusEnum = Literal[
    "idle", "starting", "running", "streaming", "stopping", "error", "completed"
]
MessageRoleEnum = Literal["user", "assistant", "system"]
StreamEventTypeEnum = Literal["start", "chunk", "thinking", "done", "error", "status"]


# ============================================================================
# Session Schemas
# ============================================================================


class CLISessionCreate(BaseModel):
    """Request to create a CLI chat session."""

    cli_type: CLITypeEnum = Field(
        ...,
        description="CLI type: 'claude' or 'gemini'",
    )
    repository_id: str | None = Field(
        default=None,
        description="Associated repository UUID",
    )
    display_name: str | None = Field(
        default=None,
        max_length=100,
        description="Custom display name for the session",
    )
    icon: str = Field(
        default="chat",
        max_length=50,
        description="Icon identifier",
    )
    color: str = Field(
        default="#6366f1",
        max_length=20,
        description="Hex color for icon",
    )
    # Mockup context
    mockup_project_id: str | None = Field(
        default=None,
        description="Mockup project UUID (for mockup generation)",
    )
    mockup_id: str | None = Field(
        default=None,
        description="Mockup UUID (for viewing/editing a specific mockup)",
    )


class CLISessionSettings(BaseModel):
    """Settings for a CLI chat session."""

    model: str | None = Field(
        default=None,
        description="Model to use (e.g., 'claude-opus-4-5-20251101')",
    )
    agent_name: str | None = Field(
        default=None,
        description="Agent name from /agents/ directory",
    )

    # Claude-specific
    thinking_enabled: bool = Field(
        default=False,
        description="Enable extended thinking (Claude only)",
    )
    thinking_budget: int = Field(
        default=8000,
        ge=1000,
        le=50000,
        description="Extended thinking token budget",
    )

    # Gemini-specific
    reasoning_enabled: bool = Field(
        default=False,
        description="Enable deep reasoning (Gemini only)",
    )

    # MCP
    mcp_servers: list[str] | None = Field(
        default=None,
        description="List of active MCP server names",
    )


class CLISessionResponse(BaseModel):
    """CLI chat session response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Session UUID")
    cli_type: CLITypeEnum = Field(..., description="CLI type")
    repository_id: str | None = Field(default=None, description="Associated repository")
    current_branch: str | None = Field(default=None, description="Current branch in repository")
    status: SessionStatusEnum = Field(..., description="Session status")

    # Mockup context
    mockup_project_id: str | None = Field(default=None, description="Mockup project UUID")
    mockup_id: str | None = Field(default=None, description="Mockup UUID being viewed/edited")

    # Configuration
    model: str | None = Field(default=None, description="Model in use")
    agent_name: str | None = Field(default=None, description="Agent in use")
    thinking_enabled: bool = Field(default=False, description="Extended thinking enabled")
    thinking_budget: int = Field(default=8000, description="Thinking token budget")
    reasoning_enabled: bool = Field(default=False, description="Deep reasoning enabled")
    mcp_servers: list[str] | None = Field(default=None, description="Active MCP servers")

    # UI
    icon: str = Field(default="chat", description="Icon identifier")
    color: str = Field(default="#6366f1", description="Hex color")
    display_name: str | None = Field(default=None, description="Display name")
    position: int = Field(default=0, description="Position in sidebar")

    # Stats
    total_messages: int = Field(default=0, ge=0, description="Total messages")
    total_tokens_in: int = Field(default=0, ge=0, description="Total input tokens")
    total_tokens_out: int = Field(default=0, ge=0, description="Total output tokens")

    # Timestamps
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    last_message_at: datetime | None = Field(default=None, description="Last message timestamp")


class CLISessionUpdate(BaseModel):
    """Request to update CLI session settings."""

    display_name: str | None = Field(default=None, max_length=100)
    icon: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=20)
    position: int | None = Field(default=None, ge=0)

    # Settings
    model: str | None = None
    agent_name: str | None = None
    thinking_enabled: bool | None = None
    thinking_budget: int | None = Field(default=None, ge=1000, le=50000)
    reasoning_enabled: bool | None = None
    mcp_servers: list[str] | None = None

    # Mockup context (dynamic, updated when user views mockups)
    mockup_project_id: str | None = None
    mockup_id: str | None = None


class CLIBranchChange(BaseModel):
    """Request to change branch in chat session."""

    branch: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Branch name to checkout",
    )


# ============================================================================
# Message Schemas
# ============================================================================


class CLIMessageCreate(BaseModel):
    """Request to send a message in CLI chat."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=100000,  # 100k chars for large prompts
        description="Message content",
    )
    model_override: str | None = Field(
        default=None,
        description="Override model for this message (e.g., for slash commands)",
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate and clean message content."""
        return v.strip()


class CLIMessageResponse(BaseModel):
    """CLI chat message response."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Message UUID")
    session_id: str = Field(..., description="Parent session UUID")
    role: MessageRoleEnum = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    is_thinking: bool = Field(default=False, description="Is extended thinking content")

    # Metadata
    tokens_in: int | None = Field(default=None, description="Input tokens")
    tokens_out: int | None = Field(default=None, description="Output tokens")
    model_used: str | None = Field(default=None, description="Model used")
    agent_used: str | None = Field(default=None, description="Agent used")
    duration_ms: int | None = Field(default=None, description="Response time in ms")

    created_at: datetime = Field(..., description="Creation timestamp")


# ============================================================================
# Streaming Schemas
# ============================================================================


class StreamEvent(BaseModel):
    """SSE stream event."""

    type: StreamEventTypeEnum = Field(..., description="Event type")
    content: str | None = Field(default=None, description="Content chunk")
    session_id: str | None = Field(default=None, description="Session ID")
    message_id: str | None = Field(default=None, description="Message ID")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional metadata")


# ============================================================================
# Agent Schemas
# ============================================================================


class AgentResponse(BaseModel):
    """Agent information response."""

    name: str = Field(..., description="Agent name")
    version: str = Field(..., description="Agent version")
    tokens: int = Field(..., description="Estimated token count")
    description: str = Field(..., description="Agent description")
    model: str = Field(..., description="Recommended model")
    color: str = Field(..., description="Display color")
    path: str = Field(..., description="Absolute file path")


class AgentListResponse(BaseModel):
    """List of available agents."""

    agents: list[AgentResponse] = Field(..., description="Available agents")
    total: int = Field(..., description="Total count")


# ============================================================================
# MCP Schemas
# ============================================================================


class MCPServerResponse(BaseModel):
    """MCP server configuration response."""

    name: str = Field(..., description="Server name")
    command: str = Field(..., description="Command to run")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    enabled: bool = Field(default=True, description="Is server enabled")


class MCPServerCreate(BaseModel):
    """Request to add an MCP server."""

    name: str = Field(..., min_length=1, max_length=50, description="Server name")
    command: str = Field(..., min_length=1, description="Command to run")
    args: list[str] = Field(default_factory=list, description="Command arguments")


class MCPConfigResponse(BaseModel):
    """MCP configuration response."""

    servers: list[MCPServerResponse] = Field(..., description="Configured servers")
    config_path: str = Field(..., description="Path to config file")
