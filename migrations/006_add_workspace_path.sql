-- Migration: Add workspace_path for monorepo support
-- Date: 2025-12-25
-- Description: Adds workspace_path column to repositories table.
--              Allows same GitHub URL to be cloned multiple times with different workspaces.
--              When workspace_path is set, all fix/lint operations are scoped to that folder.

-- Add workspace_path column (relative path within repo, e.g., "packages/frontend")
ALTER TABLE repositories ADD COLUMN workspace_path VARCHAR(512);

-- Note: We intentionally do NOT add a unique constraint on (url, workspace_path)
-- because the same repo can have workspace_path = NULL (full repo) and also
-- specific workspaces. The local_path will be unique anyway.
