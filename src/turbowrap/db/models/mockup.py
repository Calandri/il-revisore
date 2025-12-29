"""Mockup models."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import SoftDeleteMixin, generate_uuid


class MockupStatus(str, Enum):
    """Mockup generation status."""

    GENERATING = "generating"  # LLM is generating the mockup
    COMPLETED = "completed"  # Mockup saved successfully
    FAILED = "failed"  # Generation failed


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
    status = Column(String(20), default=MockupStatus.GENERATING.value, nullable=False, index=True)

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

    # Error tracking (for failed generations)
    error_message = Column(Text, nullable=True)

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
        Index("idx_mockups_status", "status"),
        Index("idx_mockups_deleted", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<Mockup {self.name} v{self.version}>"
