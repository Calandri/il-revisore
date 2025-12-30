"""add_test_suite_ai_analysis

Revision ID: a07ccf0ac58c
Revises: 0b943bf06bfb
Create Date: 2025-12-30 13:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a07ccf0ac58c"
down_revision: str | None = "0b943bf06bfb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ai_analysis column to test_suites."""
    op.add_column(
        "test_suites",
        sa.Column("ai_analysis", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove ai_analysis column from test_suites."""
    op.drop_column("test_suites", "ai_analysis")
