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

// Configuration for memory management
const MAX_SESSIONS = 20;
const SESSION_TIMEOUT_MS = 30 * 60 * 1000;  // 30 minutes
const HEARTBEAT_INTERVAL_MS = 30 * 1000;    // 30 seconds
const CLEANUP_INTERVAL_MS = 60 * 1000;      // 1 minute

// Debug logging
function log(...args) {
    console.log('[ChatWorker]', ...args);
}

/**
 * Broadcast message to all connected ports
 * Improved with better dead port detection and logging
 */
function broadcast(message) {
    const deadPorts = [];

    for (let i = ports.length - 1; i >= 0; i--) {
        try {
            ports[i].postMessage(message);
        } catch (e) {
            console.warn('[Worker] Dead port detected during broadcast:', e.message);
            deadPorts.push(i);
        }
    }

    // Remove dead ports (already iterating in reverse, so indices stay valid)
    deadPorts.forEach(idx => ports.splice(idx, 1));

    if (deadPorts.length > 0) {
        log(`Removed ${deadPorts.length} dead port(s), ${ports.length} remaining`);
    }
}

/**
 * Heartbeat to detect dead ports proactively
 */
function sendHeartbeat() {
    for (let i = ports.length - 1; i >= 0; i--) {
        try {
            ports[i].postMessage({ type: 'PING', timestamp: Date.now() });
        } catch (e) {
            log('Removing dead port detected by heartbeat');
            ports.splice(i, 1);
        }
    }
}

/**
 * Cleanup old inactive sessions to prevent memory leaks
 */
function cleanupOldSessions() {
    const now = Date.now();
    const toDelete = [];

    sessionState.forEach((state, sessionId) => {
        // Never delete sessions with active streaming
        if (state.streaming) return;

        // Delete sessions inactive for more than 30 minutes
        if (state.lastActivity && (now - state.lastActivity) > SESSION_TIMEOUT_MS) {
            toDelete.push(sessionId);
        }
    });

    // Delete old sessions
    toDelete.forEach(id => {
        sessionState.delete(id);
        log('Cleaned up inactive session:', id);
    });

    // If still too many, evict the oldest non-streaming sessions
    if (sessionState.size > MAX_SESSIONS) {
        const sorted = [...sessionState.entries()]
            .filter(([_, s]) => !s.streaming)  // Never evict active sessions
            .sort((a, b) => (a[1].lastActivity || 0) - (b[1].lastActivity || 0));

        const toRemove = sorted.slice(0, sessionState.size - MAX_SESSIONS);
        toRemove.forEach(([id]) => {
            sessionState.delete(id);
            log('Evicted old session:', id);
        });
    }
}

// Start periodic heartbeat and cleanup
setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
setInterval(cleanupOldSessions, CLEANUP_INTERVAL_MS);

/**
 * Handle new page connection
 */
self.onconnect = (e) => {
    const port = e.ports[0];
    ports.push(port);
    log('Page connected, total ports:', ports.length);

    // Handle port message errors
    port.onmessageerror = (err) => {
        console.warn('[Worker] Port message error:', err);
        const idx = ports.indexOf(port);
        if (idx >= 0) ports.splice(idx, 1);
    };

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

            case 'PONG':
                // Client responded to heartbeat - connection is alive
                break;
        }
    };

    port.start();
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
 * Get or create session state
 */
function getSessionState(sessionId) {
    if (!sessionState.has(sessionId)) {
        sessionState.set(sessionId, {
            streaming: false,
            streamContent: '',
            systemInfo: [],
            activeTools: [],  // Currently running tools
            activeAgents: [],  // Currently running agents (Task tool)
            lastMessageId: null,
            title: null,
            lastActivity: Date.now()
        });
    }
    const state = sessionState.get(sessionId);
    // Update activity timestamp on access
    state.lastActivity = Date.now();
    return state;
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
    state.hadError = false;

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
        let currentEventType = 'chunk';  // Track current SSE event type

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
                // Track event type for next data line
                if (line.startsWith('event: ')) {
                    currentEventType = line.slice(7).trim();
                    continue;
                }

                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        processEvent(sessionId, data, currentEventType);
                        currentEventType = 'chunk';  // Reset after processing
                    } catch (e) {
                        // Ignore parse errors for incomplete chunks
                    }
                }
            }
        }

    } catch (error) {
        state.hadError = true;
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

        // Issue 1 Fix: Send unified completion events to avoid race condition
        // First send DONE if we have a messageId (for backwards compatibility)
        if (state.lastMessageId) {
            broadcast({
                type: 'DONE',
                sessionId,
                messageId: state.lastMessageId,
                content: state.streamContent
            });
        }

        // Then send STREAM_END with full context
        broadcast({
            type: 'STREAM_END',
            sessionId,
            messageId: state.lastMessageId || null,
            finalContent: state.streamContent,
            success: !state.hadError
        });

        // Reset state after sending events
        state.streamContent = '';
        state.lastMessageId = null;
        state.hadError = false;
        state.lastActivity = Date.now();
    }
}

/**
 * Process a single SSE event
 * @param {string} sessionId - Session ID
 * @param {object} data - Event data
 * @param {string} eventType - SSE event type (e.g., 'chunk', 'action', 'done')
 */
function processEvent(sessionId, data, eventType = 'chunk') {
    const state = getSessionState(sessionId);

    // Handle action events from AI (navigate, highlight)
    if (eventType === 'action') {
        log('Action event received:', data);
        broadcast({
            type: 'ACTION',
            sessionId,
            action: data
        });
        return;
    }

    // Tool start events
    if (eventType === 'tool_start') {
        log('Tool started:', data.tool_name);
        state.activeTools.push({
            name: data.tool_name,
            id: data.tool_id,
            startedAt: Date.now()
        });
        broadcast({
            type: 'TOOL_START',
            sessionId,
            toolName: data.tool_name,
            toolId: data.tool_id
        });
        return;
    }

    // Tool end events
    if (eventType === 'tool_end') {
        log('Tool completed:', data.tool_name);
        // Remove from active tools
        state.activeTools = state.activeTools.filter(t => t.name !== data.tool_name);
        broadcast({
            type: 'TOOL_END',
            sessionId,
            toolName: data.tool_name,
            toolInput: data.tool_input
        });
        return;
    }

    // Agent start events (Task tool = sub-agent)
    if (eventType === 'agent_start') {
        log('Agent launched:', data.agent_type, '(model:', data.agent_model, ')');
        state.activeAgents.push({
            type: data.agent_type,
            model: data.agent_model,
            description: data.description,
            startedAt: Date.now()
        });
        broadcast({
            type: 'AGENT_START',
            sessionId,
            agentType: data.agent_type,
            agentModel: data.agent_model,
            description: data.description
        });
        return;
    }

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
    // Issue 1 Fix: Store messageId but DON'T broadcast DONE here
    // The DONE event will be sent in the finally block to avoid race condition
    if (data.message_id) {
        state.lastMessageId = data.message_id;
        // Note: DONE broadcast moved to finally block in startStream()
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
        state.hadError = true;
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
            state.lastActivity = Date.now();
        }
    }
}

log('SharedWorker initialized');
