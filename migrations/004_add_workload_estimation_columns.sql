-- Migration: Add workload estimation columns to issues table
-- Date: 2024-12-25
-- Description: Columns for reviewer to estimate fix effort, used by orchestrator for dynamic batching

-- Add workload estimation columns
ALTER TABLE issues ADD COLUMN estimated_effort INTEGER;
ALTER TABLE issues ADD COLUMN estimated_files_count INTEGER;

-- estimated_effort: 1-5 scale
--   1 = trivial (simple typo, obvious fix)
--   2 = simple (single line change, clear fix)
--   3 = moderate (multi-line change, some context needed)
--   4 = complex (significant changes, multiple considerations)
--   5 = major refactor (architectural change, affects many parts)

-- estimated_files_count: Number of files that need to be modified to fix the issue
--   1 = single file fix
--   2+ = affects multiple files (dependency updates, interface changes, etc.)

-- Example usage after review:
-- UPDATE issues SET
--   estimated_effort = 3,
--   estimated_files_count = 2
-- WHERE id = 'issue-uuid';
