"""TurboWrap database models."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

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
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

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
    def deleted_at(cls) -> Mapped[datetime | None]:  # noqa: N805
        """Timestamp when the record was soft-deleted. None means active."""
        return mapped_column(DateTime, nullable=True, default=None, index=True)

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
    workspace_path = Column(
        String(512), nullable=True
    )  # Monorepo: relative path (e.g., "packages/frontend")
    allowed_extra_paths = Column(
        JSON, nullable=True
    )  # Monorepo: additional allowed paths for fix (e.g., ["frontend/", "shared/"])
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tasks = relationship("Task", back_populates="repository", cascade="all, delete-orphan")
    chat_sessions = relationship(
        "ChatSession", back_populates="repository", cascade="all, delete-orphan"
    )
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

    # External links (staging, production, docs, etc.)
    external_links = relationship(
        "RepositoryExternalLink",
        back_populates="repository",
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
        src = self.source_repo_id[:8]
        tgt = self.target_repo_id[:8]
        return f"<RepositoryLink {src}--{self.link_type}-->{tgt}>"


class ExternalLinkType(str, Enum):
    """Types of external links for repositories."""

    STAGING = "staging"
    PRODUCTION = "production"
    DOCS = "docs"
    API = "api"
    ADMIN = "admin"
    SWAGGER = "swagger"
    GRAPHQL = "graphql"
    MONITORING = "monitoring"
    LOGS = "logs"
    CI_CD = "ci_cd"
    OTHER = "other"


class RepositoryExternalLink(Base):
    """External URL links for a repository (staging, production, docs, etc.)."""

    __tablename__ = "repository_external_links"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    link_type = Column(String(50), nullable=False)  # Uses ExternalLinkType enum values
    url = Column(String(1024), nullable=False)
    label = Column(String(100), nullable=True)  # Optional custom label
    is_primary = Column(Boolean, default=False)  # Mark one link as primary per type
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", back_populates="external_links")

    __table_args__ = (
        Index("idx_external_links_repo", "repository_id"),
        Index("idx_external_links_type", "link_type"),
    )

    def __repr__(self) -> str:
        return f"<RepositoryExternalLink {self.link_type}: {self.url[:30]}>"


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

    __table_args__ = (Index("idx_agent_runs_task", "task_id"),)

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

    __table_args__ = (Index("idx_chat_messages_session", "session_id"),)

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
    fix_files_modified = Column(
        JSON, nullable=True
    )  # Lista file modificati: ["file1.ts", "file2.ts"]
    fix_commit_sha = Column(String(40), nullable=True)  # SHA del commit
    fix_branch = Column(
        String(100), nullable=True
    )  # Branch dove è stato fatto il fix (e.g., "fix/1234567890")
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


class ReviewCheckpoint(Base):
    """Checkpoint for a single reviewer in a review task.

    Enables resume functionality: when a review fails, completed reviewers
    can be skipped on retry using their checkpoint data.
    """

    __tablename__ = "review_checkpoints"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    reviewer_name = Column(String(100), nullable=False)  # e.g., 'reviewer_be_architecture'

    # Status
    status = Column(String(20), nullable=False, default="completed")  # completed, failed

    # Checkpoint data
    issues_data = Column(JSON, nullable=False)  # Serialized Issue list
    final_satisfaction = Column(Float, nullable=True)  # Challenger satisfaction 0-100
    iterations = Column(Integer, nullable=True)  # Challenger loop iterations
    model_usage = Column(JSON, nullable=True)  # Token/cost info

    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    task = relationship("Task", backref="checkpoints")

    __table_args__ = (
        Index("idx_review_checkpoints_task", "task_id"),
        Index("idx_review_checkpoints_status", "status"),
        UniqueConstraint("task_id", "reviewer_name", name="uq_task_reviewer"),
    )

    def __repr__(self) -> str:
        return f"<ReviewCheckpoint {self.reviewer_name} ({self.status})>"


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


# ============================================================================
# Database Connection Models (external database viewer)
# ============================================================================


class EndpointVisibility(str, Enum):
    """Endpoint visibility/access level."""

    PUBLIC = "public"  # Accessible from internet without auth
    PRIVATE = "private"  # Requires authentication
    INTERNAL = "internal"  # Only accessible from internal network


class Endpoint(Base):
    """API endpoint detected in a repository.

    Stores endpoint metadata with unique constraint on (repository_id, method, path).
    Running detection multiple times will update existing endpoints, not duplicate.
    """

    __tablename__ = "endpoints"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)

    # Endpoint identification (unique per repo)
    method = Column(String(10), nullable=False)  # GET, POST, PUT, DELETE, PATCH
    path = Column(String(500), nullable=False)  # /api/v1/users

    # Source location
    file = Column(String(500), nullable=True)  # src/routes/users.py
    line = Column(Integer, nullable=True)  # Line number in file

    # Documentation
    description = Column(Text, nullable=True)  # What the endpoint does
    response_type = Column(String(255), nullable=True)  # List[User], UserResponse, etc.
    tags = Column(JSON, nullable=True)  # ["users", "admin"]

    # Parameters stored as JSON array
    parameters = Column(
        JSON, nullable=True
    )  # [{name, param_type, data_type, required, description}]

    # Authentication & Visibility
    requires_auth = Column(Boolean, default=False, index=True)  # True if auth required
    visibility = Column(
        String(20), default=EndpointVisibility.PRIVATE.value, index=True
    )  # public, private, internal
    auth_type = Column(String(50), nullable=True)  # Bearer, Basic, API-Key, OAuth2, etc.

    # Detection metadata
    detected_at = Column(DateTime, nullable=True)  # When this endpoint was detected
    detection_confidence = Column(Float, nullable=True)  # 0-100 confidence score
    framework = Column(String(50), nullable=True)  # fastapi, flask, express, etc.

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", backref="endpoints")

    __table_args__ = (
        # Unique constraint: one entry per method+path per repository
        UniqueConstraint("repository_id", "method", "path", name="uq_repo_method_path"),
        Index("idx_endpoints_repository", "repository_id"),
        Index("idx_endpoints_auth", "requires_auth"),
        Index("idx_endpoints_visibility", "visibility"),
        Index("idx_endpoints_path", "path"),
    )

    def __repr__(self) -> str:
        auth = "🔒" if self.requires_auth else "🔓"
        return f"<Endpoint {auth} {self.method} {self.path}>"


class DatabaseType(str, Enum):
    """Supported database types."""

    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"
    MONGODB = "mongodb"
    REDIS = "redis"
    MARIADB = "mariadb"
    MSSQL = "mssql"


class DatabaseConnection(Base, SoftDeleteMixin):
    """External database connection for the database viewer.

    Stores connection details for databases that users want to browse/manage.
    Passwords are stored encrypted using Fernet symmetric encryption.
    """

    __tablename__ = "database_connections"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Basic info
    name = Column(String(100), nullable=False)  # User-friendly name
    description = Column(Text, nullable=True)  # Optional description
    db_type = Column(String(20), nullable=False)  # mysql, postgresql, sqlite, etc.

    # Connection details
    host = Column(String(255), nullable=True)  # NULL for SQLite
    port = Column(Integer, nullable=True)  # Default ports: MySQL=3306, PG=5432, etc.
    database = Column(String(255), nullable=False)  # Database name or file path for SQLite
    username = Column(String(100), nullable=True)  # NULL for SQLite
    encrypted_password = Column(Text, nullable=True)  # Fernet encrypted password

    # SSL/TLS Configuration
    ssl_enabled = Column(Boolean, default=False)
    ssl_ca_cert = Column(Text, nullable=True)  # CA certificate content
    ssl_client_cert = Column(Text, nullable=True)  # Client certificate
    ssl_client_key = Column(Text, nullable=True)  # Client private key
    ssl_verify = Column(Boolean, default=True)  # Verify server certificate

    # SSH Tunnel Configuration (for remote databases)
    ssh_enabled = Column(Boolean, default=False)
    ssh_host = Column(String(255), nullable=True)
    ssh_port = Column(Integer, default=22)
    ssh_username = Column(String(100), nullable=True)
    ssh_private_key = Column(Text, nullable=True)  # Encrypted SSH key
    ssh_passphrase = Column(Text, nullable=True)  # Encrypted passphrase

    # Connection options
    connection_timeout = Column(Integer, default=30)  # Seconds
    read_only = Column(Boolean, default=False)  # Read-only mode
    max_connections = Column(Integer, default=5)  # Connection pool size

    # Additional options stored as JSON
    extra_options = Column(JSON, nullable=True)  # Driver-specific options

    # Status tracking
    last_connected_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)  # Last connection error
    is_favorite = Column(Boolean, default=False, index=True)  # Starred connections

    # Organization
    color = Column(String(20), nullable=True)  # Hex color for UI
    icon = Column(String(50), nullable=True)  # Icon identifier
    tags = Column(JSON, nullable=True)  # ["production", "staging", etc.]

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_database_connections_type", "db_type"),
        Index("idx_database_connections_favorite", "is_favorite"),
        Index("idx_database_connections_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<DatabaseConnection {self.name} ({self.db_type})>"


class OperationStatus(str, Enum):
    """Status of a tracked operation."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationType(str, Enum):
    """Types of tracked operations."""

    # AI-powered operations (long-running)
    FIX = "fix"
    REVIEW = "review"

    # Git write operations
    GIT_COMMIT = "git_commit"
    GIT_MERGE = "git_merge"
    GIT_PUSH = "git_push"
    GIT_PULL = "git_pull"

    # Repository operations
    CLONE = "clone"
    SYNC = "sync"

    # Post-fix operations
    MERGE_AND_PUSH = "merge_and_push"
    OPEN_PR = "open_pr"

    # Deployment
    DEPLOY = "deploy"
    PROMOTE = "promote"

    # Generic CLI task
    CLI_TASK = "cli_task"


