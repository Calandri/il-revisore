"""Chat session models (SDK-based)."""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import SoftDeleteMixin, generate_uuid


class ChatSession(Base, SoftDeleteMixin):
    """Chat session for interactive communication."""

    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=True)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    title = Column(String(255), nullable=True)
    status = Column(String(50), default="active")  # active, archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ChatSession {self.id[:8]}>"


class ChatMessage(Base):
    """Chat message in a session."""

    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(50), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)  # agent_type, tokens, etc
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    session = relationship("ChatSession", back_populates="messages")

    __table_args__ = (Index("idx_chat_messages_session", "session_id"),)

    def __repr__(self) -> str:
        return f"<ChatMessage {self.role}>"
