/**
 * SessionTabs - Horizontal tabs for active sessions
 */

import React from 'react';
import type { Session } from '../../types';

export interface SessionTabsProps {
  sessions: Session[];
  activeSessionId: string | null;
  secondarySessionId?: string | null;
  onSelect: (sessionId: string) => void;
  onContextMenu?: (sessionId: string, event: React.MouseEvent) => void;
  className?: string;
}

/**
 * Format relative time (e.g., "5m", "2h", "1d")
 */
function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'now';
  if (diffMins < 60) return `${diffMins}m`;

  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h`;

  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d`;
}

/**
 * Single session tab
 */
function SessionTab({
  session,
  isActive,
  isSecondary,
  onSelect,
  onContextMenu,
}: {
  session: Session;
  isActive: boolean;
  isSecondary: boolean;
  onSelect: () => void;
  onContextMenu?: (event: React.MouseEvent) => void;
}) {
  const lastActivity = session.lastMessageAt || session.updatedAt;

  return (
    <button
      onClick={onSelect}
      onContextMenu={onContextMenu}
      className={`flex items-center gap-1.5 px-2 py-1 rounded text-sm whitespace-nowrap transition-colors ${
        isActive
          ? 'bg-white dark:bg-gray-700 shadow-sm'
          : isSecondary
          ? 'bg-indigo-50 dark:bg-indigo-900/30 ring-1 ring-indigo-300'
          : 'hover:bg-gray-200 dark:hover:bg-gray-700'
      }`}
    >
      {/* CLI badge */}
      <span
        className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold ${
          session.cliType === 'gemini'
            ? 'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400'
            : 'bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400'
        }`}
      >
        {session.cliType === 'gemini' ? 'G' : 'C'}
      </span>

      {/* Name */}
      <span className="truncate max-w-[100px]">
        {session.displayName || 'Untitled'}
      </span>

      {/* Relative time */}
      <span className="text-xs text-gray-400">
        {formatRelativeTime(lastActivity)}
      </span>
    </button>
  );
}

/**
 * Renders the session tabs
 */
export function SessionTabs({
  sessions,
  activeSessionId,
  secondarySessionId,
  onSelect,
  onContextMenu,
  className = '',
}: SessionTabsProps) {
  if (sessions.length === 0) {
    return null;
  }

  return (
    <div className={`flex items-center gap-1 overflow-x-auto ${className}`}>
      {sessions.map((session) => (
        <SessionTab
          key={session.id}
          session={session}
          isActive={session.id === activeSessionId}
          isSecondary={session.id === secondarySessionId}
          onSelect={() => onSelect(session.id)}
          onContextMenu={(e) => {
            e.preventDefault();
            onContextMenu?.(session.id, e);
          }}
        />
      ))}
    </div>
  );
}
