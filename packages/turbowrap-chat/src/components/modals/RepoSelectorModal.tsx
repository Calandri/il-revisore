/**
 * RepoSelectorModal - Modal for selecting a repository
 */

import { useState, useMemo } from 'react';
import type { Repository } from '../../types';

export interface RepoSelectorModalProps {
  isOpen: boolean;
  repositories: Repository[];
  selectedRepoId: string | null;
  isLoading?: boolean;
  onSelect: (repoId: string) => void;
  onClose: () => void;
  className?: string;
}

/**
 * Search icon
 */
function SearchIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
    </svg>
  );
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
 * Repository icon
 */
function RepoIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
    </svg>
  );
}

/**
 * Renders the repository selector modal
 */
export function RepoSelectorModal({
  isOpen,
  repositories,
  selectedRepoId,
  isLoading = false,
  onSelect,
  onClose,
  className = '',
}: RepoSelectorModalProps) {
  const [search, setSearch] = useState('');

  // Filter repositories
  const filteredRepos = useMemo(() => {
    if (!search.trim()) return repositories;
    const lowerSearch = search.toLowerCase();
    return repositories.filter(
      (repo) =>
        repo.name.toLowerCase().includes(lowerSearch) ||
        repo.fullName?.toLowerCase().includes(lowerSearch)
    );
  }, [repositories, search]);

  // Reset search on close
  const handleClose = () => {
    setSearch('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-50"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className={`fixed inset-0 z-50 flex items-center justify-center p-4 ${className}`}>
        <div
          className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
            <h2 className="text-lg font-semibold">Select Repository</h2>
            <button
              onClick={handleClose}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <CloseIcon />
            </button>
          </div>

          {/* Search */}
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                <SearchIcon />
              </span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search repositories..."
                className="w-full pl-10 pr-4 py-2 bg-gray-100 dark:bg-gray-800 border border-transparent focus:border-indigo-500 rounded-lg outline-none transition-colors"
                autoFocus
              />
            </div>
          </div>

          {/* Repository list */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full" />
              </div>
            ) : filteredRepos.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                {search ? 'No repositories match your search' : 'No repositories available'}
              </div>
            ) : (
              <div className="py-2">
                {filteredRepos.map((repo) => (
                  <button
                    key={repo.id}
                    onClick={() => {
                      onSelect(repo.id);
                      handleClose();
                    }}
                    className={`w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors ${
                      repo.id === selectedRepoId
                        ? 'bg-indigo-50 dark:bg-indigo-900/30'
                        : ''
                    }`}
                  >
                    <span className="text-gray-400">
                      <RepoIcon />
                    </span>
                    <div className="flex-1 text-left">
                      <div className="font-medium">{repo.name}</div>
                      {repo.fullName && repo.fullName !== repo.name && (
                        <div className="text-sm text-gray-500">{repo.fullName}</div>
                      )}
                    </div>
                    {repo.id === selectedRepoId && (
                      <span className="text-indigo-600 dark:text-indigo-400">
                        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd"
                            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                            clipRule="evenodd" />
                        </svg>
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
