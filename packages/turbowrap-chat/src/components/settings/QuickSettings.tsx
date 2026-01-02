/**
 * QuickSettings - Compact settings bar at top of chat
 */

import { useState } from 'react';
import type { Session, Repository } from '../../types';

export interface QuickSettingsProps {
  session: Session;
  repository?: Repository | null;
  branches?: string[];
  currentBranch?: string | null;
  onModelChange: (model: string) => void;
  onRepoClick: () => void;
  onBranchChange?: (branch: string) => void;
  onInfoClick: () => void;
  className?: string;
}

/**
 * Get available models for CLI type
 */
function getModels(cliType: 'claude' | 'gemini'): { value: string; label: string }[] {
  if (cliType === 'gemini') {
    return [
      { value: 'gemini-2.0-flash-exp', label: 'Flash' },
      { value: 'gemini-exp-1206', label: 'Pro' },
    ];
  }
  return [
    { value: 'opus', label: 'Opus' },
    { value: 'sonnet', label: 'Sonnet' },
    { value: 'haiku', label: 'Haiku' },
  ];
}

/**
 * Get short model name
 */
function getModelShortName(model: string | null): string {
  if (!model) return 'Select';
  if (model.includes('opus')) return 'Opus';
  if (model.includes('sonnet')) return 'Sonnet';
  if (model.includes('haiku')) return 'Haiku';
  if (model.includes('flash')) return 'Flash';
  if (model.includes('pro')) return 'Pro';
  return model.split('-')[0];
}

/**
 * Chevron icon
 */
function ChevronIcon() {
  return (
    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  );
}

/**
 * Info icon
 */
function InfoIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

/**
 * Renders the quick settings bar
 */
export function QuickSettings({
  session,
  repository,
  branches = [],
  currentBranch,
  onModelChange,
  onRepoClick,
  onBranchChange,
  onInfoClick,
  className = '',
}: QuickSettingsProps) {
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [showBranchMenu, setShowBranchMenu] = useState(false);

  const models = getModels(session.cliType);

  return (
    <div className={`flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-200 dark:border-gray-700 text-sm ${className}`}>
      {/* CLI badge */}
      <span
        className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
          session.cliType === 'gemini'
            ? 'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400'
            : 'bg-orange-100 text-orange-600 dark:bg-orange-900 dark:text-orange-400'
        }`}
      >
        {session.cliType === 'gemini' ? 'G' : 'C'}
      </span>

      {/* Model selector */}
      <div className="relative">
        <button
          onClick={() => setShowModelMenu(!showModelMenu)}
          className="flex items-center gap-1 px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
        >
          <span>{getModelShortName(session.model)}</span>
          <ChevronIcon />
        </button>

        {showModelMenu && (
          <>
            <div
              className="fixed inset-0 z-40"
              onClick={() => setShowModelMenu(false)}
            />
            <div className="absolute left-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1 min-w-[100px]">
              {models.map((model) => (
                <button
                  key={model.value}
                  onClick={() => {
                    onModelChange(model.value);
                    setShowModelMenu(false);
                  }}
                  className={`w-full px-3 py-1.5 text-left hover:bg-gray-100 dark:hover:bg-gray-700 ${
                    session.model?.includes(model.value.toLowerCase())
                      ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600'
                      : ''
                  }`}
                >
                  {model.label}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Divider */}
      <span className="text-gray-300 dark:text-gray-600">|</span>

      {/* Repository selector */}
      <button
        onClick={onRepoClick}
        className="flex items-center gap-1 px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors truncate max-w-[150px]"
      >
        <span className="truncate">
          {repository?.name || 'Select repo'}
        </span>
        <ChevronIcon />
      </button>

      {/* Branch selector (if repo selected) */}
      {repository && branches.length > 0 && onBranchChange && (
        <div className="relative">
          <button
            onClick={() => setShowBranchMenu(!showBranchMenu)}
            className="flex items-center gap-1 px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors text-gray-500"
          >
            <span className="truncate max-w-[100px]">
              {currentBranch || 'main'}
            </span>
            <ChevronIcon />
          </button>

          {showBranchMenu && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setShowBranchMenu(false)}
              />
              <div className="absolute left-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1 min-w-[120px] max-h-48 overflow-y-auto">
                {branches.map((branch) => (
                  <button
                    key={branch}
                    onClick={() => {
                      onBranchChange(branch);
                      setShowBranchMenu(false);
                    }}
                    className={`w-full px-3 py-1.5 text-left hover:bg-gray-100 dark:hover:bg-gray-700 truncate ${
                      branch === currentBranch
                        ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600'
                        : ''
                    }`}
                  >
                    {branch}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Info button */}
      <button
        onClick={onInfoClick}
        className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors text-gray-500"
        title="Session info"
      >
        <InfoIcon />
      </button>
    </div>
  );
}
