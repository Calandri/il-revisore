/**
 * API client configuration types
 */

import type { StreamingCallbacks } from '../types/streaming';

/**
 * Configuration for ChatAPIClient
 */
export interface ChatClientConfig {
  /** Base URL for the API (e.g., 'https://api.turbowrap.io') */
  baseUrl: string;

  /** Optional static headers to include in all requests */
  headers?: Record<string, string>;

  /** Function to get auth token (called before each request) */
  getAuthToken?: () => string | Promise<string>;

  /** Request timeout in milliseconds (default: 120000) */
  timeout?: number;

  /** Callback when auth token is invalid (401 response) */
  onUnauthorized?: () => void;

  /** Global error callback */
  onError?: (error: Error) => void;
}

/**
 * Options for streaming a message
 */
export interface StreamMessageOptions extends StreamingCallbacks {
  /** AbortSignal for cancellation */
  signal?: AbortSignal;

  /** Override model for this message */
  modelOverride?: string;
}

/**
 * Options for fetching sessions
 */
export interface GetSessionsOptions {
  /** Filter by repository ID */
  repositoryId?: string;

  /** Filter by CLI type */
  cliType?: 'claude' | 'gemini';

  /** Maximum number of sessions to return */
  limit?: number;
}

/**
 * Options for fetching messages
 */
export interface GetMessagesOptions {
  /** Maximum number of messages to return */
  limit?: number;

  /** Include extended thinking messages */
  includeThinking?: boolean;
}

/**
 * API error with additional context
 */
export class ChatAPIError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
    this.name = 'ChatAPIError';
  }
}
