"""update_endpoint_source_values

Revision ID: update_source_vals
Revises: 7dfb5155efbc
Create Date: 2026-01-02 17:30:00.000000+00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "update_source_vals"
down_revision: str | None = "7dfb5155efbc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update source values: backend -> served, frontend -> consumed."""
    op.execute("UPDATE endpoints SET source = 'served' WHERE source = 'backend'")
    op.execute("UPDATE endpoints SET source = 'consumed' WHERE source = 'frontend'")


def downgrade() -> None:
    """Revert source values: served -> backend, consumed -> frontend."""
    op.execute("UPDATE endpoints SET source = 'backend' WHERE source = 'served'")
    op.execute("UPDATE endpoints SET source = 'frontend' WHERE source = 'consumed'")
