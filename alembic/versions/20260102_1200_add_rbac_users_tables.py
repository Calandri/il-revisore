"""add RBAC users and user_repositories tables

Revision ID: add_rbac_users
Revises: 02f7eb3341ce
Create Date: 2026-01-02 12:00:00.000000+00:00

This migration adds Role-Based Access Control (RBAC) support:
1. Creates the users table to store role assignments (linked to Cognito via cognito_sub)
2. Creates the user_repositories join table for per-repository access control
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_rbac_users"
down_revision: str | None = "02f7eb3341ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # ==========================================================================
    # 1. Create users table
    # ==========================================================================
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cognito_sub", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="coder"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_users_cognito_sub", "users", ["cognito_sub"], unique=True)
    op.create_index("idx_users_email", "users", ["email"], unique=False)
    op.create_index("idx_users_role", "users", ["role"], unique=False)

    # ==========================================================================
    # 2. Create user_repositories join table
    # ==========================================================================
    op.create_table(
        "user_repositories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "repository_id", name="uq_user_repository"),
    )
    op.create_index("idx_user_repos_user", "user_repositories", ["user_id"], unique=False)
    op.create_index("idx_user_repos_repo", "user_repositories", ["repository_id"], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    # ==========================================================================
    # 1. Drop user_repositories table
    # ==========================================================================
    op.drop_index("idx_user_repos_repo", table_name="user_repositories")
    op.drop_index("idx_user_repos_user", table_name="user_repositories")
    op.drop_table("user_repositories")

    # ==========================================================================
    # 2. Drop users table
    # ==========================================================================
    op.drop_index("idx_users_role", table_name="users")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_index("idx_users_cognito_sub", table_name="users")
    op.drop_table("users")
