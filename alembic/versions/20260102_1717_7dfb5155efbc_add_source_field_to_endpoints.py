"""add_source_field_to_endpoints

Revision ID: 7dfb5155efbc
Revises: add_rbac_users
Create Date: 2026-01-02 17:17:32.818378+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7dfb5155efbc"
down_revision: str | None = "add_rbac_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add source column to endpoints table
    op.add_column("endpoints", sa.Column("source", sa.String(length=20), nullable=True))

    # Set default value for existing rows
    op.execute("UPDATE endpoints SET source = 'backend' WHERE source IS NULL")


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("endpoints", "source")
