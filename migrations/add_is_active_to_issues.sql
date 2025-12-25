-- Add is_active column to issues table for Active Development banner
ALTER TABLE issues ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT FALSE;

-- Create index for performance
CREATE INDEX IF NOT EXISTS idx_issues_is_active ON issues(is_active);

-- Add comment
COMMENT ON COLUMN issues.is_active IS 'True when issue is actively being developed (shown in sidebar banner)';
