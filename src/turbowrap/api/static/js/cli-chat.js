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
        eventSource: null,

        // Computed - get chatMode from parent scope
        get chatMode() {
            return Alpine.raw(this.$data)?.chatMode || 'hidden';
        },

        /**
         * Initialize component
         */
        async init() {
            await this.loadSessions();
            await this.loadAgents();

            // Poll for session updates every 10s
            setInterval(() => this.loadSessions(), 10000);
        },

        /**
         * Load all chat sessions
         */
        async loadSessions() {
            try {
                const res = await fetch('/api/cli-chat/sessions');
                if (res.ok) {
                    this.sessions = await res.json();
                }
            } catch (error) {
                console.error('Error loading sessions:', error);
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
            this.activeSession = session;
            this.messages = [];
            this.showSettings = false;

            try {
                const res = await fetch(`/api/cli-chat/sessions/${session.id}/messages`);
                if (res.ok) {
                    this.messages = await res.json();
                    this.$nextTick(() => this.scrollToBottom());
                }
            } catch (error) {
                console.error('Error loading messages:', error);
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
         */
        async deleteSession(session) {
            if (!confirm('Eliminare questa chat?')) return;

            try {
                const res = await fetch(`/api/cli-chat/sessions/${session.id}`, {
                    method: 'DELETE'
                });

                if (res.ok) {
                    this.sessions = this.sessions.filter(s => s.id !== session.id);
                    if (this.activeSession?.id === session.id) {
                        this.activeSession = null;
                    }
                    this.showToast('Chat eliminata', 'success');
                }
            } catch (error) {
                console.error('Error deleting session:', error);
                this.showToast('Errore eliminazione', 'error');
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
                    body: JSON.stringify({ content })
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
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));

                                if (data.content) {
                                    this.streamContent += data.content;
                                    this.$nextTick(() => this.scrollToBottom());
                                }

                                if (data.message_id) {
                                    // Stream complete
                                    this.messages.push({
                                        id: data.message_id,
                                        role: 'assistant',
                                        content: this.streamContent,
                                        created_at: new Date().toISOString()
                                    });
                                    this.streamContent = '';
                                    this.streaming = false;
                                }

                                if (data.error) {
                                    console.error('Stream error:', data.error);
                                    this.showToast('Errore: ' + data.error, 'error');
                                    this.streaming = false;
                                }
                            } catch (e) {
                                // Ignore parse errors for incomplete chunks
                            }
                        }
                    }
                }

            } catch (error) {
                console.error('Error sending message:', error);
                this.showToast('Errore invio messaggio', 'error');
                this.streaming = false;
            }
        },

        /**
         * Format message content (basic markdown support)
         */
        formatMessage(content) {
            if (!content) return '';

            // Escape HTML
            let html = content
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');

            // Code blocks
            html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
                return `<pre class="bg-gray-800 text-gray-100 p-2 rounded text-xs overflow-x-auto my-2"><code>${code.trim()}</code></pre>`;
            });

            // Inline code
            html = html.replace(/`([^`]+)`/g, '<code class="bg-gray-200 dark:bg-gray-600 px-1 rounded text-xs">$1</code>');

            // Bold
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

            // Italic
            html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

            // Line breaks
            html = html.replace(/\n/g, '<br>');

            return html;
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
