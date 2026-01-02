/**
 * SSE (Server-Sent Events) stream parser
 */

import type { SSEEventType, StreamingCallbacks, ToolState, AgentState } from '../types';

/**
 * Parse SSE stream from fetch Response
 */
export async function parseSSEStream(
  response: Response,
  callbacks: StreamingCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError?.(new Error('Response body is not readable'));
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let dataBuffer = ''; // Accumulates incomplete JSON data across chunks
  let currentEventType: SSEEventType = 'chunk';

  try {
    while (true) {
      if (signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError');
      }

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        // Skip empty lines (SSE keepalive)
        if (!line.trim()) continue;

        if (line.startsWith('event: ')) {
          currentEventType = line.slice(7).trim() as SSEEventType;
          // Reset data buffer when new event starts
          dataBuffer = '';
        } else if (line.startsWith('data: ')) {
          // Accumulate data (could be split across multiple lines)
          dataBuffer += line.slice(6);
          try {
            const data = JSON.parse(dataBuffer);
            processSSEEvent(currentEventType, data, callbacks);
            currentEventType = 'chunk'; // Reset after processing
            dataBuffer = ''; // Clear buffer after successful parse
          } catch {
            // Incomplete JSON, continue accumulating in dataBuffer
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Process a single SSE event and dispatch to callbacks
 */
function processSSEEvent(
  eventType: SSEEventType,
  data: Record<string, unknown>,
  callbacks: StreamingCallbacks
): void {
  switch (eventType) {
    case 'start':
      if (typeof data.session_id === 'string') {
        callbacks.onStart?.(data.session_id);
      }
      break;

    case 'chunk':
      if (typeof data.content === 'string') {
        callbacks.onChunk?.(
          data.content,
          typeof data.fullContent === 'string' ? data.fullContent : undefined
        );
      }
      break;

    case 'thinking':
      if (typeof data.content === 'string') {
        callbacks.onThinking?.(data.content);
      }
      break;

    case 'tool_start': {
      if (typeof data.tool_name !== 'string' || typeof data.tool_id !== 'string') {
        break;
      }
      const tool: ToolState = {
        name: data.tool_name,
        id: data.tool_id,
        startedAt: Date.now(),
      };
      callbacks.onToolStart?.(tool);
      break;
    }

    case 'tool_end':
      if (typeof data.tool_name === 'string') {
        callbacks.onToolEnd?.(
          data.tool_name,
          typeof data.tool_input === 'object' && data.tool_input !== null
            ? (data.tool_input as Record<string, unknown>)
            : undefined
        );
      }
      break;

    case 'agent_start': {
      if (
        typeof data.agent_type !== 'string' ||
        typeof data.agent_model !== 'string' ||
        typeof data.description !== 'string'
      ) {
        break;
      }
      const agent: AgentState = {
        type: data.agent_type,
        model: data.agent_model,
        description: data.description,
        startedAt: Date.now(),
      };
      callbacks.onAgentStart?.(agent);
      break;
    }

    case 'done':
      if (typeof data.message_id === 'string' && typeof data.total_length === 'number') {
        callbacks.onDone?.(data.message_id, data.total_length);
      }
      break;

    case 'title_updated':
      if (typeof data.title === 'string') {
        callbacks.onTitleUpdate?.(data.title);
      }
      break;

    case 'action':
      if (
        (data.type === 'navigate' || data.type === 'highlight') &&
        typeof data.target === 'string'
      ) {
        callbacks.onAction?.({
          type: data.type,
          target: data.target,
        });
      }
      break;

    case 'usage':
      if (typeof data.input_tokens === 'number' && typeof data.output_tokens === 'number') {
        callbacks.onUsage?.({
          inputTokens: data.input_tokens,
          outputTokens: data.output_tokens,
          cacheReadInputTokens:
            typeof data.cache_read_input_tokens === 'number'
              ? data.cache_read_input_tokens
              : undefined,
          cacheCreationInputTokens:
            typeof data.cache_creation_input_tokens === 'number'
              ? data.cache_creation_input_tokens
              : undefined,
        });
      }
      break;

    case 'error':
      if (typeof data.error === 'string') {
        callbacks.onError?.(new Error(data.error));
      }
      break;

    case 'system':
    case 'status':
      // System events can be handled if needed
      break;
  }
}

/**
 * Reconnection configuration for SSE streams
 */
export interface SSEReconnectConfig {
  maxRetries?: number;
  retryDelay?: number;
  exponentialBackoff?: boolean;
  maxRetryDelay?: number;
  onReconnecting?: (attempt: number) => void;
  onReconnected?: () => void;
  onMaxRetriesExceeded?: () => void;
}

/**
 * Calculate retry delay with exponential backoff
 */
export function calculateRetryDelay(
  attempt: number,
  config: SSEReconnectConfig
): number {
  const baseDelay = config.retryDelay ?? 1000;
  const maxDelay = config.maxRetryDelay ?? 30000;

  if (!config.exponentialBackoff) {
    return baseDelay;
  }

  const delay = baseDelay * Math.pow(2, attempt);
  return Math.min(delay, maxDelay);
}
