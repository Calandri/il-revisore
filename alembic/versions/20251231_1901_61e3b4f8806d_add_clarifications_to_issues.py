"""add clarifications to issues

Revision ID: 61e3b4f8806d
Revises: 0c9706197704
Create Date: 2025-12-31 19:01:29.763837+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "61e3b4f8806d"
down_revision: str | None = "0c9706197704"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("issues", sa.Column("clarifications", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("issues", "clarifications")
