/**
 * TurboWrap Global Error Handler
 *
 * Provides intelligent error handling with AI assistance option.
 *
 * Usage in catch blocks:
 *   TurboWrapError.handle('Sync Repository', error, { repoId: '123' });
 *   TurboWrapError.warning('Upload File', error);  // Toast only
 *   TurboWrapError.critical('Database Error', error);  // Modal
 */

window.TurboWrapError = {
    /**
     * Handle an error with automatic severity detection
     * @param {string} commandName - What operation failed
     * @param {Error|string} error - The error object or message
     * @param {Object} context - Additional context (repoId, userId, etc.)
     * @param {string} severity - 'warning' (toast) or 'error' (modal)
     */
    handle(commandName, error, context = {}, severity = 'auto') {
        const errorInfo = this._parseError(error);

        // Auto-detect severity based on error type
        if (severity === 'auto') {
            severity = this._detectSeverity(errorInfo);
        }

        console.error(`[TurboWrapError] ${severity.toUpperCase()}: ${commandName}`, errorInfo);

        // Dispatch event for UI components
        window.dispatchEvent(new CustomEvent('turbowrap-error', {
            detail: {
                commandName,
                error: errorInfo,
                context,
                severity,
                timestamp: Date.now()
            }
        }));
    },

    /**
     * Show warning toast with AI help option
     */
    warning(commandName, error, context = {}) {
        this.handle(commandName, error, context, 'warning');
    },

    /**
     * Show critical error modal
     */
    critical(commandName, error, context = {}) {
        this.handle(commandName, error, context, 'error');
    },

    /**
     * Request AI help for an error (called when user clicks help button)
     */
    requestHelp(commandName, errorInfo, context = {}) {
        window.dispatchEvent(new CustomEvent('request-ai-help', {
            detail: {
                commandName,
                error: errorInfo,
                context,
                timestamp: Date.now()
            }
        }));
    },

    /**
     * Parse error into consistent format
     */
    _parseError(error) {
        if (typeof error === 'string') {
            return { message: error, stack: null, name: 'Error' };
        }

        return {
            message: error.message || String(error),
            stack: error.stack || null,
            name: error.name || 'Error',
            code: error.code || null,
            status: error.status || null
        };
    },

    /**
     * Auto-detect severity based on error characteristics
     */
    _detectSeverity(errorInfo) {
        const criticalPatterns = [
            /database/i,
            /connection/i,
            /authentication/i,
            /unauthorized/i,
            /forbidden/i,
            /internal server/i,
            /500/,
            /503/
        ];

        const message = errorInfo.message || '';
        const status = errorInfo.status;

        // HTTP 5xx errors are critical
        if (status >= 500) return 'error';

        // Check for critical patterns
        for (const pattern of criticalPatterns) {
            if (pattern.test(message)) return 'error';
        }

        // Default to warning
        return 'warning';
    }
};

/**
 * Wrap an async function with automatic error handling
 * @param {string} commandName - Name of the operation for error reporting
 * @param {Function} fn - Async function to wrap
 * @param {Object} context - Additional context for error reporting
 * @returns {Function} Wrapped function
 *
 * Usage:
 *   const safeFetch = TurboWrapError.wrap('Fetch Data', async () => {
 *       const res = await fetch('/api/data');
 *       return res.json();
 *   }, { endpoint: '/api/data' });
 *
 *   // Or wrap existing function:
 *   const safeSync = TurboWrapError.wrap('Sync Repo', syncRepository, { repoId });
 *   await safeSync();
 */
window.TurboWrapError.wrap = function(commandName, fn, context = {}) {
    return async (...args) => {
        try {
            return await fn(...args);
        } catch (error) {
            this.handle(commandName, error, context);
            throw error; // Re-throw so caller knows it failed
        }
    };
};

/**
 * Execute an async function with error handling (one-shot)
 * @param {string} commandName - Name of the operation
 * @param {Function} fn - Async function to execute
 * @param {Object} context - Additional context
 * @returns {Promise<any>} Result or undefined if error
 *
 * Usage:
 *   const data = await TurboWrapError.try('Load User', async () => {
 *       return await fetchUser(userId);
 *   }, { userId });
 */
window.TurboWrapError.try = async function(commandName, fn, context = {}) {
    try {
        return await fn();
    } catch (error) {
        this.handle(commandName, error, context);
        return undefined;
    }
};

/**
 * Decorator-style wrapper for class methods
 * @param {string} commandName - Name of the operation
 * @param {Object} context - Additional context
 *
 * Usage in Alpine component:
 *   async loadData() {
 *       return TurboWrapError.run(this, 'Load Data', async () => {
 *           const res = await fetch('/api/data');
 *           this.data = await res.json();
 *       }, { component: 'DataList' });
 *   }
 */
window.TurboWrapError.run = async function(thisArg, commandName, fn, context = {}) {
    try {
        return await fn.call(thisArg);
    } catch (error) {
        this.handle(commandName, error, context);
        return undefined;
    }
};

// Log when loaded
console.log('[error-handler.js] TurboWrapError handler registered');
