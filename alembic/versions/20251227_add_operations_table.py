"""add_operations_table

Revision ID: add_operations_table
Revises: f8e1cbdd9375
Create Date: 2025-12-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_operations_table"
down_revision: str | None = "f8e1cbdd9375"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create operations table for persistent operation tracking."""
    op.create_table(
        "operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=True),
        sa.Column("repository_name", sa.String(length=255), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
    )
    # Create indexes for common queries
    op.create_index("idx_operations_type", "operations", ["operation_type"], unique=False)
    op.create_index("idx_operations_status", "operations", ["status"], unique=False)
    op.create_index("idx_operations_repo", "operations", ["repository_id"], unique=False)
    op.create_index("idx_operations_started", "operations", ["started_at"], unique=False)
    op.create_index(
        "idx_operations_type_status", "operations", ["operation_type", "status"], unique=False
    )


def downgrade() -> None:
    """Drop operations table."""
    op.drop_index("idx_operations_type_status", table_name="operations")
    op.drop_index("idx_operations_started", table_name="operations")
    op.drop_index("idx_operations_repo", table_name="operations")
    op.drop_index("idx_operations_status", table_name="operations")
    op.drop_index("idx_operations_type", table_name="operations")
    op.drop_table("operations")
