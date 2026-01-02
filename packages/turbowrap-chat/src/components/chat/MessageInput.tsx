/**
 * MessageInput - Chat input with send/stop/queue buttons
 */

import React, { useState, useRef, useCallback, useEffect } from 'react';

export interface MessageInputProps {
  onSend: (content: string) => void;
  onStop?: () => void;
  isStreaming?: boolean;
  pendingMessage?: string | null;
  onClearPending?: () => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
}

/**
 * Send button icon
 */
function SendIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
    </svg>
  );
}

/**
 * Stop button icon
 */
function StopIcon() {
  return (
    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

/**
 * Queue button icon (clock)
 */
function QueueIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

/**
 * Chat input component with auto-resize textarea
 */
export function MessageInput({
  onSend,
  onStop,
  isStreaming = false,
  pendingMessage,
  onClearPending,
  disabled = false,
  placeholder = 'Write a message...',
  className = '',
}: MessageInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
    }
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  // Handle send
  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;

    onSend(trimmed);
    setValue('');

    // Reset height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, disabled, onSend]);

  // Handle key press
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // Enter sends, Shift+Enter or Ctrl+Enter for newline
      if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  // Determine button state
  const hasValue = value.trim().length > 0;
  const showQueue = isStreaming && hasValue;
  const showStop = isStreaming && !hasValue;
  const showSend = !isStreaming && hasValue;

  return (
    <div className={`border-t border-gray-200 dark:border-gray-700 p-3 ${className}`}>
      {/* Pending message indicator */}
      {pendingMessage && (
        <div className="mb-2 px-3 py-2 bg-amber-50 dark:bg-amber-900/20 rounded-lg flex items-center justify-between text-sm">
          <span className="text-amber-700 dark:text-amber-300 truncate">
            Queued: {pendingMessage.slice(0, 30)}...
          </span>
          <button
            onClick={onClearPending}
            className="text-amber-600 hover:text-amber-800 dark:text-amber-400"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* Input area */}
      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isStreaming ? 'Write to queue...' : placeholder}
            disabled={disabled}
            className="chat-input w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
            rows={1}
          />
        </div>

        {/* Action button */}
        <button
          onClick={showStop ? onStop : handleSend}
          disabled={disabled || (!showSend && !showQueue && !showStop)}
          className={`chat-send-button ${
            showStop
              ? 'chat-send-button-stop'
              : showQueue
              ? 'chat-send-button-queue'
              : 'chat-send-button-primary'
          }`}
        >
          {showStop ? <StopIcon /> : showQueue ? <QueueIcon /> : <SendIcon />}
        </button>
      </div>
    </div>
  );
}
