"""Repository models."""

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import SoftDeleteMixin, TZDateTime, generate_uuid, now_utc


class Repository(Base, SoftDeleteMixin):
    """Cloned GitHub repository."""

    __tablename__ = "repositories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)  # owner/repo
    url = Column(String(512), nullable=False)  # GitHub URL
    local_path = Column(String(512), nullable=False)  # ~/.turbowrap/repos/<hash>/
    default_branch = Column(String(100), default="main")
    last_synced_at = Column(TZDateTime(), nullable=True)
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

    # AI test analysis for all test suites in this repo
    test_analysis = Column(JSON, nullable=True)
    # {
    #   "scores": {"overall": 7.5, "coverage": 8, ...},
    #   "total_suites": 3,
    #   "total_tests": 150,
    #   "test_type_breakdown": {"unit": 100, "integration": 50},
    #   "strengths": [...],
    #   "weaknesses": [...],
    #   "suggestions": [...],
    #   "analyzed_at": "2024-01-01T00:00:00Z"
    # }

    # AI-generated README analysis with descriptions and diagrams
    readme_analysis = Column(JSON, nullable=True)
    # {
    #   "functionality": {"summary": "...", "main_features": [...], "use_cases": [...]},
    #   "logic": {"overview": "...", "main_flows": [...], "key_algorithms": [...]},
    #   "structure": {"layers": [...], "key_modules": [...], "directory_tree": "..."},
    #   "code": {"language": "...", "framework": "...", "patterns": [...], ...},
    #   "diagrams": [{"type": "...", "title": "...", "code": "...", "description": "..."}],
    #   "generated_at": "2024-01-01T00:00:00Z"
    # }

    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

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

    __table_args__ = ({"extend_existing": True},)

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
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

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
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        src = self.source_repo_id[:8]
        tgt = self.target_repo_id[:8]
        return f"<RepositoryLink {src}--{self.link_type}-->{tgt}>"


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
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

    # Relationships
    repository = relationship("Repository", back_populates="external_links")

    __table_args__ = (
        Index("idx_external_links_repo", "repository_id"),
        Index("idx_external_links_type", "link_type"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return f"<RepositoryExternalLink {self.link_type}: {self.url[:30]}>"
