/**
 * Streaming state types for SSE handling
 */

import type { ContentSegment } from './message';

/**
 * Active tool being executed
 */
export interface ToolState {
  name: string;
  id: string;
  startedAt: number;
  input?: Record<string, unknown>;
}

/**
 * Active sub-agent being executed
 */
export interface AgentState {
  type: string;
  model: string;
  description: string;
  startedAt: number;
}

/**
 * Per-session streaming state
 */
export interface StreamState {
  isStreaming: boolean;
  content: string;
  segments: ContentSegment[];
  activeTools: ToolState[];
  activeAgents: AgentState[];
  pendingMessage: string | null;
  error: string | null;
}

/**
 * Create initial streaming state
 */
export function createInitialStreamState(): StreamState {
  return {
    isStreaming: false,
    content: '',
    segments: [{ type: 'text', content: '' }],
    activeTools: [],
    activeAgents: [],
    pendingMessage: null,
    error: null,
  };
}

/**
 * SSE event types from backend
 */
export type SSEEventType =
  | 'start'
  | 'chunk'
  | 'thinking'
  | 'tool_start'
  | 'tool_end'
  | 'agent_start'
  | 'done'
  | 'error'
  | 'status'
  | 'system'
  | 'usage'
  | 'action'
  | 'title_updated';

/**
 * SSE event data structure
 */
export interface SSEEvent {
  type: SSEEventType;
  content?: string;
  sessionId?: string;
  messageId?: string;

  // Tool events
  toolName?: string;
  toolId?: string;
  toolInput?: Record<string, unknown>;

  // Agent events
  agentType?: string;
  agentModel?: string;
  description?: string;

  // Done event
  totalLength?: number;

  // Title event
  title?: string;

  // Action event
  action?: {
    type: 'navigate' | 'highlight';
    target: string;
  };

  // Usage event
  usage?: {
    inputTokens: number;
    outputTokens: number;
    cacheReadInputTokens?: number;
    cacheCreationInputTokens?: number;
  };

  // Error
  error?: string;
  errorType?: string;

  // Generic metadata
  metadata?: Record<string, unknown>;
}

/**
 * Streaming callbacks for SSE handler
 */
export interface StreamingCallbacks {
  onStart?: (sessionId: string) => void;
  onChunk?: (content: string, fullContent?: string) => void;
  onThinking?: (content: string) => void;
  onToolStart?: (tool: ToolState) => void;
  onToolEnd?: (toolName: string, input?: Record<string, unknown>) => void;
  onAgentStart?: (agent: AgentState) => void;
  onDone?: (messageId: string, totalLength: number) => void;
  onTitleUpdate?: (title: string) => void;
  onAction?: (action: { type: 'navigate' | 'highlight'; target: string }) => void;
  onUsage?: (usage: SSEEvent['usage']) => void;
  onError?: (error: Error) => void;
}
