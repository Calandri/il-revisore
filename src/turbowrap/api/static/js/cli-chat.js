/**
 * CLI Chat Alpine.js Components
 *
 * Manages the right sidebar chat interface for Claude/Gemini CLI.
 * Supports:
 * - Multi-chat sessions
 * - SSE streaming via SharedWorker (persists across page navigation)
 * - Quick settings (model, agent, thinking)
 * - 3 display modes (full/third/icons)
 */

// SharedWorker singleton (shared across all chatSidebar instances)
let chatWorker = null;
let chatWorkerPort = null;
let workerMessageHandler = null;

/**
 * Get or create the SharedWorker connection
 */
function getChatWorker() {
    if (!chatWorker) {
        try {
            chatWorker = new SharedWorker('/static/js/chat-worker.js');
            chatWorkerPort = chatWorker.port;
            chatWorkerPort.start();
            console.log('[cli-chat] SharedWorker connected');
        } catch (e) {
            console.warn('[cli-chat] SharedWorker not supported, falling back to direct fetch:', e);
            return null;
        }
    }
    return chatWorkerPort;
}

/**
 * Format a timestamp as relative time (5m, 2h, 1d, etc.)
 * @param {string|Date|null} timestamp - ISO timestamp or Date object
 * @returns {string} Relative time string or empty string if no timestamp
 */
