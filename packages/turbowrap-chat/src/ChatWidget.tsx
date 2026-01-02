/**
 * ChatWidget - Main entry point component for @turbowrap/chat
 *
 * Integrates with TurboWrap application by:
 * 1. Receiving global context (repository, branch) from parent via props
 * 2. Connecting to existing SharedWorker for SSE persistence
 * 3. Using the existing API endpoints
 */

import React, { useEffect, useCallback, useMemo, useState } from 'react';
import { ChatProvider, useChatContext } from './context/chat-provider';
import { useSharedWorker } from './hooks/use-shared-worker';
import type { ChatClientConfig } from './api/types';
import type { ChatMode, ActivePane } from './store/types';
import type { Session, Message, ActionEvent, Repository, CLIType } from './types';

// Components
import { ChatHeader } from './components/layout/ChatHeader';
import { SessionTabs } from './components/session/SessionTabs';
import { HistoryPanel } from './components/session/HistoryPanel';
import { QuickSettings } from './components/settings/QuickSettings';
import { MessageList } from './components/chat/MessageList';
import { MessageInput } from './components/chat/MessageInput';
import { RepoSelectorModal } from './components/modals/RepoSelectorModal';
import { SessionInfoModal } from './components/modals/SessionInfoModal';

/**
 * Global context from TurboWrap app
 */
export interface GlobalContext {
  /** Selected repository ID */
  repositoryId?: string;
  /** Repository name for display */
  repositoryName?: string;
  /** Current git branch */
  currentBranch?: string;
  /** Available branches */
  branches?: string[];
}

/**
 * Configuration for the ChatWidget
 */
export interface ChatWidgetConfig extends ChatClientConfig {
  // Defaults
  defaultCliType?: CLIType;
  defaultMode?: ChatMode;
  theme?: 'light' | 'dark' | 'auto';
  accentColor?: string;

  // Feature toggles
  enableDualChat?: boolean;
  enableAgentAutocomplete?: boolean;
  enableSlashCommands?: boolean;
  enableSharedWorker?: boolean;

  // SharedWorker URL (defaults to /static/js/chat-worker.js)
  workerUrl?: string;

  // Initial context (legacy - use globalContext prop instead)
  repositoryId?: string;
  sessionId?: string;

  // Callbacks
  onSessionCreate?: (session: Session) => void;
  onSessionDelete?: (sessionId: string) => void;
  onMessageSend?: (sessionId: string, content: string) => void;
  onMessageReceive?: (sessionId: string, message: Message) => void;
  onModeChange?: (mode: ChatMode) => void;
  onPaneChange?: (pane: ActivePane) => void;
  onNavigate?: (path: string) => void;
  onHighlight?: (selector: string) => void;
  onAction?: (action: ActionEvent) => void;
}

/**
 * Props for the ChatWidget component
 */
export interface ChatWidgetProps {
  /** Widget configuration */
  config: ChatWidgetConfig;

  /** Global context from parent TurboWrap app */
  globalContext?: GlobalContext;

  /** Available repositories from parent app */
  repositories?: Repository[];

  /** Additional CSS class name */
  className?: string;

  /** Inline styles */
  style?: React.CSSProperties;

  /** Callback when close button is clicked */
  onClose?: () => void;

  /** Callback when expand button is clicked */
  onExpand?: () => void;
}

/**
 * Main ChatWidget component with full integration
 */
export function ChatWidget({
  config,
  globalContext,
  repositories = [],
  className = '',
  style,
  onClose,
  onExpand,
}: ChatWidgetProps) {
  // Extract ChatClientConfig
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
        className={`turbowrap-chat turbowrap-chat-${config.defaultMode || 'third'} ${className}`.trim()}
        style={style}
        data-theme={config.theme ?? 'auto'}
      >
        <ChatWidgetInner
          config={config}
          globalContext={globalContext}
          repositories={repositories}
          onClose={onClose}
          onExpand={onExpand}
        />
      </div>
    </ChatProvider>
  );
}

/**
 * Inner component that uses the ChatContext
 */
