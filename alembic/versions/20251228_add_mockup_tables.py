"""Add mockup_projects and mockups tables.

Create tables for UI mockup management:
- mockup_projects: Container for related mockups, linked to repositories
- mockups: Individual mockups with LLM metadata and S3 storage

Revision ID: add_mockup_tables
Revises: drop_orphan_helpdesk
Create Date: 2025-12-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_mockup_tables"
down_revision: str = "drop_orphan_helpdesk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create mockup_projects and mockups tables."""
    # Create mockup_projects table
    op.create_table(
        "mockup_projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("design_system", sa.String(length=100), nullable=True),
        sa.Column("color", sa.String(length=20), server_default="#6366f1"),
        sa.Column("icon", sa.String(length=50), server_default="layout"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_mockup_projects_repository", "mockup_projects", ["repository_id"])
    op.create_index("idx_mockup_projects_deleted", "mockup_projects", ["deleted_at"])

    # Create mockups table
    op.create_table(
        "mockups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("component_type", sa.String(length=100), nullable=True),
        # LLM metadata
        sa.Column("llm_type", sa.String(length=50), server_default="claude"),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_used", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0"),
        sa.Column("tokens_out", sa.Integer(), server_default="0"),
        # S3 storage
        sa.Column("s3_html_url", sa.String(length=512), nullable=True),
        sa.Column("s3_css_url", sa.String(length=512), nullable=True),
        sa.Column("s3_js_url", sa.String(length=512), nullable=True),
        sa.Column("s3_prompt_url", sa.String(length=512), nullable=True),
        # Versioning
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("parent_mockup_id", sa.String(length=36), nullable=True),
        sa.Column("chat_session_id", sa.String(length=36), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["mockup_projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_mockup_id"],
            ["mockups.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["cli_chat_sessions.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("idx_mockups_project", "mockups", ["project_id"])
    op.create_index("idx_mockups_parent", "mockups", ["parent_mockup_id"])
    op.create_index("idx_mockups_llm_type", "mockups", ["llm_type"])
    op.create_index("idx_mockups_deleted", "mockups", ["deleted_at"])


def downgrade() -> None:
    """Drop mockups and mockup_projects tables."""
    # Drop mockups first (depends on mockup_projects)
    op.drop_index("idx_mockups_deleted", table_name="mockups")
    op.drop_index("idx_mockups_llm_type", table_name="mockups")
    op.drop_index("idx_mockups_parent", table_name="mockups")
    op.drop_index("idx_mockups_project", table_name="mockups")
    op.drop_table("mockups")

    # Drop mockup_projects
    op.drop_index("idx_mockup_projects_deleted", table_name="mockup_projects")
    op.drop_index("idx_mockup_projects_repository", table_name="mockup_projects")
    op.drop_table("mockup_projects")
