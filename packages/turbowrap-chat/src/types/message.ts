/**
 * Message types - mirrors backend Pydantic schemas
 */

export type MessageRole = 'user' | 'assistant' | 'system';

/**
 * Content segment within a message (for tool/agent interleaving)
 */
export interface ContentSegment {
  type: 'text' | 'tool' | 'agent';
  content?: string;
  // Tool-specific
  name?: string;
  id?: string;
  input?: Record<string, unknown>;
  completedAt?: number;
  // Agent-specific
  agentType?: string;
  model?: string;
  description?: string;
  launchedAt?: number;
}

/**
 * Chat message
 */
export interface Message {
  id: string;
  sessionId: string;
  role: MessageRole;
  content: string;
  segments?: ContentSegment[];
  isThinking: boolean;

  // Metadata
  tokensIn?: number;
  tokensOut?: number;
  modelUsed?: string;
  agentUsed?: string;
  durationMs?: number;

  createdAt: Date;
}

/**
 * Request to send a message
 */
export interface SendMessageOptions {
  content: string;
  modelOverride?: string;
}

/**
 * Transform API response to Message type
 */
export function transformMessage(data: MessageAPIResponse): Message {
  return {
    id: data.id,
    sessionId: data.session_id,
    role: data.role,
    content: data.content,
    isThinking: data.is_thinking,
    tokensIn: data.tokens_in ?? undefined,
    tokensOut: data.tokens_out ?? undefined,
    modelUsed: data.model_used ?? undefined,
    agentUsed: data.agent_used ?? undefined,
    durationMs: data.duration_ms ?? undefined,
    createdAt: new Date(data.created_at),
  };
}

/**
 * Raw API response (snake_case from Python backend)
 */
export interface MessageAPIResponse {
  id: string;
  session_id: string;
  role: MessageRole;
  content: string;
  is_thinking: boolean;
  tokens_in: number | null;
  tokens_out: number | null;
  model_used: string | null;
  agent_used: string | null;
  duration_ms: number | null;
  created_at: string;
}
