"""add_repository_database_connections

Revision ID: dd843afd43f7
Revises: ecfc633dff83
Create Date: 2025-12-30 09:38:45.535721+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd843afd43f7"
down_revision: str | None = "ecfc633dff83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # 1. Create junction table for Repository-DatabaseConnection many-to-many
    op.create_table(
        "repository_database_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "database_connection_id",
            sa.String(36),
            sa.ForeignKey("database_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("usage_type", sa.String(50), nullable=False, server_default="testing"),
        sa.Column("is_default", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("idx_repo_db_conn_repo", "repository_database_connections", ["repository_id"])
    op.create_index(
        "idx_repo_db_conn_db", "repository_database_connections", ["database_connection_id"]
    )
    # Unique constraint to prevent duplicate links
    op.create_unique_constraint(
        "uq_repo_db_connection",
        "repository_database_connections",
        ["repository_id", "database_connection_id"],
    )

    # 2. Add database_connection_id to test_runs
    op.add_column(
        "test_runs",
        sa.Column("database_connection_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_test_runs_db_conn",
        "test_runs",
        "database_connections",
        ["database_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Remove FK from test_runs
    op.drop_constraint("fk_test_runs_db_conn", "test_runs", type_="foreignkey")
    op.drop_column("test_runs", "database_connection_id")

    # Drop junction table
    op.drop_constraint("uq_repo_db_connection", "repository_database_connections", type_="unique")
    op.drop_index("idx_repo_db_conn_db", table_name="repository_database_connections")
    op.drop_index("idx_repo_db_conn_repo", table_name="repository_database_connections")
    op.drop_table("repository_database_connections")
