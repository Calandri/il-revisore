/**
 * CLI Chat Formatting Utilities
 *
 * Functions for formatting dates, context usage, model names,
 * tool descriptions, and token categories.
 */

import {
    MODEL_SHORTCUTS,
    CONTEXT_LIMITS,
    TOKEN_CATEGORY_COLORS,
    DEFAULT_CATEGORY_COLOR,
} from './constants.js';

/**
 * Format a timestamp as relative time (5m, 2h, 1d, etc.)
 *
 * @param {string|Date|null} timestamp - ISO timestamp or Date object
 * @returns {string} Relative time string or empty string if no timestamp
 *
 * @example
 * formatRelativeTime('2024-01-01T12:00:00Z') // '2d' (if 2 days ago)
 * formatRelativeTime(new Date()) // 'now'
 * formatRelativeTime(null) // ''
 */
export function formatRelativeTime(timestamp) {
    if (!timestamp) return '';

    // Ensure UTC interpretation: add 'Z' if timestamp has no timezone info
    let ts = timestamp;
    if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+') && !ts.includes('-', 10)) {
        ts = ts + 'Z';
    }

    const date = typeof ts === 'string' ? new Date(ts) : ts;
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    const diffWeeks = Math.floor(diffDays / 7);
    const diffMonths = Math.floor(diffDays / 30);

    if (diffSecs < 10) return 'now';
    if (diffSecs < 60) return `${diffSecs}s`;
    if (diffMins < 60) return `${diffMins}m`;
    if (diffHours < 24) return `${diffHours}h`;
    if (diffDays < 7) return `${diffDays}d`;
    if (diffWeeks < 4) return `${diffWeeks}w`;
    return `${diffMonths}mo`;
}

/**
 * Format context usage as "XK / 200K (Y%)"
 *
 * @param {number} tokensIn - Total input tokens used
 * @param {string} cliType - CLI type ('claude' or 'gemini')
 * @returns {string} Formatted context usage string
 *
 * @example
 * formatContextUsage(50000, 'claude') // '50K / 200K (25%)'
 * formatContextUsage(500, 'gemini') // '<1K / 1000K'
 */
export function formatContextUsage(tokensIn, cliType) {
    const contextLimit = CONTEXT_LIMITS[cliType] || CONTEXT_LIMITS.claude;
    const usedK = Math.round(tokensIn / 1000);
    const limitK = Math.round(contextLimit / 1000);
    const percentage = Math.round((tokensIn / contextLimit) * 100);

    if (usedK < 1) {
        return `<1K / ${limitK}K`;
    }
    return `${usedK}K / ${limitK}K (${percentage}%)`;
}

/**
 * Get short model name for display
 *
 * @param {string|null} model - Full model name (e.g., 'claude-3-opus-20240229')
 * @returns {string} Short name (e.g., 'Opus')
 *
 * @example
 * getModelShortName('claude-3-opus-20240229') // 'Opus'
 * getModelShortName('gemini-1.5-pro') // 'Pro'
 * getModelShortName(null) // 'default'
 */
export function getModelShortName(model) {
    if (!model) return 'default';

    // Check each shortcut keyword
    for (const [keyword, shortName] of Object.entries(MODEL_SHORTCUTS)) {
        if (model.includes(keyword)) {
            return shortName;
        }
    }

    // Fallback: extract meaningful part from model name
    return model.split('-').slice(1, 2).join(' ') || model;
}

/**
 * Get tool description for display in the UI
 *
 * Extracts the most relevant field from the tool input
 * to show a concise description of what the tool is doing.
 *
 * @param {Object|null} tool - Tool object with name and input
 * @param {string} tool.name - Tool name (e.g., 'Read', 'Bash')
 * @param {Object} tool.input - Tool input parameters
 * @returns {string} Description to display
 *
 * @example
 * getToolDescription({ name: 'Read', input: { file_path: '/src/main.js' } })
 * // '/src/main.js'
 *
 * getToolDescription({ name: 'Bash', input: { command: 'npm install' } })
 * // 'npm install'
 */
export function getToolDescription(tool) {
    if (!tool || !tool.input) return '';

    const input = tool.input;

    switch (tool.name) {
        case 'Read':
        case 'Edit':
        case 'Write':
            return input.file_path || '';

        case 'Bash': {
            const cmd = input.command || input.description || '';
            return cmd.length > 60 ? cmd.substring(0, 57) + '...' : cmd;
        }

        case 'Grep':
        case 'Glob':
            return input.pattern || '';

        case 'Task':
            return input.description || input.subagent_type || '';

        case 'WebSearch':
            return input.query || '';

        case 'WebFetch':
            return input.url || '';

        default:
            return (
                input.file_path ||
                input.pattern ||
                input.command?.substring(0, 50) ||
                input.description ||
                ''
            );
    }
}

/**
 * Get color for token category in context breakdown visualization
 *
 * @param {string} name - Category name (e.g., 'System prompt', 'Messages')
 * @returns {string} Hex color code
 *
 * @example
 * getTokenCategoryColor('System prompt') // '#f472b6'
 * getTokenCategoryColor('Unknown') // '#6b7280' (default)
 */
export function getTokenCategoryColor(name) {
    return TOKEN_CATEGORY_COLORS[name] || DEFAULT_CATEGORY_COLOR;
}
