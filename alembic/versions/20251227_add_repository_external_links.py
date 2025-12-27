"""add_repository_external_links

Revision ID: add_repo_external_links
Revises: add_operations_table
Create Date: 2025-12-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_repo_external_links"
down_revision: str | None = "add_operations_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create repository_external_links table for external URLs (staging, production, docs, etc.)."""
    op.create_table(
        "repository_external_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=50), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("is_primary", sa.Boolean(), default=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
    )
    # Create indexes for common queries
    op.create_index(
        "idx_external_links_repo", "repository_external_links", ["repository_id"], unique=False
    )
    op.create_index(
        "idx_external_links_type", "repository_external_links", ["link_type"], unique=False
    )


def downgrade() -> None:
    """Drop repository_external_links table."""
    op.drop_index("idx_external_links_type", table_name="repository_external_links")
    op.drop_index("idx_external_links_repo", table_name="repository_external_links")
    op.drop_table("repository_external_links")
