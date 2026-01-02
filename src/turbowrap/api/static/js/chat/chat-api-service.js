/**
 * Chat API Service
 *
 * Centralizes all API calls for the CLI chat system.
 * Provides consistent error handling, response parsing, and abort support.
 *
 * @example
 * import { ChatApiService } from './chat/chat-api-service.js';
 *
 * // Load sessions
 * const sessions = await ChatApiService.getSessions({ repositoryId: 'repo-123' });
 *
 * // Create session with error handling
 * try {
 *     const session = await ChatApiService.createSession({
 *         cli_type: 'claude',
 *         display_name: 'New Chat',
 *         repository_id: 'repo-123'
 *     });
 * } catch (error) {
 *     TurboWrapError.handle('Create Session', error);
 * }
 */

/**
 * Base URL for CLI chat API endpoints
 * @type {string}
 */
const BASE_URL = '/api/cli-chat';

/**
 * Base URL for Git API endpoints
 * @type {string}
 */
const GIT_BASE_URL = '/api/git';

/**
 * Custom error class for API errors with status code
 */
class ApiError extends Error {
    /**
     * @param {string} message - Error message
     * @param {number} status - HTTP status code
     * @param {string} [statusText] - HTTP status text
     */
    constructor(message, status, statusText = '') {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.statusText = statusText;
    }
}

/**
 * Internal helper for making fetch requests with consistent error handling
 *
 * @param {string} url - Full URL to fetch
 * @param {Object} [options={}] - Fetch options
 * @param {string} [options.method='GET'] - HTTP method
 * @param {Object} [options.body] - Request body (will be JSON stringified)
 * @param {AbortSignal} [options.signal] - AbortController signal for cancellation
 * @param {Object} [options.headers] - Additional headers
 * @returns {Promise<any>} Parsed JSON response
 * @throws {ApiError} When response is not ok
 *
 * @private
 */
async function _fetch(url, options = {}) {
    const { method = 'GET', body, signal, headers = {} } = options;

    const fetchOptions = {
        method,
        headers: {
            'Content-Type': 'application/json',
            ...headers,
        },
    };

    if (body) {
        fetchOptions.body = JSON.stringify(body);
    }

    if (signal) {
        fetchOptions.signal = signal;
    }

    const response = await fetch(url, fetchOptions);

    if (!response.ok) {
        const errorText = await response.text().catch(() => '');
        throw new ApiError(
            errorText || `HTTP ${response.status}`,
            response.status,
            response.statusText
        );
    }

    // Handle 204 No Content
    if (response.status === 204) {
        return null;
    }

    return response.json();
}

/**
 * Chat API Service
 *
 * Static class providing methods for all CLI chat API interactions.
 * All methods are async and return parsed JSON responses.
 * Errors are thrown as ApiError instances for consistent handling.
 */
