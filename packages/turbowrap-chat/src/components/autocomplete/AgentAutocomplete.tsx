/**
 * AgentAutocomplete - Dropdown for @agent mentions
 */

import { useEffect, useRef, useCallback } from 'react';
import type { Agent } from '../../types';

export interface AgentAutocompleteProps {
  isOpen: boolean;
  agents: Agent[];
  filter: string;
  selectedIndex: number;
  position: { top: number; left: number };
  onSelect: (agent: Agent) => void;
  onClose: () => void;
  onNavigate: (direction: 'up' | 'down') => void;
  className?: string;
}

/**
 * Get agent icon based on type
 */
function getAgentIcon(type: string): string {
  switch (type) {
    case 'reviewer':
      return '🔍';
    case 'fixer':
      return '🔧';
    case 'analyzer':
      return '📊';
    case 'creator':
      return '✨';
    default:
      return '🤖';
  }
}

/**
 * Renders the autocomplete dropdown
 */
export function AgentAutocomplete({
  isOpen,
  agents,
  filter,
  selectedIndex,
  position,
  onSelect,
  onClose,
  onNavigate,
  className = '',
}: AgentAutocompleteProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);

  // Filter agents based on search
  const filteredAgents = agents.filter((agent) =>
    agent.name.toLowerCase().includes(filter.toLowerCase()) ||
    agent.description.toLowerCase().includes(filter.toLowerCase())
  );

  // Scroll selected item into view
  useEffect(() => {
    if (selectedRef.current) {
      selectedRef.current.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex]);

  // Handle keyboard navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          onNavigate('down');
          break;
        case 'ArrowUp':
          e.preventDefault();
          onNavigate('up');
          break;
        case 'Enter':
          e.preventDefault();
          if (filteredAgents[selectedIndex]) {
            onSelect(filteredAgents[selectedIndex]);
          }
          break;
        case 'Escape':
          e.preventDefault();
          onClose();
          break;
      }
    },
    [isOpen, filteredAgents, selectedIndex, onSelect, onClose, onNavigate]
  );

  // Add keyboard listener
  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen, onClose]);

  if (!isOpen || filteredAgents.length === 0) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      className={`absolute bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 max-h-64 overflow-y-auto min-w-[280px] ${className}`}
      style={{
        bottom: `calc(100% - ${position.top}px + 8px)`,
        left: position.left,
      }}
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 rounded-t-lg">
        <span className="text-xs text-gray-500 font-medium">
          Agents {filter && `matching "${filter}"`}
        </span>
      </div>

      {/* Agent list */}
      <div className="py-1">
        {filteredAgents.map((agent, index) => (
          <button
            key={agent.id}
            ref={index === selectedIndex ? selectedRef : undefined}
            onClick={() => onSelect(agent)}
            className={`w-full px-3 py-2 text-left flex items-start gap-3 transition-colors ${
              index === selectedIndex
                ? 'bg-indigo-50 dark:bg-indigo-900/30'
                : 'hover:bg-gray-100 dark:hover:bg-gray-700'
            }`}
          >
            {/* Icon */}
            <span className="text-lg flex-shrink-0">
              {getAgentIcon(agent.type)}
            </span>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900 dark:text-white">
                  @{agent.name}
                </span>
                {agent.model && (
                  <span className="text-xs px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-gray-500">
                    {agent.model}
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 truncate">
                {agent.description}
              </p>
            </div>
          </button>
        ))}
      </div>

      {/* Footer hint */}
      <div className="px-3 py-1.5 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 rounded-b-lg">
        <span className="text-xs text-gray-400">
          ↑↓ navigate · Enter select · Esc close
        </span>
      </div>
    </div>
  );
}
