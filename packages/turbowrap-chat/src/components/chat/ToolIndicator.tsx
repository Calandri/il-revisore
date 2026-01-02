/**
 * ToolIndicator - Shows active tool/agent execution
 */

import type { ToolState, AgentState } from '../../types';

export interface ToolIndicatorProps {
  tool?: ToolState;
  agent?: AgentState;
  className?: string;
}

/**
 * Get a short description for a tool
 */
function getToolDescription(tool: ToolState): string {
  const input = tool.input;
  if (!input) return tool.name;

  // Common patterns
  if (input.file_path) return String(input.file_path).split('/').pop() || tool.name;
  if (input.pattern) return String(input.pattern).slice(0, 30);
  if (input.command) return String(input.command).slice(0, 40);
  if (input.query) return String(input.query).slice(0, 30);
  if (input.url) return String(input.url).slice(0, 40);

  return tool.name;
}

/**
 * Renders a tool or agent indicator during streaming
 */
export function ToolIndicator({
  tool,
  agent,
  className = '',
}: ToolIndicatorProps) {
  if (agent) {
    return (
      <div className={`chat-agent-indicator ${className}`}>
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
        </svg>
        <span className="font-medium">Task</span>
        <span className="text-gray-400 truncate max-w-[200px]">
          {agent.description}
        </span>
      </div>
    );
  }

  if (tool) {
    return (
      <div className={`chat-tool-indicator ${className}`}>
        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <span className="font-medium">{tool.name}</span>
        <span className="text-gray-400 truncate max-w-[200px]">
          {getToolDescription(tool)}
        </span>
      </div>
    );
  }

  return null;
}
