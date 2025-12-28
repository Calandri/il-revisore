"""Expand operations.id column to 100 chars.

The original String(36) was too small for operation IDs like:
'merge-fix/e4a339f5-0ac4-4d8f-9-163313' (42 chars)

Revision ID: expand_operations_id
Revises: add_mockup_tables
Create Date: 2025-12-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "expand_operations_id"
down_revision: str = "add_mockup_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Expand operations.id from VARCHAR(36) to VARCHAR(100)."""
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table("operations", schema=None) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.String(36),
            type_=sa.String(100),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Shrink operations.id back to VARCHAR(36)."""
    with op.batch_alter_table("operations", schema=None) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.String(100),
            type_=sa.String(36),
            existing_nullable=False,
        )