export const ChatApiService = {
    // ========================================================================
    // SESSIONS
    // ========================================================================

    /**
     * Get all chat sessions, optionally filtered by repository
     *
     * @param {Object} [options={}] - Query options
     * @param {string} [options.repositoryId] - Filter by repository ID
     * @param {AbortSignal} [options.signal] - AbortController signal
     * @returns {Promise<Array>} Array of session objects
     *
     * @example
     * const allSessions = await ChatApiService.getSessions();
     * const repoSessions = await ChatApiService.getSessions({ repositoryId: 'repo-123' });
     */
    async getSessions({ repositoryId, signal } = {}) {
        let url = `${BASE_URL}/sessions`;
        if (repositoryId) {
            url += `?repository_id=${encodeURIComponent(repositoryId)}`;
        }
        return _fetch(url, { signal });
    },

    /**
     * Create a new chat session
     *
     * @param {Object} data - Session creation data
     * @param {string} data.cli_type - CLI type ('claude' or 'gemini')
     * @param {string} [data.display_name] - Display name for the session
     * @param {string} [data.color] - Color hex code for the session
     * @param {string} [data.repository_id] - Associated repository ID
     * @param {string} [data.agent_name] - Agent name to use
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Created session object
     *
     * @example
     * const session = await ChatApiService.createSession({
     *     cli_type: 'claude',
     *     display_name: 'Code Review',
     *     repository_id: 'repo-123'
     * });
     */
    async createSession(data, signal) {
        return _fetch(`${BASE_URL}/sessions`, {
            method: 'POST',
            body: data,
            signal,
        });
    },

    /**
     * Get a single session by ID
     *
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Session object
     *
     * @example
     * const session = await ChatApiService.getSession('session-uuid');
     */
    async getSession(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}`, { signal });
    },

    /**
     * Update session settings
     *
     * @param {string} sessionId - Session UUID
     * @param {Object} data - Fields to update
     * @param {string} [data.model] - Model to use
     * @param {string} [data.agent_name] - Agent name
     * @param {boolean} [data.thinking_enabled] - Enable thinking mode
     * @param {number} [data.thinking_budget] - Thinking budget tokens
     * @param {boolean} [data.reasoning_enabled] - Enable reasoning
     * @param {string} [data.mockup_id] - Associated mockup ID
     * @param {string} [data.mockup_project_id] - Associated mockup project ID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Updated session object
     *
     * @example
     * const updated = await ChatApiService.updateSession('session-uuid', {
     *     model: 'claude-3-opus',
     *     thinking_enabled: true
     * });
     */
    async updateSession(sessionId, data, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}`, {
            method: 'PUT',
            body: data,
            signal,
        });
    },

    /**
     * Delete a session
     *
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<null>} Null on success
     *
     * @example
     * await ChatApiService.deleteSession('session-uuid');
     */
    async deleteSession(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}`, {
            method: 'DELETE',
            signal,
        });
    },

    // ========================================================================
    // MESSAGES
    // ========================================================================

    /**
     * Get all messages for a session
     *
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Array>} Array of message objects
     *
     * @example
     * const messages = await ChatApiService.getMessages('session-uuid');
     */
    async getMessages(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/messages`, { signal });
    },

    // ========================================================================
    // CONTEXT & USAGE
    // ========================================================================

    /**
     * Get context information for a session (token usage breakdown)
     *
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Context info with categories, tokens, etc.
     *
     * @example
     * const context = await ChatApiService.getContext('session-uuid');
     * console.log(context.tokens.used, context.tokens.limit);
     */
    async getContext(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/context`, { signal });
    },

    /**
     * Get usage statistics for a session
     *
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Usage info with token counts, costs, etc.
     *
     * @example
     * const usage = await ChatApiService.getUsage('session-uuid');
     */
    async getUsage(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/usage`, { signal });
    },

    // ========================================================================
    // FORK & BRANCH
    // ========================================================================

    /**
     * Fork a session (create a copy with same messages)
     *
     * @param {string} sessionId - Session UUID to fork
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Newly created forked session
     *
     * @example
     * const forkedSession = await ChatApiService.forkSession('session-uuid');
     */
    async forkSession(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/fork`, {
            method: 'POST',
            signal,
        });
    },

    /**
     * Change the git branch for a session's repository
     *
     * @param {string} sessionId - Session UUID
     * @param {string} branch - Branch name to switch to
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Updated session object
     *
     * @example
     * const updated = await ChatApiService.changeBranch('session-uuid', 'feature/new-feature');
     */
    async changeBranch(sessionId, branch, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/branch`, {
            method: 'POST',
            body: { branch },
            signal,
        });
    },

    /**
     * Get available git branches for a session's repository
     *
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Array<string>>} Array of branch names
     *
     * @example
     * const branches = await ChatApiService.getBranches('session-uuid');
     * // ['main', 'develop', 'feature/new-feature']
     */
    async getBranches(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/branches`, { signal });
    },

    // ========================================================================
    // AGENTS & COMMANDS
    // ========================================================================

    /**
     * Get all available agents
     *
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Object with agents array
     *
     * @example
     * const { agents } = await ChatApiService.getAgents();
     */
    async getAgents(signal) {
        return _fetch(`${BASE_URL}/agents`, { signal });
    },

    /**
     * Get a slash command prompt by name
     *
     * @param {string} commandName - Command name without slash (e.g., 'test', 'review')
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Command object with prompt
     *
     * @example
     * const { prompt } = await ChatApiService.getCommand('test');
     */
    async getCommand(commandName, signal) {
        return _fetch(`${BASE_URL}/commands/${encodeURIComponent(commandName)}`, { signal });
    },

    // ========================================================================
    // SERVER LOGS
    // ========================================================================

    /**
     * Fetch server logs from CloudWatch for analysis
     *
     * @param {Object} [options={}] - Query options
     * @param {number} [options.minutes=30] - Number of minutes of logs to fetch
     * @param {AbortSignal} [options.signal] - AbortController signal
     * @returns {Promise<Object>} Object with markdown log content and summary
     *
     * @example
     * const { markdown, summary } = await ChatApiService.getServerLogs({ minutes: 60 });
     */
    async getServerLogs({ minutes = 30, signal } = {}) {
        return _fetch(`${BASE_URL}/server-logs?minutes=${minutes}`, { signal });
    },

    // ========================================================================
    // REPOSITORIES (from /api/git)
    // ========================================================================

    /**
     * Get all available repositories
     *
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Array>} Array of repository objects
     *
     * @example
     * const repos = await ChatApiService.getRepositories();
     */
    async getRepositories(signal) {
        return _fetch(`${GIT_BASE_URL}/repositories`, { signal });
    },
};

/**
 * Export the ApiError class for external error type checking
 */
export { ApiError };
