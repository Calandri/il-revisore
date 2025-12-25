-- Migration: Add Linear integration tables and update GitHub issues status
-- Created: 2025-12-25

-- Create linear_issues table
CREATE TABLE IF NOT EXISTS linear_issues (
    id VARCHAR(36) PRIMARY KEY,
    linear_id VARCHAR(100) NOT NULL UNIQUE,
    linear_identifier VARCHAR(50) NOT NULL,
    linear_url VARCHAR(512) NOT NULL,
    linear_team_id VARCHAR(100) NOT NULL,
    linear_team_name VARCHAR(255),

    -- Content
    title VARCHAR(500) NOT NULL,
    description TEXT,
    improved_description TEXT,

    -- Metadata
    assignee_id VARCHAR(100),
    assignee_name VARCHAR(255),
    priority INTEGER DEFAULT 0,
    labels JSON,

    -- Workflow states
    turbowrap_state VARCHAR(50) DEFAULT 'analysis' NOT NULL,
    linear_state_id VARCHAR(100),
    linear_state_name VARCHAR(100),

    -- Cached Linear state IDs (for performance)
    linear_state_triage_id VARCHAR(100),
    linear_state_todo_id VARCHAR(100),
    linear_state_inprogress_id VARCHAR(100),
    linear_state_inreview_id VARCHAR(100),
    linear_state_done_id VARCHAR(100),

    -- Active development constraint
    is_active BOOLEAN DEFAULT FALSE,

    -- Analysis results
    analysis_summary TEXT,
    analysis_comment_id VARCHAR(100),
    analyzed_at TIMESTAMP,
    analyzed_by VARCHAR(100),
    user_answers JSON,

    -- Development results
    task_id VARCHAR(36),
    fix_commit_sha VARCHAR(40),
    fix_branch VARCHAR(100),
    fix_explanation TEXT,
    fix_files_modified JSON,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_at TIMESTAMP,
    deleted_at TIMESTAMP,

    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Create indexes for linear_issues
CREATE INDEX IF NOT EXISTS idx_linear_issues_linear_id ON linear_issues(linear_id);
CREATE INDEX IF NOT EXISTS idx_linear_issues_identifier ON linear_issues(linear_identifier);
CREATE INDEX IF NOT EXISTS idx_linear_issues_team ON linear_issues(linear_team_id);
CREATE INDEX IF NOT EXISTS idx_linear_issues_state ON linear_issues(turbowrap_state);
CREATE INDEX IF NOT EXISTS idx_linear_issues_active ON linear_issues(is_active);
CREATE INDEX IF NOT EXISTS idx_linear_issues_deleted ON linear_issues(deleted_at);

-- Create linear_issue_repository_links table
CREATE TABLE IF NOT EXISTS linear_issue_repository_links (
    id VARCHAR(36) PRIMARY KEY,
    linear_issue_id VARCHAR(36) NOT NULL,
    repository_id VARCHAR(36) NOT NULL,
    link_source VARCHAR(50) NOT NULL,
    source_label VARCHAR(100),
    confidence_score FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (linear_issue_id) REFERENCES linear_issues(id) ON DELETE CASCADE,
    FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
    UNIQUE (linear_issue_id, repository_id)
);

-- Create indexes for linear_issue_repository_links
CREATE INDEX IF NOT EXISTS idx_linear_repo_links_issue ON linear_issue_repository_links(linear_issue_id);
CREATE INDEX IF NOT EXISTS idx_linear_repo_links_repo ON linear_issue_repository_links(repository_id);

-- Insert Linear settings
INSERT INTO settings (key, value, is_secret, description, created_at, updated_at)
VALUES
    ('linear_api_key', NULL, 'Y', 'Linear API key', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('linear_team_id', NULL, 'N', 'Linear team ID per sync', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('linear_state_triage_id', NULL, 'N', 'Linear Triage state ID', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('linear_state_todo_id', NULL, 'N', 'Linear To Do state ID', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('linear_state_inprogress_id', NULL, 'N', 'Linear In Progress state ID', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('linear_state_inreview_id', NULL, 'N', 'Linear In Review state ID', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('linear_state_done_id', NULL, 'N', 'Linear Done state ID', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (key) DO NOTHING;

-- Migration: Rename "done" to "in_review" for existing GitHub issues
-- This affects the IssueStatus enum value
UPDATE issues SET status = 'in_review' WHERE status = 'done';

-- Add comment for migration tracking
COMMENT ON TABLE linear_issues IS 'Linear issues imported for development workflow';
COMMENT ON TABLE linear_issue_repository_links IS 'Links Linear issues to TurboWrap repositories';
