"""add_claude_session_id

Revision ID: add_claude_session_id
Revises: add_allowed_extra_paths
Create Date: 2025-12-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_claude_session_id"
down_revision: str | None = "add_allowed_extra_paths"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add claude_session_id column to cli_chat_sessions."""
    op.add_column(
        "cli_chat_sessions",
        sa.Column("claude_session_id", sa.String(36), nullable=True),
    )


def downgrade() -> None:
    """Remove claude_session_id column from cli_chat_sessions."""
    op.drop_column("cli_chat_sessions", "claude_session_id")
