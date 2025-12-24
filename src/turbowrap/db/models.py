"""TurboWrap database models."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship, declared_attr

from .base import Base


class SoftDeleteMixin:
    """Mixin for soft delete functionality.

    Adds a `deleted_at` column that marks when a record was "deleted".
    Records with deleted_at set should be filtered out in normal queries.

    Usage:
        class MyModel(Base, SoftDeleteMixin):
            ...

        # Soft delete a record
        record.soft_delete()

        # Restore a soft-deleted record
        record.restore()

        # Check if deleted
        if record.is_deleted:
            ...

        # Query only active records
        session.query(MyModel).filter(MyModel.deleted_at.is_(None))
    """

    @declared_attr
    def deleted_at(cls):
        """Timestamp when the record was soft-deleted. None means active."""
        return Column(DateTime, nullable=True, default=None, index=True)

    @property
    def is_deleted(self) -> bool:
        """Check if this record has been soft-deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this record as deleted without removing from database."""
        self.deleted_at = datetime.utcnow()

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None


class LinkType(str, Enum):
    """Types of repository relationships."""

    FRONTEND_FOR = "frontend_for"  # FE repo linked to its BE
    BACKEND_FOR = "backend_for"  # BE repo linked to its FE
    SHARED_LIB = "shared_lib"  # Shared library dependency
    MICROSERVICE = "microservice"  # Related microservice
    MONOREPO_MODULE = "monorepo_module"  # Module in same monorepo
    RELATED = "related"  # Generic relation


class IssueSeverity(str, Enum):
    """Issue severity levels."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IssueStatus(str, Enum):
    """Issue tracking status."""

    OPEN = "open"  # Newly found, needs attention
    IN_PROGRESS = "in_progress"  # Being worked on
    RESOLVED = "resolved"  # Fixed
    MERGED = "merged"  # PR merged, issue closed
    IGNORED = "ignored"  # Marked as false positive or won't fix
    DUPLICATE = "duplicate"  # Duplicate of another issue


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


class Repository(Base, SoftDeleteMixin):
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
    project_name = Column(String(255), nullable=True, index=True)  # Group related repos by project
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tasks = relationship("Task", back_populates="repository", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="repository", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="repository", cascade="all, delete-orphan")

    # Link relationships
    outgoing_links = relationship(
        "RepositoryLink",
        foreign_keys="RepositoryLink.source_repo_id",
        back_populates="source_repo",
        cascade="all, delete-orphan",
    )
    incoming_links = relationship(
        "RepositoryLink",
        foreign_keys="RepositoryLink.target_repo_id",
        back_populates="target_repo",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Repository {self.name}>"


class RepositoryLink(Base):
    """Link between two repositories."""

    __tablename__ = "repository_links"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    source_repo_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    target_repo_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    link_type = Column(String(50), nullable=False)  # Uses LinkType enum values
    metadata_ = Column("metadata", JSON, nullable=True)  # Additional info
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    source_repo = relationship(
        "Repository",
        foreign_keys=[source_repo_id],
        back_populates="outgoing_links",
    )
    target_repo = relationship(
        "Repository",
        foreign_keys=[target_repo_id],
        back_populates="incoming_links",
    )

    __table_args__ = (
        Index("idx_repository_links_source", "source_repo_id"),
        Index("idx_repository_links_target", "target_repo_id"),
        Index("idx_repository_links_type", "link_type"),
    )

    def __repr__(self) -> str:
        return f"<RepositoryLink {self.source_repo_id[:8]}--{self.link_type}-->{self.target_repo_id[:8]}>"


class Task(Base, SoftDeleteMixin):
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
    progress = Column(Integer, default=0)  # 0-100 percentage
    progress_message = Column(String(255), nullable=True)  # Current step description
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", back_populates="tasks")
    agent_runs = relationship("AgentRun", back_populates="task", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="task", cascade="all, delete-orphan")

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


class Issue(Base, SoftDeleteMixin):
    """Code review issue found in a repository."""

    __tablename__ = "issues"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)

    # Issue identification
    issue_code = Column(String(50), nullable=False)  # e.g., BE-CRIT-001
    severity = Column(String(20), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    category = Column(String(50), nullable=False)  # security, performance, architecture, etc.
    rule = Column(String(100), nullable=True)  # Linting rule code if applicable

    # Location
    file = Column(String(500), nullable=False)
    line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)

    # Content
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    current_code = Column(Text, nullable=True)
    suggested_fix = Column(Text, nullable=True)
    references = Column(JSON, nullable=True)  # List of URLs/docs
    flagged_by = Column(JSON, nullable=True)  # List of agents that flagged this

    # Tracking
    status = Column(String(20), default=IssueStatus.OPEN.value)
    resolution_note = Column(Text, nullable=True)  # Why it was resolved/ignored
    resolved_at = Column(DateTime, nullable=True)

    # Fix result fields (populated when issue is fixed)
    fix_code = Column(Text, nullable=True)  # Snippet del codice fixato (display: max 500 chars)
    fix_explanation = Column(Text, nullable=True)  # Spiegazione PR-style del fix
    fix_files_modified = Column(JSON, nullable=True)  # Lista file modificati: ["file1.ts", "file2.ts"]
    fix_commit_sha = Column(String(40), nullable=True)  # SHA del commit
    fix_branch = Column(String(100), nullable=True)  # Branch dove è stato fatto il fix (e.g., "fix/1234567890")
    fixed_at = Column(DateTime, nullable=True)  # Quando è stato fixato
    fixed_by = Column(String(50), nullable=True)  # Agent che ha fixato (e.g., "fixer_claude")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    task = relationship("Task", back_populates="issues")
    repository = relationship("Repository", back_populates="issues")

    __table_args__ = (
        Index("idx_issues_repository", "repository_id"),
        Index("idx_issues_task", "task_id"),
        Index("idx_issues_severity", "severity"),
        Index("idx_issues_status", "status"),
        Index("idx_issues_category", "category"),
        Index("idx_issues_file", "file"),
    )

    def __repr__(self) -> str:
        return f"<Issue {self.issue_code} ({self.severity})>"
