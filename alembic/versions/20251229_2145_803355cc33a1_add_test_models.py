"""add test models

Revision ID: 803355cc33a1
Revises: 8fe8b3ab3aa1
Create Date: 2025-12-29 21:45:42.034253+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "803355cc33a1"
down_revision: str | None = "8fe8b3ab3aa1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create test_suites table
    op.create_table(
        "test_suites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(50), server_default="classic"),
        sa.Column("framework", sa.String(50), nullable=False),
        sa.Column("command", sa.String(1024), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("is_auto_discovered", sa.Boolean(), server_default="0"),
        sa.Column("discovered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_test_suites_repository", "test_suites", ["repository_id"])
    op.create_index("idx_test_suites_framework", "test_suites", ["framework"])
    op.create_index("idx_test_suites_type", "test_suites", ["type"])

    # Create test_runs table
    op.create_table(
        "test_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "suite_id",
            sa.String(36),
            sa.ForeignKey("test_suites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("branch", sa.String(255), nullable=True),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("total_tests", sa.Integer(), server_default="0"),
        sa.Column("passed", sa.Integer(), server_default="0"),
        sa.Column("failed", sa.Integer(), server_default="0"),
        sa.Column("skipped", sa.Integer(), server_default="0"),
        sa.Column("errors", sa.Integer(), server_default="0"),
        sa.Column("coverage_percent", sa.Float(), nullable=True),
        sa.Column("coverage_report_url", sa.String(1024), nullable=True),
        sa.Column("report_url", sa.String(1024), nullable=True),
        sa.Column("report_data", sa.JSON(), nullable=True),
        sa.Column("ai_analysis", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_test_runs_suite", "test_runs", ["suite_id"])
    op.create_index("idx_test_runs_repository", "test_runs", ["repository_id"])
    op.create_index("idx_test_runs_status", "test_runs", ["status"])
    op.create_index("idx_test_runs_created", "test_runs", ["created_at"])

    # Create test_cases table
    op.create_table(
        "test_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("test_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("class_name", sa.String(512), nullable=True),
        sa.Column("file", sa.String(1024), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("ai_suggestion", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_test_cases_run", "test_cases", ["run_id"])
    op.create_index("idx_test_cases_status", "test_cases", ["status"])
    op.create_index("idx_test_cases_file", "test_cases", ["file"])


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("test_cases")
    op.drop_table("test_runs")
    op.drop_table("test_suites")
