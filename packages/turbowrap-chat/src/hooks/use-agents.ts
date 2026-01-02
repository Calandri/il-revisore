/**
 * Hook for agent autocomplete functionality
 */

import { useState, useCallback, useMemo, useEffect } from 'react';
import { useChatStore } from '../store';
import { selectAgents } from '../store/selectors';
import { useChatClient } from './use-chat-client';
import type { Agent } from '../types';

export interface UseAgentsReturn {
  /** All available agents */
  agents: Agent[];
  /** Filtered agents based on query */
  filteredAgents: Agent[];
  /** Current search query */
  query: string;
  /** Selected agent index */
  selectedIndex: number;
  /** Loading state */
  isLoading: boolean;

  /** Set the search query */
  setQuery: (query: string) => void;
  /** Move selection up */
  selectPrevious: () => void;
  /** Move selection down */
  selectNext: () => void;
  /** Get the currently selected agent */
  getSelectedAgent: () => Agent | null;
  /** Reset selection */
  resetSelection: () => void;
  /** Refresh agents from server */
  refreshAgents: () => Promise<void>;
}

/**
 * Hook for managing agent autocomplete
 */
export function useAgents(): UseAgentsReturn {
  const client = useChatClient();
  const agents = useChatStore(selectAgents);
  const { setAgents } = useChatStore((s) => s.actions);

  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);

  // Filter agents based on query
  const filteredAgents = useMemo(() => {
    if (!query) return agents.slice(0, 10);

    const lowerQuery = query.toLowerCase();
    return agents
      .filter(
        (agent) =>
          agent.name.toLowerCase().includes(lowerQuery) ||
          agent.description.toLowerCase().includes(lowerQuery)
      )
      .slice(0, 10);
  }, [agents, query]);

  // Reset selection when query changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const selectPrevious = useCallback(() => {
    setSelectedIndex((prev) =>
      prev > 0 ? prev - 1 : filteredAgents.length - 1
    );
  }, [filteredAgents.length]);

  const selectNext = useCallback(() => {
    setSelectedIndex((prev) =>
      prev < filteredAgents.length - 1 ? prev + 1 : 0
    );
  }, [filteredAgents.length]);

  const getSelectedAgent = useCallback(() => {
    return filteredAgents[selectedIndex] ?? null;
  }, [filteredAgents, selectedIndex]);

  const resetSelection = useCallback(() => {
    setQuery('');
    setSelectedIndex(0);
  }, []);

  const refreshAgents = useCallback(async () => {
    setIsLoading(true);
    try {
      const newAgents = await client.getAgents();
      setAgents(newAgents);
    } finally {
      setIsLoading(false);
    }
  }, [client, setAgents]);

  return {
    agents,
    filteredAgents,
    query,
    selectedIndex,
    isLoading,
    setQuery,
    selectPrevious,
    selectNext,
    getSelectedAgent,
    resetSelection,
    refreshAgents,
  };
}
