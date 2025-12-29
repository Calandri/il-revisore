"""add_features_and_update_issues_tables

Revision ID: b9cf6cb3a39a
Revises: add_parent_session_id
Create Date: 2025-12-29 11:25:59.678873+00:00

This migration:
1. Adds Linear integration columns to the issues table
2. Creates the features table for multi-repo feature development
3. Creates the feature_repositories pivot table
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9cf6cb3a39a'
down_revision: str | None = 'add_parent_session_id'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # ==========================================================================
    # 1. Update issues table with Linear integration and new columns
    # Using batch_alter_table for SQLite compatibility
    # ==========================================================================

    # Add new columns (works on both SQLite and other databases)
    op.add_column('issues', sa.Column('linear_id', sa.String(length=100), nullable=True))
    op.add_column('issues', sa.Column('linear_identifier', sa.String(length=50), nullable=True))
    op.add_column('issues', sa.Column('linear_url', sa.String(length=512), nullable=True))
    op.add_column('issues', sa.Column('phase_started_at', sa.DateTime(), nullable=True))
    op.add_column('issues', sa.Column('attachments', sa.JSON(), nullable=True))
    op.add_column('issues', sa.Column('comments', sa.JSON(), nullable=True))

    # Use batch mode for ALTER operations (SQLite compatible)
    with op.batch_alter_table('issues', schema=None) as batch_op:
        # Make task_id nullable (not all issues come from tasks)
        batch_op.alter_column('task_id',
                              existing_type=sa.String(length=36),
                              nullable=True)
        # Create indexes for Linear integration
        batch_op.create_index('idx_issues_linear_id', ['linear_id'], unique=True)
        batch_op.create_index('idx_issues_linear_identifier', ['linear_identifier'], unique=False)

    # ==========================================================================
    # 2. Create features table
    # ==========================================================================
    op.create_table('features',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('linear_id', sa.String(length=100), nullable=True),
    sa.Column('linear_identifier', sa.String(length=50), nullable=True),
    sa.Column('linear_url', sa.String(length=512), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('phase_started_at', sa.DateTime(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('improved_description', sa.Text(), nullable=True),
    sa.Column('implementation_plan', sa.JSON(), nullable=True),
    sa.Column('user_qa', sa.JSON(), nullable=True),
    sa.Column('mockup_id', sa.String(length=36), nullable=True),
    sa.Column('figma_link', sa.String(length=512), nullable=True),
    sa.Column('attachments', sa.JSON(), nullable=True),
    sa.Column('comments', sa.JSON(), nullable=True),
    sa.Column('estimated_effort', sa.Integer(), nullable=True),
    sa.Column('estimated_days', sa.Integer(), nullable=True),
    sa.Column('fix_commit_sha', sa.String(length=40), nullable=True),
    sa.Column('fix_branch', sa.String(length=100), nullable=True),
    sa.Column('fix_explanation', sa.Text(), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=True),
    sa.Column('assignee_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['mockup_id'], ['mockups.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_features_linear_id', 'features', ['linear_id'], unique=True)
    op.create_index('idx_features_linear_identifier', 'features', ['linear_identifier'], unique=False)
    op.create_index('idx_features_priority', 'features', ['priority'], unique=False)
    op.create_index('idx_features_status', 'features', ['status'], unique=False)
    op.create_index('idx_features_deleted_at', 'features', ['deleted_at'], unique=False)

    # ==========================================================================
    # 3. Create feature_repositories pivot table
    # ==========================================================================
    op.create_table('feature_repositories',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('feature_id', sa.String(length=36), nullable=False),
    sa.Column('repository_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['feature_id'], ['features.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('feature_id', 'repository_id', name='uq_feature_repository')
    )
    op.create_index('idx_feature_repos_feature', 'feature_repositories', ['feature_id'], unique=False)
    op.create_index('idx_feature_repos_repo', 'feature_repositories', ['repository_id'], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    # ==========================================================================
    # 1. Drop feature_repositories table
    # ==========================================================================
    op.drop_index('idx_feature_repos_repo', table_name='feature_repositories')
    op.drop_index('idx_feature_repos_feature', table_name='feature_repositories')
    op.drop_table('feature_repositories')

    # ==========================================================================
    # 2. Drop features table
    # ==========================================================================
    op.drop_index('idx_features_deleted_at', table_name='features')
    op.drop_index('idx_features_status', table_name='features')
    op.drop_index('idx_features_priority', table_name='features')
    op.drop_index('idx_features_linear_identifier', table_name='features')
    op.drop_index('idx_features_linear_id', table_name='features')
    op.drop_table('features')

    # ==========================================================================
    # 3. Restore issues table (using batch for SQLite)
    # ==========================================================================
    with op.batch_alter_table('issues', schema=None) as batch_op:
        batch_op.drop_index('idx_issues_linear_identifier')
        batch_op.drop_index('idx_issues_linear_id')
        # Make task_id required again
        batch_op.alter_column('task_id',
                              existing_type=sa.String(length=36),
                              nullable=False)

    # Drop new columns
    op.drop_column('issues', 'comments')
    op.drop_column('issues', 'attachments')
    op.drop_column('issues', 'phase_started_at')
    op.drop_column('issues', 'linear_url')
    op.drop_column('issues', 'linear_identifier')
    op.drop_column('issues', 'linear_id')
