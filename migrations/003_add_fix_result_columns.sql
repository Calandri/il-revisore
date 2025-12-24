-- Migration: Add fix result columns to issues table
-- Date: 2024-12-24
-- Description: Columns to store fix results when an issue is fixed

-- Add fix result columns
ALTER TABLE issues ADD COLUMN fix_code TEXT;
ALTER TABLE issues ADD COLUMN fix_explanation TEXT;
ALTER TABLE issues ADD COLUMN fix_files_modified JSON;
ALTER TABLE issues ADD COLUMN fix_commit_sha VARCHAR(40);
ALTER TABLE issues ADD COLUMN fixed_at DATETIME;
ALTER TABLE issues ADD COLUMN fixed_by VARCHAR(50);

-- Example usage after fix:
-- UPDATE issues SET
--   status = 'resolved',
--   fix_code = 'const sanitized = DOMPurify.sanitize(html);',
--   fix_explanation = 'Added DOMPurify sanitization before innerHTML assignment to prevent XSS attacks.',
--   fix_files_modified = '["src/components/Preview.tsx"]',
--   fix_commit_sha = 'abc1234567890',
--   fixed_at = CURRENT_TIMESTAMP,
--   fixed_by = 'fixer_claude'
-- WHERE id = 'issue-uuid';
