/**
 * MessageList - Scrollable list of messages
 */

import { useRef, useEffect } from 'react';
import type { Message, ContentSegment, ToolState, AgentState } from '../../types';
import { MessageItem } from './MessageItem';
import { StreamingMessage } from './StreamingMessage';

export interface MessageListProps {
  messages: Message[];
  isStreaming?: boolean;
  streamContent?: string;
  streamSegments?: ContentSegment[];
  activeTools?: ToolState[];
  activeAgents?: AgentState[];
  className?: string;
}

/**
 * Empty state when no messages
 */
function EmptyState({ cliType }: { cliType?: 'claude' | 'gemini' }) {
  return (
    <div className="flex flex-col items-center justify-center h-full py-12 text-gray-400">
      <div
        className={`w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold mb-4 ${
          cliType === 'gemini'
            ? 'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400'
            : 'bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400'
        }`}
      >
        {cliType === 'gemini' ? 'G' : 'C'}
      </div>
      <p className="text-lg font-medium">Start the conversation</p>
      <p className="text-sm mt-1">Write a message to chat with the AI</p>
    </div>
  );
}

/**
 * Renders the scrollable message list
 */
export function MessageList({
  messages,
  isStreaming = false,
  streamContent = '',
  streamSegments = [],
  activeTools = [],
  activeAgents = [],
  className = '',
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages or streaming state change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isStreaming]);

  // Show empty state if no messages
  if (messages.length === 0 && !isStreaming) {
    return (
      <div className={`flex-1 overflow-y-auto chat-scrollbar ${className}`}>
        <EmptyState />
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className={`flex-1 overflow-y-auto chat-scrollbar p-4 space-y-4 ${className}`}
    >
      {/* Rendered messages */}
      {messages.map((message) => (
        <MessageItem
          key={message.id}
          message={message}
          className="animate-fade-in-up"
        />
      ))}

      {/* Streaming response */}
      {isStreaming && (
        <StreamingMessage
          content={streamContent}
          segments={streamSegments}
          activeTools={activeTools}
          activeAgents={activeAgents}
          className="animate-fade-in-up"
        />
      )}

      {/* Scroll anchor */}
      <div ref={bottomRef} />
    </div>
  );
}
