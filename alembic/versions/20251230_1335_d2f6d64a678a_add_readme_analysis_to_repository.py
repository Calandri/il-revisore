"""add_readme_analysis_to_repository

Revision ID: d2f6d64a678a
Revises: a07ccf0ac58c
Create Date: 2025-12-30 13:35:58.660829+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2f6d64a678a"
down_revision: Union[str, None] = "a07ccf0ac58c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("repositories", sa.Column("readme_analysis", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("repositories", "readme_analysis")
