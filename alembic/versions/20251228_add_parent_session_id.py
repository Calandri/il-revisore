"""Add parent_session_id to operations table.

This column enables hierarchical grouping of operations.
Child operations (fixer, committer, reviewer) link to the parent session_id.

Revision ID: add_parent_session_id
Revises: expand_operations_id
Create Date: 2025-12-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_parent_session_id"
down_revision: str = "expand_operations_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add parent_session_id column and index."""
    with op.batch_alter_table("operations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_session_id", sa.String(100), nullable=True))
        batch_op.create_index(
            "idx_operations_parent_session",
            ["parent_session_id"],
        )


def downgrade() -> None:
    """Remove parent_session_id column and index."""
    with op.batch_alter_table("operations", schema=None) as batch_op:
        batch_op.drop_index("idx_operations_parent_session")
        batch_op.drop_column("parent_session_id")
