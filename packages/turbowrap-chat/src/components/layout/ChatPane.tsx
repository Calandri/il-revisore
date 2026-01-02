/**
 * ChatPane - Single chat pane with messages and input
 */

import { useCallback } from 'react';
import type { Session, Message, ContentSegment, ToolState, AgentState } from '../../types';
import { MessageList } from '../chat/MessageList';
import { MessageInput } from '../chat/MessageInput';

export interface ChatPaneProps {
  session: Session | null;
  messages: Message[];
  isStreaming?: boolean;
  streamContent?: string;
  streamSegments?: ContentSegment[];
  activeTools?: ToolState[];
  activeAgents?: AgentState[];
  pendingMessage?: string | null;
  isActive?: boolean;
  onSend: (content: string) => void;
  onStop?: () => void;
  onClearPending?: () => void;
  onFocus?: () => void;
  className?: string;
}

/**
 * Renders a complete chat pane with messages and input
 */
export function ChatPane({
  session,
  messages,
  isStreaming = false,
  streamContent = '',
  streamSegments = [],
  activeTools = [],
  activeAgents = [],
  pendingMessage,
  isActive = true,
  onSend,
  onStop,
  onClearPending,
  onFocus,
  className = '',
}: ChatPaneProps) {
  const handleClick = useCallback(() => {
    onFocus?.();
  }, [onFocus]);

  if (!session) {
    return (
      <div className={`flex flex-col h-full ${className}`}>
        <div className="flex-1 flex items-center justify-center text-gray-400">
          <div className="text-center">
            <svg className="w-12 h-12 mx-auto mb-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p className="font-medium">Select a chat</p>
            <p className="text-sm mt-1">Choose a session from the tabs above</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={handleClick}
      className={`flex flex-col h-full ${isActive ? 'ring-2 ring-indigo-500 ring-opacity-50' : ''} ${className}`}
    >
      {/* Session header info */}
      <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
        <div
          className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
            session.cliType === 'gemini'
              ? 'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400'
              : 'bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400'
          }`}
        >
          {session.cliType === 'gemini' ? 'G' : 'C'}
        </div>
        <span className="font-medium truncate flex-1">
          {session.displayName || 'Untitled Chat'}
        </span>
        {session.model && (
          <span className="text-xs text-gray-400">
            {getModelShortName(session.model)}
          </span>
        )}
      </div>

      {/* Messages */}
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        streamContent={streamContent}
        streamSegments={streamSegments}
        activeTools={activeTools}
        activeAgents={activeAgents}
        className="flex-1"
      />

      {/* Input */}
      <MessageInput
        onSend={onSend}
        onStop={onStop}
        isStreaming={isStreaming}
        pendingMessage={pendingMessage}
        onClearPending={onClearPending}
        placeholder={`Message ${session.cliType === 'gemini' ? 'Gemini' : 'Claude'}...`}
      />
    </div>
  );
}

/**
 * Get short model name
 */
function getModelShortName(model: string): string {
  if (model.includes('opus')) return 'Opus';
  if (model.includes('sonnet')) return 'Sonnet';
  if (model.includes('haiku')) return 'Haiku';
  if (model.includes('pro')) return 'Pro';
  if (model.includes('flash')) return 'Flash';
  return model.split('-').pop() || model;
}
