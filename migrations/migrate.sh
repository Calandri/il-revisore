#!/bin/bash
# TurboWrap Database Migration Script
# Usage: ./migrations/migrate.sh [db_path]
# Default db_path: ~/.turbowrap/turbowrap.db

DB_PATH="${1:-$HOME/.turbowrap/turbowrap.db}"

echo "Running migrations on: $DB_PATH"

# Migration 001: Add deleted_at columns
echo "Migration 001: Adding deleted_at columns..."

sqlite3 "$DB_PATH" "ALTER TABLE chat_sessions ADD COLUMN deleted_at DATETIME;" 2>/dev/null && \
    echo "  - Added deleted_at to chat_sessions" || \
    echo "  - chat_sessions.deleted_at already exists"

sqlite3 "$DB_PATH" "ALTER TABLE issues ADD COLUMN deleted_at DATETIME;" 2>/dev/null && \
    echo "  - Added deleted_at to issues" || \
    echo "  - issues.deleted_at already exists"

sqlite3 "$DB_PATH" "ALTER TABLE repositories ADD COLUMN deleted_at DATETIME;" 2>/dev/null && \
    echo "  - Added deleted_at to repositories" || \
    echo "  - repositories.deleted_at already exists"

sqlite3 "$DB_PATH" "ALTER TABLE tasks ADD COLUMN deleted_at DATETIME;" 2>/dev/null && \
    echo "  - Added deleted_at to tasks" || \
    echo "  - tasks.deleted_at already exists"

echo ""
echo "Migrations complete!"
