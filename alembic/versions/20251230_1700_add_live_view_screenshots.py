"""add_live_view_screenshots

Revision ID: add_live_view_screenshots
Revises: add_test_suite_test_count
Create Date: 2025-12-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_live_view_screenshots"
down_revision: str | None = "8f7e6d5c4b3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create live_view_screenshots table for caching production site screenshots."""
    op.create_table(
        "live_view_screenshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("external_link_id", sa.String(length=36), nullable=False),
        sa.Column("s3_url", sa.String(length=1024), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("viewport_width", sa.Integer(), default=1920),
        sa.Column("viewport_height", sa.Integer(), default=1080),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.ForeignKeyConstraint(["external_link_id"], ["repository_external_links.id"]),
    )
    # Create indexes
    op.create_index("idx_live_view_repo", "live_view_screenshots", ["repository_id"], unique=False)
    op.create_index(
        "idx_live_view_link", "live_view_screenshots", ["external_link_id"], unique=True
    )


def downgrade() -> None:
    """Drop live_view_screenshots table."""
    op.drop_index("idx_live_view_link", table_name="live_view_screenshots")
    op.drop_index("idx_live_view_repo", table_name="live_view_screenshots")
    op.drop_table("live_view_screenshots")