function formatRelativeTime(timestamp) {
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

// Expose to Alpine/window for template use
window.formatRelativeTime = formatRelativeTime;

/**
 * Chat Sidebar Alpine Component
 */
function chatSidebar() {
    return {
        // State
        sessions: [],
        activeSession: null,
        messages: [],
        agents: [],
        loading: false,
        creating: false,
        streaming: false,  // Legacy: true if ANY stream is active
        streamContent: '',
        streamContentBySession: {}, // Keep separate content per sessionId
        streamingBySession: {},     // Track streaming state per sessionId
        pendingMessageBySession: {}, // Queued messages per sessionId
        contentSegmentsBySession: {}, // Segments per session: [{type: 'text', content: ''}, {type: 'tool', ...}, ...]
        lastKnownLengthBySession: {}, // Track position in fullContent for delta calculation
        sessionMessagesCache: {},  // Cache messages per session to avoid refetching
        inputMessage: '',
        showSettings: false,
        showModelDropdown: false,
        showNewChatMenu: false,
        showSystemInfo: false,
        systemInfo: [],
        activeTools: [],        // Currently running tools (for UI display)
        completedTools: [],     // Tools completed in current response
        activeAgents: [],       // Currently running agents (Task tool)
        completedAgents: [],    // Agents completed in current response
        eventSource: null,
        abortController: null,
        // Queue and Fork functionality
        pendingMessage: null,   // Message queued to send after current stream
        forkInProgress: false,  // Prevents double-fork
        // Branch management
        branches: [],           // Available branches in repo
        loadingBranches: false, // Loading state for branches
        // Server logs
        isLoadingLogs: false,   // Loading state for server logs fetch
        // Repository management
        repositories: [],       // Available repositories
        selectedRepoId: null,   // Selected repo for new session
        showRepoSelector: false, // Show repo selector modal
        pendingCliType: null,   // CLI type waiting for repo selection
        // SharedWorker support
        useWorker: true,        // Will be set to false if worker not supported
        // Stream limit tracking
        activeStreamCount: 0,    // Number of streams currently running
        maxStreamsReached: false, // True when activeStreamCount >= 10
        // UI state
        showHistory: false,     // Show history panel (hamburger)
        activeTooltip: null,    // Active tooltip in toolbar
        tooltipText: '',        // Text for fixed tooltip
        tooltipPosition: { top: 0, left: 0 }, // Position for fixed tooltip
        // Dual chat state
        dualChatEnabled: false,
        secondarySession: null,
        secondaryMessages: [],
        streamContentSecondary: '',
        inputMessageSecondary: '',
        activePane: 'left',     // 'left' or 'right'
        showTabContextMenu: false,
        contextMenuSession: null,
        contextMenuX: 0,
        contextMenuY: 0,
        // Agent autocomplete state
        showAgentAutocomplete: false,
        agentSearchQuery: '',
        selectedAgentIndex: 0,
        agentTriggerPosition: 0,  // Position of @ in input
        // Session Info Modal
        showSessionInfoModal: false,
        sessionInfoLoading: false,
        usageInfo: null,

        // NOTE: chatMode is inherited from parent scope (html element x-data)
        // Do NOT define a getter here - it causes infinite recursion!

        /**
         * Initialize component
         */
        async init() {
            console.log('[chatSidebar] Initializing...');

            // Connect to SharedWorker
            this.setupWorker();

            try {
                await this.loadSessions();
                console.log('[chatSidebar] Sessions loaded:', this.sessions.length);
                await this.loadAgents();
                console.log('[chatSidebar] Agents loaded:', this.agents.length);
                await this.loadRepositories();

                // Restore active session from localStorage
                const savedSessionId = localStorage.getItem('chatActiveSessionId');
                if (savedSessionId && this.sessions.length > 0) {
                    const session = this.sessions.find(s => s.id === savedSessionId);
                    if (session) {
                        console.log('[chatSidebar] Restoring active session:', savedSessionId);
                        await this.selectSession(session);

                        // Request state from worker (in case stream was active during navigation)
                        if (this.useWorker && chatWorkerPort) {
                            chatWorkerPort.postMessage({
                                type: 'GET_STATE',
                                sessionId: savedSessionId
                            });
                        }
                    }
                }
            } catch (error) {
                console.error('[chatSidebar] Init error:', error);
            }

            // Poll for session updates every 10s
            setInterval(() => this.loadSessions(), 10000);

            // Listen for global context changes (repo/branch selection in footer)
            window.addEventListener('global-context-changed', (e) => {
                console.log('[chatSidebar] Global context changed:', e.detail);
                this.onGlobalContextChanged(e.detail.repoId);
            });

            // Listen for open-chat-with-command events (from Mockups page, etc.)
            window.addEventListener('open-chat-with-command', async (e) => {
                console.log('[chatSidebar] Received open-chat-with-command event:', e.detail);

                // Open chat if hidden
                const htmlData = Alpine.$data(document.documentElement);
                console.log('[chatSidebar] Current chatMode:', htmlData?.chatMode);

                if (htmlData) {
                    if (htmlData.chatMode === 'hidden') {
                        htmlData.chatMode = 'third';
                        console.log('[chatSidebar] Changed chatMode to third');
                    }

                    const repoId = Alpine.store('globalContext')?.selectedRepoId;
                    const agentName = e.detail?.agent || null;
                    const cliType = e.detail?.cli || 'claude';

                    // Handle session selection
                    if (e.detail?.newSession || agentName) {
                        // Create a new session (always new when agent is specified)
                        console.log('[chatSidebar] Creating new session with agent:', agentName);
                        await this.createSession(cliType, repoId, agentName);
                    } else if (e.detail?.reuseSession) {
                        // Reuse active session if exists, otherwise create new
                        if (!this.activeSession) {
                            console.log('[chatSidebar] No active session, creating new one');
                            await this.createSession(cliType, repoId);
                        } else {
                            console.log('[chatSidebar] Reusing active session:', this.activeSession.id);
                        }
                    } else if (e.detail?.sessionId) {
                        // Switch to existing session
                        console.log('[chatSidebar] Switching to session:', e.detail.sessionId);
                        const session = this.sessions.find(s => s.id === e.detail.sessionId);
                        if (session) {
                            await this.selectSession(session);
                        } else {
                            // Session not in list, try to fetch it
                            try {
                                const res = await fetch(`/api/cli-chat/sessions/${e.detail.sessionId}`);
                                if (res.ok) {
                                    const session = await res.json();
                                    await this.selectSession(session);
                                }
                            } catch (err) {
                                console.error('[chatSidebar] Failed to load session:', err);
                            }
                        }
                    }

                    // Pre-fill the command after a small delay to ensure chat is rendered
                    if (e.detail?.command) {
                        setTimeout(() => {
                            this.inputMessage = e.detail.command + ' ';
                            console.log('[chatSidebar] Set inputMessage:', this.inputMessage);
                            // Focus input
                            const input = document.querySelector('[x-ref="messageInput"]');
                            if (input) {
                                input.focus();
                                console.log('[chatSidebar] Focused input');
                            } else {
                                console.warn('[chatSidebar] Could not find messageInput');
                            }
                        }, 150);
                    }
                } else {
                    console.error('[chatSidebar] Could not access Alpine data on html element');
                }
            });

            // Listen for submit-chat-answers events (from question blocks in messages)
            window.addEventListener('submit-chat-answers', (e) => {
                const questionId = e.detail?.id;
                if (!questionId) return;

                // Find all inputs with this question ID
                const inputs = document.querySelectorAll(`input[data-question-id="${questionId}"]`);
                if (inputs.length === 0) return;

                // Collect answers
                const answers = [];
                inputs.forEach(input => {
                    const question = input.getAttribute('data-question');
                    const answer = input.value.trim();
                    if (answer) {
                        answers.push(`**${question}**\n${answer}`);
                    }
                });

                if (answers.length === 0) {
                    this.showToast('Compila almeno una risposta', 'warning');
                    return;
                }

                // Format as message and send
                const message = answers.join('\n\n');
                this.inputMessage = message;
                this.sendMessage();

                // Clear the inputs
                inputs.forEach(input => {
                    input.value = '';
                    input.disabled = true;
                });

                // Disable the submit button
                const btn = document.querySelector(`button[onclick*="${questionId}"]`);
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = `<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg> Invio...`;
                }
            });

            // Listen for AI help requests (from error handler modal)
            window.addEventListener('request-ai-help', async (e) => {
                console.log('[chatSidebar] Request AI help:', e.detail);
                await this.handleAIHelpRequest(e.detail);
            });

            // Listen for mockup context changes (from Mockups page)
            window.addEventListener('mockup-context-changed', async (e) => {
                const { mockup_id, mockup_project_id, mockup_name } = e.detail || {};
                console.log('[chatSidebar] Mockup context changed:', e.detail);

                // Update active session's mockup context if we have one
                if (this.activeSession) {
                    try {
                        await fetch(`/api/cli-chat/sessions/${this.activeSession.id}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                mockup_id,
                                mockup_project_id
                            })
                        });
                        // Update local state
                        this.activeSession.mockup_id = mockup_id;
                        this.activeSession.mockup_project_id = mockup_project_id;
                        console.log('[chatSidebar] Updated session mockup context');
                    } catch (err) {
                        console.warn('[chatSidebar] Failed to update mockup context:', err);
                    }
                }
            });
        },

        /**
         * Handle AI help request from error handler
         * Opens chat, creates/selects session, and sends error context
         */
        async handleAIHelpRequest(detail) {
            const { commandName, error, context } = detail;

            // 1. Open chat if hidden
            const htmlData = Alpine.$data(document.documentElement);
            if (htmlData && htmlData.chatMode === 'hidden') {
                htmlData.chatMode = 'third';
            }

            // 2. Ensure we have a session (create if needed)
            if (!this.activeSession) {
                const repoId = Alpine.store('globalContext')?.selectedRepoId;
                await this.createSession('claude', repoId);
            }

            // 3. Build the help message with /help-error command
            // Format: /help-error <command_name> | <error_message> | <context>
            const errorMsg = error?.message || 'Errore sconosciuto';
            const errorStack = error?.stack || '';
            const contextStr = context && Object.keys(context).length > 0
                ? JSON.stringify(context)
                : '';

            // Slash command with structured arguments
            const helpMessage = `/help-error
Comando: ${commandName}
Errore: ${errorMsg}
Stack: ${errorStack}
Contesto: ${contextStr}`;

            // 4. Send the message (slash command will be expanded)
            this.inputMessage = helpMessage;
            await this.sendMessage();
        },

        /**
         * Handle global context (repo/branch) changes
         */
        async onGlobalContextChanged(repoId) {
            // Reload sessions filtered by the new repo
            await this.loadSessions(repoId);

            // Check if active session still belongs to the new repo filter
            if (this.activeSession) {
                const sessionRepoId = this.activeSession.repository_id;

                // If filtering by repo and active session doesn't match, clear it
                if (repoId && sessionRepoId !== repoId) {
                    console.log('[chatSidebar] Active session repo mismatch, clearing');
                    this.activeSession = null;
                    this.messages = [];
                    localStorage.removeItem('chatActiveSessionId');

                    // Auto-select first session of new repo if available
                    if (this.sessions.length > 0) {
                        await this.selectSession(this.sessions[0]);
                    }
                }
                // If no filter (null repo), keep current session
            }
        },

        /**
         * Setup SharedWorker connection and message handler
         */
        setupWorker() {
            const port = getChatWorker();
            if (!port) {
                this.useWorker = false;
                console.log('[chatSidebar] Worker not available, using direct fetch');
                return;
            }

            // Set up message handler (only once globally)
            if (!workerMessageHandler) {
                const self = this;
                workerMessageHandler = (event) => {
                    self.handleWorkerMessage(event.data);
                };
                port.onmessage = workerMessageHandler;
            }

            console.log('[chatSidebar] Worker setup complete');
        },

        /**
         * Handle messages from SharedWorker
         * Supports parallel streaming: each sessionId keeps independent stream content
         */
        handleWorkerMessage(data) {
            const { type, sessionId, content, fullContent, event, messageId, title, error, state, activeStreams } = data;

            // Initialize stream content for this sessionId if not present
            if (sessionId && !this.streamContentBySession[sessionId]) {
                this.streamContentBySession[sessionId] = '';
            }

            // Only update UI if message is for the ACTIVE session or SECONDARY session (dual-chat)
            const isActiveSession = sessionId && this.activeSession?.id === sessionId;
            const isSecondarySession = this.dualChatEnabled && sessionId && this.secondarySession?.id === sessionId;

            switch (type) {
                case 'STREAM_START':
                    console.log('[chatSidebar] Worker: stream started for session:', sessionId);
                    // Initialize empty stream content for this session
                    if (sessionId) {
                        this.streamContentBySession[sessionId] = '';
                        this.streamingBySession[sessionId] = true;  // Track per-session streaming
                        // Initialize segments: start with one empty text segment
                        this.contentSegmentsBySession[sessionId] = [{ type: 'text', content: '' }];
                        this.lastKnownLengthBySession[sessionId] = 0;
                    }
                    // Only update UI flags if it's the active session
                    if (isActiveSession) {
                        this.streaming = true;
                        this.streamContent = '';
                        this.systemInfo = [];
                        this.activeTools = [];      // Reset active tools
                        this.completedTools = [];   // Reset completed tools
                        this.activeAgents = [];     // Reset active agents
                        this.completedAgents = [];  // Reset completed agents
                    }
                    break;

                case 'CHUNK':
                    // Accumulate content for this specific session
                    if (sessionId) {
                        // Defensive initialization if STREAM_START was missed
                        if (!this.contentSegmentsBySession[sessionId]) {
                            console.warn('[CHUNK] Defensive init for session:', sessionId);
                            this.contentSegmentsBySession[sessionId] = [{ type: 'text', content: '' }];
                            this.lastKnownLengthBySession[sessionId] = 0;
                        }

                        // Keep legacy streamContentBySession for backwards compatibility
                        this.streamContentBySession[sessionId] = fullContent || (this.streamContentBySession[sessionId] + content);

                        // Update segments: append delta to last text segment
                        const segments = this.contentSegmentsBySession[sessionId];
                        if (segments && segments.length > 0) {
                            let lastSegment = segments[segments.length - 1];
                            // If last segment is not text, create a new text segment
                            if (lastSegment.type !== 'text') {
                                segments.push({ type: 'text', content: '' });
                                lastSegment = segments[segments.length - 1];
                            }
                            // Calculate delta from fullContent
                            if (fullContent) {
                                const lastKnown = this.lastKnownLengthBySession[sessionId] || 0;
                                const delta = fullContent.substring(lastKnown);
                                lastSegment.content += delta;
                                this.lastKnownLengthBySession[sessionId] = fullContent.length;
                            } else if (content) {
                                lastSegment.content += content;
                            }
                        }
                    }
                    // Update UI for active session
                    if (isActiveSession) {
                        this.streamContent = this.streamContentBySession[sessionId];
                        this.$nextTick(() => this.scrollToBottom());
                    }
                    // Update UI for secondary session (dual-chat)
                    if (isSecondarySession) {
                        this.streamContentSecondary = this.streamContentBySession[sessionId];
                        this.$nextTick(() => this.scrollToBottomSecondary());
                    }
                    break;

                case 'SYSTEM':
                    console.log('[chatSidebar] Worker: system event:', event?.subtype);
                    // Only show system info if it's the active session
                    if (isActiveSession) {
                        if (!this.systemInfo) this.systemInfo = [];
                        this.systemInfo.push(event);
                    }
                    break;

                case 'TOOL_START':
                    console.log('[chatSidebar] Worker: tool started:', data.toolName);
                    // Only update UI if it's the active session
                    if (isActiveSession) {
                        this.activeTools.push({
                            name: data.toolName,
                            id: data.toolId,
                            startedAt: Date.now()
                        });
                    }
                    break;

                case 'TOOL_END':
                    console.log('[chatSidebar] Worker: tool completed:', data.toolName, data.toolInput);

                    // Add tool as segment (works for all sessions)
                    if (sessionId) {
                        const toolSegments = this.contentSegmentsBySession[sessionId];
                        if (toolSegments) {
                            // Add tool segment
                            toolSegments.push({
                                type: 'tool',
                                name: data.toolName,
                                input: data.toolInput,
                                completedAt: Date.now()
                            });
                            // Start new empty text segment for subsequent content
                            toolSegments.push({ type: 'text', content: '' });
                        }
                    }

                    // Only update arrays if it's the active session (legacy)
                    if (isActiveSession) {
                        // Move from active to completed
                        const toolIndex = this.activeTools.findIndex(t => t.name === data.toolName);
                        if (toolIndex >= 0) {
                            const tool = this.activeTools.splice(toolIndex, 1)[0];
                            this.completedTools.push({
                                ...tool,
                                input: data.toolInput,
                                completedAt: Date.now()
                            });
                        } else {
                            // Tool wasn't in activeTools, add directly to completed
                            this.completedTools.push({
                                name: data.toolName,
                                input: data.toolInput,
                                completedAt: Date.now()
                            });
                        }
                        this.$nextTick(() => this.scrollToBottom());
                    }
                    break;

                case 'AGENT_START':
                    console.log('[chatSidebar] Worker: agent launched:', data.agentType, '(model:', data.agentModel, ')');

                    // Add agent as segment (works for all sessions)
                    if (sessionId) {
                        const agentSegments = this.contentSegmentsBySession[sessionId];
                        if (agentSegments) {
                            // Add agent segment
                            agentSegments.push({
                                type: 'agent',
                                agentType: data.agentType,
                                model: data.agentModel,
                                description: data.description,
                                launchedAt: Date.now()
                            });
                            // Start new empty text segment for subsequent content
                            agentSegments.push({ type: 'text', content: '' });
                        }
                    }

                    // Only update arrays if it's the active session (legacy)
                    if (isActiveSession) {
                        this.activeAgents.push({
                            type: data.agentType,
                            model: data.agentModel,
                            description: data.description,
                            startedAt: Date.now()
                        });
                        // Also move to completed immediately (agents run async, no explicit end event)
                        this.completedAgents.push({
                            type: data.agentType,
                            model: data.agentModel,
                            description: data.description,
                            launchedAt: Date.now()
                        });
                        this.$nextTick(() => this.scrollToBottom());
                    }
                    break;

                case 'DONE':
                    console.log('[chatSidebar] Worker: stream done for session:', sessionId, 'messageId:', messageId);
                    // Save message with final content for this session
                    const finalContent = content || this.streamContentBySession[sessionId];
                    // Get segments for this session (includes agents and tools inline)
                    const finalSegments = this.contentSegmentsBySession[sessionId]
                        ? [...this.contentSegmentsBySession[sessionId]]
                        : null;

                    // Add to messages UI for active session
                    if (isActiveSession) {
                        this.messages.push({
                            id: messageId,
                            role: 'assistant',
                            content: finalContent,
                            segments: finalSegments,  // Include segments with agents/tools
                            created_at: new Date().toISOString()
                        });
                        this.streamContent = '';
                        this.streaming = false;
                        this.activeTools = [];      // Clear active tools
                        this.completedTools = [];   // Clear completed tools
                        this.activeAgents = [];     // Clear active agents
                        // Keep completedAgents visible after stream ends
                    }

                    // Add to messages UI for secondary session (dual-chat)
                    if (isSecondarySession) {
                        this.secondaryMessages.push({
                            id: messageId,
                            role: 'assistant',
                            content: finalContent,
                            segments: finalSegments,  // Include segments with agents/tools
                            created_at: new Date().toISOString()
                        });
                        this.streamContentSecondary = '';
                        this.$nextTick(() => this.scrollToBottomSecondary());
                    }

                    // Clear accumulated content and streaming state for this session
                    if (sessionId) {
                        this.streamContentBySession[sessionId] = '';
                        this.streamingBySession[sessionId] = false;
                        // Invalidate message cache since new message was added
                        delete this.sessionMessagesCache[sessionId];
                    }

                    // Check for queued message for THIS session (per-session queue)
                    const queuedMsg = this.pendingMessageBySession[sessionId];
                    if (queuedMsg) {
                        delete this.pendingMessageBySession[sessionId];
                        console.log('[chatSidebar] Sending queued message for session:', sessionId, queuedMsg.substring(0, 50));
                        setTimeout(() => {
                            // Only auto-send if this is still the active session
                            if (this.activeSession?.id === sessionId) {
                                this.inputMessage = queuedMsg;
                                this.sendMessage();
                            }
                        }, 100);
                    }
                    break;

                case 'TITLE_UPDATE':
                    console.log('[chatSidebar] Worker: title updated:', title);
                    if (this.activeSession) {
                        this.activeSession.display_name = title;
                    }
                    const idx = this.sessions.findIndex(s => s.id === sessionId);
                    if (idx >= 0) {
                        this.sessions[idx].display_name = title;
                    }
                    break;

                case 'ERROR':
                    console.error('[chatSidebar] Worker: error for session:', sessionId, ':', error);
                    // Only show toast if it's the active session's error
                    if (isActiveSession) {
                        this.showToast('Errore: ' + error, 'error');
                        this.streaming = false;
                    }
                    // Clear stream content and streaming state for this session on error
                    if (sessionId) {
                        this.streamContentBySession[sessionId] = '';
                        this.streamingBySession[sessionId] = false;
                    }
                    break;

                case 'STREAM_ABORTED':
                    console.log('[chatSidebar] Worker: stream aborted for session:', sessionId);
                    // Only save partial content if it's the active session
                    if (isActiveSession) {
                        const partialContent = this.streamContentBySession[sessionId] || this.streamContent;
                        if (partialContent.trim()) {
                            this.messages.push({
                                id: 'stopped-' + Date.now(),
                                role: 'assistant',
                                content: partialContent + '\n\n*[Interrotto]*',
                                created_at: new Date().toISOString()
                            });
                        }
                        this.streamContent = '';
                        this.streaming = false;
                    }
                    // Clear accumulated content and streaming state for this session
                    if (sessionId) {
                        this.streamContentBySession[sessionId] = '';
                        this.streamingBySession[sessionId] = false;
                        // Invalidate message cache since new message was added
                        delete this.sessionMessagesCache[sessionId];
                    }
                    break;

                case 'STREAM_END':
                    console.log('[chatSidebar] Worker: stream ended for session:', sessionId);
                    // Clear streaming state for this session
                    if (sessionId) {
                        this.streamingBySession[sessionId] = false;
                    }
                    // Only update UI if it's the active session
                    if (isActiveSession) {
                        this.streaming = false;
                    }
                    // Request updated stream count from worker
                    if (this.useWorker && chatWorkerPort) {
                        setTimeout(() => {
                            chatWorkerPort.postMessage({
                                type: 'GET_STATE',
                                sessionId: this.activeSession?.id
                            });
                        }, 100);
                    }
                    break;

                case 'STATE_SYNC':
                    console.log('[chatSidebar] Worker: state sync received', { activeStreams, state });
                    // Track active stream count for UI limit
                    if (activeStreams && Array.isArray(activeStreams)) {
                        this.activeStreamCount = activeStreams.length;
                        this.maxStreamsReached = activeStreams.length >= 10;
                        console.log(`[chatSidebar] Active streams: ${this.activeStreamCount}/10${this.maxStreamsReached ? ' (LIMIT REACHED)' : ''}`);

                        // Update per-session streaming state for all active streams
                        activeStreams.forEach(streamSessionId => {
                            this.streamingBySession[streamSessionId] = true;
                        });

                        // Show warning if limit is reached
                        if (this.maxStreamsReached) {
                            console.warn('[chatSidebar] Maximum concurrent streams reached (10)');
                        }
                    }
                    // Restore state if there was an active stream for current session
                    if (state && sessionId === this.activeSession?.id) {
                        if (state.streaming) {
                            this.streaming = true;
                            this.streamingBySession[sessionId] = true;
                            this.streamContent = state.streamContent || '';
                            this.streamContentBySession[sessionId] = state.streamContent || '';
                            this.systemInfo = state.systemInfo || [];
                            console.log('[chatSidebar] Restored active stream state for session:', sessionId);
                        }
                    }
                    break;

                case 'ACTION':
                    console.log('[chatSidebar] Worker: action received for session:', sessionId, data);
                    // Only execute action if it's for the active session
                    if (isActiveSession) {
                        this.executeAction(data.action);
                    }
                    break;

                default:
                    console.log('[chatSidebar] Worker: unknown message type:', type);
            }
        },

        /**
         * Load all chat sessions
         */
        async loadSessions(filterRepoId = undefined) {
            try {
                // Use global context repo if not explicitly specified
                const repoId = filterRepoId !== undefined
                    ? filterRepoId
                    : (typeof Alpine !== 'undefined' && Alpine.store('globalContext')?.selectedRepoId) || null;

                let url = '/api/cli-chat/sessions';
                if (repoId) {
                    url += `?repository_id=${repoId}`;
                }

                console.log('[chatSidebar] Fetching sessions...', repoId ? `(filtered by repo: ${repoId})` : '(all)');
                const res = await fetch(url);
                console.log('[chatSidebar] Sessions response:', res.status);
                if (res.ok) {
                    this.sessions = await res.json();
                } else {
                    console.error('[chatSidebar] Sessions API error:', res.status, await res.text());
                }
            } catch (error) {
                console.error('[chatSidebar] Error loading sessions:', error);
            }
        },

        /**
         * Load available agents
         */
        async loadAgents() {
            try {
                const res = await fetch('/api/cli-chat/agents');
                if (res.ok) {
                    const data = await res.json();
                    this.agents = data.agents || [];
                }
            } catch (error) {
                console.error('Error loading agents:', error);
            }
        },

        /**
         * Get filtered agents based on search query
         */
        get filteredAgents() {
            if (!this.agentSearchQuery) {
                return this.agents.slice(0, 10);  // Show first 10 if no query
            }
            const query = this.agentSearchQuery.toLowerCase();
            return this.agents.filter(a =>
                a.name.toLowerCase().includes(query) ||
                (a.description && a.description.toLowerCase().includes(query))
            ).slice(0, 10);  // Limit to 10 results
        },

        /**
         * Handle input in message textarea - detect @ for agent autocomplete
         */
        handleMessageInput(event) {
            const textarea = event.target;
            const value = textarea.value;
            const cursorPos = textarea.selectionStart;

            // Find the last @ before cursor
            const textBeforeCursor = value.substring(0, cursorPos);
            const atIndex = textBeforeCursor.lastIndexOf('@');

            if (atIndex >= 0) {
                // Check if @ is at start or preceded by whitespace
                const charBefore = atIndex > 0 ? textBeforeCursor[atIndex - 1] : ' ';
                if (charBefore === ' ' || charBefore === '\n' || atIndex === 0) {
                    // Extract query after @
                    const query = textBeforeCursor.substring(atIndex + 1);
                    // Only show autocomplete if query doesn't contain spaces
                    if (!query.includes(' ')) {
                        this.agentSearchQuery = query;
                        this.agentTriggerPosition = atIndex;
                        this.showAgentAutocomplete = true;
                        this.selectedAgentIndex = 0;
                        return;
                    }
                }
            }

            // Close autocomplete if no valid @ context
            this.showAgentAutocomplete = false;
            this.agentSearchQuery = '';
        },

        /**
         * Handle keyboard navigation in agent autocomplete
         */
        handleAutocompleteKeydown(event) {
            if (!this.showAgentAutocomplete) return false;

            const agents = this.filteredAgents;
            if (agents.length === 0) return false;

            switch (event.key) {
                case 'ArrowDown':
                    event.preventDefault();
                    this.selectedAgentIndex = (this.selectedAgentIndex + 1) % agents.length;
                    return true;
                case 'ArrowUp':
                    event.preventDefault();
                    this.selectedAgentIndex = (this.selectedAgentIndex - 1 + agents.length) % agents.length;
                    return true;
                case 'Tab':
                case 'Enter':
                    if (this.showAgentAutocomplete && agents.length > 0) {
                        event.preventDefault();
                        this.selectAgent(agents[this.selectedAgentIndex]);
                        return true;
                    }
                    return false;
                case 'Escape':
                    event.preventDefault();
                    this.showAgentAutocomplete = false;
                    return true;
            }
            return false;
        },

        /**
         * Select an agent from autocomplete
         */
        selectAgent(agent) {
            // Replace @query with @agent-name
            const before = this.inputMessage.substring(0, this.agentTriggerPosition);
            const afterCursor = this.inputMessage.substring(
                this.agentTriggerPosition + 1 + this.agentSearchQuery.length
            );
            this.inputMessage = before + '@' + agent.name + ' ' + afterCursor;

            // Close autocomplete
            this.showAgentAutocomplete = false;
            this.agentSearchQuery = '';

            // Focus back on input
            this.$nextTick(() => {
                const input = this.$refs.messageInput;
                if (input) {
                    input.focus();
                    // Position cursor after agent name
                    const newPos = this.agentTriggerPosition + agent.name.length + 2;
                    input.setSelectionRange(newPos, newPos);
                }
            });
        },

        /**
         * Load available repositories for session context
         */
        async loadRepositories() {
            try {
                const res = await fetch('/api/git/repositories');
                if (res.ok) {
                    this.repositories = await res.json();
                    console.log('[chatSidebar] Loaded repositories:', this.repositories.length);
                }
            } catch (error) {
                console.error('Error loading repositories:', error);
            }
        },

        /**
         * Start creating a new session (show repo selector)
         */
        startCreateSession(cliType) {
            this.pendingCliType = cliType;
            // Pre-select repo from global context if available
            const globalRepoId = typeof Alpine !== 'undefined' && Alpine.store('globalContext')?.selectedRepoId;
            this.selectedRepoId = globalRepoId || null;
            this.showRepoSelector = true;
        },

        /**
         * Confirm repo selection and create session
         */
        async confirmCreateSession() {
            if (!this.pendingCliType) return;
            this.showRepoSelector = false;
            await this.createSession(this.pendingCliType, this.selectedRepoId);
            this.pendingCliType = null;
            this.selectedRepoId = null;
        },

        /**
         * Cancel repo selection
         */
        cancelCreateSession() {
            this.showRepoSelector = false;
            this.pendingCliType = null;
            this.selectedRepoId = null;
        },

        /**
         * Load branches for the active session's repository
         */
        async loadBranches() {
            if (!this.activeSession?.repository_id) {
                this.branches = [];
                return;
            }

            this.loadingBranches = true;
            try {
                const res = await fetch(`/api/cli-chat/sessions/${this.activeSession.id}/branches`);
                if (res.ok) {
                    this.branches = await res.json();
                    console.log('[chatSidebar] Loaded branches:', this.branches.length);
                } else {
                    console.error('[chatSidebar] Failed to load branches:', res.status);
                    this.branches = [];
                }
            } catch (error) {
                console.error('[chatSidebar] Error loading branches:', error);
                this.branches = [];
            } finally {
                this.loadingBranches = false;
            }
        },

        /**
         * Change branch for the active session (with confirmation)
         */
        async changeBranch(newBranch) {
            if (!this.activeSession || !newBranch) return;
            if (newBranch === this.activeSession.current_branch) return;
            if (!confirm(`Cambiare branch a "${newBranch}"?`)) return;

            try {
                const res = await fetch(`/api/cli-chat/sessions/${this.activeSession.id}/branch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ branch: newBranch })
                });

                if (!res.ok) {
                    throw new Error(await res.text() || `HTTP ${res.status}`);
                }

                const updated = await res.json();
                this.activeSession = updated;
                const idx = this.sessions.findIndex(s => s.id === updated.id);
                if (idx >= 0) this.sessions[idx] = updated;
                this.showToast(`Branch: ${newBranch}`, 'success');
            } catch (error) {
                TurboWrapError.handle('Change Git Branch', error, { repoId: this.activeSession?.repository_id, branch: newBranch });
            }
        },

        /**
         * Create a new chat session
         * @param {string} cliType - 'claude' or 'gemini'
         * @param {string|null} repositoryId - Optional repository ID
         * @param {string|null} agentName - Optional agent name (e.g., 'test_creator')
         */
        async createSession(cliType, repositoryId = null, agentName = null) {
            this.creating = true;
            try {
                const payload = {
                    cli_type: cliType,
                    display_name: agentName ? `${agentName}` : (cliType === 'claude' ? 'Claude Chat' : 'Gemini Chat'),
                    color: cliType === 'claude' ? '#f97316' : '#3b82f6',
                    ...(repositoryId && { repository_id: repositoryId }),
                    ...(agentName && { agent_name: agentName })
                };

                const res = await fetch('/api/cli-chat/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    throw new Error(await res.text() || `HTTP ${res.status}`);
                }

                const session = await res.json();

                // Start the process immediately
                console.log('[createSession] Starting process for session:', session.id);
                try {
                    const startRes = await fetch(`/api/cli-chat/sessions/${session.id}/start`, {
                        method: 'POST'
                    });
                    if (startRes.ok) {
                        const startData = await startRes.json();
                        console.log('[createSession] Process started:', startData);
                        if (startData.claude_session_id) {
                            session.claude_session_id = startData.claude_session_id;
                        }
                        session.status = 'running';
                    } else {
                        const errorText = await startRes.text();
                        console.error('[createSession] Start endpoint failed:', {
                            status: startRes.status,
                            statusText: startRes.statusText,
                            error: errorText
                        });
                        // Try to parse JSON error response
                        try {
                            const errorData = JSON.parse(errorText);
                            console.error('[createSession] Error detail:', errorData.detail);
                        } catch (e) {
                            // Not JSON, log raw text
                        }
                    }
                } catch (error) {
                    console.error('[createSession] Failed to start process (network error):', error);
                    console.error('[createSession] Error details:', {
                        name: error.name,
                        message: error.message,
                        stack: error.stack
                    });
                }

                this.sessions.unshift(session);
                this.selectSession(session);
                this.showToast('Chat creata e avviata', 'success');
            } catch (error) {
                TurboWrapError.handle('Create Chat Session', error, { agent: cliType, repoId: repositoryId });
            } finally {
                this.creating = false;
            }
        },

        /**
         * Select a session and load its messages
         * Supports parallel streaming: each session keeps its own streamContent
         */
        async selectSession(session) {
            // Abort any in-flight fetch from previous session change
            if (this._fetchAbortController) {
                this._fetchAbortController.abort();
            }
            this._fetchAbortController = new AbortController();

            // When switching session, preserve the old session's stream in background
            // and load the new session's accumulated stream content
            if (this.activeSession?.id) {
                // Save current streamContent for this session before switching
                this.streamContentBySession[this.activeSession.id] = this.streamContent;
            }

            this.activeSession = session;
            this.messages = [];
            // Reset state arrays from previous session
            this.systemInfo = [];
            this.activeTools = [];
            this.completedTools = [];
            this.activeAgents = [];
            this.completedAgents = [];
            this.showSettings = false;
            this.branches = [];

            // Load the new session's accumulated stream content and streaming state
            this.streamContent = this.streamContentBySession[session.id] || '';
            this.streaming = !!this.streamingBySession[session.id];  // Update streaming flag for new session

            localStorage.setItem('chatActiveSessionId', session.id);

            try {
                // Check cache before fetching
                if (this.sessionMessagesCache[session.id]) {
                    console.log('[selectSession] Using cached messages for session:', session.id);
                    this.messages = this.sessionMessagesCache[session.id];
                } else {
                    const res = await fetch(
                        `/api/cli-chat/sessions/${session.id}/messages`,
                        { signal: this._fetchAbortController.signal }
                    );
                    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);

                    this.messages = await res.json();
                    // Cache the fetched messages
                    this.sessionMessagesCache[session.id] = this.messages;
                }
                this.$nextTick(() => this.scrollToBottom());

                // Always start/ensure process is running (for Claude sessions)
                // Status in DB might be 'running' but process might not exist (e.g., after server restart)
                if (session.cli_type === 'claude') {
                    console.log('[selectSession] Ensuring process is running for session:', session.id);
                    try {
                        const startRes = await fetch(`/api/cli-chat/sessions/${session.id}/start`, {
                            method: 'POST'
                        });
                        if (startRes.ok) {
                            const startData = await startRes.json();
                            console.log('[selectSession] Process started:', startData);
                            if (startData.claude_session_id) {
                                session.claude_session_id = startData.claude_session_id;
                            }
                            session.status = 'running';
                        } else {
                            const errorText = await startRes.text();
                            console.error('[selectSession] Start endpoint failed:', {
                                status: startRes.status,
                                statusText: startRes.statusText,
                                error: errorText
                            });
                            // Try to parse JSON error response
                            try {
                                const errorData = JSON.parse(errorText);
                                console.error('[selectSession] Error detail:', errorData.detail);
                            } catch (e) {
                                // Not JSON, log raw text
                            }
                        }
                    } catch (error) {
                        console.error('[selectSession] Failed to start process (network error):', error);
                        console.error('[selectSession] Error details:', {
                            name: error.name,
                            message: error.message,
                            stack: error.stack
                        });
                    }
                }

                if (session.repository_id) await this.loadBranches();

                // Context/usage info fetched only when modal is opened (too slow for auto-fetch)
            } catch (error) {
                if (error.name === 'AbortError') {
                    console.log('[selectSession] Fetch aborted due to session change');
                    return;
                }
                TurboWrapError.handle('Load Chat Session', error, { sessionId: session?.id });
            }
        },

        /**
         * Toggle dual chat mode (only in full/page modes)
         */
        toggleDualChat() {
            if (this.chatMode === 'third' || this.chatMode === 'hidden') {
                this.showToast('Dual chat disponibile solo in full/page', 'warning');
                return;
            }
            this.dualChatEnabled = !this.dualChatEnabled;
            if (!this.dualChatEnabled) {
                this.secondarySession = null;
                this.secondaryMessages = [];
                this.streamContentSecondary = '';
            }
            localStorage.setItem('dualChatEnabled', this.dualChatEnabled);
        },

        /**
         * Show context menu on tab right-click
         */
        showContextMenu(event, session) {
            event.preventDefault();
            if (!this.dualChatEnabled) return;
            this.contextMenuSession = session;
            this.contextMenuX = event.clientX;
            this.contextMenuY = event.clientY;
            this.showTabContextMenu = true;
        },

        /**
         * Select session in a specific pane (left or right)
         */
        async selectSessionInPane(session, pane) {
            this.showTabContextMenu = false;
            if (pane === 'left') {
                await this.selectSession(session);
            } else {
                await this.selectSecondarySession(session);
            }
        },

        /**
         * Select a session for the secondary (right) pane
         */
        async selectSecondarySession(session) {
            this.secondarySession = session;
            this.secondaryMessages = [];
            this.streamContentSecondary = this.streamContentBySession[session.id] || '';
            localStorage.setItem('chatSecondarySessionId', session.id);

            try {
                const res = await fetch(`/api/cli-chat/sessions/${session.id}/messages`);
                if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
                this.secondaryMessages = await res.json();
                this.$nextTick(() => this.scrollToBottomSecondary());
            } catch (error) {
                TurboWrapError.handle('Load Secondary Session', error, { sessionId: session?.id });
            }
        },

        /**
         * Scroll secondary pane to bottom
         */
        scrollToBottomSecondary() {
            const container = document.getElementById('chat-messages-secondary');
            if (container) container.scrollTop = container.scrollHeight;
        },

        /**
         * Send message to secondary session (simplified, uses direct fetch)
         */
        async sendMessageSecondary() {
            if (!this.inputMessageSecondary.trim() || !this.secondarySession) return;

            const content = this.inputMessageSecondary.trim();
            this.inputMessageSecondary = '';

            // Add user message immediately
            const userMsg = {
                id: 'temp-secondary-' + Date.now(),
                role: 'user',
                content: content,
                created_at: new Date().toISOString()
            };
            this.secondaryMessages.push(userMsg);
            this.$nextTick(() => this.scrollToBottomSecondary());

            // Use SharedWorker if available
            if (this.useWorker && chatWorkerPort) {
                console.log('[chatSidebar] Sending secondary message via SharedWorker');
                chatWorkerPort.postMessage({
                    type: 'SEND_MESSAGE',
                    sessionId: this.secondarySession.id,
                    content: content,
                    modelOverride: null,
                    userMessage: userMsg
                });
                return;
            }

            // Fallback: direct fetch
            try {
                const res = await fetch(`/api/cli-chat/sessions/${this.secondarySession.id}/messages/stream`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content })
                });

                if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);

                const reader = res.body?.getReader();
                const decoder = new TextDecoder();
                let fullContent = '';

                while (reader) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split('\n');

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.type === 'chunk' && data.content) {
                                    fullContent += data.content;
                                    this.streamContentSecondary = fullContent;
                                }
                            } catch (e) { /* ignore parse errors */ }
                        }
                    }
                }

                // Add assistant message
                if (fullContent) {
                    this.secondaryMessages.push({
                        id: 'temp-assistant-secondary-' + Date.now(),
                        role: 'assistant',
                        content: fullContent,
                        created_at: new Date().toISOString()
                    });
                    this.streamContentSecondary = '';
                    this.$nextTick(() => this.scrollToBottomSecondary());
                }
            } catch (error) {
                TurboWrapError.handle('Send Secondary Message', error);
            }
        },

        /**
         * Update session settings
         */
        async updateSession() {
            if (!this.activeSession) return;

            try {
                const res = await fetch(`/api/cli-chat/sessions/${this.activeSession.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: this.activeSession.model,
                        agent_name: this.activeSession.agent_name,
                        thinking_enabled: this.activeSession.thinking_enabled,
                        thinking_budget: this.activeSession.thinking_budget,
                        reasoning_enabled: this.activeSession.reasoning_enabled
                    })
                });

                if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);

                const updated = await res.json();
                const idx = this.sessions.findIndex(s => s.id === updated.id);
                if (idx >= 0) this.sessions[idx] = updated;
            } catch (error) {
                TurboWrapError.handle('Update Session Settings', error, { sessionId: this.activeSession?.id });
            }
        },

        /**
         * Delete a session
         */
        async deleteSession(sessionId) {
            if (!confirm('Eliminare questa chat?')) return;

            try {
                const res = await fetch(`/api/cli-chat/sessions/${sessionId}`, { method: 'DELETE' });
                if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);

                this.sessions = this.sessions.filter(s => s.id !== sessionId);
                if (this.activeSession?.id === sessionId) {
                    this.activeSession = null;
                    localStorage.removeItem('chatActiveSessionId');
                }

                // Cleanup per-session state to prevent memory leaks
                delete this.streamContentBySession[sessionId];
                delete this.streamingBySession[sessionId];
                delete this.contentSegmentsBySession[sessionId];
                delete this.lastKnownLengthBySession[sessionId];
                delete this.pendingMessageBySession[sessionId];
                delete this.sessionMessagesCache[sessionId];

                this.showToast('Chat eliminata', 'success');
            } catch (error) {
                TurboWrapError.handle('Delete Chat Session', error, { sessionId });
            }
        },

        /**
         * Stop the current streaming response
         */
        stopStreaming() {
            // If using worker, tell it to stop
            if (this.useWorker && chatWorkerPort && this.activeSession) {
                chatWorkerPort.postMessage({
                    type: 'STOP_STREAM',
                    sessionId: this.activeSession.id
                });
            }

            // Legacy: abort direct fetch if in use
            if (this.abortController) {
                this.abortController.abort();
                this.abortController = null;
            }
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }

            // Clear pending message (user stopped, so don't auto-send)
            this.pendingMessage = null;

            // If we have partial content, save it as a message
            if (this.streamContent.trim()) {
                this.messages.push({
                    id: 'stopped-' + Date.now(),
                    role: 'assistant',
                    content: this.streamContent + '\n\n*[Interrotto]*',
                    created_at: new Date().toISOString()
                });
            }

            this.streamContent = '';
            this.streaming = false;
            this.showToast('Risposta interrotta', 'info');
        },

        /**
         * Queue a message to send after current stream completes (ACCODA)
         */
        queueMessage(message) {
            if (!message || !message.trim()) return;
            this.pendingMessage = message.trim();
            this.inputMessage = '';  // Clear input
            this.showToast('Messaggio in coda - sarà inviato al termine', 'info');
        },

        /**
         * Fork session and send message immediately (DUPLICA)
         */
        async forkAndSend(message) {
            if (!message || !message.trim() || !this.activeSession || this.forkInProgress) return;

            this.forkInProgress = true;
            const msgContent = message.trim();
            this.inputMessage = '';  // Clear input immediately

            try {
                // 1. Call API to fork session
                const res = await fetch(`/api/cli-chat/sessions/${this.activeSession.id}/fork`, {
                    method: 'POST'
                });

                if (!res.ok) {
                    throw new Error(`Fork failed: ${res.status}`);
                }

                const forkedSession = await res.json();
                console.log('[FORK] Created forked session:', forkedSession.id);

                // 2. Add to sessions list
                this.sessions.unshift(forkedSession);

                // 3. Switch to forked session
                this.activeSession = forkedSession;

                // 4. Load messages from forked session (copied from original)
                const messagesRes = await fetch(`/api/cli-chat/sessions/${forkedSession.id}/messages`);
                if (messagesRes.ok) {
                    this.messages = await messagesRes.json();
                }

                this.showToast('Sessione duplicata - invio in corso...', 'success');

                // 5. Send the message in the forked session
                this.inputMessage = msgContent;
                await this.sendMessage();

            } catch (e) {
                TurboWrapError.handle('Fork Chat Session', e, { sessionId: this.activeSession?.id, messageIdx });
            } finally {
                this.forkInProgress = false;
            }
        },

        /**
         * Check if the current active session is streaming
         * @returns {boolean}
         */
        isCurrentSessionStreaming() {
            if (!this.activeSession?.id) return false;
            return !!this.streamingBySession[this.activeSession.id];
        },

        /**
         * Handle Enter key in textarea
         * - ENTER alone: send or queue message
         * - CTRL+ENTER or SHIFT+ENTER: insert new line
         */
        handleEnterKey(event) {
            if (event.ctrlKey || event.shiftKey) {
                // Insert newline at cursor position
                const textarea = event.target;
                const start = textarea.selectionStart;
                const end = textarea.selectionEnd;
                const value = this.inputMessage;

                this.inputMessage = value.substring(0, start) + '\n' + value.substring(end);

                // Use nextTick to set cursor position after Alpine updates the value
                this.$nextTick(() => {
                    textarea.selectionStart = textarea.selectionEnd = start + 1;
                    // Trigger resize
                    textarea.style.height = 'auto';
                    textarea.style.height = textarea.scrollHeight + 'px';
                });
            } else {
                // Send or queue message
                event.preventDefault();
                if (this.inputMessage.trim()) {
                    this.sendMessage();
                }
            }
        },

        /**
         * Send a message and stream response via SSE
         * Uses SharedWorker if available, falls back to direct fetch
         * If current session is streaming, queues the message for later
         */
        async sendMessage() {
            if (!this.inputMessage.trim() || !this.activeSession) return;

            const sessionId = this.activeSession.id;

            // If this session is already streaming, QUEUE the message instead of blocking
            if (this.isCurrentSessionStreaming()) {
                const msgToQueue = this.inputMessage.trim();
                this.pendingMessageBySession[sessionId] = msgToQueue;
                this.inputMessage = '';
                this.showToast('Messaggio in coda - sarà inviato al termine', 'info');
                console.log('[chatSidebar] Message queued for session:', sessionId);
                return;
            }

            let content = this.inputMessage.trim();
            this.inputMessage = '';

            // Check for slash commands
            const { isCommand, expandedContent } = await this.expandSlashCommand(content);
            let modelOverride = null;

            if (isCommand) {
                if (!expandedContent) {
                    // Command not found, abort
                    return;
                }
                content = expandedContent;

                // Use lightweight models for slash commands
                const cliType = this.activeSession.cli_type;
                if (cliType === 'claude') {
                    modelOverride = 'claude-haiku-4-5-20251001';
                } else if (cliType === 'gemini') {
                    modelOverride = 'gemini-3-flash-preview';
                }
                console.log(`[chatSidebar] Slash command detected, using model: ${modelOverride}`);
            }

            this.streaming = true;
            this.streamingBySession[sessionId] = true;  // Track per-session
            this.streamContent = '';
            this.systemInfo = [];  // Reset system info for new message

            // Add user message immediately
            const userMsg = {
                id: 'temp-' + Date.now(),
                role: 'user',
                content: content,
                created_at: new Date().toISOString()
            };
            this.messages.push(userMsg);
            this.$nextTick(() => this.scrollToBottom());

            // Use SharedWorker if available
            if (this.useWorker && chatWorkerPort) {
                console.log('[chatSidebar] Sending via SharedWorker');
                chatWorkerPort.postMessage({
                    type: 'SEND_MESSAGE',
                    sessionId: this.activeSession.id,
                    content: content,
                    modelOverride: modelOverride,
                    userMessage: userMsg
                });
                // Response will come via handleWorkerMessage
                return;
            }

            // Fallback: direct fetch (legacy behavior)
            console.log('[chatSidebar] Sending via direct fetch (worker not available)');
            await this.sendMessageDirect(content, modelOverride);
        },

        /**
         * Direct fetch implementation (fallback when worker not available)
         * @param {string} content - Message content
         * @param {string|null} modelOverride - Optional model override for this message
         */
        async sendMessageDirect(content, modelOverride = null) {
            // Create AbortController for cancellation
            this.abortController = new AbortController();

            try {
                // Close any existing EventSource
                if (this.eventSource) {
                    this.eventSource.close();
                }

                // Create new EventSource for SSE
                const url = `/api/cli-chat/sessions/${this.activeSession.id}/message`;

                // Build request body
                const body = { content };
                if (modelOverride) {
                    body.model_override = modelOverride;
                }

                // Use fetch with POST for SSE (EventSource only supports GET)
                const response = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                    signal: this.abortController.signal
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                // Read the stream
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let currentEventType = 'chunk';  // Track current SSE event type

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });

                    // Process SSE events
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        // Handle SSE event format
                        if (line.startsWith('event: ')) {
                            currentEventType = line.slice(7).trim();
                            console.log('[chatSidebar] SSE event:', currentEventType);
                            continue;
                        }

                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));

                                // Handle action events from AI
                                if (currentEventType === 'action') {
                                    console.log('[chatSidebar] Action event:', data);
                                    this.executeAction(data);
                                    currentEventType = 'chunk';  // Reset after handling
                                    continue;
                                }

                                // Handle usage events from Claude CLI
                                if (currentEventType === 'usage') {
                                    console.log('[chatSidebar] Usage event:', data);
                                    // Update session token counts
                                    if (this.activeSession) {
                                        // Claude CLI returns: {input_tokens, output_tokens, cache_read_input_tokens, ...}
                                        const inputTokens = data.input_tokens || 0;
                                        const outputTokens = data.output_tokens || 0;
                                        const cacheTokens = data.cache_read_input_tokens || 0;

                                        // Update session stats (cumulative context = input + cache)
                                        this.activeSession.total_tokens_in = inputTokens + cacheTokens;
                                        this.activeSession.total_tokens_out = (this.activeSession.total_tokens_out || 0) + outputTokens;

                                        // Store detailed usage for (i) info button
                                        this.activeSession.last_usage = data;

                                        console.log('[chatSidebar] Updated tokens - in:', this.activeSession.total_tokens_in, 'out:', this.activeSession.total_tokens_out);
                                    }
                                    currentEventType = 'chunk';  // Reset after handling
                                    continue;
                                }

                                // Handle system events - show collapsible
                                if (data.type === 'system') {
                                    console.log('[chatSidebar] System event:', data.subtype);
                                    // Add as collapsible system message
                                    if (!this.systemInfo) this.systemInfo = [];
                                    this.systemInfo.push(data);
                                    continue;
                                }

                                // Handle content chunks
                                if (data.content) {
                                    this.streamContent += data.content;
                                    this.$nextTick(() => this.scrollToBottom());
                                }

                                // Handle stream completion
                                if (data.message_id) {
                                    this.messages.push({
                                        id: data.message_id,
                                        role: 'assistant',
                                        content: this.streamContent,
                                        created_at: new Date().toISOString()
                                    });
                                    this.streamContent = '';
                                    this.streaming = false;

                                    // Check for queued message (ACCODA functionality)
                                    if (this.pendingMessage) {
                                        const queuedMsg = this.pendingMessage;
                                        this.pendingMessage = null;
                                        console.log('[chatSidebar] Sending queued message:', queuedMsg.substring(0, 50));
                                        // Use setTimeout to let the UI update first
                                        setTimeout(() => {
                                            this.inputMessage = queuedMsg;
                                            this.sendMessage();
                                        }, 100);
                                    }
                                }

                                // Handle total_length (done event)
                                if (data.total_length !== undefined) {
                                    console.log('[chatSidebar] Stream done, length:', data.total_length);
                                }

                                // Handle errors
                                if (data.error) {
                                    console.error('Stream error:', data.error);
                                    this.showToast('Errore: ' + data.error, 'error');
                                    this.streaming = false;
                                }

                                // Handle title update (auto-generated after first message)
                                if (data.title) {
                                    console.log('[chatSidebar] Title updated:', data.title);
                                    // Update active session
                                    if (this.activeSession) {
                                        this.activeSession.display_name = data.title;
                                    }
                                    // Update in sessions list
                                    const idx = this.sessions.findIndex(s => s.id === this.activeSession?.id);
                                    if (idx >= 0) {
                                        this.sessions[idx].display_name = data.title;
                                    }
                                }
                            } catch (e) {
                                // Ignore parse errors for incomplete chunks
                                console.debug('[chatSidebar] Parse error (partial chunk):', e.message);
                            }
                        }
                    }
                }

            } catch (error) {
                // Don't show error for user-initiated abort
                if (error.name === 'AbortError') {
                    console.log('[chatSidebar] Stream aborted by user');
                    return;
                }
                TurboWrapError.handle('Send Chat Message', error, { sessionId: this.activeSession?.id });
                this.streaming = false;
            } finally {
                this.abortController = null;
            }
        },

        /**
         * Get content segments for the active session
         * @returns {Array} Array of segments [{type: 'text', content: ''}, {type: 'tool', name: '', input: {}}, ...]
         */
        getContentSegments() {
            if (!this.activeSession?.id) return [];
            return this.contentSegmentsBySession[this.activeSession.id] || [];
        },

        /**
         * Get tool description for display
         * @param {Object} tool - Tool object with name and input
         * @returns {string} Description to display
         */
        getToolDescription(tool) {
            if (!tool || !tool.input) return '';
            const input = tool.input;
            switch (tool.name) {
                case 'Read':
                    return input.file_path || '';
                case 'Edit':
                    return input.file_path || '';
                case 'Write':
                    return input.file_path || '';
                case 'Bash':
                    const cmd = input.command || input.description || '';
                    return cmd.length > 60 ? cmd.substring(0, 57) + '...' : cmd;
                case 'Grep':
                    return input.pattern || '';
                case 'Glob':
                    return input.pattern || '';
                case 'Task':
                    return input.description || input.subagent_type || '';
                case 'WebSearch':
                    return input.query || '';
                case 'WebFetch':
                    return input.url || '';
                default:
                    return input.file_path || input.pattern || input.command?.substring(0, 50) || input.description || '';
            }
        },

        /**
         * Get short model name for display
         * @param {string} model - Full model name
         * @returns {string} Short name
         */
        getModelShortName(model) {
            if (!model) return 'default';
            // Claude models
            if (model.includes('opus')) return 'Opus';
            if (model.includes('sonnet')) return 'Sonnet';
            if (model.includes('haiku')) return 'Haiku';
            // Gemini models
            if (model.includes('pro')) return 'Pro';
            if (model.includes('flash')) return 'Flash';
            // Grok models
            if (model.includes('grok')) return 'Grok';
            // Fallback: extract meaningful part
            return model.split('-').slice(1, 2).join(' ') || model;
        },

        /**
         * Format context usage as "XK / 200K" or percentage
         * @param {number} tokensIn - Total input tokens used
         * @param {string} cliType - 'claude' or 'gemini'
         * @returns {string} Formatted context usage
         */
        formatContextUsage(tokensIn, cliType) {
            // Context limits by CLI type
            const contextLimit = cliType === 'gemini' ? 1000000 : 200000;  // Gemini 1M, Claude 200K
            const usedK = Math.round(tokensIn / 1000);
            const limitK = Math.round(contextLimit / 1000);
            const percentage = Math.round((tokensIn / contextLimit) * 100);

            // Show different format based on usage
            if (usedK < 1) {
                return `<1K / ${limitK}K`;
            }
            return `${usedK}K / ${limitK}K (${percentage}%)`;
        },

        /**
         * Parse /context command output from Claude CLI
         * @param {string} output - Raw output from /context command
         * @returns {Object} Parsed context info
         */
        parseContextOutput(output) {
            const info = {
                model: null,
                tokens: { used: 0, limit: 0, percentage: 0 },
                categories: [],
                mcpTools: [],
                agents: []
            };

            try {
                const lines = output.split('\n');
                let section = null;

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed) continue;

                    // Detect sections
                    if (trimmed === 'Context Usage' || trimmed === 'Categories' ||
                        trimmed === 'MCP Tools' || trimmed === 'Custom Agents') {
                        section = trimmed;
                        continue;
                    }

                    // Parse model
                    if (trimmed.startsWith('Model:')) {
                        info.model = trimmed.replace('Model:', '').trim();
                        continue;
                    }

                    // Parse total tokens
                    if (trimmed.startsWith('Tokens:')) {
                        const match = trimmed.match(/Tokens:\s*([\d.]+)k\s*\/\s*([\d.]+)k\s*\((\d+)%\)/i);
                        if (match) {
                            info.tokens.used = parseFloat(match[1]) * 1000;
                            info.tokens.limit = parseFloat(match[2]) * 1000;
                            info.tokens.percentage = parseInt(match[3]);
                        }
                        continue;
                    }

                    // Skip header rows
                    if (trimmed.startsWith('Category\t') || trimmed.startsWith('Tool\t') ||
                        trimmed.startsWith('Agent Type\t')) {
                        continue;
                    }

                    // Parse tab-separated data based on section
                    const parts = trimmed.split('\t').map(p => p.trim());

                    if (section === 'Categories' && parts.length >= 2) {
                        const tokensMatch = parts[1].match(/([\d.]+)k/i);
                        if (tokensMatch) {
                            info.categories.push({
                                name: parts[0],
                                tokens: parseFloat(tokensMatch[1]) * 1000,
                                percentage: parts[2] ? parseFloat(parts[2]) : null
                            });
                        }
                    } else if (section === 'MCP Tools' && parts.length >= 2) {
                        info.mcpTools.push({
                            name: parts[0],
                            server: parts[1] || null,
                            tokens: parts[2] ? parseInt(parts[2]) : null
                        });
                    } else if (section === 'Custom Agents' && parts.length >= 2) {
                        info.agents.push({
                            name: parts[0],
                            source: parts[1] || null,
                            tokens: parts[2] ? parseInt(parts[2]) : null
                        });
                    }
                }
            } catch (e) {
                console.error('[chatSidebar] Error parsing /context output:', e);
            }

            return info;
        },

        /**
         * Request detailed context info by sending /context command
         */
        async requestContextInfo() {
            if (!this.activeSession?.id) return;

            // Show loading state
            this.contextInfoLoading = true;

            try {
                // Send /context as a special command that returns structured output
                const response = await fetch(`/api/cli-chat/sessions/${this.activeSession.id}/context`);
                if (response.ok) {
                    const data = await response.json();
                    // Store parsed context info
                    this.activeSession.contextInfo = data;
                    // Update model in session from context (more accurate than config)
                    if (data.model) {
                        this.activeSession.model = data.model;
                    }
                    console.log('[chatSidebar] Context info loaded:', data);
                }
            } catch (e) {
                console.error('[chatSidebar] Error fetching context info:', e);
            } finally {
                this.sessionInfoLoading = false;
            }
        },

        /**
         * Request both context and usage info for session info modal
         */
        async requestSessionInfo() {
            if (!this.activeSession?.id) return;

            this.sessionInfoLoading = true;

            try {
                // Fetch both context and usage in parallel
                const [contextRes, usageRes] = await Promise.all([
                    fetch(`/api/cli-chat/sessions/${this.activeSession.id}/context`),
                    fetch(`/api/cli-chat/sessions/${this.activeSession.id}/usage`)
                ]);

                if (contextRes.ok) {
                    const contextData = await contextRes.json();
                    this.activeSession.contextInfo = contextData;
                    if (contextData.model) {
                        this.activeSession.model = contextData.model;
                    }
                }

                if (usageRes.ok) {
                    this.usageInfo = await usageRes.json();
                }

                console.log('[chatSidebar] Session info loaded:', {
                    context: this.activeSession.contextInfo,
                    usage: this.usageInfo
                });
            } catch (e) {
                console.error('[chatSidebar] Error fetching session info:', e);
            } finally {
                this.sessionInfoLoading = false;
            }
        },

        /**
         * Copy text to clipboard
         */
        async copyToClipboard(text) {
            try {
                await navigator.clipboard.writeText(text);
                // Brief visual feedback could be added here
            } catch (e) {
                console.error('[chatSidebar] Failed to copy:', e);
            }
        },

        /**
         * Get color for token category
         */
        getTokenCategoryColor(name) {
            const colors = {
                'System prompt': '#f472b6',
                'System tools': '#a78bfa',
                'MCP tools': '#60a5fa',
                'Custom agents': '#34d399',
                'Memory files': '#fbbf24',
                'Messages': '#f97316',
                'Free space': '#374151',
                'Autocompact buffer': '#6b7280',
            };
            return colors[name] || '#6b7280';
        },

        /**
         * Format message content (full markdown support)
         * @param {string} content - Message content
         * @param {string} role - Message role ('user' or 'assistant')
         */
        formatMessage(content, role = 'assistant') {
            if (!content) return '';

            try {

            // Check if content is JSON (system message)
            const trimmed = content.trim();
            if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
                try {
                    const json = JSON.parse(trimmed);
                    // Filter out system/init messages
                    if (json.type === 'system' || json.subtype === 'init' || json.tools || json.mcpServers) {
                        // Show as collapsible system info
                        return `<details class="my-2">
                            <summary class="cursor-pointer text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 flex items-center gap-1">
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                </svg>
                                Info di sistema
                            </summary>
                            <pre class="mt-2 bg-gray-800 text-gray-300 p-2 rounded text-[10px] overflow-x-auto max-h-32">${JSON.stringify(json, null, 2)}</pre>
                        </details>`;
                    }
                    // Regular JSON - format nicely
                    return `<pre class="bg-gray-900 text-gray-100 p-3 rounded-lg text-xs overflow-x-auto font-mono my-2"><code>${JSON.stringify(json, null, 2)}</code></pre>`;
                } catch (e) {
                    // Not valid JSON, continue with normal formatting
                }
            }

            // Escape HTML first
            let html = content
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');

            // Code blocks with language label
            html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
                const langLabel = lang ? `<div class="text-[10px] text-gray-400 mb-1 font-mono">${lang}</div>` : '';
                return `<div class="relative my-3">
                    ${langLabel}
                    <pre class="bg-gray-900 text-gray-100 p-3 rounded-lg text-xs overflow-x-auto font-mono leading-relaxed"><code>${code.trim()}</code></pre>
                </div>`;
            });

            // Markdown tables
            html = html.replace(/^(\|.+\|)\n(\|[-:\s|]+\|)\n((?:\|.+\|\n?)+)/gm, (match, headerRow, separatorRow, bodyRows) => {
                // Parse header cells
                const headers = headerRow.split('|').filter(cell => cell.trim()).map(cell => cell.trim());

                // Parse alignment from separator
                const alignments = separatorRow.split('|').filter(cell => cell.trim()).map(cell => {
                    const trimmed = cell.trim();
                    if (trimmed.startsWith(':') && trimmed.endsWith(':')) return 'center';
                    if (trimmed.endsWith(':')) return 'right';
                    return 'left';
                });

                // Parse body rows
                const rows = bodyRows.trim().split('\n').map(row =>
                    row.split('|').filter(cell => cell.trim()).map(cell => cell.trim())
                );

                // Build HTML table
                let table = '<div class="overflow-x-auto my-3"><table class="min-w-full text-sm border-collapse">';

                // Header
                table += '<thead><tr class="bg-gray-100 dark:bg-gray-700">';
                headers.forEach((header, i) => {
                    const align = alignments[i] || 'left';
                    table += `<th class="border border-gray-300 dark:border-gray-600 px-3 py-2 text-${align} font-semibold">${header}</th>`;
                });
                table += '</tr></thead>';

                // Body
                table += '<tbody>';
                rows.forEach((row, rowIndex) => {
                    const bgClass = rowIndex % 2 === 0 ? '' : 'bg-gray-50 dark:bg-gray-800';
                    table += `<tr class="${bgClass}">`;
                    row.forEach((cell, i) => {
                        const align = alignments[i] || 'left';
                        table += `<td class="border border-gray-300 dark:border-gray-600 px-3 py-2 text-${align}">${cell}</td>`;
                    });
                    table += '</tr>';
                });
                table += '</tbody></table></div>';

                return table;
            });

            // Inline code
            html = html.replace(/`([^`]+)`/g,
                '<code class="bg-gray-200 dark:bg-gray-700 text-pink-600 dark:text-pink-400 px-1.5 py-0.5 rounded text-xs font-mono">$1</code>');

            // Headers with improved styling
            html = html.replace(/^######\s+(.+)$/gm, '<h6 class="text-xs font-semibold mt-3 mb-1 text-gray-500 dark:text-gray-400 uppercase tracking-wide">$1</h6>');
            html = html.replace(/^#####\s+(.+)$/gm, '<h5 class="text-xs font-semibold mt-3 mb-1 text-gray-600 dark:text-gray-300">$1</h5>');
            html = html.replace(/^####\s+(.+)$/gm, '<h4 class="text-sm font-semibold mt-4 mb-2 text-gray-700 dark:text-gray-200">$1</h4>');
            html = html.replace(/^###\s+(.+)$/gm, '<h3 class="text-base font-semibold mt-5 mb-2 text-gray-800 dark:text-gray-100 flex items-center gap-2"><span class="w-1 h-4 bg-blue-500 rounded-full"></span>$1</h3>');
            html = html.replace(/^##\s+(.+)$/gm, '<h2 class="text-lg font-bold mt-6 mb-3 text-gray-900 dark:text-white border-b border-gray-200 dark:border-gray-700 pb-2">$1</h2>');
            html = html.replace(/^#\s+(.+)$/gm, '<h1 class="text-xl font-bold mt-6 mb-3 bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent">$1</h1>');

            // Callout boxes (must be before blockquotes) - support [!TYPE] syntax
            html = html.replace(/^&gt;\s*\[!INFO\]\s*(.*)$/gm, '<div class="my-3 p-3 bg-blue-50 dark:bg-blue-900/20 border-l-4 border-blue-500 rounded-r-lg"><div class="flex items-start gap-2"><svg class="w-5 h-5 text-blue-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/></svg><span class="text-blue-800 dark:text-blue-200 text-sm">$1</span></div></div>');
            html = html.replace(/^&gt;\s*\[!WARNING\]\s*(.*)$/gm, '<div class="my-3 p-3 bg-amber-50 dark:bg-amber-900/20 border-l-4 border-amber-500 rounded-r-lg"><div class="flex items-start gap-2"><svg class="w-5 h-5 text-amber-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg><span class="text-amber-800 dark:text-amber-200 text-sm">$1</span></div></div>');
            html = html.replace(/^&gt;\s*\[!SUCCESS\]\s*(.*)$/gm, '<div class="my-3 p-3 bg-green-50 dark:bg-green-900/20 border-l-4 border-green-500 rounded-r-lg"><div class="flex items-start gap-2"><svg class="w-5 h-5 text-green-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg><span class="text-green-800 dark:text-green-200 text-sm">$1</span></div></div>');
            html = html.replace(/^&gt;\s*\[!TIP\]\s*(.*)$/gm, '<div class="my-3 p-3 bg-purple-50 dark:bg-purple-900/20 border-l-4 border-purple-500 rounded-r-lg"><div class="flex items-start gap-2"><svg class="w-5 h-5 text-purple-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z"/></svg><span class="text-purple-800 dark:text-purple-200 text-sm">$1</span></div></div>');
            html = html.replace(/^&gt;\s*\[!ERROR\]\s*(.*)$/gm, '<div class="my-3 p-3 bg-red-50 dark:bg-red-900/20 border-l-4 border-red-500 rounded-r-lg"><div class="flex items-start gap-2"><svg class="w-5 h-5 text-red-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg><span class="text-red-800 dark:text-red-200 text-sm">$1</span></div></div>');

            // Regular blockquotes
            html = html.replace(/^&gt;\s+(.+)$/gm,
                '<blockquote class="border-l-4 border-gray-300 dark:border-gray-600 pl-4 py-2 my-3 text-gray-600 dark:text-gray-400 italic bg-gray-50 dark:bg-gray-800/50 rounded-r-lg">$1</blockquote>');

            // Horizontal rules with better styling
            html = html.replace(/^---+$/gm, '<hr class="my-6 border-0 h-px bg-gradient-to-r from-transparent via-gray-300 dark:via-gray-600 to-transparent">');
            html = html.replace(/^\*\*\*+$/gm, '<hr class="my-6 border-0 h-px bg-gradient-to-r from-transparent via-gray-300 dark:via-gray-600 to-transparent">');

            // Task lists (checkboxes) - must be before regular lists
            html = html.replace(/^[-*]\s+\[x\]\s+(.+)$/gim, '<div class="flex items-start gap-2 my-1"><svg class="w-5 h-5 text-green-500 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg><span class="text-sm text-gray-500 dark:text-gray-400 line-through">$1</span></div>');
            html = html.replace(/^[-*]\s+\[\s?\]\s+(.+)$/gm, '<div class="flex items-start gap-2 my-1"><svg class="w-5 h-5 text-gray-300 dark:text-gray-600 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/></svg><span class="text-sm text-gray-700 dark:text-gray-300">$1</span></div>');

            // Unordered lists with better styling
            html = html.replace(/^[-*]\s+(.+)$/gm,
                '<li class="ml-4 text-sm flex items-start gap-2"><span class="text-blue-500 mt-1.5">•</span><span>$1</span></li>');

            // Ordered lists
            html = html.replace(/^(\d+)\.\s+(.+)$/gm,
                '<li class="ml-4 text-sm flex items-start gap-2"><span class="text-blue-500 font-medium min-w-[1.25rem]">$1.</span><span>$2</span></li>');

            // Wrap consecutive list items
            html = html.replace(/(<li class="ml-4 text-sm flex[^>]*>.*<\/li>\n?)+/g,
                '<ul class="my-2 space-y-1">$&</ul>');
            html = html.replace(/(<li class="ml-4 list-decimal[^>]*>.*<\/li>\n?)+/g,
                '<ol class="my-2 space-y-1">$&</ol>');

            // Links [text](url)
            html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
                '<a href="$2" target="_blank" rel="noopener" class="text-blue-500 hover:text-blue-600 dark:text-blue-400 underline">$1</a>');

            // Auto-link plain URLs (that aren't already inside href="...")
            html = html.replace(/(^|[^="'])(https?:\/\/[^\s<>"')\]]+)/g,
                '$1<a href="$2" target="_blank" rel="noopener" class="text-blue-500 hover:text-blue-600 dark:text-blue-400 underline break-all">$2</a>');

            // Bold **text** or __text__
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold">$1</strong>');
            html = html.replace(/__([^_]+)__/g, '<strong class="font-semibold">$1</strong>');

            // Italic *text* or _text_
            html = html.replace(/\*([^*]+)\*/g, '<em class="italic">$1</em>');
            html = html.replace(/_([^_]+)_/g, '<em class="italic">$1</em>');

            // Strikethrough ~~text~~
            html = html.replace(/~~([^~]+)~~/g, '<del class="line-through text-gray-500">$1</del>');

            // Highlight ==text== (yellow background)
            html = html.replace(/==([^=]+)==/g, '<mark class="bg-yellow-200 dark:bg-yellow-500/30 text-yellow-900 dark:text-yellow-100 px-1 rounded">$1</mark>');

            // Questions with input fields (lines ending with ? that are actual questions)
            // ONLY for assistant messages - user messages should not have question cards
            const questionId = Math.random().toString(36).substr(2, 9);
            let hasQuestions = false;
            if (role === 'assistant') {
                html = html.replace(/^([A-Z][^<\n]{10,}\?)\s*$/gm, (match, question) => {
                    // Skip if inside a code block indicator or looks like code
                    if (question.includes('`') || question.includes('//') || question.includes('/*')) return match;
                    hasQuestions = true;
                    const escapedQ = question.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
                    // Single line to avoid \n → <br> breaking the HTML
                    return `<div class="question-block my-3 p-3 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 rounded-xl border border-blue-200 dark:border-blue-800"><div class="font-medium text-blue-800 dark:text-blue-200 mb-2 flex items-start gap-2"><svg class="w-5 h-5 mt-0.5 text-blue-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg><span>${question}</span></div><input type="text" data-question-id="${questionId}" data-question="${escapedQ}" placeholder="Scrivi la tua risposta..." class="question-input w-full px-3 py-2 text-sm border border-blue-200 dark:border-blue-700 rounded-lg bg-white dark:bg-gray-800 focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"></div>`;
                });

                // Add submit button if there are questions (single line to avoid \n → <br> breaking HTML)
                if (hasQuestions) {
                    html += `<div class="mt-4 flex justify-end"><button onclick="window.dispatchEvent(new CustomEvent('submit-chat-answers', {detail: {id: '${questionId}'}}))" class="px-4 py-2 bg-gradient-to-r from-blue-500 to-indigo-500 text-white rounded-lg hover:from-blue-600 hover:to-indigo-600 transition-all text-sm font-medium shadow-md hover:shadow-lg flex items-center gap-2"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>Invia Risposte</button></div>`;
                }
            }

            // Paragraphs: double newlines become paragraph breaks with spacing
            html = html.replace(/\n\n+/g, '</p><p class="my-4">');

            // Single line breaks
            html = html.replace(/\n/g, '<br>');

            // Wrap content in paragraph if it starts with text (not a tag)
            if (html && !html.startsWith('<')) {
                html = '<p class="my-3 leading-relaxed">' + html + '</p>';
            }

            // Clean up empty paragraphs
            html = html.replace(/<p[^>]*>\s*<\/p>/g, '');

            // Fix paragraphs wrapping block elements
            html = html.replace(/<p[^>]*>(\s*<(h[1-6]|blockquote|pre|ul|ol|hr|div|table|mark))/g, '$1');
            html = html.replace(/(<\/(h[1-6]|blockquote|pre|ul|ol|hr|div|table|mark)>)\s*<\/p>/g, '$1');

            // Clean up extra <br> after block elements
            html = html.replace(/<\/(h[1-6]|blockquote|pre|ul|ol|hr|div|table|thead|tbody|tr|th|td)><br>/g, '</$1>');
            html = html.replace(/<br><(h[1-6]|blockquote|pre|ul|ol|hr|div|table|thead|tbody|tr|th|td)/g, '<$1');

            return html;
            } catch (e) {
                console.error('[chatSidebar] formatMessage error:', e);
                // Return escaped plain text as fallback
                return content
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/\n/g, '<br>');
            }
        },

        /**
         * Format tool for inline display in stream content
         * @param {string} toolName - Name of the tool (Read, Edit, Bash, etc.)
         * @param {Object} toolInput - Tool input parameters
         * @returns {string} Formatted inline tool text
         */
        formatToolInline(toolName, toolInput) {
            let description = '';

            if (toolInput) {
                switch (toolName) {
                    case 'Read':
                        description = toolInput.file_path || '';
                        break;
                    case 'Edit':
                        description = toolInput.file_path || '';
                        break;
                    case 'Write':
                        description = toolInput.file_path || '';
                        break;
                    case 'Bash':
                        // Truncate long commands
                        const cmd = toolInput.command || toolInput.description || '';
                        description = cmd.length > 60 ? cmd.substring(0, 57) + '...' : cmd;
                        break;
                    case 'Glob':
                        description = toolInput.pattern || '';
                        break;
                    case 'Grep':
                        description = toolInput.pattern || '';
                        break;
                    case 'Task':
                        description = toolInput.description || toolInput.subagent_type || '';
                        break;
                    case 'WebFetch':
                        description = toolInput.url || '';
                        break;
                    case 'WebSearch':
                        description = toolInput.query || '';
                        break;
                    default:
                        // Try common field names
                        description = toolInput.file_path || toolInput.path || toolInput.pattern || toolInput.command || '';
                }
            }

            // Format: "🔧 ToolName: description" on its own line
            if (description) {
                return `\n\n🔧 ${toolName}: ${description}\n\n`;
            }
            return `\n\n🔧 ${toolName}\n\n`;
        },

        /**
         * Scroll chat to bottom
         */
        scrollToBottom() {
            const container = document.getElementById('chat-messages');
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        },

        /**
         * Show toast notification
         */
        showToast(message, type = 'success') {
            window.dispatchEvent(new CustomEvent('show-toast', {
                detail: { message, type }
            }));
        },

        /**
         * Execute an action from the AI (navigate, highlight)
         * @param {Object} action - Action object with type and target
         */
        executeAction(action) {
            if (!action || !action.type) {
                console.warn('[chatSidebar] Invalid action:', action);
                return;
            }

            console.log('[chatSidebar] Executing action:', action);

            switch (action.type) {
                case 'navigate':
                    this.executeNavigateAction(action.target);
                    break;

                case 'highlight':
                    this.executeHighlightAction(action.target);
                    break;

                default:
                    console.warn('[chatSidebar] Unknown action type:', action.type);
            }
        },

        /**
         * Navigate to a page
         * @param {string} path - URL path to navigate to (e.g., '/tests', '/issues')
         */
        executeNavigateAction(path) {
            if (!path) {
                console.warn('[chatSidebar] Navigate action missing path');
                return;
            }

            console.log('[chatSidebar] Navigating to:', path);

            // Check if path is relative or absolute
            const url = path.startsWith('http') ? path : path;

            // Use HTMX boost if available for smoother navigation
            const mainContent = document.querySelector('main');
            if (mainContent && window.htmx) {
                // Use HTMX to load the page content
                window.htmx.ajax('GET', url, {
                    target: 'body',
                    swap: 'innerHTML'
                }).then(() => {
                    window.history.pushState({}, '', url);
                    this.showToast(`Navigato a ${path}`, 'success');
                }).catch(() => {
                    // Fallback to regular navigation
                    window.location.href = url;
                });
            } else {
                // Fallback: regular navigation
                window.location.href = url;
            }
        },

        /**
         * Highlight a DOM element temporarily
         * @param {string} selector - CSS selector for the element(s) to highlight
         */
        executeHighlightAction(selector) {
            if (!selector) {
                console.warn('[chatSidebar] Highlight action missing selector');
                return;
            }

            console.log('[chatSidebar] Highlighting:', selector);

            // Find elements matching the selector
            const elements = document.querySelectorAll(selector);

            if (elements.length === 0) {
                console.warn('[chatSidebar] No elements found for selector:', selector);
                this.showToast(`Elemento non trovato: ${selector}`, 'warning');
                return;
            }

            // Highlight each matching element
            elements.forEach((el, index) => {
                // Add highlight class
                el.classList.add('ai-highlight');

                // Scroll first element into view
                if (index === 0) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }

                // Remove highlight after animation completes (3 seconds)
                setTimeout(() => {
                    el.classList.remove('ai-highlight');
                }, 3000);
            });

            this.showToast(`Evidenziato: ${elements.length} elemento/i`, 'success');
        },

        /**
         * Cycle through chat display modes: third → full → page → third
         */
        expandChat() {
            const modes = ['third', 'full', 'page'];
            const idx = modes.indexOf(this.chatMode);
            const newMode = modes[(idx + 1) % modes.length];
            this.chatMode = newMode;

            // Disable dual-chat when switching to 'third' mode (too narrow)
            if (newMode === 'third' && this.dualChatEnabled) {
                this.dualChatEnabled = false;
                this.secondarySession = null;
                this.secondaryMessages = [];
                this.streamContentSecondary = '';
                localStorage.setItem('dualChatEnabled', 'false');
            }

            // When entering 'page' mode, collapse left sidebar
            // sidebarOpen is in parent scope (html x-data)
            if (newMode === 'page') {
                // Access parent scope's sidebarOpen
                const htmlEl = document.documentElement;
                if (htmlEl._x_dataStack) {
                    htmlEl._x_dataStack[0].sidebarOpen = false;
                }
            }
        },

        /**
         * Toggle history panel (hamburger menu)
         */
        toggleHistory() {
            this.showHistory = !this.showHistory;
        },

        /**
         * Highlight the global context footer to draw attention
         */
        highlightFooter() {
            window.dispatchEvent(new CustomEvent('highlight-footer'));
        },

        /**
         * Show tooltip at button position
         * @param {string} text - Tooltip text
         * @param {MouseEvent} event - Mouse event from button
         */
        showTooltip(text, event) {
            const btn = event.currentTarget;
            const rect = btn.getBoundingClientRect();
            this.tooltipText = text;
            this.tooltipPosition = {
                top: rect.top + rect.height / 2,
                left: rect.left - 8 // 8px gap from button
            };
            this.activeTooltip = text;
        },

        /**
         * Hide tooltip
         */
        hideTooltip() {
            this.activeTooltip = null;
            this.tooltipText = '';
        },

        // ============================================================
        // SLASH COMMANDS
        // ============================================================

        /**
         * Available slash commands (loaded from backend)
         */
        slashCommands: {},

        /**
         * Load slash command prompt from backend
         * @param {string} commandName - Command name without slash (e.g., 'test')
         * @returns {Promise<string|null>} - Command prompt or null if not found
         */
        async loadSlashCommand(commandName) {
            console.log(`[chatSidebar] Loading slash command: /${commandName}`);

            // Check cache first
            if (this.slashCommands[commandName]) {
                console.log(`[chatSidebar] Found in cache: /${commandName}`);
                return this.slashCommands[commandName];
            }

            try {
                const url = `/api/cli-chat/commands/${commandName}`;
                console.log(`[chatSidebar] Fetching: ${url}`);
                const res = await fetch(url);
                console.log(`[chatSidebar] Response status: ${res.status}`);
                if (res.ok) {
                    const data = await res.json();
                    this.slashCommands[commandName] = data.prompt;
                    console.log(`[chatSidebar] Loaded command /${commandName}, prompt length: ${data.prompt?.length}`);
                    return data.prompt;
                } else {
                    const errorText = await res.text();
                    console.warn(`[chatSidebar] Slash command /${commandName} not found. Status: ${res.status}, Response: ${errorText}`);
                    return null;
                }
            } catch (error) {
                console.error(`[chatSidebar] Error loading slash command /${commandName}:`, error);
                return null;
            }
        },

        /**
         * Check if message is a slash command and expand it
         * @param {string} content - Message content
         * @returns {Promise<{isCommand: boolean, expandedContent: string}>}
         */
        async expandSlashCommand(content) {
            const trimmed = content.trim();

            // Check if starts with /
            if (!trimmed.startsWith('/')) {
                return { isCommand: false, expandedContent: content };
            }

            // Extract command name (first word after /)
            const match = trimmed.match(/^\/(\w+)(?:\s+(.*))?$/);
            if (!match) {
                return { isCommand: false, expandedContent: content };
            }

            const commandName = match[1].toLowerCase();
            const additionalArgs = match[2] || '';

            // Load command prompt
            const prompt = await this.loadSlashCommand(commandName);
            if (!prompt) {
                console.error(`[chatSidebar] Slash command /${commandName} not found. API returned null. Check server logs for COMMANDS_DIR path.`);
                this.showToast(`Comando /${commandName} non trovato. Verifica i log del server.`, 'error');
                return { isCommand: true, expandedContent: null };
            }

            // Build context-aware prompt
            let expandedContent = prompt;

            // Add repository context if available
            if (this.activeSession?.repository_id) {
                const repo = this.repositories.find(r => r.id === this.activeSession.repository_id);
                const repoName = repo?.name || 'repository';
                const branch = this.activeSession.current_branch || 'main';

                expandedContent = `[Contesto: Repository "${repoName}", Branch "${branch}"]\n\n${expandedContent}`;
            }

            // Append any additional arguments from user
            if (additionalArgs) {
                expandedContent += `\n\n---\n**COMMAND ARGUMENTS (USE THESE VALUES!):**\n${additionalArgs}`;
            }

            console.log(`[chatSidebar] Expanded /${commandName} command`);
            return { isCommand: true, expandedContent };
        },

        /**
         * Insert a slash command into the input field
         * @param {string} commandName - Command name without slash
         */
        insertSlashCommand(commandName) {
            this.inputMessage = `/${commandName}`;
            // Focus the input
            this.$nextTick(() => {
                const input = document.querySelector('#chat-input');
                if (input) {
                    input.focus();
                }
            });
        },

        /**
         * Send slash command directly (from toolbar button)
         * @param {string} commandName - Command name without slash
         */
        async sendSlashCommand(commandName) {
            if (!this.activeSession || this.streaming) {
                this.showToast('Seleziona una chat prima', 'error');
                return;
            }

            this.inputMessage = `/${commandName}`;
            await this.sendMessage();
        },

        /**
         * Fetch server logs from CloudWatch and send to chat for analysis
         */
        async fetchServerLogs() {
            if (!this.activeSession) {
                this.showToast('Seleziona una chat prima', 'error');
                return;
            }

            if (this.streaming) {
                this.showToast('Attendi il completamento della risposta', 'warning');
                return;
            }

            this.isLoadingLogs = true;

            try {
                const response = await fetch('/api/cli-chat/server-logs?minutes=30');

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Errore nel recupero dei log');
                }

                const data = await response.json();

                // Show summary toast
                const summary = data.summary;
                this.showToast(
                    `Log recuperati: ${summary.errors} errori, ${summary.warnings} warning, ${summary.info} info`,
                    summary.errors > 0 ? 'error' : summary.warnings > 0 ? 'warning' : 'success'
                );

                // Set the markdown as input and send to agent for analysis
                this.inputMessage = data.markdown + '\n\nAnalizza questi log e identifica eventuali problemi o pattern.';
                await this.sendMessage();

            } catch (error) {
                TurboWrapError.handle('Analyze Server Logs', error, { lines });
            } finally {
                this.isLoadingLogs = false;
            }
        }
    };
}

// Register globally for Alpine.js
window.chatSidebar = chatSidebar;

// Debug: log when script is loaded
console.log('[cli-chat.js] Script loaded, chatSidebar function registered');
