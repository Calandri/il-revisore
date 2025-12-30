/**
 * UI Actions WebSocket Client
 *
 * Connects to the TurboWrap API WebSocket to receive UI actions
 * triggered by AI (Claude/Gemini) through MCP tools.
 *
 * Supported actions:
 * - navigate: Navigate to a page
 * - highlight: Highlight DOM elements
 * - toast: Show a notification toast
 * - modal: Open a modal dialog
 */

(function() {
    'use strict';

    const WS_RECONNECT_DELAY = 3000;  // Reconnect delay in ms
    const WS_MAX_RETRIES = 10;        // Max reconnection attempts

    let ws = null;
    let reconnectAttempts = 0;
    let reconnectTimer = null;

    /**
     * Get the WebSocket URL
     */
    function getWsUrl() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.host}/api/ui-actions/ws`;
    }

    /**
     * Connect to the WebSocket
     */
    function connect() {
        if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
            console.log('[UIActions] Already connected or connecting');
            return;
        }

        const url = getWsUrl();
        console.log('[UIActions] Connecting to WebSocket:', url);

        try {
            ws = new WebSocket(url);

            ws.onopen = function() {
                console.log('[UIActions] WebSocket connected');
                reconnectAttempts = 0;

                // Send current page info
                sendPageUpdate();

                // Listen for page changes
                window.addEventListener('popstate', sendPageUpdate);
                document.body.addEventListener('htmx:pushedIntoHistory', sendPageUpdate);
            };

            ws.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    handleMessage(data);
                } catch (e) {
                    console.error('[UIActions] Failed to parse message:', e);
                }
            };

            ws.onclose = function(event) {
                console.log('[UIActions] WebSocket closed:', event.code, event.reason);
                ws = null;
                scheduleReconnect();
            };

            ws.onerror = function(error) {
                console.error('[UIActions] WebSocket error:', error);
            };

        } catch (e) {
            console.error('[UIActions] Failed to create WebSocket:', e);
            scheduleReconnect();
        }
    }

    /**
     * Schedule a reconnection attempt
     */
    function scheduleReconnect() {
        if (reconnectTimer) return;

        if (reconnectAttempts >= WS_MAX_RETRIES) {
            console.warn('[UIActions] Max reconnection attempts reached');
            return;
        }

        reconnectAttempts++;
        const delay = WS_RECONNECT_DELAY * Math.min(reconnectAttempts, 5);
        console.log(`[UIActions] Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${WS_MAX_RETRIES})`);

        reconnectTimer = setTimeout(function() {
            reconnectTimer = null;
            connect();
        }, delay);
    }

    /**
     * Send current page info to the server
     */
    function sendPageUpdate() {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        ws.send(JSON.stringify({
            type: 'page_update',
            path: window.location.pathname,
            title: document.title
        }));
    }

    /**
     * Handle incoming message from WebSocket
     */
    function handleMessage(data) {
        console.log('[UIActions] Received:', data);

        if (data.type === 'pong') {
            // Keepalive response, ignore
            return;
        }

        if (data.type === 'action') {
            executeAction(data);
        }
    }

    /**
     * Execute a UI action
     */
    function executeAction(data) {
        const action = data.action;

        switch (action) {
            case 'navigate':
                navigateTo(data.path);
                break;

            case 'highlight':
                highlightElements(data.selector);
                break;

            case 'toast':
                showToast(data.message, data.toast_type || 'info');
                break;

            case 'modal':
                openModal(data.modal_id);
                break;

            default:
                console.warn('[UIActions] Unknown action:', action);
        }
    }

    /**
     * Navigate to a page
     */
    function navigateTo(path) {
        if (!path) {
            console.warn('[UIActions] Navigate: missing path');
            return;
        }

        console.log('[UIActions] Navigating to:', path);

        // Use HTMX for smooth navigation if available
        if (window.htmx) {
            htmx.ajax('GET', path, {
                target: 'body',
                swap: 'innerHTML'
            }).then(function() {
                window.history.pushState({}, '', path);
                showToast(`Navigato a ${path}`, 'success');
            }).catch(function() {
                // Fallback to regular navigation
                window.location.href = path;
            });
        } else {
            window.location.href = path;
        }
    }

    /**
     * Highlight DOM elements
     */
    function highlightElements(selector) {
        if (!selector) {
            console.warn('[UIActions] Highlight: missing selector');
            return;
        }

        console.log('[UIActions] Highlighting:', selector);

        const elements = document.querySelectorAll(selector);

        if (elements.length === 0) {
            console.warn('[UIActions] No elements found for selector:', selector);
            showToast(`Elemento non trovato: ${selector}`, 'warning');
            return;
        }

        elements.forEach(function(el, index) {
            // Add highlight class
            el.classList.add('ai-highlight');

            // Scroll first element into view
            if (index === 0) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }

            // Remove highlight after 3 seconds
            setTimeout(function() {
                el.classList.remove('ai-highlight');
            }, 3000);
        });

        showToast(`Evidenziato: ${elements.length} elemento/i`, 'success');
    }

    /**
     * Show a toast notification
     */
    function showToast(message, type) {
        // Dispatch event for existing toast system
        window.dispatchEvent(new CustomEvent('show-toast', {
            detail: { message: message, type: type || 'info' }
        }));
    }

    /**
     * Open a modal dialog
     */
    function openModal(modalId) {
        if (!modalId) {
            console.warn('[UIActions] OpenModal: missing modal_id');
            return;
        }

        console.log('[UIActions] Opening modal:', modalId);

        // Try to find and open the modal
        const modal = document.getElementById(modalId);
        if (modal) {
            // Check if it's an Alpine.js controlled modal
            if (modal.hasAttribute('x-show') || modal.hasAttribute('x-data')) {
                // Dispatch Alpine event
                window.dispatchEvent(new CustomEvent('open-modal', {
                    detail: { modalId: modalId }
                }));
            } else {
                // Fallback: try to show it directly
                modal.style.display = 'block';
                modal.classList.remove('hidden');
            }
            showToast(`Modal aperto: ${modalId}`, 'success');
        } else {
            console.warn('[UIActions] Modal not found:', modalId);
            showToast(`Modal non trovato: ${modalId}`, 'warning');
        }
    }

    /**
     * Keepalive ping
     */
    function sendPing() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
        }
    }

    // Start keepalive pings every 30 seconds
    setInterval(sendPing, 30000);

    // Connect when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', connect);
    } else {
        connect();
    }

    // Expose for debugging
    window.UIActionsWS = {
        connect: connect,
        sendPageUpdate: sendPageUpdate,
        getStatus: function() {
            return {
                connected: ws && ws.readyState === WebSocket.OPEN,
                readyState: ws ? ws.readyState : null,
                reconnectAttempts: reconnectAttempts
            };
        }
    };

    console.log('[UIActions] WebSocket client initialized');
})();
