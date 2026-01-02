/**
 * ChatWidget - Main entry point component for @turbowrap/chat
 */

import React from 'react';
import { ChatProvider } from './context/chat-provider';
import type { ChatClientConfig } from './api/types';
import type { ChatMode, ActivePane } from './store/types';
import type { Session, Message, ActionEvent } from './types';

/**
 * Configuration for the ChatWidget
 */
export interface ChatWidgetConfig extends ChatClientConfig {
  // ============================================================================
  // Defaults
  // ============================================================================

  /** Default CLI type for new sessions (default: 'claude') */
  defaultCliType?: 'claude' | 'gemini';

  /** Default chat mode (default: 'third') */
  defaultMode?: ChatMode;

  /** Theme (default: 'auto') */
  theme?: 'light' | 'dark' | 'auto';

  /** Accent color (CSS color value) */
  accentColor?: string;

  // ============================================================================
  // Feature toggles
  // ============================================================================

  /** Enable dual chat mode (default: true) */
  enableDualChat?: boolean;

  /** Enable agent autocomplete (default: true) */
  enableAgentAutocomplete?: boolean;

  /** Enable slash commands (default: true) */
  enableSlashCommands?: boolean;

  /** Enable SharedWorker for persistence (default: true) */
  enableSharedWorker?: boolean;

  // ============================================================================
  // Initial context
  // ============================================================================

  /** Pre-selected repository ID */
  repositoryId?: string;

  /** Resume specific session */
  sessionId?: string;

  // ============================================================================
  // Callbacks
  // ============================================================================

  /** Called when a session is created */
  onSessionCreate?: (session: Session) => void;

  /** Called when a session is deleted */
  onSessionDelete?: (sessionId: string) => void;

  /** Called when a message is sent */
  onMessageSend?: (sessionId: string, content: string) => void;

  /** Called when a message is received */
  onMessageReceive?: (sessionId: string, message: Message) => void;

  /** Called when chat mode changes */
  onModeChange?: (mode: ChatMode) => void;

  /** Called when active pane changes */
  onPaneChange?: (pane: ActivePane) => void;

  /** Called on navigation action from AI */
  onNavigate?: (path: string) => void;

  /** Called on highlight action from AI */
  onHighlight?: (selector: string) => void;

  /** Called on any action from AI */
  onAction?: (action: ActionEvent) => void;
}

/**
 * Props for the ChatWidget component
 */
export interface ChatWidgetProps {
  /** Widget configuration */
  config: ChatWidgetConfig;

  /** Additional CSS class name */
  className?: string;

  /** Inline styles */
  style?: React.CSSProperties;

  /** Children (custom content) */
  children?: React.ReactNode;
}

/**
 * Main ChatWidget component
 *
 * @example
 * ```tsx
 * <ChatWidget
 *   config={{
 *     apiUrl: 'https://api.turbowrap.io',
 *     getAuthToken: () => localStorage.getItem('token') || '',
 *     defaultCliType: 'claude',
 *   }}
 * />
 * ```
 */
export function ChatWidget({
  config,
  className = '',
  style,
  children,
}: ChatWidgetProps) {
  // Extract ChatClientConfig from ChatWidgetConfig
  const clientConfig: ChatClientConfig = {
    baseUrl: config.baseUrl,
    headers: config.headers,
    getAuthToken: config.getAuthToken,
    timeout: config.timeout,
    onUnauthorized: config.onUnauthorized,
    onError: config.onError,
  };

  return (
    <ChatProvider config={clientConfig}>
      <div
        className={`turbowrap-chat ${className}`.trim()}
        style={style}
        data-theme={config.theme ?? 'auto'}
      >
        {children || (
          <ChatWidgetPlaceholder config={config} />
        )}
      </div>
    </ChatProvider>
  );
}

/**
 * Placeholder component shown when no children are provided
 * This will be replaced with the full ChatSidebar once implemented
 */
function ChatWidgetPlaceholder({ config }: { config: ChatWidgetConfig }) {
  return (
    <div className="flex items-center justify-center h-full p-4 text-gray-500 dark:text-gray-400">
      <div className="text-center">
        <div className="text-lg font-medium mb-2">@turbowrap/chat</div>
        <div className="text-sm">
          Connected to: {config.baseUrl}
        </div>
        <div className="text-xs mt-2 text-gray-400">
          ChatSidebar component coming soon...
        </div>
      </div>
    </div>
  );
}
