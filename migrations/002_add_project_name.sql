-- Migration 002: Add project_name column to repositories for grouping related repos
-- Run with: sqlite3 ~/.turbowrap/turbowrap.db < migrations/002_add_project_name.sql

-- Add project_name column to repositories
ALTER TABLE repositories ADD COLUMN project_name VARCHAR(255);

-- Create index for faster project filtering
CREATE INDEX IF NOT EXISTS idx_repositories_project_name ON repositories(project_name);
