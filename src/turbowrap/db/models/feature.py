"""Feature model for development workflow."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import FeatureRepositoryRole, FeatureStatus, SoftDeleteMixin, generate_uuid


class Feature(Base, SoftDeleteMixin):
    """Feature for development workflow.

    Represents a feature request that can span multiple repositories.
    Supports Linear integration and multi-repo development.
    """

    __tablename__ = "features"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Linear integration (optional)
    linear_id = Column(String(100), unique=True, nullable=True, index=True)  # Linear UUID
    linear_identifier = Column(String(50), nullable=True, index=True)  # e.g., "TEAM-123"
    linear_url = Column(String(512), nullable=True)

    # Status tracking
    status = Column(String(20), default=FeatureStatus.ANALYSIS.value, nullable=False, index=True)
    phase_started_at = Column(DateTime, nullable=True)  # When current phase started

    # Content
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)  # Original description
    improved_description = Column(Text, nullable=True)  # Claude-improved description

    # Planning
    implementation_plan = Column(JSON, nullable=True)  # [{id, step, completed, notes, assigned_to}]
    user_qa = Column(JSON, nullable=True)  # [{id, question, why, answer, asked_at}]

    # Design
    mockup_id = Column(String(36), ForeignKey("mockups.id"), nullable=True)
    figma_link = Column(String(512), nullable=True)

    # Attachments
    attachments = Column(JSON, nullable=True)  # [{filename, s3_key, type, uploaded_at}]

    # Discussion (Linear-style comments)
    comments = Column(JSON, nullable=True)  # [{id, author, content, created_at, type}]

    # Effort estimation
    estimated_effort = Column(Integer, nullable=True)  # 1-5 scale
    estimated_days = Column(Integer, nullable=True)  # Optional: estimated days

    # Development results
    fix_commit_sha = Column(String(40), nullable=True)  # Final commit SHA
    fix_branch = Column(String(100), nullable=True)  # Development branch
    fix_explanation = Column(Text, nullable=True)  # Summary of changes

    # Metadata
    priority = Column(Integer, default=3)  # 1=Urgent, 2=High, 3=Normal, 4=Low
    assignee_name = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    mockup = relationship("Mockup", backref="features")
    repository_links = relationship(
        "FeatureRepository",
        back_populates="feature",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_features_status", "status"),
        Index("idx_features_linear_id", "linear_id"),
        Index("idx_features_linear_identifier", "linear_identifier"),
        Index("idx_features_priority", "priority"),
    )

    def __repr__(self) -> str:
        identifier = self.linear_identifier or self.id[:8]
        return f"<Feature {identifier} ({self.status})>"

    @property
    def primary_repository(self) -> "FeatureRepository | None":
        """Get the primary repository for this feature."""
        for link in self.repository_links:
            if link.role == FeatureRepositoryRole.PRIMARY.value:
                return link
        return None

    @property
    def repositories(self) -> list:
        """Get all linked repositories."""
        return [link.repository for link in self.repository_links]


class FeatureRepository(Base):
    """Links Features to Repositories (many-to-many with role)."""

    __tablename__ = "feature_repositories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    feature_id = Column(String(36), ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=False)

    # Role of this repository in the feature
    role = Column(String(20), default=FeatureRepositoryRole.PRIMARY.value, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    feature = relationship("Feature", back_populates="repository_links")
    repository = relationship("Repository", backref="feature_links")

    __table_args__ = (
        Index("idx_feature_repos_feature", "feature_id"),
        Index("idx_feature_repos_repo", "repository_id"),
        UniqueConstraint("feature_id", "repository_id", name="uq_feature_repository"),
    )

    def __repr__(self) -> str:
        return f"<FeatureRepository feature={self.feature_id[:8]} repo={self.repository_id[:8]} role={self.role}>"
