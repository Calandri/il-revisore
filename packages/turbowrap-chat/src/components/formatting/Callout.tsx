/**
 * Callout - Info/Warning/Error/Success/Tip boxes
 */

import React from 'react';

export type CalloutType = 'info' | 'warning' | 'error' | 'success' | 'tip';

export interface CalloutProps {
  type: CalloutType;
  children: React.ReactNode;
  className?: string;
}

const icons: Record<CalloutType, string> = {
  info: '💡',
  warning: '⚠️',
  error: '❌',
  success: '✅',
  tip: '💡',
};

/**
 * Renders a callout box
 */
export function Callout({
  type,
  children,
  className = '',
}: CalloutProps) {
  return (
    <div className={`chat-callout chat-callout-${type} ${className}`}>
      <span className="mr-2 flex-shrink-0">{icons[type]}</span>
      <div className="flex-1">{children}</div>
    </div>
  );
}
