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

# Migration 002: Add project_name
echo ""
echo "Migration 002: Adding project_name..."
sqlite3 "$DB_PATH" "ALTER TABLE tasks ADD COLUMN project_name VARCHAR(255);" 2>/dev/null && \
    echo "  - Added project_name to tasks" || \
    echo "  - tasks.project_name already exists"

# Migration 003: Add fix result columns to issues
echo ""
echo "Migration 003: Adding fix result columns..."

sqlite3 "$DB_PATH" "ALTER TABLE issues ADD COLUMN fix_code TEXT;" 2>/dev/null && \
    echo "  - Added fix_code to issues" || \
    echo "  - issues.fix_code already exists"

sqlite3 "$DB_PATH" "ALTER TABLE issues ADD COLUMN fix_explanation TEXT;" 2>/dev/null && \
    echo "  - Added fix_explanation to issues" || \
    echo "  - issues.fix_explanation already exists"

sqlite3 "$DB_PATH" "ALTER TABLE issues ADD COLUMN fix_files_modified JSON;" 2>/dev/null && \
    echo "  - Added fix_files_modified to issues" || \
    echo "  - issues.fix_files_modified already exists"

sqlite3 "$DB_PATH" "ALTER TABLE issues ADD COLUMN fix_commit_sha VARCHAR(40);" 2>/dev/null && \
    echo "  - Added fix_commit_sha to issues" || \
    echo "  - issues.fix_commit_sha already exists"

sqlite3 "$DB_PATH" "ALTER TABLE issues ADD COLUMN fixed_at DATETIME;" 2>/dev/null && \
    echo "  - Added fixed_at to issues" || \
    echo "  - issues.fixed_at already exists"

sqlite3 "$DB_PATH" "ALTER TABLE issues ADD COLUMN fixed_by VARCHAR(50);" 2>/dev/null && \
    echo "  - Added fixed_by to issues" || \
    echo "  - issues.fixed_by already exists"

echo ""
echo "Migrations complete!"
