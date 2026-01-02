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
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            processSSEEvent(currentEventType, data, callbacks);
            currentEventType = 'chunk'; // Reset after processing
          } catch {
            // Incomplete JSON, continue accumulating
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
      callbacks.onStart?.(data.session_id as string);
      break;

    case 'chunk':
      if (data.content) {
        callbacks.onChunk?.(
          data.content as string,
          data.fullContent as string | undefined
        );
      }
      break;

    case 'thinking':
      if (data.content) {
        callbacks.onThinking?.(data.content as string);
      }
      break;

    case 'tool_start': {
      const tool: ToolState = {
        name: data.tool_name as string,
        id: data.tool_id as string,
        startedAt: Date.now(),
      };
      callbacks.onToolStart?.(tool);
      break;
    }

    case 'tool_end':
      callbacks.onToolEnd?.(
        data.tool_name as string,
        data.tool_input as Record<string, unknown> | undefined
      );
      break;

    case 'agent_start': {
      const agent: AgentState = {
        type: data.agent_type as string,
        model: data.agent_model as string,
        description: data.description as string,
        startedAt: Date.now(),
      };
      callbacks.onAgentStart?.(agent);
      break;
    }

    case 'done':
      callbacks.onDone?.(
        data.message_id as string,
        data.total_length as number
      );
      break;

    case 'title_updated':
      callbacks.onTitleUpdate?.(data.title as string);
      break;

    case 'action':
      if (data.type && data.target) {
        callbacks.onAction?.({
          type: data.type as 'navigate' | 'highlight',
          target: data.target as string,
        });
      }
      break;

    case 'usage':
      callbacks.onUsage?.({
        inputTokens: data.input_tokens as number,
        outputTokens: data.output_tokens as number,
        cacheReadInputTokens: data.cache_read_input_tokens as number | undefined,
        cacheCreationInputTokens: data.cache_creation_input_tokens as number | undefined,
      });
      break;

    case 'error':
      callbacks.onError?.(new Error(data.error as string));
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
