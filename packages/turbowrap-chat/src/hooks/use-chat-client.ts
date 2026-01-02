/**
 * Hook to access the ChatAPIClient from context
 */

import { createContext, useContext } from 'react';
import type { ChatAPIClient } from '../api/client';

/**
 * Context for ChatAPIClient
 */
export const ChatClientContext = createContext<ChatAPIClient | null>(null);

/**
 * Hook to get the ChatAPIClient instance
 * @throws Error if used outside ChatProvider
 */
export function useChatClient(): ChatAPIClient {
  const client = useContext(ChatClientContext);
  if (!client) {
    throw new Error('useChatClient must be used within a ChatProvider');
  }
  return client;
}
