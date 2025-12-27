"""Drop orphan helpdesk tables.

These tables were created by a different project and are not used by TurboWrap.
All tables have 0 records and no foreign keys to TurboWrap tables.

Revision ID: drop_orphan_helpdesk
Revises: add_claude_session_id
Create Date: 2025-12-27
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "drop_orphan_helpdesk"
down_revision: str = "add_claude_session_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables to drop (in dependency order - children first)
ORPHAN_TABLES = [
    "notifications",
    "ticket_activities",
    "messages",
    "inbound_social_raw",
    "inbound_emails_raw",
    "tickets",
    "response_templates",
    "social_accounts",
    "contacts",
    "operators",
    "releases",
    "organizations",
]


def upgrade() -> None:
    """Drop orphan helpdesk tables."""
    for table in ORPHAN_TABLES:
        op.drop_table(table)


def downgrade() -> None:
    """Cannot restore - tables were not part of TurboWrap."""
    raise NotImplementedError(
        "Cannot restore orphan helpdesk tables. " "They were created by a different project."
    )
