/**
 * Chat API Service
 *
 * Centralizes all API calls for the CLI chat system.
 * Provides consistent error handling, response parsing, and abort support.
 *
 * @example
 * import { ChatApiService } from './chat/chat-api-service.js';
 *
 * const sessions = await ChatApiService.getSessions({ repositoryId: 'repo-123' });
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
 * @returns {Promise<any>} Parsed JSON response
 * @throws {ApiError} When response is not ok
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
 * Chat API Service - Static methods for all CLI chat API interactions
 */
export const ChatApiService = {
    // ========================================================================
    // SESSIONS
    // ========================================================================

    /**
     * Get all chat sessions, optionally filtered by repository
     * @param {Object} [options={}] - Query options
     * @returns {Promise<Array>} Array of session objects
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
     * @param {Object} data - Session creation data
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Created session object
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
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Session object
     */
    async getSession(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}`, { signal });
    },

    /**
     * Update session settings
     * @param {string} sessionId - Session UUID
     * @param {Object} data - Fields to update
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Updated session object
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
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<null>} Null on success
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
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Array>} Array of message objects
     */
    async getMessages(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/messages`, { signal });
    },

    // ========================================================================
    // CONTEXT & USAGE
    // ========================================================================

    /**
     * Get context information for a session (token usage breakdown)
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Context info with categories, tokens, etc.
     */
    async getContext(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/context`, { signal });
    },

    /**
     * Get usage statistics for a session
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Usage info with token counts, costs, etc.
     */
    async getUsage(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/usage`, { signal });
    },

    // ========================================================================
    // FORK & BRANCH
    // ========================================================================

    /**
     * Fork a session (create a copy with same messages)
     * @param {string} sessionId - Session UUID to fork
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Newly created forked session
     */
    async forkSession(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/fork`, {
            method: 'POST',
            signal,
        });
    },

    /**
     * Change the git branch for a session's repository
     * @param {string} sessionId - Session UUID
     * @param {string} branch - Branch name to switch to
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Updated session object
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
     * @param {string} sessionId - Session UUID
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Array<string>>} Array of branch names
     */
    async getBranches(sessionId, signal) {
        return _fetch(`${BASE_URL}/sessions/${sessionId}/branches`, { signal });
    },

    // ========================================================================
    // AGENTS & COMMANDS
    // ========================================================================

    /**
     * Get all available agents
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Object with agents array
     */
    async getAgents(signal) {
        return _fetch(`${BASE_URL}/agents`, { signal });
    },

    /**
     * Get a slash command prompt by name
     * @param {string} commandName - Command name without slash
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Object>} Command object with prompt
     */
    async getCommand(commandName, signal) {
        return _fetch(`${BASE_URL}/commands/${encodeURIComponent(commandName)}`, { signal });
    },

    // ========================================================================
    // SERVER LOGS
    // ========================================================================

    /**
     * Fetch server logs from CloudWatch for analysis
     * @param {Object} [options={}] - Query options
     * @returns {Promise<Object>} Object with markdown log content and summary
     */
    async getServerLogs({ minutes = 30, signal } = {}) {
        return _fetch(`${BASE_URL}/server-logs?minutes=${minutes}`, { signal });
    },

    // ========================================================================
    // REPOSITORIES
    // ========================================================================

    /**
     * Get all available repositories
     * @param {AbortSignal} [signal] - AbortController signal
     * @returns {Promise<Array>} Array of repository objects
     */
    async getRepositories(signal) {
        return _fetch(`${GIT_BASE_URL}/repositories`, { signal });
    },
};

export { ApiError };
