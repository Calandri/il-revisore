"""add_live_view_updated_at

Revision ID: f23f890d78ce
Revises: add_live_view_screenshots
Create Date: 2025-12-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f23f890d78ce"
down_revision: str | None = "add_live_view_screenshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add updated_at column to live_view_screenshots."""
    # SQLite doesn't support NOT NULL for new columns without default
    # Use server_default to work around this
    op.add_column(
        "live_view_screenshots",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    """Remove updated_at column from live_view_screenshots."""
    op.drop_column("live_view_screenshots", "updated_at")
