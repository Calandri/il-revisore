"""TurboWrap database models."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declared_attr, relationship

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
    IN_REVIEW = "in_review"  # Code review/developed, awaiting merge
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
    workspace_path = Column(String(512), nullable=True)  # Monorepo: relative path (e.g., "packages/frontend")
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

    # Workload estimation (populated by reviewer agent)
    estimated_effort = Column(Integer, nullable=True)  # 1-5 scale (1=trivial, 5=major refactor)
    estimated_files_count = Column(Integer, nullable=True)  # Number of files to modify

    # Tracking
    status = Column(String(20), default=IssueStatus.OPEN.value)
    is_active = Column(Boolean, default=False, index=True)  # True when in development
    resolution_note = Column(Text, nullable=True)  # Why it was resolved/ignored
    resolved_at = Column(DateTime, nullable=True)

    # Fix result fields (populated when issue is fixed)
    fix_code = Column(Text, nullable=True)  # Snippet del codice fixato (display: max 500 chars)
    fix_explanation = Column(Text, nullable=True)  # Spiegazione PR-style del fix
    fix_files_modified = Column(JSON, nullable=True)  # Lista file modificati: ["file1.ts", "file2.ts"]
    fix_commit_sha = Column(String(40), nullable=True)  # SHA del commit
    fix_branch = Column(String(100), nullable=True)  # Branch dove è stato fatto il fix (e.g., "fix/1234567890")
    fix_session_id = Column(String(36), nullable=True, index=True)  # UUID sessione fix (per log S3)
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


class LinearIssue(Base, SoftDeleteMixin):
    """Linear issue imported for development workflow."""

    __tablename__ = "linear_issues"

    # Primary key
    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Linear metadata
    linear_id = Column(String(100), nullable=False, unique=True, index=True)  # Linear UUID
    linear_identifier = Column(String(50), nullable=False, index=True)  # e.g., "TEAM-123"
    linear_url = Column(String(512), nullable=False)
    linear_team_id = Column(String(100), nullable=False, index=True)
    linear_team_name = Column(String(255), nullable=True)

    # Content
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)  # Original description from Linear
    improved_description = Column(Text, nullable=True)  # Claude-improved description

    # Metadata
    assignee_id = Column(String(100), nullable=True)
    assignee_name = Column(String(255), nullable=True)
    priority = Column(Integer, default=0)  # 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low
    labels = Column(JSON, nullable=True)  # Array of {name, color}

    # Workflow state
    turbowrap_state = Column(String(50), default="analysis", index=True, nullable=False)
    # States: analysis, repo_link, in_progress, in_review, merged
    linear_state_id = Column(String(100), nullable=True)  # Linear workflow state UUID
    linear_state_name = Column(String(100), nullable=True)

    # Cached Linear state IDs (for performance)
    linear_state_triage_id = Column(String(100), nullable=True)
    linear_state_todo_id = Column(String(100), nullable=True)
    linear_state_inprogress_id = Column(String(100), nullable=True)
    linear_state_inreview_id = Column(String(100), nullable=True)
    linear_state_done_id = Column(String(100), nullable=True)

    # Active development tracking (constraint: max 1 active)
    is_active = Column(Boolean, default=False, index=True)

    # Analysis results (from Claude)
    analysis_summary = Column(Text, nullable=True)
    analysis_comment_id = Column(String(100), nullable=True)  # Linear comment ID
    analyzed_at = Column(DateTime, nullable=True)
    analyzed_by = Column(String(100), nullable=True)  # "claude_opus"
    user_answers = Column(JSON, nullable=True)  # User responses to clarifying questions

    # Development results
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)  # Task when in dev
    fix_commit_sha = Column(String(40), nullable=True)
    fix_branch = Column(String(100), nullable=True)
    fix_explanation = Column(Text, nullable=True)
    fix_files_modified = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    synced_at = Column(DateTime, nullable=True)  # Last sync from Linear

    # Relationships
    task = relationship("Task", backref="linear_issues")
    repository_links = relationship(
        "LinearIssueRepositoryLink",
        back_populates="linear_issue",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_linear_issues_linear_id", "linear_id"),
        Index("idx_linear_issues_identifier", "linear_identifier"),
        Index("idx_linear_issues_team", "linear_team_id"),
        Index("idx_linear_issues_state", "turbowrap_state"),
        Index("idx_linear_issues_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<LinearIssue {self.linear_identifier} ({self.turbowrap_state})>"


class LinearIssueRepositoryLink(Base):
    """Links Linear issues to TurboWrap repositories."""

    __tablename__ = "linear_issue_repository_links"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    linear_issue_id = Column(String(36), ForeignKey("linear_issues.id"), nullable=False)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)

    # How was this link determined?
    link_source = Column(String(50), nullable=False)  # "label", "manual", "claude_analysis"
    source_label = Column(String(100), nullable=True)  # Original label that created this link
    confidence_score = Column(Float, nullable=True)  # 0-100 if from Claude analysis

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    linear_issue = relationship("LinearIssue", back_populates="repository_links")
    repository = relationship("Repository")

    __table_args__ = (
        Index("idx_linear_repo_links_issue", "linear_issue_id"),
        Index("idx_linear_repo_links_repo", "repository_id"),
        UniqueConstraint("linear_issue_id", "repository_id", name="uq_linear_issue_repo"),
    )

    def __repr__(self) -> str:
        return f"<LinearIssueRepositoryLink issue={self.linear_issue_id} repo={self.repository_id}>"


# ============================================================================
# CLI Chat Models (claude/gemini CLI-based chat)
# ============================================================================


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
    status = Column(String(20), default="idle")  # idle, starting, running, streaming, stopping, error

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_message_at = Column(DateTime, nullable=True)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
