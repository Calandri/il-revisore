# CLI Chat System - Implementation Log

**Data:** 2024-12-26
**Obiettivo:** Sistema chat basato su CLI (claude/gemini) invece di SDK

---

## Step 1: Package Base ✅

**File creati:**
- `src/turbowrap/chat_cli/__init__.py`
- `src/turbowrap/chat_cli/models.py`

**Contenuto models.py:**
```python
class CLIType(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"

class SessionStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STREAMING = "streaming"
    STOPPING = "stopping"
    ERROR = "error"
    COMPLETED = "completed"

class StreamEventType(str, Enum):
    START = "start"
    DONE = "done"
    ERROR = "error"
    CHUNK = "chunk"
    THINKING = "thinking"
    STATUS = "status"
    TYPING = "typing"

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class AgentInfo(TypedDict):
    name: str
    version: str
    tokens: int
    description: str
    model: str
    color: str
    path: str

class MCPServerConfig(TypedDict):
    command: str
    args: list[str]
    env: dict[str, str] | None
```

**Decisione:** Package `chat_cli/` invece di `cli/` per evitare conflitto con `cli.py` esistente.

---

## Step 2: Database Models ✅

**File modificato:** `src/turbowrap/db/models.py`

**Aggiunti:**
```python
class CLIChatSession(Base, SoftDeleteMixin):
    __tablename__ = "cli_chat_sessions"

    id = Column(String(36), primary_key=True)
    repository_id = Column(String(36), ForeignKey("repositories.id"), nullable=True)

    # CLI Configuration
    cli_type = Column(String(20), nullable=False)  # "claude" or "gemini"
    model = Column(String(100), nullable=True)
    agent_name = Column(String(100), nullable=True)

    # Claude-specific
    thinking_enabled = Column(Boolean, default=False)
    thinking_budget = Column(Integer, default=8000)

    # Gemini-specific
    reasoning_enabled = Column(Boolean, default=False)

    # MCP
    mcp_servers = Column(JSON, nullable=True)

    # Process State
    process_pid = Column(Integer, nullable=True)
    status = Column(String(20), default="idle")

    # UI
    icon = Column(String(50), default="chat")
    color = Column(String(20), default="#6366f1")
    display_name = Column(String(100), nullable=True)
    position = Column(Integer, default=0)

    # Stats
    total_messages = Column(Integer, default=0)
    total_tokens_in = Column(Integer, default=0)
    total_tokens_out = Column(Integer, default=0)

    # Timestamps
    created_at, updated_at, last_message_at

class CLIChatMessage(Base):
    __tablename__ = "cli_chat_messages"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("cli_chat_sessions.id"))
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    is_thinking = Column(Boolean, default=False)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    model_used = Column(String(100), nullable=True)
    agent_used = Column(String(100), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime)
```

---

## Step 3: Agent Loader ✅

**File creato:** `src/turbowrap/chat_cli/agent_loader.py`

**Classe AgentLoader:**
```python
class AgentLoader:
    def __init__(self, agents_dir: Path | None = None)
    def list_agents(self, reload: bool = False) -> list[AgentInfo]
    def get_agent(self, name: str) -> AgentContent | None
    def get_agent_path(self, name: str) -> Path | None
    def get_agent_instructions(self, name: str) -> str | None

def get_agent_loader() -> AgentLoader  # Singleton
```

**Funzionalità:**
- Parsing YAML frontmatter degli agenti
- Cache in memoria
- 21 agenti trovati in `/agents/`

**Formato agenti:**
```yaml
---
name: fixer
version: "2025-12-25"
tokens: 800
model: claude-opus-4-5-20251101
color: green
---
Markdown instructions...
```

---

## Step 4: CLI Process Manager ✅

**File creato:** `src/turbowrap/chat_cli/process_manager.py`

