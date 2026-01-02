"""Task and AgentRun models."""

from sqlalchemy import JSON, Column, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import SoftDeleteMixin, TZDateTime, generate_uuid, now_utc


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
    started_at = Column(TZDateTime(), nullable=True)
    completed_at = Column(TZDateTime(), nullable=True)
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

    # Relationships
    repository = relationship("Repository", back_populates="tasks")
    agent_runs = relationship("AgentRun", back_populates="task", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tasks_repository", "repository_id"),
        Index("idx_tasks_status", "status"),
        {"extend_existing": True},
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
    created_at = Column(TZDateTime(), default=now_utc)

    # Relationships
    task = relationship("Task", back_populates="agent_runs")

    __table_args__ = (
        Index("idx_agent_runs_task", "task_id"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent_type}/{self.agent_name}>"
