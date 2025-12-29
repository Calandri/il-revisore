"""sync_all_issue_columns

Revision ID: 8fe8b3ab3aa1
Revises: add_issue_is_viewed
Create Date: 2025-12-29 16:42:38.320335+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8fe8b3ab3aa1"
down_revision: str | None = "add_issue_is_viewed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema - SQLite compatible operations only."""
    # Add is_viewed column to issues
    op.add_column("issues", sa.Column("is_viewed", sa.Boolean(), nullable=True, server_default="0"))

    # Create indexes for issues (ignore if already exist)
    try:
        op.create_index("idx_issues_linear_id", "issues", ["linear_id"], unique=False)
    except Exception:
        pass
    try:
        op.create_index(
            "idx_issues_linear_identifier", "issues", ["linear_identifier"], unique=False
        )
    except Exception:
        pass
    try:
        op.create_index(op.f("ix_issues_is_viewed"), "issues", ["is_viewed"], unique=False)
    except Exception:
        pass
    try:
        op.create_index(
            op.f("ix_issues_fix_session_id"), "issues", ["fix_session_id"], unique=False
        )
    except Exception:
        pass


def downgrade() -> None:
    """Downgrade database schema."""
    try:
        op.drop_index(op.f("ix_issues_fix_session_id"), table_name="issues")
    except Exception:
        pass
    try:
        op.drop_index(op.f("ix_issues_is_viewed"), table_name="issues")
    except Exception:
        pass
    try:
        op.drop_index("idx_issues_linear_identifier", table_name="issues")
    except Exception:
        pass
    try:
        op.drop_index("idx_issues_linear_id", table_name="issues")
    except Exception:
        pass
    op.drop_column("issues", "is_viewed")