class Operation(Base):
    """Persistent record of CLI/system operations.

    This table stores all operations (fix, review, git, etc.) for:
    - Live monitoring (status = in_progress)
    - Historical analysis (completed/failed operations)
    - Debugging and auditing
    """

    __tablename__ = "operations"

    # Primary key
    id = Column(String(100), primary_key=True, default=generate_uuid)

    # Operation identity
    operation_type = Column(String(50), nullable=False, index=True)  # Uses OperationType values
    status = Column(String(50), nullable=False, default="in_progress", index=True)

    # Context
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=True, index=True)
    repository_name = Column(String(255), nullable=True)  # Cached for display
    branch_name = Column(String(255), nullable=True)
    user_name = Column(String(255), nullable=True)

    # Hierarchy - links child operations to parent session
    parent_session_id = Column(String(100), nullable=True, index=True)

    # Details (flexible JSON for operation-specific data)
    details = Column(JSON, nullable=True)
    # Expected keys: model, cli, agent, working_dir, prompt_preview, prompt_length, s3_prompt_url, etc.

    # Result (populated on completion)
    result = Column(JSON, nullable=True)
    # Expected keys: duration_ms, tokens, cost_usd, etc.

    # Error (populated on failure)
    error = Column(Text, nullable=True)

    # Timing
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)  # Computed on completion

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", backref="operations")

    __table_args__ = (
        Index("idx_operations_type", "operation_type"),
        Index("idx_operations_status", "status"),
        Index("idx_operations_repo", "repository_id"),
        Index("idx_operations_started", "started_at"),
        Index("idx_operations_type_status", "operation_type", "status"),
        Index("idx_operations_parent_session", "parent_session_id"),
    )

    @property
    def is_stale(self) -> bool:
        """True if operation has been running for >30 minutes."""
        if self.status != OperationStatus.IN_PROGRESS.value:
            return False
        if not self.started_at:
            return False
        elapsed = (datetime.utcnow() - self.started_at).total_seconds()
        return elapsed > 1800

    def to_dict(self) -> dict[str, Any]:
        """Convert to API response format."""
        from turbowrap.api.services.operation_tracker import OPERATION_COLORS, OPERATION_LABELS
        from turbowrap.api.services.operation_tracker import OperationType as TrackerOpType

        try:
            op_type = TrackerOpType(self.operation_type)
            label = OPERATION_LABELS.get(op_type, self.operation_type)
            color = OPERATION_COLORS.get(op_type, "gray")
        except ValueError:
            label = self.operation_type
            color = "gray"

        return {
            "operation_id": self.id,
            "type": self.operation_type,
            "label": label,
            "color": color,
            "status": self.status,
            "repository_id": self.repository_id,
            "repository_name": self.repository_name,
            "branch_name": self.branch_name,
            "user_name": self.user_name,
            "parent_session_id": self.parent_session_id,
            "details": self.details or {},
            "result": self.result,
            "error": self.error,
            "started_at": (self.started_at.isoformat() + "Z") if self.started_at else None,
            "completed_at": (self.completed_at.isoformat() + "Z") if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "is_stale": self.is_stale,
        }

    def __repr__(self) -> str:
        return f"<Operation {self.operation_type} ({self.status})>"


