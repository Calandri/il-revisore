/**
 * StreamingMessage - Live streaming response with cursor
 */

import type { ContentSegment, ToolState, AgentState } from '../../types';
import { MessageFormatter } from '../formatting/MessageFormatter';
import { ToolIndicator } from './ToolIndicator';

export interface StreamingMessageProps {
  content: string;
  segments: ContentSegment[];
  activeTools: ToolState[];
  activeAgents: AgentState[];
  className?: string;
}

/**
 * Loading dots animation
 */
function LoadingDots() {
  return (
    <div className="flex items-center gap-1 py-2">
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce-dot animate-bounce-dot-1" />
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce-dot animate-bounce-dot-2" />
      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce-dot animate-bounce-dot-3" />
    </div>
  );
}

/**
 * Renders the streaming response with live updates
 */
export function StreamingMessage({
  content,
  segments = [],
  activeTools = [],
  activeAgents = [],
  className = '',
}: StreamingMessageProps) {
  // Safe arrays with defaults
  const safeSegments = segments || [];
  const safeActiveTools = activeTools || [];
  const safeActiveAgents = activeAgents || [];

  // Show loading dots if no content yet
  if (!content && safeSegments.every((s) => !s.content?.trim()) && safeActiveTools.length === 0) {
    return (
      <div className={`flex items-start ${className}`}>
        <div className="chat-message-assistant">
          <LoadingDots />
        </div>
      </div>
    );
  }

  return (
    <div className={`flex flex-col items-start gap-2 ${className}`}>
      {/* Render segments */}
      {safeSegments.map((segment, index) => (
        <SegmentRenderer key={index} segment={segment} isLast={index === safeSegments.length - 1} />
      ))}

      {/* Show active tools */}
      {safeActiveTools.map((tool) => (
        <ToolIndicator key={tool.id} tool={tool} />
      ))}

      {/* Show active agents */}
      {safeActiveAgents.map((agent, index) => (
        <ToolIndicator key={`agent-${index}`} agent={agent} />
      ))}
    </div>
  );
}

/**
 * Renders a streaming segment
 */
function SegmentRenderer({
  segment,
  isLast,
}: {
  segment: ContentSegment;
  isLast: boolean;
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
    <div className="chat-message-assistant">
      <MessageFormatter content={segment.content} role="assistant" />
      {isLast && (
        <span className="inline-block w-2 h-4 bg-indigo-500 ml-0.5 animate-blink" />
      )}
    </div>
  );
}
