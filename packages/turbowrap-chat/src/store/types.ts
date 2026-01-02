/**
 * Zustand store types
 */

import type { Session, Message, Agent, StreamState } from '../types';

/**
 * UI state for chat widget
 */
export type ChatMode = 'hidden' | 'third' | 'full' | 'page';
export type ActivePane = 'left' | 'right';

/**
 * Main chat store state
 */
export interface ChatStoreState {
  // ============================================================================
  // Sessions
  // ============================================================================
  sessions: Map<string, Session>;
  activeSessionId: string | null;
  secondarySessionId: string | null;

  // ============================================================================
  // Messages (per-session)
  // ============================================================================
  messages: Map<string, Message[]>;

  // ============================================================================
  // Streaming (per-session)
  // ============================================================================
  streamState: Map<string, StreamState>;

  // ============================================================================
  // Global data
  // ============================================================================
  agents: Agent[];
  isInitialized: boolean;

  // ============================================================================
  // UI State
  // ============================================================================
  chatMode: ChatMode;
  dualChatEnabled: boolean;
  showHistory: boolean;
  showSettings: boolean;
  activePane: ActivePane;
}

/**
 * Store actions
 */
export interface ChatStoreActions {
  // Session management
  setActiveSession: (sessionId: string | null) => void;
  setSecondarySession: (sessionId: string | null) => void;
  addSession: (session: Session) => void;
  updateSession: (sessionId: string, updates: Partial<Session>) => void;
  removeSession: (sessionId: string) => void;
  setSessions: (sessions: Session[]) => void;

  // Message management
  addMessage: (sessionId: string, message: Message) => void;
  updateMessage: (sessionId: string, messageId: string, updates: Partial<Message>) => void;
  setMessages: (sessionId: string, messages: Message[]) => void;
  clearMessages: (sessionId: string) => void;

  // Streaming
  startStream: (sessionId: string) => void;
  appendStreamContent: (sessionId: string, content: string, fullContent?: string) => void;
  addStreamSegment: (sessionId: string, segment: { type: 'text' | 'tool' | 'agent'; [key: string]: unknown }) => void;
  endStream: (sessionId: string, finalMessage?: Message) => void;
  abortStream: (sessionId: string) => void;
  setStreamError: (sessionId: string, error: string | null) => void;

  // Tool/Agent tracking
  addActiveTool: (sessionId: string, tool: { name: string; id: string; startedAt: number }) => void;
  removeActiveTool: (sessionId: string, toolName: string, input?: Record<string, unknown>) => void;
  addActiveAgent: (sessionId: string, agent: { type: string; model: string; description: string; startedAt: number }) => void;

  // Pending messages
  setPendingMessage: (sessionId: string, message: string | null) => void;

  // Agents
  setAgents: (agents: Agent[]) => void;

  // UI State
  setChatMode: (mode: ChatMode) => void;
  toggleDualChat: () => void;
  toggleHistory: () => void;
  toggleSettings: () => void;
  setActivePane: (pane: ActivePane) => void;

  // Initialization
  initialize: (sessions: Session[], agents: Agent[]) => void;
  reset: () => void;
}

/**
 * Complete store type
 */
export interface ChatStore extends ChatStoreState {
  actions: ChatStoreActions;
}
