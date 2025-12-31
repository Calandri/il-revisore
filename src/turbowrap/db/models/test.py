"""Test suite, run, and case models."""

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
)
from sqlalchemy.orm import relationship

from turbowrap.db.base import Base

from .base import SoftDeleteMixin, TZDateTime, generate_uuid, now_utc


class TestSuite(Base, SoftDeleteMixin):
    """Test suite configuration for a repository.

    A test suite represents a collection of tests that can be executed together.
    Can be auto-discovered from folder structure or manually configured.
    """

    __tablename__ = "test_suites"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )

    # Suite identification
    name = Column(String(255), nullable=False)  # "API Integration Tests"
    path = Column(String(512), nullable=False)  # "tests/api/"
    description = Column(Text, nullable=True)

    # Configuration
    type = Column(String(50), default="classic")  # classic | ai_analysis | ai_generation
    framework = Column(String(50), nullable=False)  # pytest | playwright | vitest | jest | cypress
    command = Column(String(1024), nullable=True)  # Custom command, e.g. "pytest {path} -v"

    # Framework-specific config and user Q&A for AI-generated suites
    config = Column(JSON, nullable=True)

    # AI analysis results (populated by "Analizza con AI" feature)
    ai_analysis = Column(JSON, nullable=True)
    # {
    #   "test_type": "unit|integration|e2e|api|performance",
    #   "coverage_description": "What this test suite covers",
    #   "how_it_works": "Description of how tests work",
    #   "strengths": ["..."],
    #   "weaknesses": ["..."],
    #   "suggestions": ["..."],
    #   "analyzed_at": "2024-01-01T00:00:00Z"
    # }

    # Test count (from scanner, updated when drawer is opened)
    test_count = Column(Integer, default=0)

    # Discovery metadata
    is_auto_discovered = Column(Boolean, default=False)
    discovered_at = Column(TZDateTime(), nullable=True)

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)
    updated_at = Column(TZDateTime(), default=now_utc, onupdate=now_utc)

    # Relationships
    repository = relationship("Repository", backref="test_suites")
    runs = relationship("TestRun", back_populates="suite", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_test_suites_repository", "repository_id"),
        Index("idx_test_suites_framework", "framework"),
        Index("idx_test_suites_type", "type"),
    )

    def __repr__(self) -> str:
        return f"<TestSuite {self.name} ({self.framework})>"


class TestRun(Base):
    """A single execution of a test suite.

    Tracks the results of running tests including pass/fail counts,
    duration, and optional AI analysis.
    """

    __tablename__ = "test_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    suite_id = Column(String(36), ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False)
    repository_id = Column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)

    # Database connection used for this test run (optional)
    database_connection_id = Column(
        String(36), ForeignKey("database_connections.id", ondelete="SET NULL"), nullable=True
    )

    # Status
    status = Column(String(50), default="pending")  # pending | running | passed | failed | error
    branch = Column(String(255), nullable=True)  # Git branch tested
    commit_sha = Column(String(40), nullable=True)  # Git commit SHA

    # Timing
    started_at = Column(TZDateTime(), nullable=True)
    completed_at = Column(TZDateTime(), nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Results summary
    total_tests = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    errors = Column(Integer, default=0)

    # Coverage (optional)
    coverage_percent = Column(Float, nullable=True)
    coverage_report_url = Column(String(1024), nullable=True)

    # Full report (S3 URL or JSON)
    report_url = Column(String(1024), nullable=True)
    report_data = Column(JSON, nullable=True)  # Parsed report data

    # AI analysis (for ai_analysis type suites)
    ai_analysis = Column(JSON, nullable=True)
    # {
    #   "summary": "...",
    #   "failure_patterns": [...],
    #   "suggestions": [...],
    #   "analyzed_at": "..."
    # }

    # Error info (for error status)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)

    # Relationships
    suite = relationship("TestSuite", back_populates="runs")
    repository = relationship("Repository", backref="test_runs")
    task = relationship("Task", backref="test_runs")
    database_connection = relationship("DatabaseConnection", backref="test_runs")
    test_cases = relationship("TestCase", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_test_runs_suite", "suite_id"),
        Index("idx_test_runs_repository", "repository_id"),
        Index("idx_test_runs_status", "status"),
        Index("idx_test_runs_created", "created_at"),
    )

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as percentage."""
        if self.total_tests == 0:
            return 0.0
        return round((self.passed / self.total_tests) * 100, 1)

    @property
    def is_successful(self) -> bool:
        """Check if all tests passed."""
        return self.status == "passed" and self.failed == 0 and self.errors == 0

    def __repr__(self) -> str:
        return f"<TestRun {self.id[:8]} status={self.status} {self.passed}/{self.total_tests}>"


class TestCase(Base):
    """A single test case result within a test run.

    Stores detailed information about each test including
    status, duration, and error details if failed.
    """

    __tablename__ = "test_cases"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False)

    # Test identification
    name = Column(String(512), nullable=False)  # "test_user_login"
    class_name = Column(String(512), nullable=True)  # "TestAuthModule"
    file = Column(String(1024), nullable=True)  # "tests/api/test_auth.py"
    line = Column(Integer, nullable=True)  # Line number in file

    # Status
    status = Column(String(50), nullable=False)  # passed | failed | skipped | error

    # Timing
    duration_ms = Column(Integer, nullable=True)

    # Error details (for failed/error status)
    error_message = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)

    # AI suggestions (populated by ai_analysis)
    ai_suggestion = Column(Text, nullable=True)

    # Additional metadata
    metadata_ = Column("metadata", JSON, nullable=True)
    # {
    #   "markers": ["slow", "integration"],
    #   "parameters": {...},
    #   "stdout": "...",
    #   "stderr": "..."
    # }

    # Timestamps
    created_at = Column(TZDateTime(), default=now_utc)

    # Relationships
    run = relationship("TestRun", back_populates="test_cases")

    __table_args__ = (
        Index("idx_test_cases_run", "run_id"),
        Index("idx_test_cases_status", "status"),
        Index("idx_test_cases_file", "file"),
    )

    @property
    def full_name(self) -> str:
        """Get full test name including class."""
        if self.class_name:
            return f"{self.class_name}::{self.name}"
        return self.name

    def __repr__(self) -> str:
        return f"<TestCase {self.name} status={self.status}>"
