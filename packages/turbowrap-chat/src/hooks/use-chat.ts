/**
 * Main chat hook - combines sessions, messages, and streaming
 */

import { useCallback } from 'react';
import { useChatStore } from '../store';
import {
  selectActiveSession,
  selectActiveMessages,
  selectActiveStreamState,
} from '../store/selectors';
import { useStreaming } from './use-streaming';
import type { Message, ContentSegment, ToolState, AgentState } from '../types';

export interface UseChatOptions {
  /** Session ID to use (defaults to active session) */
  sessionId?: string;
  /** Callback when a message is received */
  onMessageReceived?: (message: Message) => void;
  /** Callback when streaming starts */
  onStreamStart?: () => void;
  /** Callback when streaming ends */
  onStreamEnd?: () => void;
  /** Callback on error */
  onError?: (error: Error) => void;
}

export interface UseChatReturn {
  // State
  /** Messages for the current session */
  messages: Message[];
  /** Whether the session is currently streaming */
  isStreaming: boolean;
  /** Current stream content */
  streamContent: string;
  /** Current stream segments (text + tool + agent interleaved) */
  streamSegments: ContentSegment[];
  /** Currently active tools */
  activeTools: ToolState[];
  /** Currently active agents */
  activeAgents: AgentState[];
  /** Current error */
  error: string | null;
  /** Pending queued message */
  pendingMessage: string | null;

  // Actions
  /** Send a message */
  sendMessage: (content: string, modelOverride?: string) => Promise<void>;
  /** Stop the current stream */
  stopStream: () => void;
  /** Queue a message (sent when current stream ends) */
  queueMessage: (content: string) => void;
  /** Clear the current error */
  clearError: () => void;
}

/**
 * Main hook for chat functionality
 */
export function useChat(options: UseChatOptions = {}): UseChatReturn {
  const { sessionId: providedSessionId } = options;

  // Get session ID
  const activeSession = useChatStore(selectActiveSession);
  const sessionId = providedSessionId || activeSession?.id;

  // Get messages
  const activeMessages = useChatStore(selectActiveMessages);
  const messages = providedSessionId
    ? useChatStore((s) => s.messages.get(providedSessionId) ?? [])
    : activeMessages;

  // Get stream state
  const activeStreamState = useChatStore(selectActiveStreamState);
  const streamState = providedSessionId
    ? useChatStore((s) => s.streamState.get(providedSessionId))
    : activeStreamState;

  // Actions
  const { setPendingMessage, setStreamError } = useChatStore((s) => s.actions);
  const streaming = useStreaming();

  const sendMessage = useCallback(async (content: string, modelOverride?: string) => {
    if (!sessionId) {
      throw new Error('No session selected');
    }

    // If already streaming, queue the message
    if (streamState?.isStreaming) {
      setPendingMessage(sessionId, content);
      return;
    }

    await streaming.sendMessage(sessionId, content, modelOverride);
  }, [sessionId, streamState?.isStreaming, setPendingMessage, streaming]);

  const stopStream = useCallback(() => {
    if (sessionId) {
      streaming.abort(sessionId);
    }
  }, [sessionId, streaming]);

  const queueMessage = useCallback((content: string) => {
    if (sessionId) {
      setPendingMessage(sessionId, content);
    }
  }, [sessionId, setPendingMessage]);

  const clearError = useCallback(() => {
    if (sessionId) {
      setStreamError(sessionId, null);
    }
  }, [sessionId, setStreamError]);

  return {
    messages,
    isStreaming: streamState?.isStreaming ?? false,
    streamContent: streamState?.content ?? '',
    streamSegments: streamState?.segments ?? [],
    activeTools: streamState?.activeTools ?? [],
    activeAgents: streamState?.activeAgents ?? [],
    error: streamState?.error ?? null,
    pendingMessage: streamState?.pendingMessage ?? null,
    sendMessage,
    stopStream,
    queueMessage,
    clearError,
  };
}
