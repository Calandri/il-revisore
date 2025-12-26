/**
 * TurboWrap Frontend JavaScript
 * Alpine.js utilities and HTMX handlers
 */

// Toast notification manager for Alpine.js
function toastManager() {
    return {
        toasts: [],

        show(detail) {
            const id = Date.now();
            this.toasts.push({
                id,
                message: detail.message,
                type: detail.type || 'success',
                visible: true
            });

            // Auto-hide after 4 seconds
            setTimeout(() => {
                const toast = this.toasts.find(t => t.id === id);
                if (toast) toast.visible = false;

                // Remove from array after animation
                setTimeout(() => {
                    this.toasts = this.toasts.filter(t => t.id !== id);
                }, 300);
            }, 4000);
        }
    }
}

// System monitor for sidebar (CPU, RAM, CLI processes, deployments)
function systemMonitor() {
    return {
        cpu: 0,
        ram: 0,
        cliCount: 0,
        processes: [],
        showProcesses: false,
        buildCount: 0,
        buildProcesses: [],
        showBuilds: false,
        // Deployments
        showDeploys: false,
        deployments: [],
        currentDeploy: null,
        inProgressDeploy: null,
        previousInProgress: null,  // Track previous state for notifications
        deployLoading: true,
        deployTriggering: false,
        loading: true,

        async init() {
            await this.refresh();
            await this.refreshDeployments();
            // Poll system status every 5 seconds
            setInterval(() => this.refresh(), 5000);
            // Poll deployments every 30 seconds
            setInterval(() => this.refreshDeployments(), 30000);
        },

        async refresh() {
            try {
                const res = await fetch('/api/status/live');
                if (!res.ok) throw new Error('Status API error');
                const data = await res.json();

                this.cpu = data.system?.cpu_percent || 0;
                this.ram = data.system?.memory_percent || 0;
                this.cliCount = data.cli_processes?.count || 0;
                this.processes = data.cli_processes?.processes || [];
                this.buildCount = data.build_processes?.count || 0;
                this.buildProcesses = data.build_processes?.processes || [];
                this.loading = false;
            } catch (e) {
                console.error('System monitor error:', e);
            }
        },

        async refreshDeployments() {
            try {
                const res = await fetch('/api/deployments/status');
                if (!res.ok) throw new Error('Deployments API error');
                const data = await res.json();

                // Check if a deploy just completed (was in_progress, now isn't)
                const wasInProgress = this.previousInProgress;
                const isNowInProgress = data.in_progress;

                if (wasInProgress && !isNowInProgress) {
                    // Find what happened to the previous in-progress deploy
                    const completedDeploy = data.recent?.find(d => d.id === wasInProgress.id);
                    if (completedDeploy) {
                        this.showDeployNotification(completedDeploy);
                    }
                }

                this.currentDeploy = data.current;
                this.inProgressDeploy = data.in_progress;
                this.previousInProgress = data.in_progress;  // Save for next comparison
                this.deployments = data.recent || [];
                this.deployLoading = false;
            } catch (e) {
                console.error('Deployments error:', e);
                this.deployLoading = false;
            }
        },

        showDeployNotification(deploy) {
            const isSuccess = deploy.conclusion === 'success';
            const message = isSuccess
                ? `Deploy ${deploy.commit_short} completato con successo!`
                : `Deploy ${deploy.commit_short} fallito`;

            window.dispatchEvent(new CustomEvent('show-toast', {
                detail: {
                    message: message,
                    type: isSuccess ? 'success' : 'error'
                }
            }));
        },

        async triggerDeploy() {
            if (this.deployTriggering) return;
            this.deployTriggering = true;

            try {
                const res = await fetch('/api/deployments/trigger', { method: 'POST' });
                const data = await res.json();

                if (res.ok) {
                    window.dispatchEvent(new CustomEvent('show-toast', {
                        detail: { message: 'Deploy avviato!', type: 'success' }
                    }));
                    // Refresh deployments after a short delay
                    setTimeout(() => this.refreshDeployments(), 3000);
                } else {
                    throw new Error(data.detail || 'Failed to trigger deploy');
                }
            } catch (e) {
                window.dispatchEvent(new CustomEvent('show-toast', {
                    detail: { message: `Errore: ${e.message}`, type: 'error' }
                }));
            } finally {
                this.deployTriggering = false;
            }
        },

        async rollbackTo(commitSha) {
            if (!confirm(`Sei sicuro di voler fare rollback a ${commitSha.substring(0, 7)}?`)) {
                return;
            }

            try {
                const res = await fetch(`/api/deployments/rollback/${commitSha}`, { method: 'POST' });
                const data = await res.json();

                if (res.ok) {
                    window.dispatchEvent(new CustomEvent('show-toast', {
                        detail: { message: `Rollback a ${commitSha.substring(0, 7)} avviato!`, type: 'success' }
                    }));
                    setTimeout(() => this.refreshDeployments(), 3000);
                } else {
                    throw new Error(data.detail || 'Failed to trigger rollback');
                }
            } catch (e) {
                window.dispatchEvent(new CustomEvent('show-toast', {
                    detail: { message: `Errore: ${e.message}`, type: 'error' }
                }));
            }
        },

        formatDuration(seconds) {
            if (!seconds) return '-';
            const m = Math.floor(seconds / 60);
            const s = seconds % 60;
            return `${m}m ${s}s`;
        },

        // Docker Logs Streaming
        showLogs: false,
        logsExpanded: false,
        logFilter: 'all',
        logs: [],
        logEventSource: null,
        logConnected: false,
        logError: null,
        containerName: null,

        get filteredLogs() {
            if (this.logFilter === 'all') return this.logs;
            return this.logs.filter(l => l.level === this.logFilter.toUpperCase());
        },

        setLogFilter(filter) {
            this.logFilter = filter;
        },

        toggleLogs() {
            this.showLogs = !this.showLogs;
            if (this.showLogs) {
                this.startLogStream();
            } else {
                this.stopLogStream();
            }
        },

        startLogStream() {
            this.logs = [];
            this.logError = null;
            this.logConnected = false;

            try {
                this.logEventSource = new EventSource('/api/status/docker-logs/stream');

                this.logEventSource.addEventListener('log', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        this.logs.push(data);
                        // Keep max 1000 lines
                        if (this.logs.length > 1000) this.logs.shift();
                        // Auto-scroll to bottom
                        this.$nextTick(() => {
                            const container = this.$refs.logContainer;
                            if (container) {
                                container.scrollTop = container.scrollHeight;
                            }
                        });
                    } catch (err) {
                        console.error('Error parsing log event:', err);
                    }
                });

                this.logEventSource.addEventListener('connected', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        this.containerName = data.container || 'turbowrap';
                    } catch {}
                    this.logConnected = true;
                    this.logError = null;
                });

                // Handle keepalive pings (ignore, just confirms connection is alive)
                this.logEventSource.addEventListener('ping', () => {
                    this.logConnected = true;
                });

                this.logEventSource.addEventListener('error', (e) => {
                    try {
                        const data = JSON.parse(e.data);
                        this.logError = data.message || 'Connection error';
                    } catch {
                        this.logError = 'Connection lost';
                    }
                    this.logConnected = false;
                });

                this.logEventSource.onerror = () => {
                    this.logConnected = false;
                    this.logError = 'Stream disconnected';
                };

            } catch (err) {
                this.logError = 'Failed to connect: ' + err.message;
                this.logConnected = false;
            }
        },

        stopLogStream() {
            if (this.logEventSource) {
                this.logEventSource.close();
                this.logEventSource = null;
            }
            this.logConnected = false;
        },

        clearLogs() {
            this.logs = [];
        },

        toggleLogsExpanded() {
            this.logsExpanded = !this.logsExpanded;
        }
    };
}

