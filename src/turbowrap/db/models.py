"""TurboWrap database models."""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship

from .base import Base


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class Repository(Base):
    """Cloned GitHub repository."""

    __tablename__ = "repositories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)  # owner/repo
    url = Column(String(512), nullable=False)  # GitHub URL
    local_path = Column(String(512), nullable=False)  # ~/.turbowrap/repos/<hash>/
    default_branch = Column(String(100), default="main")
    last_synced_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="active")  # active, syncing, error
    repo_type = Column(String(50), nullable=True)  # backend, frontend, fullstack
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tasks = relationship("Task", back_populates="repository", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="repository", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Repository {self.name}>"


class Task(Base):
    """Task execution record."""

    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    type = Column(String(50), nullable=False)  # review, develop, tree
    status = Column(String(50), default="pending")  # pending, running, completed, failed, cancelled
    priority = Column(Integer, default=0)
    config = Column(JSON, nullable=True)  # task-specific config
    result = Column(JSON, nullable=True)  # output del task
    error = Column(Text, nullable=True)  # error message if failed
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", back_populates="tasks")
    agent_runs = relationship("AgentRun", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tasks_repository", "repository_id"),
        Index("idx_tasks_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Task {self.type} ({self.status})>"


class AgentRun(Base):
    """Individual agent execution record."""

    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    agent_type = Column(String(50), nullable=False)  # gemini_flash, claude_opus
    agent_name = Column(String(100), nullable=False)  # reviewer_be, reviewer_fe, flash_analyzer
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    input_hash = Column(String(64), nullable=True)  # for caching
    output = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    task = relationship("Task", back_populates="agent_runs")

    __table_args__ = (
        Index("idx_agent_runs_task", "task_id"),
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent_type}/{self.agent_name}>"


class ChatSession(Base):
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

    __table_args__ = (
        Index("idx_chat_messages_session", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<ChatMessage {self.role}>"


class Setting(Base):
    """Application settings stored in database."""

    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    is_secret = Column(String(1), default="N")  # Y = encrypted/masked in API responses
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Setting {self.key}>"
