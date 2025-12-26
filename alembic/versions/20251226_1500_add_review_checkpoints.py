"""add review checkpoints table

Revision ID: add_review_checkpoints
Revises: 1e870cf19a8b
Create Date: 2025-12-26 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "add_review_checkpoints"
down_revision: str | None = "1e870cf19a8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add review_checkpoints table for resume functionality."""
    op.create_table(
        "review_checkpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("issues_data", sa.JSON(), nullable=False),
        sa.Column("final_satisfaction", sa.Float(), nullable=True),
        sa.Column("iterations", sa.Integer(), nullable=True),
        sa.Column("model_usage", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "reviewer_name", name="uq_task_reviewer"),
    )
    op.create_index("idx_review_checkpoints_task", "review_checkpoints", ["task_id"], unique=False)
    op.create_index(
        "idx_review_checkpoints_status",
        "review_checkpoints",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove review_checkpoints table."""
    op.drop_index("idx_review_checkpoints_status", table_name="review_checkpoints")
    op.drop_index("idx_review_checkpoints_task", table_name="review_checkpoints")
    op.drop_table("review_checkpoints")
