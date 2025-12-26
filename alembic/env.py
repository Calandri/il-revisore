"""Alembic migrations environment configuration.

This file connects Alembic to TurboWrap's SQLAlchemy models
and handles database URL configuration for both SQLite and PostgreSQL.
"""

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context
from turbowrap.db import models  # noqa: F401 - ensure models are registered

# Import TurboWrap models - this imports Base with all models registered
from turbowrap.db.base import Base

# Alembic Config object
config = context.config

# Setup logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support
target_metadata = Base.metadata


def get_database_url() -> str:
    """Get database URL from environment or alembic.ini.

    Priority:
    1. TURBOWRAP_DB_URL environment variable
    2. sqlalchemy.url from alembic.ini

    Handles SQLite path expansion (~/...).
    """
    # Check environment variable first
    db_url = os.environ.get("TURBOWRAP_DB_URL")

    if not db_url:
        # Fallback to alembic.ini
        db_url = config.get_main_option("sqlalchemy.url")

    if not db_url:
        raise ValueError(
            "Database URL not configured. Set TURBOWRAP_DB_URL environment variable "
            "or sqlalchemy.url in alembic.ini"
        )

    # Expand ~ in SQLite path
    if db_url.startswith("sqlite:///~"):
        db_path = Path(db_url.replace("sqlite:///", "")).expanduser()
        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{db_path}"

    return db_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This generates SQL scripts without connecting to the database.
    Useful for reviewing migrations before applying them.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare types for better autogenerate
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates a database connection and applies migrations directly.
    """
    db_url = get_database_url()

    # Configure connection based on database type
    if db_url.startswith("sqlite"):
        connectable = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=pool.NullPool,
        )
    else:
        # PostgreSQL
        connectable = create_engine(
            db_url,
            pool_pre_ping=True,
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Compare types for better autogenerate
            compare_type=True,
            # Render nullable for column changes
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
