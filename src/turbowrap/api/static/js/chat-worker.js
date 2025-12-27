/**
 * Chat SharedWorker
 *
 * Maintains SSE connections across page navigation.
 * All pages share this worker, so when you navigate,
 * the stream continues and buffers messages.
 */

// All connected pages (MessagePorts)
const ports = [];

// Active streams by sessionId
const activeStreams = new Map();  // sessionId -> { controller, reader }

// State per session
const sessionState = new Map();   // sessionId -> { streaming, streamContent, systemInfo }

// Debug logging
function log(...args) {
    console.log('[ChatWorker]', ...args);
}

/**
 * Handle new page connection
 */
self.onconnect = (e) => {
    const port = e.ports[0];
    ports.push(port);
    log('Page connected, total ports:', ports.length);

    port.onmessage = async (event) => {
        const { type, sessionId, content, modelOverride, userMessage } = event.data;
        log('Message received:', type, sessionId);

        switch (type) {
            case 'SEND_MESSAGE':
                await startStream(sessionId, content, userMessage, modelOverride);
                break;

            case 'STOP_STREAM':
                stopStream(sessionId);
                break;

            case 'GET_STATE':
                // Send current state to the newly connected page
                sendStateSync(port, sessionId);
                break;

            case 'CLEAR_STATE':
                // Clear buffered state for a session (e.g., when switching sessions)
                sessionState.delete(sessionId);
                break;
        }
    };

    // Note: onclose doesn't fire reliably in SharedWorker
    // We handle dead ports in broadcast()
};

/**
 * Send state sync to a specific port
 */
function sendStateSync(port, sessionId) {
    const state = sessionId ? sessionState.get(sessionId) : null;
    const allStates = {};

    // Convert Map to plain object for serialization
    sessionState.forEach((value, key) => {
        allStates[key] = value;
    });

    port.postMessage({
        type: 'STATE_SYNC',
        sessionId,
        state,
        allStates,
        activeStreams: Array.from(activeStreams.keys())
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
 * Get or create session state
 */
function getSessionState(sessionId) {
    if (!sessionState.has(sessionId)) {
        sessionState.set(sessionId, {
            streaming: false,
            streamContent: '',
            systemInfo: [],
            lastMessageId: null,
            title: null
        });
    }
    return sessionState.get(sessionId);
}

/**
 * Start streaming response from backend
 * @param {string} sessionId - Session ID
 * @param {string} content - Message content
 * @param {object} userMessage - User message object
 * @param {string|null} modelOverride - Optional model override for this message
 */
async function startStream(sessionId, content, userMessage, modelOverride = null) {
    log('Starting stream for session:', sessionId, modelOverride ? `(model: ${modelOverride})` : '');

    // Stop any existing stream for this session
    if (activeStreams.has(sessionId)) {
        stopStream(sessionId);
    }

    const state = getSessionState(sessionId);
    state.streaming = true;
    state.streamContent = '';
    state.systemInfo = [];

    // Notify all pages that stream started
    broadcast({
        type: 'STREAM_START',
        sessionId,
        userMessage
    });

    // Create abort controller
    const controller = new AbortController();

    try {
        const url = `/api/cli-chat/sessions/${sessionId}/message`;

        // Build request body
        const body = { content };
        if (modelOverride) {
            body.model_override = modelOverride;
        }

        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: controller.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        activeStreams.set(sessionId, { controller, reader });

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                log('Stream ended naturally for:', sessionId);
                break;
            }

            buffer += decoder.decode(value, { stream: true });

            // Process SSE events
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                // Skip event type lines (we only care about data)
                if (line.startsWith('event: ')) {
                    continue;
                }

                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        processEvent(sessionId, data);
                    } catch (e) {
                        // Ignore parse errors for incomplete chunks
                    }
                }
            }
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            log('Stream aborted for:', sessionId);
            broadcast({
                type: 'STREAM_ABORTED',
                sessionId
            });
        } else {
            log('Stream error:', error);
            broadcast({
                type: 'ERROR',
                sessionId,
                error: error.message
            });
        }
    } finally {
        activeStreams.delete(sessionId);
        state.streaming = false;

        // Notify stream ended
        broadcast({
            type: 'STREAM_END',
            sessionId
        });
    }
}

/**
 * Process a single SSE event
 */
function processEvent(sessionId, data) {
    const state = getSessionState(sessionId);

    // System events
    if (data.type === 'system') {
        state.systemInfo.push(data);
        broadcast({
            type: 'SYSTEM',
            sessionId,
            event: data
        });
        return;
    }

    // Content chunks
    if (data.content) {
        state.streamContent += data.content;
        broadcast({
            type: 'CHUNK',
            sessionId,
            content: data.content,
            fullContent: state.streamContent
        });
    }

    // Stream completion (message saved to DB)
    if (data.message_id) {
        state.lastMessageId = data.message_id;
        broadcast({
            type: 'DONE',
            sessionId,
            messageId: data.message_id,
            content: state.streamContent
        });
        // Clear stream content after completion
        state.streamContent = '';
    }

    // Total length (informational)
    if (data.total_length !== undefined) {
        broadcast({
            type: 'TOTAL_LENGTH',
            sessionId,
            totalLength: data.total_length
        });
    }

    // Error
    if (data.error) {
        broadcast({
            type: 'ERROR',
            sessionId,
            error: data.error
        });
    }

    // Title update
    if (data.title) {
        state.title = data.title;
        broadcast({
            type: 'TITLE_UPDATE',
            sessionId,
            title: data.title
        });
    }
}

/**
 * Stop a stream
 */
function stopStream(sessionId) {
    const stream = activeStreams.get(sessionId);
    if (stream) {
        log('Stopping stream for:', sessionId);
        stream.controller.abort();
        activeStreams.delete(sessionId);

        const state = sessionState.get(sessionId);
        if (state) {
            state.streaming = false;
        }
    }
}

log('SharedWorker initialized');
