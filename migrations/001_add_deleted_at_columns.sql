-- Migration 001: Add deleted_at columns for soft delete support
-- Run with: sqlite3 ~/.turbowrap/turbowrap.db < migrations/001_add_deleted_at_columns.sql

-- Add deleted_at to chat_sessions (ignore if exists)
ALTER TABLE chat_sessions ADD COLUMN deleted_at DATETIME;

-- Add deleted_at to issues (ignore if exists)
ALTER TABLE issues ADD COLUMN deleted_at DATETIME;

-- repositories and tasks already have deleted_at, but add if missing
-- SQLite doesn't support IF NOT EXISTS for ALTER TABLE, so these may error if column exists
-- ALTER TABLE repositories ADD COLUMN deleted_at DATETIME;
-- ALTER TABLE tasks ADD COLUMN deleted_at DATETIME;
