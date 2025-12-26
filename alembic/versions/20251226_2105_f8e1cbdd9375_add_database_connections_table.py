"""add_database_connections_table

Revision ID: f8e1cbdd9375
Revises: add_review_checkpoints
Create Date: 2025-12-26 21:05:58.010099+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8e1cbdd9375'
down_revision: Union[str, None] = 'add_review_checkpoints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create database_connections table
    op.create_table('database_connections',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('db_type', sa.String(length=20), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=True),
    sa.Column('port', sa.Integer(), nullable=True),
    sa.Column('database', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=True),
    sa.Column('encrypted_password', sa.Text(), nullable=True),
    sa.Column('ssl_enabled', sa.Boolean(), nullable=True),
    sa.Column('ssl_ca_cert', sa.Text(), nullable=True),
    sa.Column('ssl_client_cert', sa.Text(), nullable=True),
    sa.Column('ssl_client_key', sa.Text(), nullable=True),
    sa.Column('ssl_verify', sa.Boolean(), nullable=True),
    sa.Column('ssh_enabled', sa.Boolean(), nullable=True),
    sa.Column('ssh_host', sa.String(length=255), nullable=True),
    sa.Column('ssh_port', sa.Integer(), nullable=True),
    sa.Column('ssh_username', sa.String(length=100), nullable=True),
    sa.Column('ssh_private_key', sa.Text(), nullable=True),
    sa.Column('ssh_passphrase', sa.Text(), nullable=True),
    sa.Column('connection_timeout', sa.Integer(), nullable=True),
    sa.Column('read_only', sa.Boolean(), nullable=True),
    sa.Column('max_connections', sa.Integer(), nullable=True),
    sa.Column('extra_options', sa.JSON(), nullable=True),
    sa.Column('last_connected_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('is_favorite', sa.Boolean(), nullable=True),
    sa.Column('color', sa.String(length=20), nullable=True),
    sa.Column('icon', sa.String(length=50), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_database_connections_favorite', 'database_connections', ['is_favorite'], unique=False)
    op.create_index('idx_database_connections_name', 'database_connections', ['name'], unique=False)
    op.create_index('idx_database_connections_type', 'database_connections', ['db_type'], unique=False)
    op.create_index(op.f('ix_database_connections_deleted_at'), 'database_connections', ['deleted_at'], unique=False)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(op.f('ix_database_connections_deleted_at'), table_name='database_connections')
    op.drop_index('idx_database_connections_type', table_name='database_connections')
    op.drop_index('idx_database_connections_name', table_name='database_connections')
    op.drop_index('idx_database_connections_favorite', table_name='database_connections')
    op.drop_table('database_connections')