// HTMX configuration
document.body.addEventListener('htmx:configRequest', function(evt) {
    // Add any custom headers here if needed
});

// Handle HTMX errors
document.body.addEventListener('htmx:responseError', function(evt) {
    window.dispatchEvent(new CustomEvent('show-toast', {
        detail: {
            message: 'Connection error. Please try again.',
            type: 'error'
        }
    }));
});

// SSE event handling helper
function createSSEConnection(url, onToken, onDone, onError) {
    const eventSource = new EventSource(url);

    eventSource.addEventListener('token', function(e) {
        const data = JSON.parse(e.data);
        onToken(data.content);
    });

    eventSource.addEventListener('done', function(e) {
        const data = JSON.parse(e.data);
        eventSource.close();
        onDone(data);
    });

    eventSource.addEventListener('error', function(e) {
        eventSource.close();
        if (onError) onError(e);
    });

    return eventSource;
}

// Basic markdown rendering (for chat messages)
function renderMarkdown(content) {
    return content
        // Code blocks
        .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
        // Inline code
        .replace(/`([^`]+)`/g, '<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">$1</code>')
        // Bold
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        // Line breaks
        .replace(/\n/g, '<br>');
}

// Debounce utility
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Mobile touch gestures for sidebar
function initTouchGestures() {
    let touchStartX = 0;
    let touchStartY = 0;
    let touchEndX = 0;
    let touchEndY = 0;
    const swipeThreshold = 80; // Minimum pixels for a swipe
    const edgeThreshold = 30; // Distance from left edge to trigger open

    document.addEventListener('touchstart', function(e) {
        touchStartX = e.changedTouches[0].screenX;
        touchStartY = e.changedTouches[0].screenY;
    }, { passive: true });

    document.addEventListener('touchend', function(e) {
        touchEndX = e.changedTouches[0].screenX;
        touchEndY = e.changedTouches[0].screenY;
        handleSwipe();
    }, { passive: true });

    function handleSwipe() {
        // Only on mobile
        if (window.innerWidth >= 768) return;

        const swipeDistanceX = touchEndX - touchStartX;
        const swipeDistanceY = Math.abs(touchEndY - touchStartY);

        // Ignore if vertical swipe is dominant (scrolling)
        if (swipeDistanceY > Math.abs(swipeDistanceX)) return;

        // Get Alpine data from html element
        const htmlEl = document.documentElement;
        const alpineData = Alpine.$data(htmlEl);
        if (!alpineData) return;

        // Swipe right from left edge - open sidebar
        if (swipeDistanceX > swipeThreshold && touchStartX < edgeThreshold) {
            alpineData.sidebarOpen = true;
        }

        // Swipe left - close sidebar (if open)
        if (swipeDistanceX < -swipeThreshold && alpineData.sidebarOpen) {
            alpineData.sidebarOpen = false;
        }
    }
}

// Initialize touch gestures when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize on touch devices
    if ('ontouchstart' in window || navigator.maxTouchPoints > 0) {
        initTouchGestures();
    }
});

// Format date utility
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;

    // Less than a minute
    if (diff < 60000) {
        return 'Now';
    }

    // Less than an hour
    if (diff < 3600000) {
        const minutes = Math.floor(diff / 60000);
        return `${minutes} min ago`;
    }

    // Less than a day
    if (diff < 86400000) {
        const hours = Math.floor(diff / 3600000);
        return `${hours} hours ago`;
    }

    // More than a day
    return date.toLocaleDateString('en-US', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit'
    });
}
