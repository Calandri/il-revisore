/**
 * ChatHeader - Top toolbar with tabs and controls
 */

import React from 'react';
import type { ChatMode } from '../../store/types';

export interface ChatHeaderProps {
  onToggleHistory?: () => void;
  onToggleDualChat?: () => void;
  onNewChat?: (cliType: 'claude' | 'gemini') => void;
  onExpand?: () => void;
  onClose?: () => void;
  chatMode: ChatMode;
  dualChatEnabled?: boolean;
  showHistory?: boolean;
  streamingCount?: number;
  className?: string;
  children?: React.ReactNode;
}

/**
 * Hamburger menu icon
 */
function MenuIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}

/**
 * Plus icon
 */
function PlusIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
    </svg>
  );
}

/**
 * Dual chat icon
 */
function DualChatIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
    </svg>
  );
}

/**
 * Expand icon
 */
function ExpandIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
    </svg>
  );
}

/**
 * Close icon
 */
function CloseIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

/**
 * Renders the chat header toolbar
 */
export function ChatHeader({
  onToggleHistory,
  onToggleDualChat,
  onNewChat,
  onExpand,
  onClose,
  chatMode,
  dualChatEnabled = false,
  showHistory = false,
  streamingCount = 0,
  className = '',
  children,
}: ChatHeaderProps) {
  const [showNewMenu, setShowNewMenu] = React.useState(false);

  return (
    <div className={`flex items-center gap-1 px-2 py-1.5 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 ${className}`}>
      {/* Hamburger menu */}
      <button
        onClick={onToggleHistory}
        className={`p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${
          showHistory ? 'bg-gray-200 dark:bg-gray-700' : ''
        }`}
        title="Toggle history"
      >
        <MenuIcon />
      </button>

      {/* Session tabs (children) */}
      <div className="flex-1 flex items-center gap-1 overflow-x-auto">
        {children}
      </div>

      {/* Dual chat toggle (only in full/page mode) */}
      {(chatMode === 'full' || chatMode === 'page') && (
        <button
          onClick={onToggleDualChat}
          className={`p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${
            dualChatEnabled ? 'bg-indigo-100 dark:bg-indigo-900 text-indigo-600' : ''
          }`}
          title="Toggle dual chat"
        >
          <DualChatIcon />
        </button>
      )}

      {/* New chat button */}
      <div className="relative">
        <button
          onClick={() => setShowNewMenu(!showNewMenu)}
          disabled={streamingCount >= 10}
          className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
          title="New chat"
        >
          <PlusIcon />
          {streamingCount > 0 && (
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-amber-500 text-white text-[10px] rounded-full flex items-center justify-center">
              {streamingCount}
            </span>
          )}
        </button>

        {/* New chat dropdown */}
        {showNewMenu && (
          <div className="absolute right-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1 min-w-[140px]">
            <button
              onClick={() => {
                onNewChat?.('claude');
                setShowNewMenu(false);
              }}
              className="w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
            >
              <span className="w-5 h-5 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-xs font-bold">C</span>
              Claude Chat
            </button>
            <button
              onClick={() => {
                onNewChat?.('gemini');
                setShowNewMenu(false);
              }}
              className="w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
            >
              <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs font-bold">G</span>
              Gemini Chat
            </button>
          </div>
        )}
      </div>

      {/* Expand button */}
      <button
        onClick={onExpand}
        className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
        title="Expand"
      >
        <ExpandIcon />
      </button>

      {/* Close button */}
      <button
        onClick={onClose}
        className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
        title="Close"
      >
        <CloseIcon />
      </button>
    </div>
  );
}
