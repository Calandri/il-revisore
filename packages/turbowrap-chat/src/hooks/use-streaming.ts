/**
 * Hook for SSE streaming management
 */

import { useCallback, useRef } from 'react';
import { useChatStore } from '../store';
import { useChatClient } from './use-chat-client';
import type { Message, ToolState, AgentState } from '../types';

export interface StreamingHandler {
  /** Send a message and stream the response */
  sendMessage: (sessionId: string, content: string, modelOverride?: string) => Promise<void>;
  /** Abort the current stream for a session */
  abort: (sessionId: string) => void;
  /** Check if a session is currently streaming */
  isStreaming: (sessionId: string) => boolean;
}

/**
 * Hook for managing SSE streaming
 */
export function useStreaming(): StreamingHandler {
  const client = useChatClient();
  const abortControllers = useRef(new Map<string, AbortController>());

  const {
    startStream,
    appendStreamContent,
    addStreamSegment,
    endStream,
    abortStream,
    setStreamError,
    addActiveTool,
    removeActiveTool,
    addActiveAgent,
    addMessage,
    updateSession,
    setPendingMessage,
  } = useChatStore((s) => s.actions);

  const sendMessage = useCallback(async (
    sessionId: string,
    content: string,
    modelOverride?: string
  ): Promise<void> => {
    // Create abort controller
    const controller = new AbortController();
    abortControllers.current.set(sessionId, controller);

    // Start streaming state
    startStream(sessionId);

    // Add user message
    const userMessage: Message = {
      id: `temp-user-${Date.now()}`,
      sessionId,
      role: 'user',
      content,
      isThinking: false,
      createdAt: new Date(),
    };
    addMessage(sessionId, userMessage);

    try {
      await client.streamMessage(sessionId, content, {
        signal: controller.signal,
        modelOverride,

        onChunk: (chunk, fullContent) => {
          appendStreamContent(sessionId, chunk, fullContent);
        },

        onThinking: (thinkingContent) => {
          // Handle thinking content if needed
          appendStreamContent(sessionId, thinkingContent);
        },

        onToolStart: (tool: ToolState) => {
          addActiveTool(sessionId, tool);
          addStreamSegment(sessionId, {
            type: 'tool',
            name: tool.name,
            id: tool.id,
          });
        },

        onToolEnd: (toolName, input) => {
          removeActiveTool(sessionId, toolName, input);
        },

        onAgentStart: (agent: AgentState) => {
          addActiveAgent(sessionId, agent);
          addStreamSegment(sessionId, {
            type: 'agent',
            agentType: agent.type,
            model: agent.model,
            description: agent.description,
          });
        },

        onDone: (messageId, _totalLength) => {
          const state = useChatStore.getState();
          const streamState = state.streamState.get(sessionId);

          // Create final message
          const message: Message = {
            id: messageId,
            sessionId,
            role: 'assistant',
            content: streamState?.content || '',
            segments: streamState?.segments,
            isThinking: false,
            createdAt: new Date(),
          };

          endStream(sessionId, message);

          // Check for pending message
          const pending = streamState?.pendingMessage;
          if (pending) {
            setPendingMessage(sessionId, null);
            // Auto-send after small delay
            setTimeout(() => sendMessage(sessionId, pending), 100);
          }
        },

        onTitleUpdate: (title) => {
          updateSession(sessionId, { displayName: title });
        },

        onError: (error) => {
          setStreamError(sessionId, error.message);
        },
      });
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        abortStream(sessionId);
      } else {
        setStreamError(sessionId, error instanceof Error ? error.message : 'Unknown error');
      }
    } finally {
      abortControllers.current.delete(sessionId);
    }
  }, [
    client,
    startStream,
    appendStreamContent,
    addStreamSegment,
    endStream,
    abortStream,
    setStreamError,
    addActiveTool,
    removeActiveTool,
    addActiveAgent,
    addMessage,
    updateSession,
    setPendingMessage,
  ]);

  const abort = useCallback((sessionId: string) => {
    const controller = abortControllers.current.get(sessionId);
    if (controller) {
      controller.abort();
      abortControllers.current.delete(sessionId);
    }
  }, []);

  const isStreaming = useCallback((sessionId: string): boolean => {
    return useChatStore.getState().streamState.get(sessionId)?.isStreaming ?? false;
  }, []);

  return { sendMessage, abort, isStreaming };
}