**Classe CLIProcessManager:**
```python
class CLIProcessManager:
    def __init__(self, max_processes: int = 10)

    async def spawn_claude(
        session_id: str,
        working_dir: Path,
        model: str = "claude-opus-4-5-20251101",
        agent_path: Path | None = None,
        thinking_budget: int | None = None,
        mcp_config: Path | None = None,
    ) -> CLIProcess

    async def spawn_gemini(
        session_id: str,
        working_dir: Path,
        model: str = "gemini-3-pro-preview",
        reasoning: bool = False,
    ) -> CLIProcess

    async def send_message(
        session_id: str,
        message: str,
        timeout: int | None = None,
    ) -> AsyncIterator[str]

    async def terminate(session_id: str) -> bool
    async def terminate_all() -> int
    def get_active_sessions() -> list[str]
    def get_process(session_id: str) -> CLIProcess | None
    def get_status(session_id: str) -> SessionStatus | None

def get_process_manager() -> CLIProcessManager  # Singleton
```

**Pattern CLI:**
```python
# Claude: stdin per prompt, stream-json output
args = ["claude", "--print", "--verbose", "--dangerously-skip-permissions",
        "--model", model, "--output-format", "stream-json"]
# Thinking via env var: MAX_THINKING_TOKENS

# Gemini: prompt come argomento posizionale
args = ["gemini", "-m", model, "--yolo", message]
```

**Timeouts:** Claude 900s, Gemini 120s

---

## Step 5: API Schemas ✅

**File creato:** `src/turbowrap/api/schemas/cli_chat.py`

**Schema principali:**
```python
# Session
CLISessionCreate(cli_type, repository_id, display_name, icon, color)
CLISessionResponse(id, cli_type, status, model, agent_name, thinking_*, mcp_servers, ...)
CLISessionUpdate(display_name, icon, color, model, thinking_*, mcp_servers)
CLISessionSettings(model, agent_name, thinking_enabled, thinking_budget, reasoning_enabled, mcp_servers)

# Messages
CLIMessageCreate(content: str)  # min 1, max 100k
CLIMessageResponse(id, session_id, role, content, is_thinking, tokens_*, model_used, ...)

# Streaming
StreamEvent(type, content, session_id, message_id, metadata)

# Agents
AgentResponse(name, version, tokens, description, model, color, path)
AgentListResponse(agents, total)

# MCP
MCPServerResponse(name, command, args, enabled)
MCPServerCreate(name, command, args)
MCPConfigResponse(servers, config_path)
```

---

## Step 6: API Routes ✅

**File creato:** `src/turbowrap/api/routes/cli_chat.py`

**File modificati:**
- `src/turbowrap/api/routes/__init__.py` - Aggiunto export
- `src/turbowrap/api/main.py` - Registrato router

**Endpoints:**
```
# Sessions
GET    /api/cli-chat/sessions              # Lista sessioni
POST   /api/cli-chat/sessions              # Crea sessione
GET    /api/cli-chat/sessions/{id}         # Dettaglio
PUT    /api/cli-chat/sessions/{id}         # Aggiorna
DELETE /api/cli-chat/sessions/{id}         # Elimina (soft)

# Messages
GET    /api/cli-chat/sessions/{id}/messages  # Lista messaggi
POST   /api/cli-chat/sessions/{id}/message   # Invia (SSE streaming)

# Process Control
POST   /api/cli-chat/sessions/{id}/start   # Avvia CLI
POST   /api/cli-chat/sessions/{id}/stop    # Ferma CLI

# Agents
GET    /api/cli-chat/agents                # Lista agenti
GET    /api/cli-chat/agents/{name}         # Dettaglio agente

# Admin
GET    /api/cli-chat/active                # Processi attivi
POST   /api/cli-chat/terminate-all         # Termina tutti
```

---

## Step 7: MCP Manager ✅

**File creato:** `src/turbowrap/chat_cli/mcp_manager.py`

**Classe MCPManager:**
```python
class MCPManager:
    def __init__(self, base_dir: Path | None = None)
    def list_servers(include_defaults: bool = True) -> list[MCPServer]
    def get_server(name: str) -> MCPServer | None
    def add_server(name, command, args, env) -> bool
    def add_default_server(name: str) -> bool
    def remove_server(name: str) -> bool
    def enable_servers(names: list[str]) -> bool
    def get_config_path(enabled_servers: list[str] | None = None) -> Path | None

def get_mcp_manager() -> MCPManager  # Singleton
```

