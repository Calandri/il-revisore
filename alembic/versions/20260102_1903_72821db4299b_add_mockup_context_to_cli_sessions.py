"""add_mockup_context_to_cli_sessions

Revision ID: 72821db4299b
Revises: update_source_vals
Create Date: 2026-01-02 19:03:13.150718+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "72821db4299b"
down_revision: str | None = "update_source_vals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add mockup_project_id and mockup_id to cli_chat_sessions."""
    op.add_column(
        "cli_chat_sessions",
        sa.Column("mockup_project_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "cli_chat_sessions",
        sa.Column("mockup_id", sa.String(36), nullable=True),
    )
    # Add foreign keys
    op.create_foreign_key(
        "fk_cli_chat_sessions_mockup_project",
        "cli_chat_sessions",
        "mockup_projects",
        ["mockup_project_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_cli_chat_sessions_mockup",
        "cli_chat_sessions",
        "mockups",
        ["mockup_id"],
        ["id"],
    )


def downgrade() -> None:
    """Remove mockup context columns from cli_chat_sessions."""
    op.drop_constraint("fk_cli_chat_sessions_mockup", "cli_chat_sessions", type_="foreignkey")
    op.drop_constraint(
        "fk_cli_chat_sessions_mockup_project", "cli_chat_sessions", type_="foreignkey"
    )
    op.drop_column("cli_chat_sessions", "mockup_id")
    op.drop_column("cli_chat_sessions", "mockup_project_id")
