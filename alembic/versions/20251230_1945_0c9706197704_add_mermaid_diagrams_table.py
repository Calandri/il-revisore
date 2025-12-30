"""Add mermaid_diagrams table

Revision ID: 0c9706197704
Revises: f23f890d78ce
Create Date: 2025-12-30 19:45:42.835444+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c9706197704"
down_revision: str | None = "f23f890d78ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "mermaid_diagrams",
        sa.Column("document_key", sa.String(255), primary_key=True),
        sa.Column("mermaid_code", sa.Text(), nullable=False),
        sa.Column("diagram_type", sa.String(50), default="flowchart"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("mermaid_diagrams")
