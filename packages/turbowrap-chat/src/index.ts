/**
 * @turbowrap/chat - React chat widget for Claude/Gemini CLI
 *
 * @example
 * ```tsx
 * import { ChatWidget } from '@turbowrap/chat';
 *
 * function App() {
 *   return (
 *     <ChatWidget
 *       config={{
 *         apiUrl: 'https://api.turbowrap.io',
 *         getAuthToken: () => localStorage.getItem('token') || '',
 *       }}
 *     />
 *   );
 * }
 * ```
 */

// ============================================================================
// Main Components
// ============================================================================

export { ChatWidget } from './ChatWidget';
export type { ChatWidgetConfig, ChatWidgetProps } from './ChatWidget';

export { ChatProvider } from './context/chat-provider';
export type { ChatProviderProps } from './context/chat-provider';

// ============================================================================
// Hooks
// ============================================================================

export { useChat, useSessions, useAgents, useDualChat } from './hooks';
export type {
  UseChatOptions,
  UseChatReturn,
  UseSessionsReturn,
  UseAgentsReturn,
  UseDualChatReturn,
} from './hooks';

// Internal hooks (for advanced usage)
export { useChatClient, useStreaming } from './hooks';
export type { StreamingHandler } from './hooks';

// ============================================================================
// Store (for advanced usage)
// ============================================================================

export { useChatStore } from './store';
export type { ChatStore, ChatMode, ActivePane } from './store';

// Selectors
export {
  selectActiveSession,
  selectSecondarySession,
  selectAllSessions,
  selectActiveMessages,
  selectActiveStreamState,
  selectIsSessionStreaming,
  selectAgents,
} from './store';

// ============================================================================
// API Client (for direct usage)
// ============================================================================

export { ChatAPIClient } from './api/client';
export type { ChatClientConfig, StreamMessageOptions, ChatAPIError } from './api/types';

// ============================================================================
// Types
// ============================================================================

export type {
  // Session
  CLIType,
  SessionStatus,
  Session,
  CreateSessionOptions,
  UpdateSessionOptions,

  // Message
  MessageRole,
  ContentSegment,
  Message,
  SendMessageOptions,

  // Streaming
  ToolState,
  AgentState,
  StreamState,
  SSEEventType,
  SSEEvent,
  StreamingCallbacks,

  // Events
  TokenCategory,
  MCPTool,
  AgentInfo,
  ContextInfo,
  MCPServerStatus,
  UsageInfo,
  SystemEvent,
  ActionEvent,
  Agent,
  Repository,
} from './types';

// Transform functions
export { transformSession, transformMessage, createInitialStreamState } from './types';

// ============================================================================
// Styles
// ============================================================================

import './styles/index.css';
