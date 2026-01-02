/**
 * Hook for dual chat mode management
 */

import { useCallback } from 'react';
import { useChatStore } from '../store';
import {
  selectActiveSession,
  selectSecondarySession,
  selectActiveMessages,
  selectSecondaryMessages,
  selectActiveStreamState,
  selectSecondaryStreamState,
  selectIsDualChatActive,
  selectActivePane,
} from '../store/selectors';
import type { Session, Message, StreamState } from '../types';
import type { ActivePane } from '../store/types';

export interface UseDualChatReturn {
  /** Whether dual chat is enabled */
  isDualChatEnabled: boolean;
  /** Whether dual chat is active (enabled + has secondary session) */
  isDualChatActive: boolean;
  /** Current active pane */
  activePane: ActivePane;

  // Left pane
  leftSession: Session | null;
  leftMessages: Message[];
  leftStreamState: StreamState | null;

  // Right pane
  rightSession: Session | null;
  rightMessages: Message[];
  rightStreamState: StreamState | null;

  // Actions
  /** Toggle dual chat mode */
  toggleDualChat: () => void;
  /** Set the secondary session */
  setSecondarySession: (sessionId: string | null) => void;
  /** Set the active pane */
  setActivePane: (pane: ActivePane) => void;
  /** Swap left and right sessions */
  swapSessions: () => void;
  /** Open a session in the specified pane */
  openInPane: (sessionId: string, pane: ActivePane) => void;
}

/**
 * Hook for managing dual chat mode
 */
export function useDualChat(): UseDualChatReturn {
  const isDualChatEnabled = useChatStore((s) => s.dualChatEnabled);
  const isDualChatActive = useChatStore(selectIsDualChatActive);
  const activePane = useChatStore(selectActivePane);

  // Left pane (primary)
  const leftSession = useChatStore(selectActiveSession);
  const leftMessages = useChatStore(selectActiveMessages);
  const leftStreamState = useChatStore(selectActiveStreamState);

  // Right pane (secondary)
  const rightSession = useChatStore(selectSecondarySession);
  const rightMessages = useChatStore(selectSecondaryMessages);
  const rightStreamState = useChatStore(selectSecondaryStreamState);

  const {
    toggleDualChat: toggleDualChatAction,
    setSecondarySession: setSecondarySessionAction,
    setActivePane: setActivePaneAction,
    setActiveSession,
  } = useChatStore((s) => s.actions);

  const toggleDualChat = useCallback(() => {
    toggleDualChatAction();
  }, [toggleDualChatAction]);

  const setSecondarySession = useCallback((sessionId: string | null) => {
    setSecondarySessionAction(sessionId);
  }, [setSecondarySessionAction]);

  const setActivePane = useCallback((pane: ActivePane) => {
    setActivePaneAction(pane);
  }, [setActivePaneAction]);

  const swapSessions = useCallback(() => {
    const state = useChatStore.getState();
    const primary = state.activeSessionId;
    const secondary = state.secondarySessionId;

    if (primary && secondary) {
      setActiveSession(secondary);
      setSecondarySessionAction(primary);
    }
  }, [setActiveSession, setSecondarySessionAction]);

  const openInPane = useCallback((sessionId: string, pane: ActivePane) => {
    if (pane === 'left') {
      setActiveSession(sessionId);
    } else {
      setSecondarySessionAction(sessionId);
    }
    setActivePaneAction(pane);
  }, [setActiveSession, setSecondarySessionAction, setActivePaneAction]);

  return {
    isDualChatEnabled,
    isDualChatActive,
    activePane,
    leftSession,
    leftMessages,
    leftStreamState,
    rightSession,
    rightMessages,
    rightStreamState,
    toggleDualChat,
    setSecondarySession,
    setActivePane,
    swapSessions,
    openInPane,
  };
}
