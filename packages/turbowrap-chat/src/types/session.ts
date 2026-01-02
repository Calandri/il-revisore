/**
 * Session types - mirrors backend Pydantic schemas
 */

export type CLIType = 'claude' | 'gemini';

export type SessionStatus =
  | 'idle'
  | 'starting'
  | 'running'
  | 'streaming'
  | 'stopping'
  | 'error'
  | 'completed';

/**
 * Chat session data from API
 */
export interface Session {
  id: string;
  cliType: CLIType;
  repositoryId: string | null;
  currentBranch: string | null;
  status: SessionStatus;

  // Mockup context
  mockupProjectId?: string | null;
  mockupId?: string | null;

  // Configuration
  model: string | null;
  agentName: string | null;
  thinkingEnabled: boolean;
  thinkingBudget: number;
  reasoningEnabled: boolean;
  mcpServers: string[] | null;
  claudeSessionId: string | null;

  // UI
  icon: string;
  color: string;
  displayName: string | null;
  position: number;

  // Stats
  totalMessages: number;
  totalTokensIn: number;
  totalTokensOut: number;

  // Timestamps
  createdAt: Date;
  updatedAt: Date;
  lastMessageAt: Date | null;
}

/**
 * Request to create a new session
 */
export interface CreateSessionOptions {
  cliType: CLIType;
  repositoryId?: string;
  displayName?: string;
  icon?: string;
  color?: string;
  mockupProjectId?: string;
  mockupId?: string;
}

/**
 * Request to update session settings
 */
export interface UpdateSessionOptions {
  displayName?: string;
  icon?: string;
  color?: string;
  position?: number;
  model?: string;
  agentName?: string;
  thinkingEnabled?: boolean;
  thinkingBudget?: number;
  reasoningEnabled?: boolean;
  mcpServers?: string[];
  mockupProjectId?: string;
  mockupId?: string;
}

/**
 * Transform API response to Session type
 */
export function transformSession(data: SessionAPIResponse): Session {
  return {
    id: data.id,
    cliType: data.cli_type,
    repositoryId: data.repository_id,
    currentBranch: data.current_branch,
    status: data.status,
    mockupProjectId: data.mockup_project_id,
    mockupId: data.mockup_id,
    model: data.model,
    agentName: data.agent_name,
    thinkingEnabled: data.thinking_enabled,
    thinkingBudget: data.thinking_budget,
    reasoningEnabled: data.reasoning_enabled,
    mcpServers: data.mcp_servers,
    claudeSessionId: data.claude_session_id,
    icon: data.icon,
    color: data.color,
    displayName: data.display_name,
    position: data.position,
    totalMessages: data.total_messages,
    totalTokensIn: data.total_tokens_in,
    totalTokensOut: data.total_tokens_out,
    createdAt: new Date(data.created_at),
    updatedAt: new Date(data.updated_at),
    lastMessageAt: data.last_message_at ? new Date(data.last_message_at) : null,
  };
}

/**
 * Raw API response (snake_case from Python backend)
 */
export interface SessionAPIResponse {
  id: string;
  cli_type: CLIType;
  repository_id: string | null;
  current_branch: string | null;
  status: SessionStatus;
  mockup_project_id?: string | null;
  mockup_id?: string | null;
  model: string | null;
  agent_name: string | null;
  thinking_enabled: boolean;
  thinking_budget: number;
  reasoning_enabled: boolean;
  mcp_servers: string[] | null;
  claude_session_id: string | null;
  icon: string;
  color: string;
  display_name: string | null;
  position: number;
  total_messages: number;
  total_tokens_in: number;
  total_tokens_out: number;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
}