**Server MCP predefiniti:**
- `linear` - @anthropic/linear-mcp
- `github` - @anthropic/github-mcp
- `filesystem` - @anthropic/filesystem-mcp
- `fetch` - @anthropic/fetch-mcp

**API Endpoints aggiunti:**
```
GET    /api/cli-chat/mcp                    # Config completa
GET    /api/cli-chat/mcp/servers            # Lista server
POST   /api/cli-chat/mcp/servers            # Aggiungi server
POST   /api/cli-chat/mcp/servers/{name}/enable  # Abilita
DELETE /api/cli-chat/mcp/servers/{name}     # Rimuovi
GET    /api/cli-chat/mcp/defaults           # Lista default
```

**Formato config `.claude/mcp.json`:**
```json
{
  "mcpServers": {
    "linear": {
      "command": "npx",
      "args": ["-y", "@anthropic/linear-mcp"]
    }
  }
}
```

**Anomalie:** Nessuna

---

## Step 8: Hooks Integration ✅

**File creato:** `src/turbowrap/chat_cli/hooks.py`

**Classe ChatHooks:**
```python
class ChatHooks:
    def __init__(self, db: Session | None = None)
    def calculate_tokens(content: str) -> dict[str, int]  # chars, lines, words, tokens
    def count_tokens(content: str) -> int
    async def on_message_sent(session_id, content) -> dict  # Input token tracking
    async def on_response_complete(session_id, content, duration_ms, message_id) -> dict
    async def on_session_start(session_id, repo_path, force_regenerate) -> dict
    async def on_tool_use(tool_name, file_path, content) -> dict
```

**HookRegistry per custom hooks:**
```python
register_hook("message_sent", my_async_callback)
await trigger_hooks("message_sent", session_id=..., content=...)
```

**CLI Entry Point:**
```bash
# Usabile come hook command per Claude
python -m turbowrap.chat_cli.hooks token_count "text to count"
python -m turbowrap.chat_cli.hooks post_tool_use Write /path/to/file
```

**Integrazione:**
- Token counting via `tiktoken` (cl100k_base encoding)
- DB update per session stats (total_tokens_in/out)
- STRUCTURE.md regeneration via `StructureGenerator`

**Anomalie:** Nessuna

---

## Step 9: Frontend Sidebar ✅

**File creato:** `src/turbowrap/api/templates/components/chat_sidebar.html`

**Funzionalità:**
- 3 modalità sidebar: `full` (w-96), `third` (w-80), `icons` (w-14)
- Toggle button per passare tra le modalità
- Lista sessioni con icone Claude (arancione) / Gemini (blu)
- Status indicator per ogni sessione (running/idle/error)
- Pulsanti "New Chat" per Claude e Gemini
- FAB button quando sidebar è nascosta

**Integrazione base.html:**
- Aggiunto stato `chatMode` in Alpine.js root
- Margine destro dinamico per main content
- Include del componente `chat_sidebar.html`

**Anomalie:** Nessuna

---

## Step 10: Frontend Chat Panel + JS ✅

**File creato:** `src/turbowrap/api/static/js/cli-chat.js`

**Alpine Component `chatSidebar()`:**
```javascript
// State
sessions: []          // Lista sessioni
activeSession: null   // Sessione attiva
messages: []          // Messaggi sessione corrente
agents: []            // Agenti disponibili
streaming: false      // Flag streaming in corso
streamContent: ''     // Content in streaming

// Methods
init()               // Carica sessions e agents
loadSessions()       // GET /api/cli-chat/sessions
loadAgents()         // GET /api/cli-chat/agents
createSession(type)  // POST /api/cli-chat/sessions
selectSession(s)     // Seleziona e carica messaggi
updateSession()      // PUT /api/cli-chat/sessions/{id}
deleteSession(s)     // DELETE /api/cli-chat/sessions/{id}
sendMessage()        // POST con SSE streaming
formatMessage(txt)   // Markdown → HTML basico
scrollToBottom()     // Auto-scroll chat
```

