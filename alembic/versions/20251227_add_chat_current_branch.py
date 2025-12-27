"""add_chat_current_branch

Revision ID: add_chat_current_branch
Revises: add_repo_external_links
Create Date: 2025-12-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_chat_current_branch"
down_revision: str | None = "add_repo_external_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add current_branch column to cli_chat_sessions for branch context tracking."""
    op.add_column(
        "cli_chat_sessions",
        sa.Column("current_branch", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    """Remove current_branch column from cli_chat_sessions."""
    op.drop_column("cli_chat_sessions", "current_branch")
