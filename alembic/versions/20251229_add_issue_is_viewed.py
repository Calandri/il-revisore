"""Add is_viewed field to issues table.

Adds a boolean flag to manually mark issues as "reviewed" during manual triage.
This helps users track which issues they've already looked at.

Revision ID: add_issue_is_viewed
Revises: add_mockup_status
Create Date: 2025-12-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_issue_is_viewed"
down_revision: str = "add_mockup_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_viewed column to issues table."""
    op.add_column(
        "issues",
        sa.Column(
            "is_viewed",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )

    # Create index for efficient filtering
    op.create_index("idx_issues_is_viewed", "issues", ["is_viewed"])


def downgrade() -> None:
    """Remove is_viewed column from issues table."""
    op.drop_index("idx_issues_is_viewed", table_name="issues")
    op.drop_column("issues", "is_viewed")
