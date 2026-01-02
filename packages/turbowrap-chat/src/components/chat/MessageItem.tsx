/**
 * MessageItem - Single message component
 */

import type { Message, ContentSegment } from '../../types';
import { MessageFormatter } from '../formatting/MessageFormatter';
import { ToolIndicator } from './ToolIndicator';

export interface MessageItemProps {
  message: Message;
  className?: string;
}

/**
 * Format timestamp to HH:mm
 */
function formatTime(date: Date): string {
  return date.toLocaleTimeString('it-IT', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Renders a single message with segments
 */
export function MessageItem({
  message,
  className = '',
}: MessageItemProps) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  // If message has segments, render them
  if (message.segments && message.segments.length > 0) {
    return (
      <div className={`flex flex-col gap-2 ${isUser ? 'items-end' : 'items-start'} ${className}`}>
        {message.segments.map((segment, index) => (
          <SegmentRenderer key={index} segment={segment} isUser={isUser} />
        ))}
        <span className="text-xs text-gray-400 mt-1">
          {formatTime(message.createdAt)}
        </span>
      </div>
    );
  }

  // Simple message without segments
  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} ${className}`}>
      <div
        className={
          isUser
            ? 'chat-message-user'
            : isSystem
            ? 'chat-message-assistant bg-gray-100 dark:bg-gray-700 text-sm'
            : 'chat-message-assistant'
        }
      >
        <MessageFormatter content={message.content} role={message.role} />
      </div>
      <span className="text-xs text-gray-400 mt-1">
        {formatTime(message.createdAt)}
      </span>
    </div>
  );
}

/**
 * Renders a content segment
 */
function SegmentRenderer({
  segment,
  isUser,
}: {
  segment: ContentSegment;
  isUser: boolean;
}) {
  if (segment.type === 'tool') {
    return (
      <ToolIndicator
        tool={{
          name: segment.name || 'Tool',
          id: segment.id || '',
          startedAt: segment.completedAt || Date.now(),
          input: segment.input,
        }}
      />
    );
  }

  if (segment.type === 'agent') {
    return (
      <ToolIndicator
        agent={{
          type: segment.agentType || 'Task',
          model: segment.model || '',
          description: segment.description || '',
          startedAt: segment.launchedAt || Date.now(),
        }}
      />
    );
  }

  // Text segment
  if (!segment.content?.trim()) return null;

  return (
    <div className={isUser ? 'chat-message-user' : 'chat-message-assistant'}>
      <MessageFormatter content={segment.content} role={isUser ? 'user' : 'assistant'} />
    </div>
  );
}
