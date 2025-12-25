-- Migration: Add fix_session_id column to issues table
-- Date: 2024-12-25
-- Description: Column to link issues to their S3 fix log for prompt retrieval

-- Add fix_session_id column
ALTER TABLE issues ADD COLUMN fix_session_id VARCHAR(36);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_issues_fix_session_id ON issues(fix_session_id);

-- The fix_session_id is a UUID that links to the S3 fix log:
-- s3://turbowrap-thinking/fix-logs/{date}/{fix_session_id}.json
--
-- This allows retrieving:
-- - claude_prompts: Array of prompts sent to Claude CLI
-- - gemini_prompt: Prompt sent to Gemini CLI for review
-- - gemini_review: Gemini's review output
