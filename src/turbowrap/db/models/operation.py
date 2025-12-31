"""Operation tracking model."""

from typing import Any

from sqlalchemy import JSON, Column, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base
from turbowrap.utils.datetime_utils import format_iso, now_utc

from .base import OperationStatus, TZDateTime, generate_uuid


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
    started_at = Column(TZDateTime(), default=now_utc, nullable=False)
    completed_at = Column(TZDateTime(), nullable=True)
    duration_seconds = Column(Float, nullable=True)  # Computed on completion

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

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
        elapsed = (now_utc() - self.started_at).total_seconds()
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
            "started_at": format_iso(self.started_at) if self.started_at else None,
            "completed_at": format_iso(self.completed_at) if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "is_stale": self.is_stale,
        }

    def __repr__(self) -> str:
        return f"<Operation {self.operation_type} ({self.status})>"
