/**
 * useSharedWorker - Hook to connect to the existing TurboWrap SharedWorker
 *
 * This integrates with the existing chat-worker.js that handles SSE persistence
 */

import { useEffect, useRef, useCallback } from 'react';
import { useChatStore } from '../store/chat-store';
import type { ContentSegment } from '../types';

// Worker message types (matching chat-worker.js)
export type WorkerMessageType =
  | 'SEND_MESSAGE'
  | 'STOP_STREAM'
  | 'GET_STATE'
  | 'CLEAR_STATE'
  | 'PONG';

export type WorkerEventType =
  | 'STREAM_START'
  | 'CHUNK'
  | 'SYSTEM'
  | 'TOOL_START'
  | 'TOOL_END'
  | 'AGENT_START'
  | 'AGENT_END'
  | 'ACTION'
  | 'DONE'
  | 'STREAM_END'
  | 'ERROR'
  | 'STREAM_ABORTED'
  | 'STATE_SYNC'
  | 'TITLE_UPDATE';

interface WorkerMessage {
  type: WorkerEventType;
  sessionId?: string;
  data?: unknown;
}

interface SendMessagePayload {
  sessionId: string;
  content: string;
  apiUrl: string;
}

interface UseSharedWorkerOptions {
  workerUrl?: string;
  apiUrl: string;
  onAction?: (type: 'navigate' | 'highlight', target: string) => void;
  onTitleUpdate?: (sessionId: string, title: string) => void;
  onError?: (error: Error) => void;
}

/**
 * Hook that connects to the TurboWrap SharedWorker for SSE persistence
 */
export function useSharedWorker(options: UseSharedWorkerOptions) {
  const { apiUrl, onAction, onTitleUpdate, onError } = options;
  const workerRef = useRef<SharedWorker | null>(null);
  const portRef = useRef<MessagePort | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const store = useChatStore();

  // Handle messages from the worker
  const handleWorkerMessage = useCallback((event: MessageEvent) => {
    const message = event.data as WorkerMessage;
    const { type, sessionId, data } = message;

    if (!sessionId && type !== 'STATE_SYNC') return;

    const actions = store.actions;

    switch (type) {
      case 'STREAM_START':
        if (sessionId) {
          actions.startStream(sessionId);
        }
        break;

      case 'CHUNK': {
        const chunkData = data as { content?: string };
        if (sessionId && chunkData?.content) {
          actions.appendStreamContent(sessionId, chunkData.content);
        }
        break;
      }

      case 'SYSTEM': {
        // Token usage updates - could update session stats
        break;
      }

      case 'TOOL_START': {
        const toolData = data as { tool_name: string; tool_id: string };
        if (sessionId && toolData) {
          actions.addActiveTool(sessionId, {
            id: toolData.tool_id,
            name: toolData.tool_name,
            startedAt: Date.now(),
          });
        }
        break;
      }

      case 'TOOL_END': {
        const toolEndData = data as { tool_name: string; tool_id?: string; tool_input?: Record<string, unknown> };
        if (sessionId && toolEndData) {
          actions.removeActiveTool(sessionId, toolEndData.tool_id || toolEndData.tool_name);
        }
        break;
      }

      case 'AGENT_START': {
        const agentData = data as { agent_type: string; agent_model: string; description: string };
        if (sessionId && agentData) {
          actions.addActiveAgent(sessionId, {
            type: agentData.agent_type,
            model: agentData.agent_model,
            description: agentData.description,
            startedAt: Date.now(),
          });
        }
        break;
      }

      case 'AGENT_END': {
        // Agent completed - could track in store
        break;
      }

      case 'ACTION': {
        const actionData = data as { type: 'navigate' | 'highlight'; target: string };
        if (actionData) {
          onAction?.(actionData.type, actionData.target);
        }
        break;
      }

      case 'DONE':
      case 'STREAM_END': {
        if (sessionId) {
          actions.endStream(sessionId);
        }
        break;
      }

      case 'STREAM_ABORTED': {
        if (sessionId) {
          actions.abortStream(sessionId);
        }
        break;
      }

      case 'ERROR': {
        const errorData = data as { message?: string };
        if (sessionId) {
          actions.endStream(sessionId);
        }
        onError?.(new Error(errorData?.message || 'Stream error'));
        break;
      }

      case 'TITLE_UPDATE': {
        const titleData = data as { title: string };
        if (sessionId && titleData?.title) {
          onTitleUpdate?.(sessionId, titleData.title);
          actions.updateSession(sessionId, { displayName: titleData.title });
        }
        break;
      }

      case 'STATE_SYNC': {
        // Sync state from worker on page reconnect
        const syncData = data as Record<string, {
          streaming: boolean;
          streamContent: string;
          segments?: ContentSegment[];
        }>;
        if (syncData) {
          Object.entries(syncData).forEach(([sid, state]) => {
            if (state.streaming) {
              actions.startStream(sid);
              if (state.streamContent) {
                actions.appendStreamContent(sid, state.streamContent);
              }
            }
          });
        }
        break;
      }
    }
  }, [store, onAction, onTitleUpdate, onError]);

  // Initialize worker connection
  useEffect(() => {
    // Check if SharedWorker is supported
    if (typeof SharedWorker === 'undefined') {
      console.warn('SharedWorker not supported, falling back to direct fetch');
      return;
    }

    try {
      // Connect to existing TurboWrap worker
      const workerUrl = options.workerUrl || '/static/js/chat-worker.js';
      workerRef.current = new SharedWorker(workerUrl, { name: 'turbowrap-chat' });
      portRef.current = workerRef.current.port;

      // Setup message handler
      portRef.current.onmessage = handleWorkerMessage;
      portRef.current.start();

      // Request initial state sync
      portRef.current.postMessage({ type: 'GET_STATE' });

      // Setup heartbeat
      heartbeatRef.current = setInterval(() => {
        portRef.current?.postMessage({ type: 'PONG' });
      }, 30000);

    } catch (error) {
      console.error('Failed to connect to SharedWorker:', error);
      onError?.(error instanceof Error ? error : new Error('Worker connection failed'));
    }

    return () => {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
      }
      portRef.current?.close();
    };
  }, [options.workerUrl, handleWorkerMessage, onError]);

  // Send message via worker
  const sendMessage = useCallback((sessionId: string, content: string) => {
    if (!portRef.current) {
      onError?.(new Error('Worker not connected'));
      return;
    }

    const payload: SendMessagePayload = {
      sessionId,
      content,
      apiUrl,
    };

    portRef.current.postMessage({
      type: 'SEND_MESSAGE',
      ...payload,
    });
  }, [apiUrl, onError]);

  // Stop streaming
  const stopStream = useCallback((sessionId: string) => {
    if (!portRef.current) return;

    portRef.current.postMessage({
      type: 'STOP_STREAM',
      sessionId,
    });

    store.actions.abortStream(sessionId);
  }, [store]);

  // Clear state for session
  const clearState = useCallback((sessionId: string) => {
    if (!portRef.current) return;

    portRef.current.postMessage({
      type: 'CLEAR_STATE',
      sessionId,
    });
  }, []);

  return {
    sendMessage,
    stopStream,
    clearState,
    isConnected: !!portRef.current,
  };
}
