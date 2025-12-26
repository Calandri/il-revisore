#!/bin/bash
# TurboWrap Database Migration Script
# Uses Alembic for both SQLite (dev) and PostgreSQL (staging/prod)
#
# Usage:
#   ./migrations/migrate.sh              # Uses TURBOWRAP_DB_URL or default SQLite
#   TURBOWRAP_DB_URL=... ./migrations/migrate.sh  # Uses specified database
#
# Examples:
#   # Local SQLite (default)
#   ./migrations/migrate.sh
#
#   # PostgreSQL
#   TURBOWRAP_DB_URL="postgresql://user:pass@host:5432/turbowrap" ./migrations/migrate.sh

set -e

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root for Alembic
cd "$PROJECT_ROOT"

# Default database URL if not set
if [ -z "$TURBOWRAP_DB_URL" ]; then
    export TURBOWRAP_DB_URL="sqlite:///$HOME/.turbowrap/turbowrap.db"
    echo "Using default SQLite database: ~/.turbowrap/turbowrap.db"
else
    echo "Using database: ${TURBOWRAP_DB_URL%%:*}://***"  # Hide password
fi

# Ensure the database directory exists for SQLite
if [[ "$TURBOWRAP_DB_URL" == sqlite:///* ]]; then
    DB_PATH="${TURBOWRAP_DB_URL#sqlite:///}"
    DB_PATH="${DB_PATH/#\~/$HOME}"
    DB_DIR="$(dirname "$DB_PATH")"
    mkdir -p "$DB_DIR"
    echo "Database path: $DB_PATH"
fi

echo ""
echo "Running Alembic migrations..."

# Run Alembic upgrade
python -m alembic upgrade head

echo ""
echo "Migrations complete!"

# Show current revision
echo ""
echo "Current database revision:"
python -m alembic current
