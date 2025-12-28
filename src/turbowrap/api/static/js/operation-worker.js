/**
 * Operation SharedWorker
 *
 * Maintains SSE connections for operations (fix, review, merge, etc.)
 * across page navigation. Pattern identical to chat-worker.js.
 *
 * All pages share this worker, so when you navigate,
 * the stream continues and buffers output.
 */

// All connected pages (MessagePorts)
const ports = [];

// Active streams by operationId
const activeStreams = new Map();  // operationId -> { controller, reader, eventSource }

// State per operation
const operationState = new Map();  // operationId -> { output[], status, connected }

// Debug logging
function log(...args) {
    console.log('[OperationWorker]', ...args);
}

/**
 * Handle new page connection
 */
self.onconnect = (e) => {
    const port = e.ports[0];
    ports.push(port);
    log('Page connected, total ports:', ports.length);

    port.onmessage = async (event) => {
        const { type, operationId } = event.data;
        log('Message received:', type, operationId);

        switch (type) {
            case 'SUBSCRIBE':
                await subscribe(operationId);
                break;

            case 'UNSUBSCRIBE':
                unsubscribe(operationId);
                break;

            case 'GET_STATE':
                // Send current state to the requesting page
                sendStateSync(port, operationId);
                break;

            case 'GET_ALL_ACTIVE':
                // Send all active operations
                sendAllActive(port);
                break;

            case 'CLEAR_STATE':
                // Clear buffered state for an operation
                operationState.delete(operationId);
                activeStreams.delete(operationId);
                break;
        }
    };

    // Note: onclose doesn't fire reliably in SharedWorker
    // We handle dead ports in broadcast()
};

/**
 * Send state sync to a specific port
 */
function sendStateSync(port, operationId) {
    const state = operationId ? operationState.get(operationId) : null;
    const isActive = activeStreams.has(operationId);

    port.postMessage({
        type: 'STATE_SYNC',
        operationId,
        state,
        isActive
    });
}

/**
 * Send all active operations to a specific port
 */
function sendAllActive(port) {
    const active = [];
    for (const [opId, stream] of activeStreams) {
        active.push({
            operationId: opId,
            state: operationState.get(opId)
        });
    }

    port.postMessage({
        type: 'ALL_ACTIVE',
        operations: active
    });
}

/**
 * Broadcast message to all connected ports
 */
function broadcast(message) {
    // Filter out dead ports
    for (let i = ports.length - 1; i >= 0; i--) {
        try {
            ports[i].postMessage(message);
        } catch (e) {
            // Port is dead, remove it
            log('Removing dead port');
            ports.splice(i, 1);
        }
    }
}

/**
 * Get or create operation state
 */
function getOperationState(operationId) {
    if (!operationState.has(operationId)) {
        operationState.set(operationId, {
            output: [],
            status: 'connecting',
            connected: false,
            lineCount: 0
        });
    }
    return operationState.get(operationId);
}

/**
 * Subscribe to operation SSE stream
 */
async function subscribe(operationId) {
    log('Subscribing to operation:', operationId);

    // Already subscribed?
    if (activeStreams.has(operationId)) {
        log('Already subscribed to:', operationId);
        // Send current state to all pages
        const state = getOperationState(operationId);
        broadcast({
            type: 'STATE_SYNC',
            operationId,
            state,
            isActive: true
        });
        return;
    }

    const state = getOperationState(operationId);
    state.status = 'connecting';

    // Notify all pages
    broadcast({
        type: 'CONNECTING',
        operationId
    });

    try {
        const url = `/api/operations/${operationId}/stream`;
        const eventSource = new EventSource(url);

        activeStreams.set(operationId, { eventSource });

        // Handle connection established
        eventSource.addEventListener('connected', (e) => {
            log('SSE connected for:', operationId);
            state.connected = true;
            state.status = 'streaming';

            try {
                const data = JSON.parse(e.data);
                broadcast({
                    type: 'CONNECTED',
                    operationId,
                    data
                });
            } catch (err) {
                broadcast({
                    type: 'CONNECTED',
                    operationId
                });
            }
        });

        // Handle output chunks
        eventSource.addEventListener('chunk', (e) => {
            try {
                const data = JSON.parse(e.data);
                const content = data.content || '';

                // Buffer output (limit to 1000 lines)
                state.output.push(content);
                if (state.output.length > 1000) {
                    state.output.shift();
                }
                state.lineCount++;

                broadcast({
                    type: 'CHUNK',
                    operationId,
                    content,
                    lineNumber: state.lineCount
                });
            } catch (err) {
                log('Error parsing chunk:', err);
            }
        });

        // Handle status updates
        eventSource.addEventListener('status', (e) => {
            try {
                const data = JSON.parse(e.data);
                state.status = data.status || 'unknown';

                broadcast({
                    type: 'STATUS',
                    operationId,
                    status: state.status
                });
            } catch (err) {
                log('Error parsing status:', err);
            }
        });

        // Handle completion
        eventSource.addEventListener('complete', (e) => {
            log('Operation completed:', operationId);
            state.status = 'completed';

            try {
                const data = JSON.parse(e.data);
                broadcast({
                    type: 'COMPLETE',
                    operationId,
                    result: data
                });
            } catch (err) {
                broadcast({
                    type: 'COMPLETE',
                    operationId
                });
            }

            // Clean up
            eventSource.close();
            activeStreams.delete(operationId);
        });

        // Handle errors
        eventSource.addEventListener('error', (e) => {
            log('SSE error for:', operationId);

            try {
                const data = JSON.parse(e.data);
                state.status = 'error';

                broadcast({
                    type: 'ERROR',
                    operationId,
                    error: data.error || 'Unknown error'
                });
            } catch (err) {
                // Generic SSE error (connection lost, etc.)
                if (eventSource.readyState === EventSource.CLOSED) {
                    state.status = 'disconnected';
                    broadcast({
                        type: 'DISCONNECTED',
                        operationId
                    });
                    activeStreams.delete(operationId);
                }
            }
        });

        // Handle ping (keep-alive)
        eventSource.addEventListener('ping', (e) => {
            // Just a keep-alive, no action needed
            log('Ping received for:', operationId);
        });

        // Handle generic SSE errors
        eventSource.onerror = (e) => {
            if (eventSource.readyState === EventSource.CLOSED) {
                log('SSE connection closed for:', operationId);
                state.status = 'disconnected';
                activeStreams.delete(operationId);

                broadcast({
                    type: 'DISCONNECTED',
                    operationId
                });
            }
        };

    } catch (error) {
        log('Failed to subscribe:', error);
        state.status = 'error';

        broadcast({
            type: 'ERROR',
            operationId,
            error: error.message
        });
    }
}

/**
 * Unsubscribe from operation stream
 */
function unsubscribe(operationId) {
    const stream = activeStreams.get(operationId);
    if (stream) {
        log('Unsubscribing from:', operationId);
        if (stream.eventSource) {
            stream.eventSource.close();
        }
        activeStreams.delete(operationId);

        const state = operationState.get(operationId);
        if (state) {
            state.status = 'unsubscribed';
        }

        broadcast({
            type: 'UNSUBSCRIBED',
            operationId
        });
    }
}

log('SharedWorker initialized');
