"""add_widget_api_keys_table

Revision ID: ac742ebbc2ba
Revises: 72821db4299b
Create Date: 2026-01-04 09:28:36.756881+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac742ebbc2ba"
down_revision: str | None = "72821db4299b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "widget_api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("allowed_origins", sqlite.JSON(), nullable=True),
        sa.Column("repository_id", sa.String(length=36), nullable=True),
        sa.Column("team_id", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_widget_api_keys_key_hash", "widget_api_keys", ["key_hash"], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_widget_api_keys_key_hash", table_name="widget_api_keys")
    op.drop_table("widget_api_keys")
