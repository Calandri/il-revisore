"""Add status and error_message fields to mockups table.

Adds:
- status: Track mockup generation state (generating/completed/failed)
- error_message: Store error details when generation fails

Revision ID: add_mockup_status
Revises: b9cf6cb3a39a
Create Date: 2025-12-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_mockup_status"
down_revision: str = "b9cf6cb3a39a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add status and error_message columns to mockups table."""
    # Add status column with default 'completed' for existing records
    op.add_column(
        "mockups",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="completed",
        ),
    )

    # Add error_message column
    op.add_column(
        "mockups",
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    # Create index for status column
    op.create_index("idx_mockups_status", "mockups", ["status"])


def downgrade() -> None:
    """Remove status and error_message columns from mockups table."""
    op.drop_index("idx_mockups_status", table_name="mockups")
    op.drop_column("mockups", "error_message")
    op.drop_column("mockups", "status")
