/**
 * ChatProvider - Main context provider for @turbowrap/chat
 */

import React, { useEffect, useMemo } from 'react';
import { ChatAPIClient } from '../api/client';
import type { ChatClientConfig } from '../api/types';
import { ChatClientContext } from '../hooks/use-chat-client';
import { useChatStore } from '../store';

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
  autoLoadSessions = true,
  autoLoadAgents = true,
}: ChatProviderProps) {
  // Create client instance (memoized)
  const client = useMemo(() => new ChatAPIClient(config), [config]);

  // Get store actions
  const { initialize } = useChatStore((s) => s.actions);
  const isInitialized = useChatStore((s) => s.isInitialized);

  // Initialize on mount
  useEffect(() => {
    async function init() {
      try {
        const [sessions, agents] = await Promise.all([
          autoLoadSessions ? client.getSessions() : Promise.resolve([]),
          autoLoadAgents ? client.getAgents() : Promise.resolve([]),
        ]);

        initialize(sessions, agents);
      } catch (error) {
        console.error('[ChatProvider] Failed to initialize:', error);
        config.onError?.(error instanceof Error ? error : new Error(String(error)));
      }
    }

    if (!isInitialized) {
      init();
    }

    // Cleanup on unmount
    return () => {
      // Optionally reset state when provider unmounts
      // reset();
    };
  }, [client, initialize, isInitialized, autoLoadSessions, autoLoadAgents, config]);

  return (
    <ChatClientContext.Provider value={client}>
      {children}
    </ChatClientContext.Provider>
  );
}