function ChatWidgetInner({
  config,
  globalContext,
  repositories,
  onClose,
  onExpand,
}: Omit<ChatWidgetProps, 'className' | 'style'>) {
  const { store, apiClient, isInitialized, initialize } = useChatContext();

  // Local UI state
  const [showHistory, setShowHistory] = useState(false);
  const [showRepoModal, setShowRepoModal] = useState(false);
  const [showSessionInfo, setShowSessionInfo] = useState(false);
  const [contextInfo, setContextInfo] = useState<{
    model?: string;
    tokens: { used: number; limit: number; percentage: number };
    categories: Array<{ name: string; tokens: number }>;
    mcpTools: Array<{ name: string; server?: string; tokens?: number }>;
    agents: Array<{ name: string; source?: string; tokens?: number }>;
  } | null>(null);
  const [usageInfo, setUsageInfo] = useState<{
    inputTokens?: number;
    outputTokens?: number;
    cacheReadTokens?: number;
    cost?: number;
    mcpServers: Array<{ name: string; connected: boolean }>;
  } | null>(null);

  // SharedWorker connection
  const { sendMessage, stopStream, isConnected } = useSharedWorker({
    apiUrl: config.baseUrl,
    workerUrl: config.workerUrl,
    onAction: (type, target) => {
      if (type === 'navigate') {
        config.onNavigate?.(target);
      } else if (type === 'highlight') {
        config.onHighlight?.(target);
      }
      config.onAction?.({ type, target });
    },
    onTitleUpdate: (sessionId, title) => {
      store.actions.updateSession(sessionId, { displayName: title });
    },
    onError: config.onError,
  });

  // Get current state from store
  const sessions = store.sessions;
  const activeSessionId = store.activeSessionId;
  const activeSession = activeSessionId ? sessions.get(activeSessionId) ?? null : null;
  const messages = activeSessionId ? (store.messages.get(activeSessionId) || []) : [];
  const streamState = activeSessionId ? store.streamState.get(activeSessionId) ?? null : null;
  // Note: store.agents is available for future autocomplete feature

  // Current repository from global context
  const currentRepository = useMemo(() => {
    const repoId = globalContext?.repositoryId || config.repositoryId;
    if (!repoId) return undefined;
    return repositories?.find(r => r.id === repoId);
  }, [globalContext?.repositoryId, config.repositoryId, repositories]);

  // Initialize: load sessions and agents
  useEffect(() => {
    if (isInitialized) return;

    const init = async () => {
      try {
        const repoId = globalContext?.repositoryId || config.repositoryId;

        // Load sessions (filtered by repo if provided)
        const sessionsData = await apiClient.getSessions({
          repositoryId: repoId,
        });
        sessionsData.forEach(session => {
          store.actions.addSession(session);
        });

        // Load agents
        const agentsData = await apiClient.getAgents();
        store.actions.setAgents(agentsData);

        // Select first session or specified one
        const targetSessionId = config.sessionId || (sessionsData.length > 0 ? sessionsData[0].id : null);
        if (targetSessionId) {
          store.actions.setActiveSession(targetSessionId);
          // Load messages
          const msgs = await apiClient.getMessages(targetSessionId);
          store.actions.setMessages(targetSessionId, msgs);
        }

        initialize();
      } catch (error) {
        config.onError?.(error instanceof Error ? error : new Error('Failed to initialize'));
      }
    };

    init();
  }, [isInitialized, apiClient, globalContext?.repositoryId, config.repositoryId, config.sessionId, store.actions, initialize, config.onError]);

  // Reload when repository changes in global context
  useEffect(() => {
    if (!isInitialized) return;

    const handleRepoChange = async () => {
      const repoId = globalContext?.repositoryId;
      if (!repoId) return;

      try {
        const sessionsData = await apiClient.getSessions({ repositoryId: repoId });
        // Update sessions in store
        store.actions.reset();
        sessionsData.forEach(session => {
          store.actions.addSession(session);
        });
        if (sessionsData.length > 0) {
          store.actions.setActiveSession(sessionsData[0].id);
          const msgs = await apiClient.getMessages(sessionsData[0].id);
          store.actions.setMessages(sessionsData[0].id, msgs);
        }
        initialize();
      } catch (error) {
        config.onError?.(error instanceof Error ? error : new Error('Failed to reload'));
      }
    };

    handleRepoChange();
  }, [globalContext?.repositoryId]);

  // Handle session selection
  const handleSelectSession = useCallback(async (sessionId: string) => {
    store.actions.setActiveSession(sessionId);

    // Load messages if needed
    const existing = store.messages.get(sessionId);
    if (!existing || existing.length === 0) {
      try {
        const msgs = await apiClient.getMessages(sessionId);
        store.actions.setMessages(sessionId, msgs);
      } catch (error) {
        config.onError?.(error instanceof Error ? error : new Error('Failed to load messages'));
      }
    }
  }, [store, apiClient, config.onError]);

  // Handle new chat
  const handleNewChat = useCallback(async (cliType: CLIType) => {
    try {
      const session = await apiClient.createSession({
        cliType,
        repositoryId: globalContext?.repositoryId || config.repositoryId,
      });
      store.actions.addSession(session);
      store.actions.setActiveSession(session.id);
      config.onSessionCreate?.(session);
    } catch (error) {
      config.onError?.(error instanceof Error ? error : new Error('Failed to create session'));
    }
  }, [apiClient, globalContext?.repositoryId, config.repositoryId, store.actions, config.onSessionCreate, config.onError]);

  // Handle send message
  const handleSendMessage = useCallback((content: string) => {
    if (!activeSessionId) return;

    // Add user message optimistically
    const userMessage: Message = {
      id: `temp-${Date.now()}`,
      sessionId: activeSessionId,
      role: 'user',
      content,
      createdAt: new Date(),
      isThinking: false,
    };
    store.actions.addMessage(activeSessionId, userMessage);
    config.onMessageSend?.(activeSessionId, content);

    // Send via SharedWorker (or fallback to direct API)
    if (isConnected && config.enableSharedWorker !== false) {
      sendMessage(activeSessionId, content);
    } else {
      // Fallback to direct streaming via API client
      apiClient.streamMessage(activeSessionId, content, {
        onChunk: (chunk) => {
          store.actions.appendStreamContent(activeSessionId, chunk);
        },
        onToolStart: (tool) => {
          store.actions.addActiveTool(activeSessionId, {
            id: tool.id,
            name: tool.name,
            startedAt: Date.now(),
          });
        },
        onToolEnd: (toolName) => {
          store.actions.removeActiveTool(activeSessionId, toolName);
        },
        onDone: () => {
          store.actions.endStream(activeSessionId);
        },
        onError: (error) => {
          store.actions.endStream(activeSessionId);
          config.onError?.(error);
        },
      });
      store.actions.startStream(activeSessionId);
    }
  }, [activeSessionId, store.actions, config, isConnected, sendMessage, apiClient]);

  // Handle stop streaming
  const handleStopStream = useCallback(() => {
    if (!activeSessionId) return;
    stopStream(activeSessionId);
    store.actions.abortStream(activeSessionId);
  }, [activeSessionId, stopStream, store.actions]);

  // Handle delete session
  const handleDeleteSession = useCallback(async (sessionId: string) => {
    try {
      await apiClient.deleteSession(sessionId);
      store.actions.removeSession(sessionId);
      config.onSessionDelete?.(sessionId);
    } catch (error) {
      config.onError?.(error instanceof Error ? error : new Error('Failed to delete'));
    }
  }, [apiClient, store.actions, config.onSessionDelete, config.onError]);

  // Handle model change
  const handleModelChange = useCallback(async (model: string) => {
    if (!activeSessionId) return;
    try {
      await apiClient.updateSession(activeSessionId, { model });
      store.actions.updateSession(activeSessionId, { model });
    } catch (error) {
      config.onError?.(error instanceof Error ? error : new Error('Failed to update model'));
    }
  }, [activeSessionId, apiClient, store.actions, config.onError]);

  // Handle branch change
  const handleBranchChange = useCallback(async (branch: string) => {
    if (!activeSessionId) return;
    try {
      await apiClient.changeBranch(activeSessionId, branch);
      store.actions.updateSession(activeSessionId, { currentBranch: branch });
    } catch (error) {
      config.onError?.(error instanceof Error ? error : new Error('Failed to change branch'));
    }
  }, [activeSessionId, apiClient, store.actions, config.onError]);

  // Load session info for modal
  const handleInfoClick = useCallback(async () => {
    if (!activeSessionId) return;

    try {
      const [ctx, usage] = await Promise.all([
        apiClient.getContextInfo(activeSessionId),
        apiClient.getUsageInfo(activeSessionId),
      ]);
      setContextInfo(ctx);
      setUsageInfo({
        inputTokens: usage.sessionId ? undefined : 0, // Placeholder
        outputTokens: undefined,
        cacheReadTokens: undefined,
        cost: undefined,
        mcpServers: usage.mcpServers,
      });
      setShowSessionInfo(true);
    } catch (error) {
      config.onError?.(error instanceof Error ? error : new Error('Failed to load session info'));
    }
  }, [activeSessionId, apiClient, config.onError]);

  // Handle repo selection from modal
  const handleRepoSelect = useCallback((repoId: string) => {
    // Emit event for parent app to handle
    window.dispatchEvent(new CustomEvent('turbowrap:repo-change', {
      detail: { repositoryId: repoId },
    }));
    setShowRepoModal(false);
  }, []);

  // Session list sorted by activity
  const sessionList = useMemo(() => {
    return Array.from(sessions.values()).sort((a, b) => {
      const aTime = a.lastMessageAt?.getTime() || a.createdAt.getTime();
      const bTime = b.lastMessageAt?.getTime() || b.createdAt.getTime();
      return bTime - aTime;
    });
  }, [sessions]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-900">
      {/* Header */}
      <ChatHeader
        chatMode={config.defaultMode || 'third'}
        showHistory={showHistory}
        onToggleHistory={() => setShowHistory(!showHistory)}
        onNewChat={handleNewChat}
        onExpand={onExpand}
        onClose={onClose}
      >
        <SessionTabs
          sessions={sessionList}
          activeSessionId={activeSessionId ?? null}
          onSelect={handleSelectSession}
        />
      </ChatHeader>

      {/* Quick Settings */}
      {activeSession && (
        <QuickSettings
          session={activeSession}
          repository={currentRepository}
          branches={globalContext?.branches || []}
          currentBranch={globalContext?.currentBranch || activeSession.currentBranch || 'main'}
          onModelChange={handleModelChange}
          onRepoClick={() => setShowRepoModal(true)}
          onBranchChange={handleBranchChange}
          onInfoClick={handleInfoClick}
        />
      )}

      {/* Messages */}
      <MessageList
        messages={messages}
        isStreaming={streamState?.isStreaming || false}
        streamContent={streamState?.content || ''}
        streamSegments={streamState?.segments || []}
        activeTools={streamState?.activeTools || []}
        activeAgents={streamState?.activeAgents || []}
        className="flex-1"
      />

      {/* Input */}
      <MessageInput
        onSend={handleSendMessage}
        onStop={handleStopStream}
        isStreaming={streamState?.isStreaming || false}
        placeholder={`Message ${activeSession?.cliType === 'gemini' ? 'Gemini' : 'Claude'}...`}
      />

      {/* History Panel */}
      <HistoryPanel
        isOpen={showHistory}
        sessions={sessionList}
        activeSessionId={activeSessionId ?? null}
        onClose={() => setShowHistory(false)}
        onSelect={(id: string) => {
          handleSelectSession(id);
          setShowHistory(false);
        }}
        onDelete={handleDeleteSession}
        onNewChat={handleNewChat}
      />

      {/* Modals */}
      <RepoSelectorModal
        isOpen={showRepoModal}
        repositories={repositories || []}
        selectedRepoId={globalContext?.repositoryId || config.repositoryId || null}
        onSelect={handleRepoSelect}
        onClose={() => setShowRepoModal(false)}
      />

      <SessionInfoModal
        isOpen={showSessionInfo}
        session={activeSession}
        contextInfo={contextInfo || undefined}
        usageInfo={usageInfo || undefined}
        onClose={() => setShowSessionInfo(false)}
      />
    </div>
  );
}
