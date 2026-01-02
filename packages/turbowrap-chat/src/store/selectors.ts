/**
 * Reusable selectors for the chat store
 */

import type { ChatStore } from './types';

// ============================================================================
// Session selectors
// ============================================================================

/**
 * Get the currently active session
 */
export const selectActiveSession = (state: ChatStore) =>
  state.activeSessionId ? state.sessions.get(state.activeSessionId) ?? null : null;

/**
 * Get the secondary session (for dual chat)
 */
export const selectSecondarySession = (state: ChatStore) =>
  state.secondarySessionId ? state.sessions.get(state.secondarySessionId) ?? null : null;

/**
 * Get all sessions as array
 */
export const selectAllSessions = (state: ChatStore) =>
  Array.from(state.sessions.values());

/**
 * Get sessions sorted by last message date
 */
export const selectSessionsSortedByActivity = (state: ChatStore) =>
  Array.from(state.sessions.values()).sort((a, b) => {
    const aTime = a.lastMessageAt?.getTime() ?? a.createdAt.getTime();
    const bTime = b.lastMessageAt?.getTime() ?? b.createdAt.getTime();
    return bTime - aTime;
  });

/**
 * Get sessions by CLI type
 */
export const selectSessionsByCliType = (cliType: 'claude' | 'gemini') => (state: ChatStore) =>
  Array.from(state.sessions.values()).filter((s) => s.cliType === cliType);

// ============================================================================
// Message selectors
// ============================================================================

/**
 * Get messages for the active session
 */
export const selectActiveMessages = (state: ChatStore) => {
  if (!state.activeSessionId) return [];
  // Verify session still exists before returning messages
  if (!state.sessions.has(state.activeSessionId)) return [];
  return state.messages.get(state.activeSessionId) ?? [];
};

/**
 * Get messages for the secondary session
 */
export const selectSecondaryMessages = (state: ChatStore) =>
  state.secondarySessionId ? state.messages.get(state.secondarySessionId) ?? [] : [];

/**
 * Get messages for a specific session
 */
export const selectMessagesForSession = (sessionId: string) => (state: ChatStore) =>
  state.messages.get(sessionId) ?? [];

// ============================================================================
// Streaming selectors
// ============================================================================

/**
 * Get stream state for the active session
 */
export const selectActiveStreamState = (state: ChatStore) =>
  state.activeSessionId ? state.streamState.get(state.activeSessionId) ?? null : null;

/**
 * Get stream state for the secondary session
 */
export const selectSecondaryStreamState = (state: ChatStore) =>
  state.secondarySessionId ? state.streamState.get(state.secondarySessionId) ?? null : null;

/**
 * Check if a specific session is streaming
 */
export const selectIsSessionStreaming = (sessionId: string) => (state: ChatStore) =>
  state.streamState.get(sessionId)?.isStreaming ?? false;

/**
 * Get stream content for a session
 */
export const selectStreamContent = (sessionId: string) => (state: ChatStore) =>
  state.streamState.get(sessionId)?.content ?? '';

/**
 * Get active tools for a session
 */
export const selectActiveTools = (sessionId: string) => (state: ChatStore) =>
  state.streamState.get(sessionId)?.activeTools ?? [];

/**
 * Get active agents for a session
 */
export const selectActiveAgents = (sessionId: string) => (state: ChatStore) =>
  state.streamState.get(sessionId)?.activeAgents ?? [];

/**
 * Get pending message for a session
 */
export const selectPendingMessage = (sessionId: string) => (state: ChatStore) =>
  state.streamState.get(sessionId)?.pendingMessage ?? null;

/**
 * Check if any session is streaming
 */
export const selectIsAnyStreaming = (state: ChatStore) =>
  Array.from(state.streamState.values()).some((s) => s.isStreaming);

/**
 * Count of currently streaming sessions
 */
export const selectStreamingCount = (state: ChatStore) =>
  Array.from(state.streamState.values()).filter((s) => s.isStreaming).length;

// ============================================================================
// UI selectors
// ============================================================================

/**
 * Check if dual chat is active
 */
export const selectIsDualChatActive = (state: ChatStore) =>
  state.dualChatEnabled && state.secondarySessionId !== null;

/**
 * Get current chat mode
 */
export const selectChatMode = (state: ChatStore) => state.chatMode;

/**
 * Check if history panel is visible
 */
export const selectShowHistory = (state: ChatStore) => state.showHistory;

/**
 * Get the active pane
 */
export const selectActivePane = (state: ChatStore) => state.activePane;

// ============================================================================
// Agent selectors
// ============================================================================

/**
 * Get all agents
 */
export const selectAgents = (state: ChatStore) => state.agents;

/**
 * Search agents by name or description
 */
export const selectAgentsByQuery = (query: string) => (state: ChatStore) => {
  const lowerQuery = query.toLowerCase();
  return state.agents.filter(
    (agent) =>
      agent.name.toLowerCase().includes(lowerQuery) ||
      agent.description.toLowerCase().includes(lowerQuery)
  );
};
