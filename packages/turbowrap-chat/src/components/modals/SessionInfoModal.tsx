/**
 * SessionInfoModal - Modal showing session details
 */

import type { Session } from '../../types';
import type { ContextInfo, UsageInfo } from '../../types';

export interface SessionInfoModalProps {
  isOpen: boolean;
  session: Session | null;
  contextInfo?: ContextInfo | null;
  usageInfo?: UsageInfo | null;
  onClose: () => void;
  className?: string;
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
 * Format number with commas
 */
function formatNumber(num: number): string {
  return num.toLocaleString();
}

/**
 * Format cost
 */
function formatCost(cost: number): string {
  return `$${cost.toFixed(4)}`;
}

/**
 * Progress bar component
 */
function ProgressBar({
  value,
  max,
  label,
  color = 'indigo',
}: {
  value: number;
  max: number;
  label: string;
  color?: 'indigo' | 'green' | 'amber' | 'red';
}) {
  const percentage = Math.min(100, (value / max) * 100);
  const colorClasses = {
    indigo: 'bg-indigo-500',
    green: 'bg-green-500',
    amber: 'bg-amber-500',
    red: 'bg-red-500',
  };

  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-600 dark:text-gray-400">{label}</span>
        <span className="font-mono">
          {formatNumber(value)} / {formatNumber(max)}
        </span>
      </div>
      <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${colorClasses[color]} transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

/**
 * Info row component
 */
function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-2 border-b border-gray-100 dark:border-gray-800 last:border-0">
      <span className="text-gray-500 dark:text-gray-400">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

/**
 * Renders the session info modal
 */
export function SessionInfoModal({
  isOpen,
  session,
  contextInfo,
  usageInfo,
  onClose,
  className = '',
}: SessionInfoModalProps) {
  if (!isOpen || !session) return null;

  const contextPercentage = contextInfo
    ? (contextInfo.tokens.used / contextInfo.tokens.limit) * 100
    : 0;

  const contextColor =
    contextPercentage > 90 ? 'red' : contextPercentage > 70 ? 'amber' : 'indigo';

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-50" onClick={onClose} />

      {/* Modal */}
      <div className={`fixed inset-0 z-50 flex items-center justify-center p-4 ${className}`}>
        <div
          className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-md"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
            <h2 className="text-lg font-semibold">Session Info</h2>
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <CloseIcon />
            </button>
          </div>

          {/* Content */}
          <div className="p-4 space-y-6">
            {/* Session details */}
            <div>
              <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                Session
              </h3>
              <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3">
                <InfoRow label="Name" value={session.displayName || 'Untitled'} />
                <InfoRow
                  label="CLI Type"
                  value={
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        session.cliType === 'gemini'
                          ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
                          : 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300'
                      }`}
                    >
                      {session.cliType === 'gemini' ? 'Gemini CLI' : 'Claude CLI'}
                    </span>
                  }
                />
                <InfoRow label="Model" value={session.model || 'Not set'} />
                <InfoRow label="Messages" value={session.totalMessages} />
                <InfoRow
                  label="Created"
                  value={new Date(session.createdAt).toLocaleDateString()}
                />
              </div>
            </div>

            {/* Context usage */}
            {contextInfo && (
              <div>
                <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                  Context Usage
                </h3>
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 space-y-3">
                  <ProgressBar
                    value={contextInfo.tokens.used}
                    max={contextInfo.tokens.limit}
                    label="Total Tokens"
                    color={contextColor}
                  />

                  {contextInfo.categories && contextInfo.categories.length > 0 && (
                    <div className="pt-2 border-t border-gray-200 dark:border-gray-700">
                      <div className="text-xs text-gray-500 mb-2">By Category</div>
                      <div className="space-y-1">
                        {contextInfo.categories.map((cat) => (
                          <div key={cat.name} className="flex justify-between text-sm">
                            <span className="text-gray-600 dark:text-gray-400">
                              {cat.name}
                            </span>
                            <span className="font-mono text-xs">
                              {formatNumber(cat.tokens)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Usage/Cost info */}
            {usageInfo && (
              <div>
                <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                  Usage
                </h3>
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3">
                  <InfoRow label="Input Tokens" value={formatNumber(usageInfo.inputTokens || 0)} />
                  <InfoRow label="Output Tokens" value={formatNumber(usageInfo.outputTokens || 0)} />
                  {usageInfo.cacheReadTokens !== undefined && usageInfo.cacheReadTokens > 0 && (
                    <InfoRow
                      label="Cache Read"
                      value={formatNumber(usageInfo.cacheReadTokens)}
                    />
                  )}
                  {usageInfo.cacheWriteTokens !== undefined && usageInfo.cacheWriteTokens > 0 && (
                    <InfoRow
                      label="Cache Write"
                      value={formatNumber(usageInfo.cacheWriteTokens)}
                    />
                  )}
                  {usageInfo.cost !== undefined && (
                    <InfoRow
                      label="Cost"
                      value={
                        <span className="text-green-600 dark:text-green-400">
                          {formatCost(usageInfo.cost)}
                        </span>
                      }
                    />
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 flex justify-end">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
