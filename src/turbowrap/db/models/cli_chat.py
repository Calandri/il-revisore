"""CLI-based chat models (claude/gemini subprocess)."""

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import SoftDeleteMixin, TZDateTime, generate_uuid, now_utc


class CLIChatSession(Base, SoftDeleteMixin):
    """CLI-based chat session (claude/gemini subprocess).

    A differenza di ChatSession (SDK-based), questa sessione gestisce
    processi CLI claude/gemini con supporto per:
    - Agenti custom (da /agents/)
    - MCP servers
    - Extended thinking
    - Multi-chat parallele
    """

    __tablename__ = "cli_chat_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=True)

    # Branch context (for repo-linked sessions)
    current_branch = Column(String(100), nullable=True)  # Active branch in chat

    # CLI Configuration
    cli_type = Column(String(20), nullable=False)  # "claude" or "gemini"
    model = Column(String(100), nullable=True)  # e.g., "claude-opus-4-5-20251101"
    agent_name = Column(String(100), nullable=True)  # Agent da /agents/ (e.g., "fixer")

    # Claude-specific settings
    thinking_enabled = Column(Boolean, default=False)
    thinking_budget = Column(Integer, default=8000)  # 1000-50000 tokens

    # Gemini-specific settings
    reasoning_enabled = Column(Boolean, default=False)

    # MCP Configuration
    mcp_servers = Column(JSON, nullable=True)  # ["linear", "github"] - active MCP servers

    # Process State
    process_pid = Column(Integer, nullable=True)  # OS process ID when running
    status = Column(
        String(20), default="idle"
    )  # idle, starting, running, streaming, stopping, error
    # Claude CLI session ID for --resume (persists across server restarts)
    claude_session_id = Column(String(36), nullable=True)

    # UI Configuration
    icon = Column(String(50), default="chat")  # Icon identifier
    color = Column(String(20), default="#6366f1")  # Hex color for icon
    display_name = Column(String(100), nullable=True)  # Custom name
    position = Column(Integer, default=0)  # Order in sidebar

    # Stats
    total_messages = Column(Integer, default=0)
    total_tokens_in = Column(Integer, default=0)
    total_tokens_out = Column(Integer, default=0)

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)
    last_message_at = Column(TZDateTime(), nullable=True)

    # Relationships
    repository = relationship("Repository")
    messages = relationship(
        "CLIChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CLIChatMessage.created_at",
    )

    __table_args__ = (
        Index("idx_cli_chat_sessions_repo", "repository_id"),
        Index("idx_cli_chat_sessions_type", "cli_type"),
        Index("idx_cli_chat_sessions_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<CLIChatSession {self.cli_type}/{self.id[:8]} ({self.status})>"


class CLIChatMessage(Base):
    """Message in a CLI chat session.

    Supporta:
    - Messaggi normali (user/assistant/system)
    - Extended thinking (is_thinking=True)
    - Token tracking per messaggio
    """

    __tablename__ = "cli_chat_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("cli_chat_sessions.id"), nullable=False)

    # Content
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)

    # Extended thinking
    is_thinking = Column(Boolean, default=False)  # True = extended thinking content

    # Token tracking
    tokens_in = Column(Integer, nullable=True)  # Tokens input (for user messages)
    tokens_out = Column(Integer, nullable=True)  # Tokens output (for assistant messages)

    # Metadata
    model_used = Column(String(100), nullable=True)  # Model used for this message
    agent_used = Column(String(100), nullable=True)  # Agent used if any
    duration_ms = Column(Integer, nullable=True)  # Response time in milliseconds

    # Timestamp
    created_at = Column(TZDateTime(), default=now_utc)

    # Relationships
    session = relationship("CLIChatSession", back_populates="messages")

    __table_args__ = (
        Index("idx_cli_chat_messages_session", "session_id"),
        Index("idx_cli_chat_messages_role", "role"),
        Index("idx_cli_chat_messages_created", "created_at"),
    )

    def __repr__(self) -> str:
        prefix = "[T]" if self.is_thinking else ""
        return f"<CLIChatMessage {prefix}{self.role}>"
