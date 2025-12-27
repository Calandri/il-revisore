"""add_allowed_extra_paths

Revision ID: add_allowed_extra_paths
Revises: add_chat_current_branch
Create Date: 2025-12-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_allowed_extra_paths"
down_revision: str | None = "add_chat_current_branch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add allowed_extra_paths column to repositories for scope exceptions.

    This column stores a JSON array of additional paths that are allowed
    during fix operations when workspace_path is set (monorepo mode).
    Example: ["frontend/", "shared/"]
    """
    op.add_column(
        "repositories",
        sa.Column("allowed_extra_paths", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove allowed_extra_paths column from repositories."""
    op.drop_column("repositories", "allowed_extra_paths")
