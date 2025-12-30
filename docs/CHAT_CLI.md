# Chat AI CLI - Multi-Agent Chat System

## Overview

Chat AI CLI è il sistema di chat basato su processi CLI (`claude`/`gemini`) invece di SDK.
Supporta multi-chat parallele, agenti custom, MCP servers, extended thinking e comandi rapidi.

**CLI Supportate**: Claude CLI, Gemini CLI
**Agenti**: Custom agents da `/agents/`
**Comandi Rapidi**: Slash commands da `/commands/`

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CHAT UI                                     │
│                    (Sidebar + Chat Panel)                            │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       API Routes                                     │
│                  /api/cli-chat/...                                   │
└─────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌──────────────────┐
│  Agent        │      │  Process          │      │  MCP             │
│  Loader       │      │  Manager          │      │  Manager         │
│               │      │                   │      │                  │
└───────────────┘      └───────────────────┘      └──────────────────┘
        │                          │                          │
        │                          ▼                          │
        │              ┌───────────────────┐                  │
        │              │  CLI Subprocess   │                  │
        │              │  (claude/gemini)  │                  │
        └──────────────┤                   ├──────────────────┘
                       └───────────────────┘
                                   │
                                   ▼
                        ┌───────────────────┐
                        │   SSE Streaming   │
                        │   to Frontend     │
                        └───────────────────┘
```

---

## Workflow

### 1. Creazione Sessione

```json
POST /api/cli-chat/sessions
{
  "cli_type": "claude",
  "repository_id": "uuid",
  "display_name": "My Chat",
  "icon": "chat",
  "color": "#6366f1"
}
```

### 2. Invio Messaggio (SSE Streaming)

```
POST /api/cli-chat/sessions/{id}/message
{
  "content": "Analizza il codice in src/main.py"
}

Response: EventSource stream
├── event: start
├── event: chunk (multiple)
├── event: thinking (Claude extended thinking)
└── event: done
```

### 3. Slash Commands

I messaggi che iniziano con `/` attivano comandi rapidi:

```
/commit     → Analizza l'ultimo commit
/pr         → Crea Pull Request
/review     → Code review
/lint       → Esegue linting
...
```

---

## Database Models

### CLIChatSession
```python
class CLIChatSession(Base):
    id: str                    # UUID
    repository_id: str | None  # FK to repositories (optional)
    current_branch: str | None # Active git branch

    # CLI Configuration
    cli_type: str              # "claude" or "gemini"
    model: str | None          # e.g., "claude-opus-4-5-20251101"
    agent_name: str | None     # Agent da /agents/

    # Claude-specific
    thinking_enabled: bool     # Extended thinking
    thinking_budget: int       # 1000-50000 tokens

    # Gemini-specific
    reasoning_enabled: bool    # Deep reasoning

    # MCP Configuration
    mcp_servers: JSON          # ["linear", "github"]

    # Process State
    process_pid: int | None
    status: str                # idle, starting, running, streaming, stopping, error
    claude_session_id: str | None  # Per --resume

    # UI Configuration
    icon: str                  # Icon identifier
    color: str                 # Hex color
    display_name: str | None
    position: int              # Order in sidebar

    # Stats
    total_messages: int
    total_tokens_in: int
    total_tokens_out: int
```

### CLIChatMessage
```python
class CLIChatMessage(Base):
    id: str
    session_id: str            # FK to cli_chat_sessions
    role: str                  # user, assistant, system
    content: str
    is_thinking: bool          # Extended thinking content
    tokens_in: int | None
    tokens_out: int | None
    model_used: str | None
    agent_used: str | None
    duration_ms: int | None
```

---

## API Endpoints

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cli-chat/sessions` | Lista sessioni |
| POST | `/api/cli-chat/sessions` | Crea sessione |
| GET | `/api/cli-chat/sessions/{id}` | Dettaglio |
| PUT | `/api/cli-chat/sessions/{id}` | Aggiorna |
| DELETE | `/api/cli-chat/sessions/{id}` | Elimina (soft) |
| POST | `/api/cli-chat/sessions/{id}/fork` | Fork sessione |

