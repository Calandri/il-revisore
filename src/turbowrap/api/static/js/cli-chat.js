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
        streaming: false,
        streamContent: '',
        inputMessage: '',
        showSettings: false,
        showNewChatMenu: false,
        showSystemInfo: false,
        systemInfo: [],
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
        // UI state
        showHistory: false,     // Show history panel (hamburger)
        activeTooltip: null,    // Active tooltip in toolbar
        tooltipText: '',        // Text for fixed tooltip
        tooltipPosition: { top: 0, left: 0 }, // Position for fixed tooltip

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
        },

        /**
         * Handle global context (repo/branch) changes
         */
        async onGlobalContextChanged(repoId) {
            // Reload sessions filtered by the new repo
            await this.loadSessions(repoId);
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
         */
        handleWorkerMessage(data) {
            const { type, sessionId, content, fullContent, event, messageId, title, error, state, activeStreams } = data;

            // Ignore messages for other sessions
            if (sessionId && this.activeSession?.id !== sessionId) {
                console.log('[chatSidebar] Ignoring worker message for different session:', sessionId);
                return;
            }

            switch (type) {
                case 'STREAM_START':
                    console.log('[chatSidebar] Worker: stream started');
                    this.streaming = true;
                    this.streamContent = '';
                    this.systemInfo = [];
                    break;

                case 'CHUNK':
                    // Use fullContent from worker for accurate state
                    this.streamContent = fullContent || this.streamContent + content;
                    this.$nextTick(() => this.scrollToBottom());
                    break;

                case 'SYSTEM':
                    console.log('[chatSidebar] Worker: system event:', event?.subtype);
                    if (!this.systemInfo) this.systemInfo = [];
                    this.systemInfo.push(event);
                    break;

                case 'DONE':
                    console.log('[chatSidebar] Worker: stream done, messageId:', messageId);
                    this.messages.push({
                        id: messageId,
                        role: 'assistant',
                        content: content || this.streamContent,
                        created_at: new Date().toISOString()
                    });
                    this.streamContent = '';
                    this.streaming = false;

                    // Check for queued message (ACCODA functionality)
                    if (this.pendingMessage) {
                        const queuedMsg = this.pendingMessage;
                        this.pendingMessage = null;
                        console.log('[chatSidebar] Sending queued message:', queuedMsg.substring(0, 50));
                        setTimeout(() => {
                            this.inputMessage = queuedMsg;
                            this.sendMessage();
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
                    console.error('[chatSidebar] Worker: error:', error);
                    this.showToast('Errore: ' + error, 'error');
                    this.streaming = false;
                    break;

                case 'STREAM_ABORTED':
                    console.log('[chatSidebar] Worker: stream aborted');
                    // If we have partial content, save it
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
                    break;

                case 'STREAM_END':
                    console.log('[chatSidebar] Worker: stream ended');
                    this.streaming = false;
                    break;

                case 'STATE_SYNC':
                    console.log('[chatSidebar] Worker: state sync received', { activeStreams, state });
                    // Restore state if there was an active stream
                    if (state && sessionId === this.activeSession?.id) {
                        if (state.streaming) {
                            this.streaming = true;
                            this.streamContent = state.streamContent || '';
                            this.systemInfo = state.systemInfo || [];
                            console.log('[chatSidebar] Restored active stream state');
                        }
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

            // Skip if same branch
            if (newBranch === this.activeSession.current_branch) return;

            // Confirmation dialog
            if (!confirm(`Sei sicuro di voler cambiare branch e lavorare su "${newBranch}"?`)) {
                // Reset select to current value
                return;
            }

            try {
                const res = await fetch(`/api/cli-chat/sessions/${this.activeSession.id}/branch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ branch: newBranch })
                });

                if (res.ok) {
                    const updated = await res.json();
                    this.activeSession = updated;

                    // Update in sessions list
                    const idx = this.sessions.findIndex(s => s.id === updated.id);
                    if (idx >= 0) {
                        this.sessions[idx] = updated;
                    }

                    this.showToast(`Branch cambiato a ${newBranch}`, 'success');
                } else {
                    const error = await res.text();
                    console.error('[chatSidebar] Failed to change branch:', error);
                    this.showToast('Errore cambio branch', 'error');
                }
            } catch (error) {
                console.error('[chatSidebar] Error changing branch:', error);
                this.showToast('Errore cambio branch', 'error');
            }
        },

        /**
         * Create a new chat session
         */
        async createSession(cliType, repositoryId = null) {
            this.creating = true;
            try {
                const payload = {
                    cli_type: cliType,
                    display_name: cliType === 'claude' ? 'Claude Chat' : 'Gemini Chat',
                    color: cliType === 'claude' ? '#f97316' : '#3b82f6'
                };

                // Add repository context if selected
                if (repositoryId) {
                    payload.repository_id = repositoryId;
                }

                const res = await fetch('/api/cli-chat/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    const session = await res.json();
                    this.sessions.unshift(session);
                    this.selectSession(session);
                    this.showToast('Chat creata', 'success');
                }
            } catch (error) {
                console.error('Error creating session:', error);
                this.showToast('Errore creazione chat', 'error');
            } finally {
                this.creating = false;
            }
        },

        /**
         * Select a session and load its messages
         */
        async selectSession(session) {
            console.log('[selectSession] Loading session:', session.id, session.display_name);
            this.activeSession = session;
            this.messages = [];
            this.showSettings = false;
            this.branches = [];

            // Persist active session ID for cross-page navigation
            localStorage.setItem('chatActiveSessionId', session.id);

            try {
                const url = `/api/cli-chat/sessions/${session.id}/messages`;
                console.log('[selectSession] Fetching:', url);
                const res = await fetch(url);
                console.log('[selectSession] Response status:', res.status);

                if (res.ok) {
                    this.messages = await res.json();
                    console.log('[selectSession] Loaded messages:', this.messages.length);
                    this.$nextTick(() => this.scrollToBottom());
                } else {
                    const errorText = await res.text();
                    console.error('[selectSession] Failed to load messages:', res.status, errorText);
                    this.showToast('Errore caricamento messaggi', 'error');
                }

                // Load branches if session is linked to a repository
                if (session.repository_id) {
                    await this.loadBranches();
                }
            } catch (error) {
                console.error('[selectSession] Error:', error);
                this.showToast('Errore connessione', 'error');
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

                if (res.ok) {
                    // Update in sessions list
                    const updated = await res.json();
                    const idx = this.sessions.findIndex(s => s.id === updated.id);
                    if (idx >= 0) {
                        this.sessions[idx] = updated;
                    }
                }
            } catch (error) {
                console.error('Error updating session:', error);
            }
        },

        /**
         * Delete a session
         * @param {string} sessionId - Session ID to delete
         */
        async deleteSession(sessionId) {
            if (!confirm('Eliminare questa chat?')) return;

            try {
                const res = await fetch(`/api/cli-chat/sessions/${sessionId}`, {
                    method: 'DELETE'
                });

                if (res.ok) {
                    this.sessions = this.sessions.filter(s => s.id !== sessionId);
                    if (this.activeSession?.id === sessionId) {
                        this.activeSession = null;
                        localStorage.removeItem('chatActiveSessionId');
                    }
                    this.showToast('Chat eliminata', 'success');
                }
            } catch (error) {
                console.error('Error deleting session:', error);
                this.showToast('Errore eliminazione', 'error');
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
                console.error('[FORK] Error:', e);
                this.showToast('Errore fork: ' + e.message, 'error');
            } finally {
                this.forkInProgress = false;
            }
        },

        /**
         * Send a message and stream response via SSE
         * Uses SharedWorker if available, falls back to direct fetch
         */
        async sendMessage() {
            if (!this.inputMessage.trim() || !this.activeSession || this.streaming) return;

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
                            const eventType = line.slice(7).trim();
                            console.log('[chatSidebar] SSE event:', eventType);
                            continue;
                        }

                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));

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
                console.error('Error sending message:', error);
                this.showToast('Errore invio messaggio', 'error');
                this.streaming = false;
            } finally {
                this.abortController = null;
            }
        },

        /**
         * Format message content (full markdown support)
         */
        formatMessage(content) {
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

            // Headers (process before other inline elements)
            html = html.replace(/^######\s+(.+)$/gm, '<h6 class="text-xs font-bold mt-3 mb-1 text-gray-600 dark:text-gray-400">$1</h6>');
            html = html.replace(/^#####\s+(.+)$/gm, '<h5 class="text-xs font-bold mt-3 mb-1">$1</h5>');
            html = html.replace(/^####\s+(.+)$/gm, '<h4 class="text-sm font-bold mt-3 mb-1">$1</h4>');
            html = html.replace(/^###\s+(.+)$/gm, '<h3 class="text-sm font-bold mt-4 mb-2 text-gray-800 dark:text-gray-200">$1</h3>');
            html = html.replace(/^##\s+(.+)$/gm, '<h2 class="text-base font-bold mt-4 mb-2 text-gray-900 dark:text-gray-100">$1</h2>');
            html = html.replace(/^#\s+(.+)$/gm, '<h1 class="text-lg font-bold mt-4 mb-2 text-gray-900 dark:text-gray-100">$1</h1>');

            // Blockquotes
            html = html.replace(/^&gt;\s+(.+)$/gm,
                '<blockquote class="border-l-4 border-gray-300 dark:border-gray-600 pl-3 py-1 my-2 text-gray-600 dark:text-gray-400 italic">$1</blockquote>');

            // Horizontal rules
            html = html.replace(/^---+$/gm, '<hr class="my-4 border-gray-300 dark:border-gray-600">');
            html = html.replace(/^\*\*\*+$/gm, '<hr class="my-4 border-gray-300 dark:border-gray-600">');

            // Unordered lists (simple single-level)
            html = html.replace(/^[-*]\s+(.+)$/gm,
                '<li class="ml-4 list-disc text-sm">$1</li>');

            // Ordered lists
            html = html.replace(/^\d+\.\s+(.+)$/gm,
                '<li class="ml-4 list-decimal text-sm">$1</li>');

            // Wrap consecutive list items
            html = html.replace(/(<li class="ml-4 list-disc[^>]*>.*<\/li>\n?)+/g,
                '<ul class="my-2 space-y-1">$&</ul>');
            html = html.replace(/(<li class="ml-4 list-decimal[^>]*>.*<\/li>\n?)+/g,
                '<ol class="my-2 space-y-1">$&</ol>');

            // Links [text](url)
            html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
                '<a href="$2" target="_blank" class="text-blue-500 hover:text-blue-600 dark:text-blue-400 underline">$1</a>');

            // Bold **text** or __text__
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold">$1</strong>');
            html = html.replace(/__([^_]+)__/g, '<strong class="font-semibold">$1</strong>');

            // Italic *text* or _text_
            html = html.replace(/\*([^*]+)\*/g, '<em class="italic">$1</em>');
            html = html.replace(/_([^_]+)_/g, '<em class="italic">$1</em>');

            // Strikethrough ~~text~~
            html = html.replace(/~~([^~]+)~~/g, '<del class="line-through text-gray-500">$1</del>');

            // Line breaks (but not inside pre/code blocks)
            html = html.replace(/\n/g, '<br>');

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
         * Cycle through chat display modes: third → full → page → third
         */
        expandChat() {
            const modes = ['third', 'full', 'page'];
            const idx = modes.indexOf(this.chatMode);
            const newMode = modes[(idx + 1) % modes.length];
            this.chatMode = newMode;

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
            // Check cache first
            if (this.slashCommands[commandName]) {
                return this.slashCommands[commandName];
            }

            try {
                const res = await fetch(`/api/cli-chat/commands/${commandName}`);
                if (res.ok) {
                    const data = await res.json();
                    this.slashCommands[commandName] = data.prompt;
                    return data.prompt;
                } else {
                    console.warn(`[chatSidebar] Slash command /${commandName} not found`);
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
                this.showToast(`Comando /${commandName} non trovato`, 'error');
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
                expandedContent += `\n\nNote aggiuntive: ${additionalArgs}`;
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
                console.error('[LOGS] Error fetching server logs:', error);
                this.showToast(error.message || 'Errore nel recupero dei log', 'error');
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
