/**
 * Event types for context, usage, and actions
 */

/**
 * Token category in context breakdown
 */
export interface TokenCategory {
  name: string;
  tokens: number;
  percentage?: number;
}

/**
 * MCP tool info
 */
export interface MCPTool {
  name: string;
  server?: string;
  tokens?: number;
}

/**
 * Agent info in context
 */
export interface AgentInfo {
  name: string;
  source?: string;
  tokens?: number;
}

/**
 * Context info from /context endpoint
 */
export interface ContextInfo {
  model?: string;
  tokens: {
    used: number;
    limit: number;
    percentage: number;
  };
  categories: TokenCategory[];
  mcpTools: MCPTool[];
  agents: AgentInfo[];
}

/**
 * MCP server status
 */
export interface MCPServerStatus {
  name: string;
  connected: boolean;
}

/**
 * Usage info from /usage endpoint
 */
export interface UsageInfo {
  version?: string;
  sessionId?: string;
  cwd?: string;
  loginMethod?: string;
  organization?: string;
  email?: string;
  model?: string;
  modelId?: string;
  ide?: string;
  ideVersion?: string;
  mcpServers: MCPServerStatus[];
  memory?: string;
  settingSources?: string;
  // Token usage
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  cost?: number;
}

/**
 * System event during streaming
 */
export interface SystemEvent {
  type: 'system';
  subtype: 'init' | 'context' | 'other';
  data?: Record<string, unknown>;
}

/**
 * Action event from AI response
 */
export interface ActionEvent {
  type: 'navigate' | 'highlight';
  target: string;
}

/**
 * Agent from /agents endpoint
 */
export interface Agent {
  id: string;
  name: string;
  version: string;
  tokens: number;
  description: string;
  model: string;
  color: string;
  path: string;
  type: 'reviewer' | 'fixer' | 'analyzer' | 'creator' | 'general';
}

/**
 * Repository info
 */
export interface Repository {
  id: string;
  name: string;
  fullName?: string;
  path: string;
  defaultBranch: string;
  url?: string;
}
