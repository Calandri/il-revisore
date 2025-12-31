"""Linear integration models."""

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

from .base import SoftDeleteMixin, TZDateTime, generate_uuid, now_utc


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
    analyzed_at = Column(TZDateTime(), nullable=True)
    analyzed_by = Column(String(100), nullable=True)  # "claude_opus"
    user_answers = Column(JSON, nullable=True)  # User responses to clarifying questions

    # Development results
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)  # Task when in dev
    fix_commit_sha = Column(String(40), nullable=True)
    fix_branch = Column(String(100), nullable=True)
    fix_explanation = Column(Text, nullable=True)
    fix_files_modified = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)
    synced_at = Column(TZDateTime(), nullable=True)  # Last sync from Linear

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

    created_at = Column(TZDateTime(), default=now_utc)

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
