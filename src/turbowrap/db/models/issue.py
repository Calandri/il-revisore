"""Issue and ReviewCheckpoint models."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import IssueStatus, SoftDeleteMixin, TZDateTime, generate_uuid, now_utc


class Issue(Base, SoftDeleteMixin):
    """Code review issue found in a repository.

    Supports Linear integration and discussion comments.
    """

    __tablename__ = "issues"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(
        String(36), ForeignKey("tasks.id"), nullable=True
    )  # Optional: not all issues come from tasks
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)

    # Linear integration (optional)
    linear_id = Column(String(100), unique=True, nullable=True, index=True)  # Linear UUID
    linear_identifier = Column(String(50), nullable=True, index=True)  # e.g., "TEAM-123"
    linear_url = Column(String(512), nullable=True)

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
    attachments = Column(JSON, nullable=True)  # [{filename, s3_key, type, uploaded_at}]

    # Discussion (Linear-style comments)
    comments = Column(JSON, nullable=True)  # [{id, author, content, created_at, type}]

    # Clarifier Q&A (saved for future fixes)
    # Format: [{"question_id": "q1", "question": "...", "context": "...", "answer": "...", "asked_at": "...", "answered_at": "..."}]
    clarifications = Column(JSON, nullable=True)

    # Workload estimation (populated by reviewer agent)
    estimated_effort = Column(Integer, nullable=True)  # 1-5 scale (1=trivial, 5=major refactor)
    estimated_files_count = Column(Integer, nullable=True)  # Number of files to modify

    # Tracking
    status = Column(String(20), default=IssueStatus.OPEN.value, index=True)
    phase_started_at = Column(TZDateTime(), nullable=True)  # When current phase started
    is_active = Column(Boolean, default=False, index=True)  # True when in active development
    is_viewed = Column(Boolean, default=False, index=True)  # True when manually marked as reviewed
    resolution_note = Column(Text, nullable=True)  # Why it was resolved/ignored
    resolved_at = Column(TZDateTime(), nullable=True)

    # Fix result fields (populated when issue is fixed)
    fix_code = Column(Text, nullable=True)  # Snippet del codice fixato (display: max 500 chars)
    fix_explanation = Column(Text, nullable=True)  # Spiegazione PR-style del fix
    fix_files_modified = Column(
        JSON, nullable=True
    )  # Lista file modificati: ["file1.ts", "file2.ts"]
    fix_commit_sha = Column(String(40), nullable=True)  # SHA del commit
    fix_branch = Column(
        String(100), nullable=True
    )  # Branch dove e stato fatto il fix (e.g., "fix/1234567890")
    fix_session_id = Column(String(36), nullable=True, index=True)  # UUID sessione fix (per log S3)
    fixed_at = Column(TZDateTime(), nullable=True)  # Quando e stato fixato
    fixed_by = Column(String(50), nullable=True)  # Agent che ha fixato (e.g., "fixer_claude")
    fix_self_score = Column(Integer, nullable=True)  # Self-evaluation score (0-100)
    fix_gemini_score = Column(Integer, nullable=True)  # Gemini challenger score (0-100)

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

    # Relationships
    task = relationship("Task", back_populates="issues")
    repository = relationship("Repository", back_populates="issues")

    __table_args__ = (
        Index("idx_issues_repository", "repository_id"),
        Index("idx_issues_task", "task_id"),
        Index("idx_issues_severity", "severity"),
        Index("idx_issues_category", "category"),
        Index("idx_issues_file", "file"),
        Index("idx_issues_linear_id", "linear_id"),
        Index("idx_issues_linear_identifier", "linear_identifier"),
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
    started_at = Column(TZDateTime(), nullable=True)
    completed_at = Column(TZDateTime(), nullable=True)
    created_at = Column(TZDateTime(), default=now_utc)

    # Relationships
    task = relationship("Task", backref="checkpoints")

    __table_args__ = (
        Index("idx_review_checkpoints_task", "task_id"),
        Index("idx_review_checkpoints_status", "status"),
        UniqueConstraint("task_id", "reviewer_name", name="uq_task_reviewer"),
    )

    def __repr__(self) -> str:
        return f"<ReviewCheckpoint {self.reviewer_name} ({self.status})>"
