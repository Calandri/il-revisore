# Chat CLI System - Development Log

## Obiettivo
Sistema di chat basato su CLI (`claude`/`gemini`) invece di SDK, con supporto per:
- Multi-chat parallele
- Agenti Claude custom
- MCP servers
- Extended thinking

---

## Step Completati

### Step 1: Package Base ✅
**Data:** 2024-12-26
**File creati:**
- `chat_cli/__init__.py` - Package init con exports
- `chat_cli/models.py` - Tipi base (CLIType, SessionStatus, StreamEventType, etc.)

**Decisioni:**
- Package chiamato `chat_cli/` invece di `cli/` per evitare conflitto con `cli.py` esistente (Typer CLI)
- Usati `str, Enum` per compatibilità JSON
- TypedDict per strutture dati complesse (AgentInfo, MCPServerConfig)

**Anomalie:** Nessuna

---

### Step 2: Database Models ✅
**Data:** 2024-12-26
**File modificati:**
- `db/models.py` - Aggiunti CLIChatSession e CLIChatMessage

**Campi CLIChatSession:**
- `cli_type` - "claude" o "gemini"
- `model` - Modello specifico
- `agent_name` - Agente da /agents/
- `thinking_enabled/budget` - Extended thinking Claude
- `reasoning_enabled` - Deep reasoning Gemini
- `mcp_servers` - JSON array MCP attivi
- `status` - idle/starting/running/streaming/stopping/error
- `icon/color/display_name/position` - UI config
- `total_messages/tokens_in/tokens_out` - Stats

**Campi CLIChatMessage:**
- `role` - user/assistant/system
- `is_thinking` - Extended thinking content
- `tokens_in/out` - Token tracking
- `model_used/agent_used/duration_ms` - Metadata

**Anomalie:** Nessuna

**Lessons Learned:**
- Usare venv per test import: `source .venv/bin/activate`

---

### Step 3: Agent Loader ✅
**Data:** 2024-12-26
**File creati:**
- `chat_cli/agent_loader.py` - AgentLoader class con caching

**Funzionalità:**
- `list_agents()` - Lista tutti i 21 agenti disponibili
- `get_agent(name)` - Carica agente specifico con metadata + instructions
- `get_agent_path(name)` - Path assoluto per `--system-prompt-file`
- `get_agent_instructions(name)` - Solo contenuto markdown
- Parsing YAML frontmatter con regex + yaml.safe_load
- Cache in memoria per performance
- Singleton via `get_agent_loader()`

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

**Anomalie:** Nessuna
**Test:** 21 agenti caricati correttamente

---

### Step 4: CLI Process Manager ✅
**Data:** 2024-12-26
**File creati:**
- `chat_cli/process_manager.py` - CLIProcessManager class

**Funzionalità:**
- `spawn_claude()` - Avvia processo Claude con:
  - model, agent_path (--system-prompt-file)
  - thinking_budget (MAX_THINKING_TOKENS env var)
  - mcp_config (--mcp-config)
- `spawn_gemini()` - Crea sessione Gemini (processo per messaggio)
- `send_message()` - AsyncIterator per streaming chunks
- `terminate()` / `terminate_all()` - Gestione lifecycle
- `get_active_sessions()` / `get_process()` / `get_status()`
- Singleton via `get_process_manager()`

**Pattern chiave:**
```python
# Claude: stdin per prompt, stream-json output
process.stdin.write(prompt.encode())
await process.stdin.wait_closed()  # EOF

# Gemini: prompt come argomento posizionale
["gemini", "-m", model, "--yolo", message]
```

**Timeouts:**
- Claude: 900s (15 min per task complessi)
- Gemini: 120s (2 min)

**Anomalie:** Nessuna

---

### Step 5: API Schemas ✅
**Data:** 2024-12-26
**File creati:**
- `api/schemas/cli_chat.py` - Pydantic schemas

**Schema creati:**
- `CLISessionCreate/Response/Update` - CRUD sessioni
- `CLISessionSettings` - Configurazione sessione
- `CLIMessageCreate/Response` - Messaggi
- `StreamEvent` - Eventi SSE streaming
- `AgentResponse/ListResponse` - Agenti
- `MCPServerResponse/Create/ConfigResponse` - MCP servers

**Validazioni:**
- `content`: min 1, max 100k chars
- `thinking_budget`: 1000-50000
- `color`: max 20 chars (hex)

**Anomalie:** Nessuna

---

### Step 6: API Routes ✅
**Data:** 2024-12-26
**File creati/modificati:**
- `api/routes/cli_chat.py` - Tutti gli endpoints
- `api/routes/__init__.py` - Export cli_chat_router
- `api/main.py` - Registrazione router

**Endpoints:**
```
GET    /api/cli-chat/sessions              # Lista sessioni
POST   /api/cli-chat/sessions              # Crea sessione
GET    /api/cli-chat/sessions/{id}         # Dettaglio
PUT    /api/cli-chat/sessions/{id}         # Aggiorna
DELETE /api/cli-chat/sessions/{id}         # Elimina (soft)

GET    /api/cli-chat/sessions/{id}/messages  # Lista messaggi
POST   /api/cli-chat/sessions/{id}/message   # Invia (SSE streaming)

POST   /api/cli-chat/sessions/{id}/start   # Avvia CLI
POST   /api/cli-chat/sessions/{id}/stop    # Ferma CLI

GET    /api/cli-chat/agents                # Lista agenti
GET    /api/cli-chat/agents/{name}         # Dettaglio agente

GET    /api/cli-chat/active                # Processi attivi
POST   /api/cli-chat/terminate-all         # Termina tutti
```

**Anomalie:** Nessuna

---

## Step In Corso

### Step 7: MCP Manager
**Status:** Da iniziare
**File target:** `chat_cli/mcp_manager.py`

---

## Step Pendenti
8. Hooks
9. Frontend Sidebar
10. Frontend Chat Panel

---

## Note Tecniche

### Enum Design
```python
class CLIType(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"
```
Usando `str, Enum` i valori sono serializzabili direttamente in JSON.

### TypedDict vs Pydantic
Per i modelli interni usiamo TypedDict (leggero).
Per gli schema API useremo Pydantic (validazione).

---

## Dipendenze Tra Moduli

```
models.py (base types)
    ↓
agent_loader.py ←── usa AgentInfo
    ↓
process_manager.py ←── usa CLIType, SessionStatus
    ↓
hooks.py ←── usa StreamEventType
    ↓
api/routes/cli_chat.py ←── usa tutto
```

---

## Lessons Learned

1. **Naming conflict:** `cli.py` esistente → usare `chat_cli/`
2. **Enum serialization:** `str, Enum` per JSON compatibility

---

## Comandi Utili

```bash
# Test import
python -c "from turbowrap.chat_cli import CLIType; print(CLIType.CLAUDE.value)"

# Run server
cd src && uvicorn turbowrap.api.main:app --reload
```
