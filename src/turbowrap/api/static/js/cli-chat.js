/**
 * CLI Chat Alpine.js Components
 *
 * Manages the right sidebar chat interface for Claude/Gemini CLI.
 * Supports:
 * - Multi-chat sessions
 * - SSE streaming
 * - Quick settings (model, agent, thinking)
 * - 3 display modes (full/third/icons)
 */

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

        // NOTE: chatMode is inherited from parent scope (html element x-data)
        // Do NOT define a getter here - it causes infinite recursion!

        /**
         * Initialize component
         */
        async init() {
            console.log('[chatSidebar] Initializing...');
            try {
                await this.loadSessions();
                console.log('[chatSidebar] Sessions loaded:', this.sessions.length);
                await this.loadAgents();
                console.log('[chatSidebar] Agents loaded:', this.agents.length);

                // Restore active session from localStorage
                const savedSessionId = localStorage.getItem('chatActiveSessionId');
                if (savedSessionId && this.sessions.length > 0) {
                    const session = this.sessions.find(s => s.id === savedSessionId);
                    if (session) {
                        console.log('[chatSidebar] Restoring active session:', savedSessionId);
                        await this.selectSession(session);
                    }
                }
            } catch (error) {
                console.error('[chatSidebar] Init error:', error);
            }

            // Poll for session updates every 10s
            setInterval(() => this.loadSessions(), 10000);
        },

        /**
         * Load all chat sessions
         */
        async loadSessions() {
            try {
                console.log('[chatSidebar] Fetching sessions...');
                const res = await fetch('/api/cli-chat/sessions');
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
         * Create a new chat session
         */
        async createSession(cliType) {
            this.creating = true;
            try {
                const res = await fetch('/api/cli-chat/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cli_type: cliType,
                        display_name: cliType === 'claude' ? 'Claude Chat' : 'Gemini Chat',
                        color: cliType === 'claude' ? '#f97316' : '#3b82f6'
                    })
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
         */
        async sendMessage() {
            if (!this.inputMessage.trim() || !this.activeSession || this.streaming) return;

            const content = this.inputMessage.trim();
            this.inputMessage = '';
            this.streaming = true;
            this.streamContent = '';
            this.systemInfo = [];  // Reset system info for new message

            // Create AbortController for cancellation
            this.abortController = new AbortController();

            // Add user message immediately
            const userMsg = {
                id: 'temp-' + Date.now(),
                role: 'user',
                content: content,
                created_at: new Date().toISOString()
            };
            this.messages.push(userMsg);
            this.$nextTick(() => this.scrollToBottom());

            try {
                // Close any existing EventSource
                if (this.eventSource) {
                    this.eventSource.close();
                }

                // Create new EventSource for SSE
                const url = `/api/cli-chat/sessions/${this.activeSession.id}/message`;

                // Use fetch with POST for SSE (EventSource only supports GET)
                const response = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content }),
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
        }
    };
}

// Register globally for Alpine.js
window.chatSidebar = chatSidebar;

// Debug: log when script is loaded
console.log('[cli-chat.js] Script loaded, chatSidebar function registered');
