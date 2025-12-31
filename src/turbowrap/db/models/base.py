"""Base classes, mixins, and enums for database models."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

# Re-export now_utc for convenience
from turbowrap.utils.datetime_utils import now_utc

__all__ = ["TZDateTime", "now_utc", "generate_uuid"]


def TZDateTime() -> Any:  # noqa: N802
    """Create a timezone-aware DateTime column.

    Use this instead of raw DateTime for consistent timezone handling.
    SQLite stores UTC, PostgreSQL uses timestamptz.

    Usage:
        created_at = Column(TZDateTime(), default=now_utc)
    """
    return DateTime(timezone=True)


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


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
        return mapped_column(TZDateTime(), nullable=True, default=None, index=True)

    @property
    def is_deleted(self) -> bool:
        """Check if this record has been soft-deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this record as deleted without removing from database."""
        self.deleted_at = now_utc()

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None


# =============================================================================
# Enums
# =============================================================================


class LinkType(str, Enum):
    """Types of repository relationships."""

    FRONTEND_FOR = "frontend_for"  # FE repo linked to its BE
    BACKEND_FOR = "backend_for"  # BE repo linked to its FE
    SHARED_LIB = "shared_lib"  # Shared library dependency
    MICROSERVICE = "microservice"  # Related microservice
    MONOREPO_MODULE = "monorepo_module"  # Module in same monorepo
    RELATED = "related"  # Generic relation


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


# Valid state transitions for Issue status
# Maps current status to list of allowed next statuses
ISSUE_STATUS_TRANSITIONS: dict["IssueStatus", list["IssueStatus"]] = {
    IssueStatus.OPEN: [
        IssueStatus.IN_PROGRESS,
        IssueStatus.IGNORED,
        IssueStatus.DUPLICATE,
    ],
    IssueStatus.IN_PROGRESS: [
        IssueStatus.RESOLVED,
        IssueStatus.OPEN,  # Reset on failure
        IssueStatus.IGNORED,
    ],
    IssueStatus.RESOLVED: [
        IssueStatus.IN_REVIEW,
        IssueStatus.MERGED,  # Direct merge (skip review phase)
        IssueStatus.OPEN,  # Reopen
    ],
    IssueStatus.IN_REVIEW: [
        IssueStatus.MERGED,
        IssueStatus.OPEN,  # Reopen
    ],
    IssueStatus.MERGED: [],  # Terminal state
    IssueStatus.IGNORED: [
        IssueStatus.OPEN,  # Reopen
    ],
    IssueStatus.DUPLICATE: [
        IssueStatus.OPEN,  # Reopen
    ],
}


def is_valid_issue_transition(current: "IssueStatus", new: "IssueStatus") -> bool:
    """Check if a status transition is valid."""
    return new in ISSUE_STATUS_TRANSITIONS.get(current, [])


# =============================================================================
# Feature Status Enums
# =============================================================================


class FeatureStatus(str, Enum):
    """Feature development status."""

    ANALYSIS = "analysis"  # Clarifying requirements, Q&A phase
    DESIGN = "design"  # Mockup/design phase
    DEVELOPMENT = "development"  # In active development
    REVIEW = "review"  # Code review, awaiting merge
    MERGED = "merged"  # Completed and merged
    ON_HOLD = "on_hold"  # Paused
    CANCELLED = "cancelled"  # Cancelled


# Valid state transitions for Feature status
FEATURE_STATUS_TRANSITIONS: dict["FeatureStatus", list["FeatureStatus"]] = {
    FeatureStatus.ANALYSIS: [
        FeatureStatus.DESIGN,
        FeatureStatus.DEVELOPMENT,  # Skip design if not needed
        FeatureStatus.ON_HOLD,
        FeatureStatus.CANCELLED,
    ],
    FeatureStatus.DESIGN: [
        FeatureStatus.DEVELOPMENT,
        FeatureStatus.ANALYSIS,  # Back to clarify
        FeatureStatus.ON_HOLD,
        FeatureStatus.CANCELLED,
    ],
    FeatureStatus.DEVELOPMENT: [
        FeatureStatus.REVIEW,
        FeatureStatus.DESIGN,  # Back to design
        FeatureStatus.ON_HOLD,
        FeatureStatus.CANCELLED,
    ],
    FeatureStatus.REVIEW: [
        FeatureStatus.MERGED,
        FeatureStatus.DEVELOPMENT,  # Needs more work
        FeatureStatus.CANCELLED,
    ],
    FeatureStatus.MERGED: [],  # Terminal state
    FeatureStatus.ON_HOLD: [
        FeatureStatus.ANALYSIS,
        FeatureStatus.DESIGN,
        FeatureStatus.DEVELOPMENT,
        FeatureStatus.CANCELLED,
    ],
    FeatureStatus.CANCELLED: [],  # Terminal state
}


def is_valid_feature_transition(current: "FeatureStatus", new: "FeatureStatus") -> bool:
    """Check if a feature status transition is valid."""
    return new in FEATURE_STATUS_TRANSITIONS.get(current, [])


class FeatureRepositoryRole(str, Enum):
    """Role of a repository in a feature."""

    PRIMARY = "primary"  # Main repository for the feature
    SECONDARY = "secondary"  # Supporting repository
    SHARED = "shared"  # Shared library affected


class EndpointVisibility(str, Enum):
    """Endpoint visibility/access level."""

    PUBLIC = "public"  # Accessible from internet without auth
    PRIVATE = "private"  # Requires authentication
    INTERNAL = "internal"  # Only accessible from internal network


class DatabaseType(str, Enum):
    """Supported database types."""

    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"
    MONGODB = "mongodb"
    REDIS = "redis"
    MARIADB = "mariadb"
    MSSQL = "mssql"


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

    # Test operations
    TEST_RUN = "test_run"
    TEST_DISCOVER = "test_discover"


# =============================================================================
# Test Enums
# =============================================================================


class TestSuiteType(str, Enum):
    """Type of test suite."""

    CLASSIC = "classic"  # Traditional test execution (pytest, playwright, etc.)
    AI_ANALYSIS = "ai_analysis"  # AI analyzes test results
    AI_GENERATION = "ai_generation"  # AI generates tests


class TestRunStatus(str, Enum):
    """Status of a test run."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"


class TestCaseStatus(str, Enum):
    """Status of a single test case."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class TestFramework(str, Enum):
    """Supported test frameworks."""

    # Python
    PYTEST = "pytest"

    # JavaScript/TypeScript
    PLAYWRIGHT = "playwright"
    VITEST = "vitest"
    JEST = "jest"
    CYPRESS = "cypress"

    # Generic
    CUSTOM = "custom"
