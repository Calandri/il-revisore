/**
 * CLI Chat Constants
 *
 * Centralized constants for the CLI chat system.
 * These values are used across multiple components for consistency.
 */

/**
 * Model name shortcuts for display
 * Maps model identifiers to human-readable short names
 * @type {Record<string, string>}
 */
export const MODEL_SHORTCUTS = {
    opus: 'Opus',
    sonnet: 'Sonnet',
    haiku: 'Haiku',
    pro: 'Pro',
    flash: 'Flash',
    grok: 'Grok',
};

/**
 * Context window limits by CLI type (in tokens)
 * @type {Record<string, number>}
 */
export const CONTEXT_LIMITS = {
    claude: 200000,
    gemini: 1000000,
};

/**
 * Colors for token category visualization in context breakdown
 * @type {Record<string, string>}
 */
export const TOKEN_CATEGORY_COLORS = {
    'System prompt': '#f472b6',
    'System tools': '#a78bfa',
    'MCP tools': '#60a5fa',
    'Custom agents': '#34d399',
    'Memory files': '#fbbf24',
    'Messages': '#f97316',
    'Free space': '#374151',
    'Autocompact buffer': '#6b7280',
};

/**
 * Worker message types for SharedWorker communication
 * @type {string[]}
 */
export const WORKER_MESSAGE_TYPES = [
    'STREAM_START',
    'CHUNK',
    'SYSTEM',
    'TOOL_START',
    'TOOL_END',
    'AGENT_START',
    'DONE',
    'TITLE_UPDATE',
    'ERROR',
    'STREAM_ABORTED',
    'STREAM_END',
    'STATE_SYNC',
    'ACTION',
];

/**
 * SSE event types received from the backend
 * @type {string[]}
 */
export const SSE_EVENT_TYPES = [
    'chunk',
    'tool_start',
    'tool_end',
    'agent_start',
    'system',
    'done',
    'error',
    'title_update',
];

/**
 * Available chat display modes
 * @type {string[]}
 */
export const CHAT_MODES = ['third', 'full', 'page'];

/**
 * Tool names that the CLI supports
 * @type {string[]}
 */
export const TOOL_NAMES = [
    'Read',
    'Edit',
    'Write',
    'Bash',
    'Grep',
    'Glob',
    'Task',
    'WebSearch',
    'WebFetch',
];

/**
 * Default fallback color for unknown token categories
 * @type {string}
 */
export const DEFAULT_CATEGORY_COLOR = '#6b7280';
