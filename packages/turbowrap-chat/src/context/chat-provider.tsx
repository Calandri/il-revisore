/**
 * ChatProvider - Main context provider for @turbowrap/chat
 */

import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import { ChatAPIClient } from '../api/client';
import type { ChatClientConfig } from '../api/types';
import { ChatClientContext } from '../hooks/use-chat-client';
import { useChatStore } from '../store';
import type { ChatStore } from '../store/types';

/**
 * Extended chat context with store access
 */
interface ChatContextValue {
  apiClient: ChatAPIClient;
  store: ChatStore;
  isInitialized: boolean;
  initialize: () => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

/**
 * Hook to access the chat context
 */
export function useChatContext(): ChatContextValue {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChatContext must be used within a ChatProvider');
  }
  return context;
}

export interface ChatProviderProps {
  /** API client configuration */
  config: ChatClientConfig;
  /** Child components */
  children: React.ReactNode;
  /** Auto-load sessions on mount (default: true) */
  autoLoadSessions?: boolean;
  /** Auto-load agents on mount (default: true) */
  autoLoadAgents?: boolean;
}

/**
 * Provider component that supplies the ChatAPIClient and initializes state
 */
export function ChatProvider({
  config,
  children,
  autoLoadSessions = false, // Changed to false - ChatWidget handles initialization
  autoLoadAgents = false,   // Changed to false - ChatWidget handles initialization
}: ChatProviderProps) {
  // Create client instance (memoized)
  const client = useMemo(() => new ChatAPIClient(config), [config]);

  // Get full store
  const store = useChatStore();
  const [initialized, setInitialized] = useState(store.isInitialized);

  // Manual initialize function for ChatWidget to call
  const initializeFn = useCallback(() => {
    setInitialized(true);
  }, []);

  // Auto-initialize if enabled (legacy behavior)
  useEffect(() => {
    async function init() {
      try {
        const [sessions, agents] = await Promise.all([
          autoLoadSessions ? client.getSessions() : Promise.resolve([]),
          autoLoadAgents ? client.getAgents() : Promise.resolve([]),
        ]);

        store.actions.initialize(sessions, agents);
        setInitialized(true);
      } catch (error) {
        console.error('[ChatProvider] Failed to initialize:', error);
        config.onError?.(error instanceof Error ? error : new Error(String(error)));
      }
    }

    if ((autoLoadSessions || autoLoadAgents) && !store.isInitialized) {
      init();
    }
  }, [client, store, autoLoadSessions, autoLoadAgents, config]);

  // Create context value
  const contextValue = useMemo<ChatContextValue>(() => ({
    apiClient: client,
    store,
    isInitialized: initialized,
    initialize: initializeFn,
  }), [client, store, initialized, initializeFn]);

  return (
    <ChatContext.Provider value={contextValue}>
      <ChatClientContext.Provider value={client}>
        {children}
      </ChatClientContext.Provider>
    </ChatContext.Provider>
  );
}