**Features Chat Panel:**
- Header con back button e settings dropdown
- Settings: model select, agent select, thinking toggle, budget slider
- Messages view con streaming support
- Input textarea con invio Enter
- Markdown rendering basico (code, bold, italic)

**Anomalie:** Nessuna

---

## IMPLEMENTAZIONE COMPLETATA

Tutti i 10 step sono stati completati con successo.

---

## File Creati

```
src/turbowrap/chat_cli/
├── __init__.py
├── models.py
├── agent_loader.py
├── process_manager.py
├── mcp_manager.py
├── hooks.py
├── README.md
└── IMPLEMENTATION_LOG.md

src/turbowrap/api/
├── schemas/cli_chat.py
├── routes/cli_chat.py
├── templates/components/chat_sidebar.html
└── static/js/cli-chat.js
```

## File Modificati

```
src/turbowrap/db/models.py          # +CLIChatSession, +CLIChatMessage
src/turbowrap/api/routes/__init__.py # +cli_chat_router export
src/turbowrap/api/main.py            # +cli_chat_router, +cli-chat.js
src/turbowrap/api/templates/base.html # +chatMode state, +right sidebar
```

---

## Comandi Test

```bash
# Test imports
source .venv/bin/activate
python -c "from turbowrap.chat_cli import CLIType, get_agent_loader, get_process_manager"
python -c "from turbowrap.api.routes.cli_chat import router"

# Run server
uvicorn turbowrap.api.main:app --reload

# Test endpoints
curl http://localhost:8000/api/cli-chat/agents
curl http://localhost:8000/api/cli-chat/sessions
```

---

## Note Tecniche

1. **Extended Thinking Claude:** Via `MAX_THINKING_TOKENS` env var, NON `--settings`
2. **Gemini Reasoning:** `gemini config set reasoning true` (pre-configurato)
3. **Enum Serialization:** `str, Enum` per compatibilità JSON
4. **Process Lifecycle:** Claude usa stdin, Gemini usa argomento posizionale

---

## Fix: Streaming Real-Time (2024-12-27) ✅

### Problema
Lo streaming della chat non funzionava in tempo reale. I chunk arrivavano tutti insieme alla fine invece che carattere per carattere.

### Causa Root
Claude CLI con `--output-format stream-json` da solo **NON** fa streaming token-by-token. Serve il flag `--include-partial-messages`.

### Soluzione

**1. Flag Claude CLI** (`process_manager.py`):
```python
args = [
    "claude",
    "--print",
    "--verbose",
    "--dangerously-skip-permissions",
    "--model", model,
    "--output-format", "stream-json",
    "--include-partial-messages",  # ← QUESTO È IL FLAG CHIAVE!
]
```

**2. Parsing stream_event** (`cli_chat.py`):

Con `--include-partial-messages`, l'output è wrappato in `stream_event`:
```json
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"C"}}}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"i"}}}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"a"}}}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"o"}}}
```

Bisogna unwrappare l'evento:
```python
event = json.loads(line)
event_type = event.get("type", "unknown")

# Unwrap stream_event
if event_type == "stream_event":
    event = event.get("event", {})
    event_type = event.get("type", "unknown")

# Poi parsare content_block_delta
if event_type == "content_block_delta":
    delta = event.get("delta", {})
    if delta.get("type") == "text_delta":
        content = delta.get("text", "")
```

**3. Headers SSE anti-buffering** (`cli_chat.py`):
```python
headers = {
    "X-Accel-Buffering": "no",  # Disable Nginx buffering
    "Cache-Control": "no-cache, no-transform",
}
return EventSourceResponse(event_generator(), headers=headers, ping=15)
```

### Riferimenti
- [GitHub Issue #733 - Streaming output](https://github.com/anthropics/claude-code/issues/733)
- [Claude Code CLI Reference](https://code.claude.com/docs/en/cli-reference)

### Lezione Appresa
> **Sempre controllare la documentazione aggiornata della CLI!**
> I flag cambiano spesso. Il comando `claude --help` è la fonte di verità.
