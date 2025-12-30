"""add_repo_test_analysis

Revision ID: 0b943bf06bfb
Revises: dd843afd43f7
Create Date: 2025-12-30 12:43:20.116189+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0b943bf06bfb"
down_revision: str | None = "dd843afd43f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add test_analysis column to repositories for repo-level test analysis.

    This column stores a JSON object with aggregated test analysis
    across all test suites in the repository.
    """
    op.add_column(
        "repositories",
        sa.Column("test_analysis", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove test_analysis column from repositories."""
    op.drop_column("repositories", "test_analysis")
