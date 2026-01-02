/**
 * HistoryPanel - Slide-in panel for session history
 */

import React from 'react';
import type { Session } from '../../types';

export interface HistoryPanelProps {
  isOpen: boolean;
  sessions: Session[];
  activeSessionId: string | null;
  onClose: () => void;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onNewChat: (cliType: 'claude' | 'gemini') => void;
  className?: string;
}

/**
 * Format date for display
 */
function formatDate(date: Date): string {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const messageDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.floor((today.getTime() - messageDate.getTime()) / 86400000);

  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return date.toLocaleDateString('en-US', { weekday: 'long' });
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Get short model name
 */
function getModelShortName(model: string | null): string {
  if (!model) return '';
  if (model.includes('opus')) return 'Opus';
  if (model.includes('sonnet')) return 'Sonnet';
  if (model.includes('haiku')) return 'Haiku';
  if (model.includes('pro')) return 'Pro';
  if (model.includes('flash')) return 'Flash';
  return '';
}

/**
 * Single session item in history
 */
function SessionItem({
  session,
  isActive,
  onSelect,
  onDelete,
}: {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [showDelete, setShowDelete] = React.useState(false);

  return (
    <div
      onMouseEnter={() => setShowDelete(true)}
      onMouseLeave={() => setShowDelete(false)}
      className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
        isActive
          ? 'bg-indigo-50 dark:bg-indigo-900/30'
          : 'hover:bg-gray-100 dark:hover:bg-gray-800'
      }`}
      onClick={onSelect}
    >
      {/* CLI badge */}
      <span
        className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
          session.cliType === 'gemini'
            ? 'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400'
            : 'bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400'
        }`}
      >
        {session.cliType === 'gemini' ? 'G' : 'C'}
      </span>

      {/* Session info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">
            {session.displayName || 'Untitled Chat'}
          </span>
          {session.model && (
            <span className="text-xs text-gray-400">
              {getModelShortName(session.model)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span>{session.totalMessages} messages</span>
        </div>
      </div>

      {/* Delete button */}
      {showDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-500"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      )}
    </div>
  );
}

/**
 * Renders the history panel
 */
export function HistoryPanel({
  isOpen,
  sessions,
  activeSessionId,
  onClose,
  onSelect,
  onDelete,
  onNewChat,
  className = '',
}: HistoryPanelProps) {
  if (!isOpen) return null;

  // Group sessions by date
  const groupedSessions = sessions.reduce((groups, session) => {
    const date = formatDate(session.lastMessageAt || session.updatedAt);
    if (!groups[date]) groups[date] = [];
    groups[date].push(session);
    return groups;
  }, {} as Record<string, Session[]>);

  return (
    <>
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/20 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className={`absolute left-0 top-0 bottom-0 w-72 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 z-50 flex flex-col animate-slide-in ${className}`}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <h3 className="font-semibold">Chat History</h3>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* New chat buttons */}
        <div className="flex gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <button
            onClick={() => onNewChat('claude')}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-orange-50 dark:bg-orange-900/20 text-orange-600 hover:bg-orange-100 dark:hover:bg-orange-900/30 transition-colors"
          >
            <span className="w-5 h-5 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold">C</span>
            Claude
          </button>
          <button
            onClick={() => onNewChat('gemini')}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-blue-50 dark:bg-blue-900/20 text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
          >
            <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs font-bold">G</span>
            Gemini
          </button>
        </div>

        {/* Sessions list */}
        <div className="flex-1 overflow-y-auto chat-scrollbar">
          {sessions.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-400">
              <p>No chat history yet</p>
              <p className="text-sm mt-1">Start a new chat to begin</p>
            </div>
          ) : (
            Object.entries(groupedSessions).map(([date, dateSessions]) => (
              <div key={date} className="px-2 py-2">
                <div className="px-2 py-1 text-xs text-gray-400 font-medium">
                  {date}
                </div>
                <div className="space-y-1">
                  {dateSessions.map((session) => (
                    <SessionItem
                      key={session.id}
                      session={session}
                      isActive={session.id === activeSessionId}
                      onSelect={() => onSelect(session.id)}
                      onDelete={() => onDelete(session.id)}
                    />
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}
