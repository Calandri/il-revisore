"""add_fix_score_fields

Revision ID: ecfc633dff83
Revises: 803355cc33a1
Create Date: 2025-12-29 23:10:44.688692+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ecfc633dff83"
down_revision: str | None = "803355cc33a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("issues", sa.Column("fix_self_score", sa.Integer(), nullable=True))
    op.add_column("issues", sa.Column("fix_gemini_score", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("issues", "fix_gemini_score")
    op.drop_column("issues", "fix_self_score")