# =========================================================================
# Mockup Models
# =========================================================================


class MockupProject(Base, SoftDeleteMixin):
    """Project container for UI mockups."""

    __tablename__ = "mockup_projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    design_system = Column(String(100), nullable=True)  # tailwind, bootstrap, material, custom
    color = Column(String(20), default="#6366f1")
    icon = Column(String(50), default="layout")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    repository = relationship("Repository", backref="mockup_projects")
    mockups = relationship("Mockup", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_mockup_projects_repository", "repository_id"),
        Index("idx_mockup_projects_deleted", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<MockupProject {self.name}>"


class Mockup(Base, SoftDeleteMixin):
    """Individual UI mockup with HTML/CSS/JS stored in S3."""

    __tablename__ = "mockups"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("mockup_projects.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    component_type = Column(String(100), nullable=True)  # page, component, modal, form, table

    # LLM metadata
    llm_type = Column(String(50), default="claude")  # claude, gemini, grok
    llm_model = Column(String(100), nullable=True)
    prompt_used = Column(Text, nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)

    # S3 storage URLs
    s3_html_url = Column(String(512), nullable=True)
    s3_css_url = Column(String(512), nullable=True)
    s3_js_url = Column(String(512), nullable=True)
    s3_prompt_url = Column(String(512), nullable=True)

    # Versioning
    version = Column(Integer, default=1)
    parent_mockup_id = Column(String(36), ForeignKey("mockups.id"), nullable=True)

    # Link to chat session (if created from CLI)
    chat_session_id = Column(String(36), ForeignKey("cli_chat_sessions.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("MockupProject", back_populates="mockups")
    parent_mockup = relationship("Mockup", remote_side="Mockup.id", backref="versions")
    chat_session = relationship("CLIChatSession", backref="mockups")

    __table_args__ = (
        Index("idx_mockups_project", "project_id"),
        Index("idx_mockups_parent", "parent_mockup_id"),
        Index("idx_mockups_llm_type", "llm_type"),
        Index("idx_mockups_deleted", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<Mockup {self.name} v{self.version}>"