### Messages

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cli-chat/sessions/{id}/messages` | Lista messaggi |
| POST | `/api/cli-chat/sessions/{id}/message` | Invia (SSE) |

### Process Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/cli-chat/sessions/{id}/start` | Avvia CLI |
| POST | `/api/cli-chat/sessions/{id}/stop` | Ferma CLI |
| GET | `/api/cli-chat/active` | Processi attivi |
| POST | `/api/cli-chat/terminate-all` | Termina tutti |

### Branch Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cli-chat/sessions/{id}/branches` | Lista branch |
| POST | `/api/cli-chat/sessions/{id}/branch` | Cambia branch |

### Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cli-chat/agents` | Lista agenti |
| GET | `/api/cli-chat/agents/{name}` | Dettaglio agente |

---

## SSE Events

| Event | Description | Data |
|-------|-------------|------|
| `start` | Stream iniziato | `{session_id}` |
| `chunk` | Chunk di testo | `{content}` |
| `thinking` | Extended thinking (Claude) | `{content}` |
| `done` | Stream completato | `{message_id, tokens_in, tokens_out}` |
| `error` | Errore | `{error, message}` |

---

## Process Manager

Il `CLIProcessManager` gestisce i processi CLI:

```python
manager = CLIProcessManager(max_processes=10)

# Spawn Claude
proc = await manager.spawn_claude(
    session_id="abc123",
    working_dir=Path("/path/to/repo"),
    model="claude-opus-4-5-20251101",
    agent_path=Path("/path/to/agent.md"),
    thinking_budget=10000,
    mcp_config=Path("/path/to/mcp.json"),
)

# Send message (streaming)
async for chunk in manager.send_message("abc123", "Hello"):
    print(chunk, end="")

# Terminate
await manager.terminate("abc123")
```

### Timeouts
```python
CLAUDE_TIMEOUT = 900   # 15 minuti (task complessi)
GEMINI_TIMEOUT = 120   # 2 minuti
STALE_PROCESS_HOURS = 3  # Kill processi > 3 ore
```

### CLI Commands

**Claude:**
```bash
claude \
  --model claude-opus-4-5-20251101 \
  --system-prompt-file /path/to/agent.md \
  --mcp-config /path/to/mcp.json \
  --resume <session_id>
```

**Gemini:**
```bash
gemini \
  -m gemini-3-pro-preview \
  --yolo \
  "Your message here"
```

---

## Agent Loader

Carica agenti da `/agents/*.md`:

```python
loader = get_agent_loader()

# Lista tutti gli agenti
agents = loader.list_agents()

# Carica agente specifico
agent = loader.get_agent("fixer")
# Returns: {name, version, tokens, model, color, instructions}

# Path per --system-prompt-file
path = loader.get_agent_path("fixer")
```

### Formato Agent

```yaml
---
name: fixer
version: "2025-12-25"
tokens: 800
model: claude-opus-4-5-20251101
color: green
---

# Agent Instructions

Markdown content with instructions for the agent...
```

---

## Slash Commands (Comandi Rapidi)

I comandi sono definiti in `/commands/*.md`:

| Comando | Descrizione |
|---------|-------------|
| `/commit` | Analizza ultimo commit |
| `/pr` | Crea Pull Request |
| `/review` | Code review del branch |
| `/lint` | Esegue linting |
| `/test` | Esegue test |
| `/format` | Formatta codice |
| `/merge` | Merge branch |
| `/branch` | Gestione branch |
| `/modified` | File modificati |
| `/deploy` | Deploy |
| `/refactor` | Refactoring suggerimenti |
| `/frontend` | Analisi frontend |
| `/backend` | Analisi backend |
| `/mockup` | Genera UI mockup |
| `/mockup_modify` | Modifica mockup |
| `/create-issue` | Crea issue da errore |
| `/help-error` | Help per errore specifico |
| `/create_test` | Crea TurboWrap test |

### Struttura Comando

```markdown
# /commit - Last Commit Analysis

Analyze the last commit on the current branch.

## Analysis Steps

### Step 1: Get Commit Info
```bash
git log -1 --format="%H%n%an%n%s"
```

### Step 2: Get Changed Files
```bash
git diff-tree --no-commit-id --name-status -r HEAD
```

...

## Response Format

```markdown
## Analisi Ultimo Commit
| Campo | Valore |
|-------|--------|
| Hash | `abc1234` |
...
```

**IMPORTANT: Respond in Italian.**
```

