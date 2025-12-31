"""add fix_plan to issues

Revision ID: 02f7eb3341ce
Revises: 61e3b4f8806d
Create Date: 2025-12-31 19:57:35.970061+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "02f7eb3341ce"
down_revision: str | None = "61e3b4f8806d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("issues", sa.Column("fix_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("issues", "fix_plan")
