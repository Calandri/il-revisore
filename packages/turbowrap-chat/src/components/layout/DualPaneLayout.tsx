/**
 * DualPaneLayout - Side-by-side chat layout
 */

import React from 'react';

export interface DualPaneLayoutProps {
  enabled: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * Renders single or dual pane layout
 */
export function DualPaneLayout({
  enabled,
  children,
  className = '',
}: DualPaneLayoutProps) {
  const childArray = React.Children.toArray(children);

  if (!enabled || childArray.length < 2) {
    return (
      <div className={`flex-1 flex flex-col ${className}`}>
        {childArray[0]}
      </div>
    );
  }

  return (
    <div className={`flex-1 flex ${className}`}>
      {/* Left pane */}
      <div className="flex-1 flex flex-col border-r border-gray-200 dark:border-gray-700">
        {childArray[0]}
      </div>

      {/* Right pane */}
      <div className="flex-1 flex flex-col">
        {childArray[1]}
      </div>
    </div>
  );
}