---

## Title Generation

Il sistema genera automaticamente titoli per le chat:

1. **Prima risposta**: Dopo il primo messaggio assistant
2. **Chiamata a CLI**: `claude --print -p "Generate title..."`
3. **Risultato**: Titolo 3 parole salvato come `display_name`

```python
title = await generate_chat_title(
    cli_type="claude",
    user_message="...",
    assistant_response="...",
)
# Returns: "Login Feature Implementation"
```

---

## Fork Session

Le sessioni possono essere "forked":

1. **Copia settings**: model, agent, thinking, MCP
2. **Copia messaggi**: Tutti i messaggi duplicati
3. **Claude resume**: Condivide `claude_session_id` per `--resume`

```
POST /api/cli-chat/sessions/{id}/fork

Response:
{
  "id": "new-session-uuid",
  "display_name": "Original Chat (fork)",
  ...
}
```

---

## Branch Management

Le sessioni collegate a repository supportano:

1. **List branches**: `git branch -a` dal repository
2. **Change branch**: `git checkout <branch>`
3. **Auto-restart**: CLI terminato e riavviato con nuovo branch

```
POST /api/cli-chat/sessions/{id}/branch
{
  "branch": "feature/my-feature"
}
```

---

## Extended Thinking (Claude)

Claude supporta "extended thinking" per ragionamento complesso:

```python
session.thinking_enabled = True
session.thinking_budget = 10000  # 1000-50000 tokens
```

**Funzionamento:**
1. Budget impostato via `MAX_THINKING_TOKENS` env var
2. Thinking content marcato con `is_thinking=True`
3. UI può mostrare/nascondere thinking

---

## MCP Servers

Model Context Protocol per integrazioni:

```python
session.mcp_servers = ["linear", "github"]
```

**Configurazione:**
- Config JSON generato dinamicamente
- Passato a Claude via `--mcp-config`
- Servers disponibili: linear, github, etc.

---

## Configuration

### Models Default

```python
# Claude
DEFAULT_CLAUDE_MODEL = "claude-opus-4-5-20251101"

# Gemini
DEFAULT_GEMINI_MODEL = "gemini-3-pro-preview"
```

### Process Limits

```python
MAX_PROCESSES = 10  # Processi paralleli max
MAX_MESSAGE_LENGTH = 100_000  # Caratteri per messaggio
```

### Session Status

```python
class SessionStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STREAMING = "streaming"
    STOPPING = "stopping"
    ERROR = "error"
```

---

## Context Injection

Quando la sessione è collegata a un repository:

1. **STRUCTURE.md** caricato se esiste
2. **Branch context** aggiunto al prompt
3. **Repository path** usato come working dir

```python
context = get_context_for_session(session)
# Returns context string with repo info
```

---

## Best Practices

### Per gli Utenti

1. **Usa slash commands** - Più veloci e strutturati
2. **Collega a repository** - Per context automatico
3. **Abilita thinking** - Per task complessi
4. **Fork sessions** - Per esplorare alternative

### Per lo Sviluppo

1. **Timeout appropriati** - Claude ha task lunghi
2. **Cleanup processi** - Kill stale dopo 3 ore
3. **Streaming** - Sempre SSE per UX migliore

---

## Troubleshooting

### Chat non risponde

1. Verifica processo attivo: `GET /api/cli-chat/active`
2. Termina e riavvia: `POST /terminate-all`
3. Controlla logs per errori

### Slash command non funziona

1. Verifica che il comando esista in `/commands/`
2. Controlla syntax nel file .md
3. Verifica context repository se richiesto

### Extended thinking non visibile

1. Verifica `thinking_enabled=True` sulla sessione
2. Verifica `include_thinking=True` nella query messages
3. UI potrebbe filtrare by default

### Fork non condivide context

1. Verifica che `claude_session_id` sia impostato
2. Il fork deve essere fatto con processo attivo
3. Usa `--resume` per continuare conversazione
