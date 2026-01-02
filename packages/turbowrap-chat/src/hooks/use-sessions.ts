/**
 * Hook for session management
 */

import { useCallback, useState } from 'react';
import { useChatStore } from '../store';
import { selectAllSessions, selectActiveSession, selectSecondarySession } from '../store/selectors';
import { useChatClient } from './use-chat-client';
import type { Session, CreateSessionOptions, UpdateSessionOptions } from '../types';

export interface UseSessionsReturn {
  /** All sessions */
  sessions: Session[];
  /** Currently active session */
  activeSession: Session | null;
  /** Secondary session (for dual chat) */
  secondarySession: Session | null;
  /** Loading state */
  isLoading: boolean;

  /** Create a new session */
  createSession: (options: CreateSessionOptions) => Promise<Session>;
  /** Select a session as active */
  selectSession: (sessionId: string) => Promise<void>;
  /** Update session settings */
  updateSession: (sessionId: string, options: UpdateSessionOptions) => Promise<Session>;
  /** Delete a session */
  deleteSession: (sessionId: string) => Promise<void>;
  /** Fork a session (duplicate with messages) */
  forkSession: (sessionId: string) => Promise<Session>;
  /** Start the CLI process for a session */
  startSession: (sessionId: string) => Promise<void>;
  /** Refresh sessions from server */
  refreshSessions: () => Promise<void>;
}

/**
 * Hook for managing chat sessions
 */
export function useSessions(): UseSessionsReturn {
  const client = useChatClient();
  const [isLoading, setIsLoading] = useState(false);

  const sessions = useChatStore(selectAllSessions);
  const activeSession = useChatStore(selectActiveSession);
  const secondarySession = useChatStore(selectSecondarySession);

  const {
    addSession,
    updateSession: updateSessionStore,
    removeSession,
    setActiveSession,
    setMessages,
    setSessions,
  } = useChatStore((s) => s.actions);

  const createSession = useCallback(async (options: CreateSessionOptions): Promise<Session> => {
    setIsLoading(true);
    try {
      const session = await client.createSession(options);
      addSession(session);

      // Auto-start the session
      await client.startSession(session.id);

      // Set as active
      setActiveSession(session.id);

      return session;
    } finally {
      setIsLoading(false);
    }
  }, [client, addSession, setActiveSession]);

  const selectSession = useCallback(async (sessionId: string): Promise<void> => {
    setIsLoading(true);
    try {
      // Set as active
      setActiveSession(sessionId);

      // Load messages if not already loaded
      const currentMessages = useChatStore.getState().messages.get(sessionId);
      if (!currentMessages || currentMessages.length === 0) {
        const messages = await client.getMessages(sessionId);
        setMessages(sessionId, messages);
      }

      // Ensure process is running
      await client.startSession(sessionId);
    } finally {
      setIsLoading(false);
    }
  }, [client, setActiveSession, setMessages]);

  const updateSession = useCallback(async (
    sessionId: string,
    options: UpdateSessionOptions
  ): Promise<Session> => {
    const session = await client.updateSession(sessionId, options);
    updateSessionStore(sessionId, session);
    return session;
  }, [client, updateSessionStore]);

  const deleteSession = useCallback(async (sessionId: string): Promise<void> => {
    await client.deleteSession(sessionId);
    removeSession(sessionId);
  }, [client, removeSession]);

  const forkSession = useCallback(async (sessionId: string): Promise<Session> => {
    setIsLoading(true);
    try {
      const session = await client.forkSession(sessionId);
      addSession(session);

      // Load messages for the forked session
      const messages = await client.getMessages(session.id);
      setMessages(session.id, messages);

      return session;
    } finally {
      setIsLoading(false);
    }
  }, [client, addSession, setMessages]);

  const startSession = useCallback(async (sessionId: string): Promise<void> => {
    await client.startSession(sessionId);
  }, [client]);

  const refreshSessions = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    try {
      const sessions = await client.getSessions();
      setSessions(sessions);
    } finally {
      setIsLoading(false);
    }
  }, [client, setSessions]);

  return {
    sessions,
    activeSession,
    secondarySession,
    isLoading,
    createSession,
    selectSession,
    updateSession,
    deleteSession,
    forkSession,
    startSession,
    refreshSessions,
  };
}
