"""add_test_suite_test_count

Revision ID: 8f7e6d5c4b3a
Revises: d2f6d64a678a
Create Date: 2025-12-30 15:30:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f7e6d5c4b3a"
down_revision: str | None = "d2f6d64a678a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add test_count column to test_suites."""
    op.add_column(
        "test_suites",
        sa.Column("test_count", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    """Remove test_count column from test_suites."""
    op.drop_column("test_suites", "test_count")
