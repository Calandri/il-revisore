/**
 * Zustand store for @turbowrap/chat
 */

import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';
import type { Session, Message, Agent, ContentSegment } from '../types';
import { createInitialStreamState } from '../types';
import type { ChatStore, ChatMode, ActivePane } from './types';

/**
 * Initial state
 */
const initialState = {
  sessions: new Map<string, Session>(),
  activeSessionId: null as string | null,
  secondarySessionId: null as string | null,
  messages: new Map<string, Message[]>(),
  streamState: new Map(),
  agents: [] as Agent[],
  isInitialized: false,
  chatMode: 'third' as ChatMode,
  dualChatEnabled: false,
  showHistory: false,
  showSettings: false,
  activePane: 'left' as ActivePane,
};

/**
 * Main chat store
 */
export const useChatStore = create<ChatStore>()(
  devtools(
    subscribeWithSelector((set, get) => ({
      ...initialState,

      actions: {
        // ======================================================================
        // Session management
        // ======================================================================

        setActiveSession: (sessionId) => {
          set({ activeSessionId: sessionId }, false, 'setActiveSession');
        },

        setSecondarySession: (sessionId) => {
          set({ secondarySessionId: sessionId }, false, 'setSecondarySession');
        },

        addSession: (session) => {
          set((state) => {
            const sessions = new Map(state.sessions);
            sessions.set(session.id, session);

            const messages = new Map(state.messages);
            messages.set(session.id, []);

            const streamState = new Map(state.streamState);
            streamState.set(session.id, createInitialStreamState());

            return { sessions, messages, streamState };
          }, false, 'addSession');
        },

        updateSession: (sessionId, updates) => {
          set((state) => {
            const sessions = new Map(state.sessions);
            const session = sessions.get(sessionId);
            if (session) {
              sessions.set(sessionId, { ...session, ...updates });
            }
            return { sessions };
          }, false, 'updateSession');
        },

        removeSession: (sessionId) => {
          set((state) => {
            const sessions = new Map(state.sessions);
            sessions.delete(sessionId);

            const messages = new Map(state.messages);
            messages.delete(sessionId);

            const streamState = new Map(state.streamState);
            streamState.delete(sessionId);

            const activeSessionId = state.activeSessionId === sessionId
              ? null
              : state.activeSessionId;
            const secondarySessionId = state.secondarySessionId === sessionId
              ? null
              : state.secondarySessionId;

            return { sessions, messages, streamState, activeSessionId, secondarySessionId };
          }, false, 'removeSession');
        },

        setSessions: (sessions) => {
          set((state) => {
            const sessionsMap = new Map<string, Session>();
            const messagesMap = new Map(state.messages);
            const streamStateMap = new Map(state.streamState);

            for (const session of sessions) {
              sessionsMap.set(session.id, session);
              if (!messagesMap.has(session.id)) {
                messagesMap.set(session.id, []);
              }
              if (!streamStateMap.has(session.id)) {
                streamStateMap.set(session.id, createInitialStreamState());
              }
            }

            return {
              sessions: sessionsMap,
              messages: messagesMap,
              streamState: streamStateMap,
            };
          }, false, 'setSessions');
        },

        // ======================================================================
        // Message management
        // ======================================================================

        addMessage: (sessionId, message) => {
          set((state) => {
            const messages = new Map(state.messages);
            const sessionMessages = [...(messages.get(sessionId) || []), message];
            messages.set(sessionId, sessionMessages);
            return { messages };
          }, false, 'addMessage');
        },

        updateMessage: (sessionId, messageId, updates) => {
          set((state) => {
            const messages = new Map(state.messages);
            const sessionMessages = messages.get(sessionId) || [];
            const updatedMessages = sessionMessages.map((msg) =>
              msg.id === messageId ? { ...msg, ...updates } : msg
            );
            messages.set(sessionId, updatedMessages);
            return { messages };
          }, false, 'updateMessage');
        },

        setMessages: (sessionId, newMessages) => {
          set((state) => {
            const messages = new Map(state.messages);
            messages.set(sessionId, newMessages);
            return { messages };
          }, false, 'setMessages');
        },

        clearMessages: (sessionId) => {
          set((state) => {
            const messages = new Map(state.messages);
            messages.set(sessionId, []);
            return { messages };
          }, false, 'clearMessages');
        },

        // ======================================================================
        // Streaming
        // ======================================================================

        startStream: (sessionId) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            streamState.set(sessionId, {
              ...createInitialStreamState(),
              isStreaming: true,
            });
            return { streamState };
          }, false, 'startStream');
        },

        appendStreamContent: (sessionId, content, fullContent) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);
            if (!current) return state;

            const newContent = fullContent !== undefined
              ? fullContent
              : current.content + content;

            // Update last text segment
            const segments = [...current.segments];
            const lastSegment = segments[segments.length - 1];
            if (lastSegment?.type === 'text') {
              const delta = fullContent !== undefined
                ? fullContent.slice((lastSegment.content?.length || 0))
                : content;
              segments[segments.length - 1] = {
                ...lastSegment,
                content: (lastSegment.content || '') + delta,
              };
            }

            streamState.set(sessionId, {
              ...current,
              content: newContent,
              segments,
            });

            return { streamState };
          }, false, 'appendStreamContent');
        },

        addStreamSegment: (sessionId, segment) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);
            if (!current) return state;

            const segments = [...current.segments, segment as ContentSegment];

            // Add a new text segment after tool/agent for continued text
            if (segment.type !== 'text') {
              segments.push({ type: 'text', content: '' });
            }

            streamState.set(sessionId, {
              ...current,
              segments,
            });

            return { streamState };
          }, false, 'addStreamSegment');
        },

        endStream: (sessionId, finalMessage) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);

            streamState.set(sessionId, {
              ...createInitialStreamState(),
              pendingMessage: current?.pendingMessage || null,
            });

            // Add final message if provided
            if (finalMessage) {
              const messages = new Map(state.messages);
              const sessionMessages = [...(messages.get(sessionId) || []), finalMessage];
              messages.set(sessionId, sessionMessages);
              return { streamState, messages };
            }

            return { streamState };
          }, false, 'endStream');
        },

        abortStream: (sessionId) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            streamState.set(sessionId, createInitialStreamState());
            return { streamState };
          }, false, 'abortStream');
        },

        setStreamError: (sessionId, error) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);
            if (current) {
              streamState.set(sessionId, {
                ...current,
                isStreaming: false,
                error,
              });
            }
            return { streamState };
          }, false, 'setStreamError');
        },

        // ======================================================================
        // Tool/Agent tracking
        // ======================================================================

        addActiveTool: (sessionId, tool) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);
            if (current) {
              streamState.set(sessionId, {
                ...current,
                activeTools: [...current.activeTools, tool],
              });
            }
            return { streamState };
          }, false, 'addActiveTool');
        },

        removeActiveTool: (sessionId, toolName, input) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);
            if (current) {
              const activeTools = current.activeTools.filter((t) => t.name !== toolName);
              // Update segment with input if provided
              const segments = current.segments.map((seg) => {
                if (seg.type === 'tool' && seg.name === toolName && !seg.input) {
                  return { ...seg, input, completedAt: Date.now() };
                }
                return seg;
              });
              streamState.set(sessionId, {
                ...current,
                activeTools,
                segments,
              });
            }
            return { streamState };
          }, false, 'removeActiveTool');
        },

        addActiveAgent: (sessionId, agent) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);
            if (current) {
              streamState.set(sessionId, {
                ...current,
                activeAgents: [...current.activeAgents, agent],
              });
            }
            return { streamState };
          }, false, 'addActiveAgent');
        },

        // ======================================================================
        // Pending messages
        // ======================================================================

        setPendingMessage: (sessionId, message) => {
          set((state) => {
            const streamState = new Map(state.streamState);
            const current = streamState.get(sessionId);
            if (current) {
              streamState.set(sessionId, {
                ...current,
                pendingMessage: message,
              });
            }
            return { streamState };
          }, false, 'setPendingMessage');
        },

        // ======================================================================
        // Agents
        // ======================================================================

        setAgents: (agents) => {
          set({ agents }, false, 'setAgents');
        },

        // ======================================================================
        // UI State
        // ======================================================================

        setChatMode: (mode) => {
          set({ chatMode: mode }, false, 'setChatMode');
        },

        toggleDualChat: () => {
          set((state) => ({
            dualChatEnabled: !state.dualChatEnabled,
          }), false, 'toggleDualChat');
        },

        toggleHistory: () => {
          set((state) => ({
            showHistory: !state.showHistory,
          }), false, 'toggleHistory');
        },

        toggleSettings: () => {
          set((state) => ({
            showSettings: !state.showSettings,
          }), false, 'toggleSettings');
        },

        setActivePane: (pane) => {
          set({ activePane: pane }, false, 'setActivePane');
        },

        // ======================================================================
        // Initialization
        // ======================================================================

        initialize: (sessions, agents) => {
          const { actions } = get();
          actions.setSessions(sessions);
          actions.setAgents(agents);
          set({ isInitialized: true }, false, 'initialize');
        },

        reset: () => {
          set(initialState, false, 'reset');
        },
      },
    })),
    { name: 'turbowrap-chat' }
  )
);
