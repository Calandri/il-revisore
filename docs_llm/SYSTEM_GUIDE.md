# TurboWrap - Guida Sistema Completa per AI

Questa guida contiene tutte le informazioni necessarie per comprendere e operare su TurboWrap.

---

## 1. OVERVIEW

### Cos'è TurboWrap
Orchestratore AI per code review e fixing automatico di repository GitHub.
Usa dual-LLM pattern (Claude + Gemini) per validazione iterativa.

### Stack Tecnologico
- **Backend**: Python 3.12, FastAPI, SQLAlchemy, Alembic
- **Frontend**: Jinja2 templates, HTMX, Alpine.js, TailwindCSS
- **Database**: SQLite (locale) / MySQL (produzione)
- **AI**: Claude CLI, Gemini CLI, Claude SDK
- **Deploy**: Docker, AWS ECR, EC2

### Struttura Progetto
```
src/turbowrap/
├── api/              # FastAPI app
│   ├── routes/       # Endpoints REST + HTMX
│   ├── templates/    # Jinja2 templates
│   │   ├── pages/    # Pagine complete
│   │   └── components/  # Parti riutilizzabili
│   ├── schemas/      # Pydantic models
│   └── services/     # Business logic
├── chat_cli/         # Gestione CLI processes
├── db/               # SQLAlchemy models
│   └── models/       # Modelli per dominio
├── fix/              # Fix orchestrator
├── review/           # Review orchestrator
├── linear/           # Linear.app integration
└── utils/            # Utilities (git, file, tokens)

agents/               # Agent prompts (.md)
docs/                 # Documentazione dettagliata
docs_llm/             # Documentazione ottimizzata per LLM
```

---

## 2. PAGINE E FUNZIONALITÀ

### 2.1 Dashboard (`/`)

**Scopo**: Overview generale del sistema

**Cosa vede l'utente**:
- Statistiche globali (repository, issues, tasks)
- Repository recenti con stato
- Tasks in corso
- Quick actions

**Azioni disponibili**:
- Navigare alle sezioni principali
- Vedere stato sistema

**Endpoints usati**:
- `GET /api/status` - Stato sistema
- `GET /api/repos` - Lista repo recenti
- `GET /api/tasks` - Tasks attivi

---

### 2.2 Repositories (`/repositories`)

**Scopo**: Gestione repository GitHub clonati

**Cosa vede l'utente**:
- Lista repository con filtri per project_name
- Card per ogni repo con: nome, tipo, ultimo sync, stato
- Azioni inline: sync, review, delete

**Azioni disponibili**:
- **Aggiungere repository**: Modal con URL GitHub, auto-clone
- **Sync**: Pull latest changes da remote
- **Code Review**: Lancia review multi-agente
- **Eliminare**: Soft delete

**Modal "Aggiungi Repository"**:
- Campo URL GitHub (es: https://github.com/owner/repo)
- Selezione project_name (opzionale)
- Selezione tipo: backend/frontend/fullstack
- Auto-detect del tipo basato su file presenti

**Endpoints**:
```
GET    /api/repos                    # Lista tutti
POST   /api/repos                    # Crea + clone
GET    /api/repos/{id}               # Dettaglio singolo
PUT    /api/repos/{id}               # Aggiorna metadati
DELETE /api/repos/{id}               # Soft delete
POST   /api/repos/{id}/sync          # Git pull
POST   /api/repos/{id}/review        # Avvia code review
GET    /api/repos/{id}/branches      # Lista branch git
POST   /api/repos/{id}/checkout      # Cambia branch
```

**Database Model - Repository**:
```python
Repository(
    id: str,                    # UUID
    name: str,                  # "owner/repo"
    url: str,                   # GitHub URL
    local_path: str,            # Path locale clonato
    default_branch: str,        # "main"
    last_synced_at: datetime,   # Ultimo sync
    status: str,                # active/syncing/error
    repo_type: str,             # backend/frontend/fullstack
    project_name: str,          # Raggruppamento progetti
    workspace_path: str,        # Per monorepo: subfolder
    test_analysis: JSON,        # Analisi AI test suites
    readme_analysis: JSON,      # Analisi AI README
)
```

---

### 2.3 Issues (`/issues`)

**Scopo**: Gestione issue trovate dal code review

**Cosa vede l'utente**:
- Lista issue con filtri: repository, severity, status, category
- Badge colorati per severity (CRITICAL=rosso, HIGH=arancione, etc.)
- Checkbox per selezione batch
- Contatori per status

**Azioni disponibili**:
- **Filtrare**: Per repo, severity, status, category
- **Selezionare**: Checkbox per batch operations
- **Vedere dettaglio**: Click su issue apre drawer
- **Cambiare status**: OPEN → IN_PROGRESS → SOLVED/IGNORED/WONT_FIX
- **Avviare fix**: Seleziona issue → "Fix Selezionate"
- **Ignorare**: Marca come IGNORED con nota

**Drawer "Dettaglio Issue"**:
- Titolo e descrizione completa
- File e linea con link
- Codice attuale (syntax highlight)
- Fix suggerito
- Storico commenti (stile Linear)
- Bottone "Avvia Fix" per singola issue

**Modal "Fix Batch"**:
- Lista issue selezionate
- Stima workload (effort × files)
- Scelta branch target
- Opzioni: dry-run, auto-commit

**Endpoints**:
```
GET    /api/issues                   # Lista con filtri
GET    /api/issues/{id}              # Dettaglio
PUT    /api/issues/{id}              # Aggiorna (status, note)
POST   /api/issues/{id}/comment      # Aggiungi commento
DELETE /api/issues/{id}              # Soft delete
POST   /api/fix/start                # Avvia fixing batch
GET    /api/fix/status/{task_id}     # Stato fix in corso
```

**Database Model - Issue**:
```python
Issue(
    id: str,
    task_id: str,                 # Task che l'ha creata
    repository_id: str,

    # Identificazione
    issue_code: str,              # "BE-CRIT-001"
    severity: str,                # CRITICAL/HIGH/MEDIUM/LOW/INFO
    category: str,                # security/performance/architecture/...
    rule: str,                    # Regola linting se applicabile

    # Localizzazione
    file: str,                    # Path relativo
    line: int,                    # Linea inizio
    end_line: int,                # Linea fine

    # Contenuto
    title: str,
    description: text,
    current_code: text,           # Snippet codice attuale
    suggested_fix: text,          # Fix suggerito dall'AI
    references: JSON,             # Link a docs
    flagged_by: JSON,             # Agenti che l'hanno segnalata
    comments: JSON,               # Thread discussione

    # Workload
    estimated_effort: int,        # 1-5 scale
    estimated_files_count: int,

    # Status workflow
    status: str,                  # OPEN/IN_PROGRESS/SOLVED/IGNORED/WONT_FIX
    is_active: bool,              # In development attivo
    resolution_note: text,
    resolved_at: datetime,

    # Fix results (dopo fix)
    fix_code: text,               # Codice fixato
    fix_explanation: text,        # Spiegazione PR-style
    fix_files_modified: JSON,     # Lista file
    fix_commit_sha: str,          # SHA commit
    fix_branch: str,              # Branch del fix
    fix_self_score: int,          # Auto-valutazione 0-100
    fix_gemini_score: int,        # Challenger score 0-100
    fixed_at: datetime,
    fixed_by: str,                # "fixer_claude"
)
```

**Severity Levels**:
- `CRITICAL`: Vulnerabilità sicurezza, data loss
- `HIGH`: Bug gravi, performance critiche
- `MEDIUM`: Bug minori, code quality
- `LOW`: Best practices, minor issues
- `INFO`: Suggerimenti, miglioramenti opzionali

**Status Workflow**:
```
OPEN → IN_PROGRESS → SOLVED
                  → IGNORED (con nota)
                  → WONT_FIX (con nota)
```

---

### 2.4 Tests (`/tests`)

**Scopo**: Gestione test suites e TurboWrapTest

**Cosa vede l'utente**:
- Tab "Classic Tests" / "TurboWrapperAI"
- Lista test suites per repository
- Stats: total tests, pass rate, coverage
- Ultima run con stato

**Tab "Classic Tests"**:
- Griglia test suites auto-discovered
- Filtro per repository e framework
- Card con: nome, path, framework, test count, last run status

**Tab "TurboWrapperAI"**:
- Griglia TurboWrapTest files (da `turbowrap_tests/`)
- Card con: nome, descrizione, CLI type, timeout
- Azioni: View, AI Edit

**Drawer "Suite Details"** (click su suite):
- Nome e descrizione
- Path e framework
- Test count e coverage
- Lista ultime runs
- Bottone "Esegui Tests"
- Bottone "Analizza con AI"
- Bottone "Genera Nuovi Test" (apre chat con test_creator agent)

**Modal "Esegui Tests"**:
- Selezione database connection (opzionale)
- Opzioni: coverage, verbose, filter
- Preview comando

**Modal "TurboWrapTest View/Edit"**:
- Toggle Preview/Edit
- Editor markdown con syntax highlight
- Bottone Salva

**Azioni disponibili**:
- **Eseguire suite**: Classic test run con pytest/jest/etc.
- **Analizzare con AI**: Genera analisi della suite
- **Creare TurboWrapTest**: Usa agent test_creator
- **Vedere/Editare TurboWrapTest**: Modal con editor

**Endpoints**:
```
# Test Suites
GET    /api/tests/suites                           # Lista suites
GET    /api/tests/suites/{id}                      # Dettaglio suite
POST   /api/tests/suites/{id}/run                  # Esegui suite
POST   /api/tests/suites/{id}/analyze              # Analisi AI
GET    /api/tests/suites/{id}/runs                 # Lista runs

# Test Runs
GET    /api/tests/runs/{id}                        # Dettaglio run
GET    /api/tests/runs/{id}/cases                  # Test cases della run

# TurboWrapTest
GET    /api/tests/turbowrap-tests/{repo_id}        # Lista files
GET    /api/tests/turbowrap-tests/{repo_id}/{name} # Contenuto file
PUT    /api/tests/turbowrap-tests/{repo_id}/{name} # Salva file
```

**Database Models**:
```python
TestSuite(
    id: str,
    repository_id: str,
    name: str,                    # "API Integration Tests"
    path: str,                    # "tests/api/"
    description: text,
    type: str,                    # classic/ai_analysis/ai_generation
    framework: str,               # pytest/playwright/vitest/jest/cypress
    command: str,                 # Custom command
    config: JSON,                 # Framework config
    ai_analysis: JSON,            # Risultati analisi AI
    test_count: int,
    is_auto_discovered: bool,
)

TestRun(
    id: str,
    suite_id: str,
    repository_id: str,
    task_id: str,
    database_connection_id: str,  # DB usato per test
    status: str,                  # pending/running/passed/failed/error
    branch: str,
    commit_sha: str,
    duration_seconds: float,
    total_tests: int,
    passed: int,
    failed: int,
    skipped: int,
    errors: int,
    coverage_percent: float,
    report_data: JSON,
    ai_analysis: JSON,
    error_message: text,
)

TestCase(
    id: str,
    run_id: str,
    name: str,                    # "test_user_login"
    class_name: str,              # "TestAuthModule"
    file: str,
    line: int,
    status: str,                  # passed/failed/skipped/error
    duration_ms: int,
    error_message: text,
    stack_trace: text,
    ai_suggestion: text,
)
```

---

### 2.5 Linear Issues (`/linear`)

**Scopo**: Integrazione con Linear.app per issue tracking

**Cosa vede l'utente**:
- Lista issue importate da Linear
- Filtri: team, stato TurboWrap, stato Linear
- Card con: identifier, titolo, priority, assignee, stato
- Badge stato TurboWrap colorato

**Stati TurboWrap**:
```
analysis → repo_link → in_progress → in_review → merged
```

**Drawer "Dettaglio Issue"**:
- Titolo e descrizione originale
- Descrizione migliorata (se analizzata)
- Link a Linear
- Repository collegati
- Analisi AI (se presente)
- Bottoni azione per stato

**Azioni per stato**:
- `analysis`: "Analizza" → genera domande AI
- `repo_link`: "Collega Repo" → seleziona repository
- `in_progress`: "Completa" → marca come in_review
- `in_review`: "Approva" → marca come merged
- `merged`: Nessuna azione

**Modal "Analisi AI"**:
- Fase 1: Genera 5-10 domande di chiarimento
- Fase 2: Utente risponde, AI analizza in profondità
- Output: Descrizione migliorata, summary, suggerimenti

**Modal "Collega Repository"**:
- Lista repository disponibili
- Multi-select
- Conferma linking

**Endpoints**:
```
GET    /api/linear/issues                    # Lista
GET    /api/linear/issues/{id}               # Dettaglio
POST   /api/linear/issues/{id}/analyze       # Avvia analisi
POST   /api/linear/issues/{id}/link-repo     # Collega repo
PUT    /api/linear/issues/{id}/state         # Cambia stato
POST   /api/linear/issues/{id}/sync          # Sync da Linear
POST   /api/linear/sync                      # Sync tutte
```

**Database Models**:
```python
LinearIssue(
    id: str,

    # Linear metadata
    linear_id: str,               # Linear UUID
    linear_identifier: str,       # "TEAM-123"
    linear_url: str,
    linear_team_id: str,
    linear_team_name: str,

    # Content
    title: str,
    description: text,            # Originale
    improved_description: text,   # AI-migliorata

    # Metadata
    assignee_id: str,
    assignee_name: str,
    priority: int,                # 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low
    labels: JSON,                 # [{name, color}]

    # Workflow
    turbowrap_state: str,         # analysis/repo_link/in_progress/in_review/merged
    linear_state_id: str,
    linear_state_name: str,
    is_active: bool,              # Max 1 attiva

    # Analysis
    analysis_summary: text,
    user_answers: JSON,           # Risposte a domande
    analyzed_at: datetime,

    # Development
    task_id: str,
    fix_commit_sha: str,
    fix_branch: str,
    fix_explanation: text,
    fix_files_modified: JSON,
)

LinearIssueRepositoryLink(
    id: str,
    linear_issue_id: str,
    repository_id: str,
    link_source: str,             # label/manual/claude_analysis
    source_label: str,
    confidence_score: float,      # 0-100
)
```

---

### 2.6 Live Tasks (`/live-tasks`)

**Scopo**: Monitoraggio processi in esecuzione

**Cosa vede l'utente**:
- Lista operazioni attive
- Card per ogni operazione con: tipo, repo, durata, progress
- Streaming output in tempo reale
- Indicatori: spinner per running, check per completed

**Tipi operazione**:
- `review`: Code review in corso
- `fix`: Fixing batch
- `fix_issue`: Fix singola issue
- `fix_clarification`: Chiarimento pre-fix
- `git_*`: Operazioni git
- `linear_*`: Operazioni Linear
- `test_*`: Esecuzione test

**Dettaglio operazione** (espandi):
- Output streaming in tempo reale
- Progress bar se disponibile
- Log completo
- Bottone "Annulla" se cancellabile

**Endpoints**:
```
GET    /api/operations                       # Lista attive
GET    /api/operations/{id}                  # Dettaglio
GET    /api/operations/{id}/stream           # SSE streaming
DELETE /api/operations/{id}                  # Annulla
GET    /api/tasks/{id}/stream                # Task streaming (legacy)
```

**Database Model - Operation**:
```python
Operation(
    id: str,
    operation_type: str,          # review/fix/git_push/...
    status: str,                  # in_progress/completed/failed/cancelled
    repository_id: str,
    repository_name: str,         # Cached
    branch_name: str,
    user_name: str,
    parent_session_id: str,       # Per gerarchie
    details: JSON,                # Dati specifici operazione
    result: JSON,                 # Risultato finale
    error: text,                  # Errore se fallita
    started_at: datetime,
    completed_at: datetime,
    duration_seconds: float,
)
```

---

### 2.7 Chat CLI (`/chat` o sidebar)

**Scopo**: Chat interattiva con Claude/Gemini CLI

**Cosa vede l'utente**:
- Sidebar con lista sessioni chat
- Ogni sessione: icona, nome, ultimo messaggio
- Chat area con messaggi
- Input area con opzioni

**Sidebar sessioni**:
- Icona colorata per tipo (claude=arancione, gemini=blu)
- Nome sessione (generato AI o custom)
- Preview ultimo messaggio
- Badge per messaggi non letti
- Drag & drop per riordinare
- Context menu: rinomina, elimina

**Chat area**:
- Messaggi alternati user/assistant
- Syntax highlighting per code
- Extended thinking (collapsible)
- Timestamp e durata
- Copy button su code blocks

**Input area**:
- Textarea auto-resize
- Bottone invio
- Menu opzioni (gear icon)

**Menu opzioni chat**:
- Selezione modello (opus, sonnet, haiku / pro, flash)
- Toggle Extended Thinking (Claude)
- Toggle Reasoning (Gemini)
- Selezione Agent (da /agents/)
- MCP servers attivi
- Repository collegato
- Branch attivo

**Modal "Nuova Chat"**:
- Selezione CLI: Claude / Gemini
- Selezione repository (opzionale)
- Selezione agent (opzionale)
- Nome custom (opzionale)

**Azioni disponibili**:
- **Creare sessione**: Nuova chat con config
- **Inviare messaggio**: Streaming response
- **Cambiare config**: Modello, thinking, agent
- **Collegare repo**: Per context
- **Eliminare sessione**: Con conferma

**Comandi slash supportati**:
- `/review` - Avvia code review
- `/fix` - Avvia fixing
- `/create_test` - Crea TurboWrapTest
- Altri definiti in `/commands/`

**Endpoints**:
```
# Sessions
GET    /api/cli-chat/sessions                    # Lista
POST   /api/cli-chat/sessions                    # Crea
GET    /api/cli-chat/sessions/{id}               # Dettaglio
PUT    /api/cli-chat/sessions/{id}               # Aggiorna
DELETE /api/cli-chat/sessions/{id}               # Elimina

# Messages
POST   /api/cli-chat/sessions/{id}/message       # Invia (SSE)
GET    /api/cli-chat/sessions/{id}/messages      # Lista

# Agents
GET    /api/cli-chat/agents                      # Lista disponibili
GET    /api/cli-chat/agents/{name}               # Dettaglio

# Utils
POST   /api/cli-chat/sessions/{id}/stop          # Ferma streaming
POST   /api/cli-chat/sessions/{id}/resume        # Riprendi sessione
```

**Database Models**:
```python
CLIChatSession(
    id: str,
    repository_id: str,           # Repo collegato (opzionale)
    current_branch: str,          # Branch attivo

    # Config CLI
    cli_type: str,                # claude/gemini
    model: str,                   # claude-opus-4-5-20251101, etc.
    agent_name: str,              # Agent da /agents/

    # Claude settings
    thinking_enabled: bool,
    thinking_budget: int,         # 1000-50000 tokens

    # Gemini settings
    reasoning_enabled: bool,

    # MCP
    mcp_servers: JSON,            # ["linear", "github"]

    # Process
    process_pid: int,
    status: str,                  # idle/starting/running/streaming/stopping/error
    claude_session_id: str,       # Per --resume

    # UI
    icon: str,
    color: str,                   # Hex
    display_name: str,
    position: int,                # Ordine sidebar

    # Stats
    total_messages: int,
    total_tokens_in: int,
    total_tokens_out: int,
)

CLIChatMessage(
    id: str,
    session_id: str,
    role: str,                    # user/assistant/system
    content: text,
    is_thinking: bool,            # Extended thinking content
    tokens_in: int,
    tokens_out: int,
    model_used: str,
    agent_used: str,
    duration_ms: int,
)
```

---

### 2.8 Mockups (`/mockups`)

**Scopo**: Generazione mockup HTML con AI

**Cosa vede l'utente**:
- Lista progetti mockup
- Card per ogni progetto: nome, count mockup, design system
- Preview thumbnail

**Drawer "Progetto"**:
- Lista mockup del progetto
- Thumbnail preview
- Azioni: preview, edit, delete

**Modal "Nuovo Progetto"**:
- Nome progetto
- Design system (tailwind/bootstrap/custom)
- Descrizione

**Preview mockup**:
- iFrame con HTML generato
- Responsive controls (mobile/tablet/desktop)
- Bottone "Apri in nuova tab"
- Bottone "Esporta HTML"

**Workflow generazione**:
1. Utente descrive UI in chat
2. AI genera HTML con stili inline
3. Salva come mockup nel progetto
4. Preview e iterazione

**Endpoints**:
```
GET    /api/mockups/projects                 # Lista progetti
POST   /api/mockups/projects                 # Crea progetto
GET    /api/mockups/projects/{id}            # Dettaglio
PUT    /api/mockups/projects/{id}            # Aggiorna
DELETE /api/mockups/projects/{id}            # Elimina

GET    /api/mockups/projects/{id}/mockups    # Lista mockup
POST   /api/mockups/projects/{id}/mockups    # Crea mockup
GET    /api/mockups/{id}                     # Dettaglio mockup
PUT    /api/mockups/{id}                     # Aggiorna
DELETE /api/mockups/{id}                     # Elimina
GET    /api/mockups/{id}/preview             # HTML preview
```

---

### 2.9 Live View (`/live-view`)

**Scopo**: Development server per frontend

**Cosa vede l'utente**:
- iFrame con app frontend
- Console log panel
- Bottoni: refresh, open in new tab
- Stato server: running/stopped

**Funzionalità**:
- Hot reload automatico
- Console logs streaming
- Screenshot capture
- Multiple ports support

**Endpoints**:
```
POST   /api/live-view/start                  # Avvia server
POST   /api/live-view/stop                   # Ferma server
GET    /api/live-view/status                 # Stato
GET    /api/live-view/logs                   # Logs streaming
POST   /api/live-view/screenshot             # Cattura screenshot
```

---

### 2.10 Files (`/files`)

**Scopo**: Editor file integrato

**Cosa vede l'utente**:
- File tree sidebar
- Editor area con tabs
- Syntax highlighting
- Git diff view

**File tree**:
- Navigazione folder
- Icone per tipo file
- Search/filter
- Context menu: rename, delete, new file

**Editor**:
- Multiple tabs
- Syntax highlight (Monaco-based)
- Line numbers
- Find/replace
- Git blame (inline)

**Azioni disponibili**:
- **Navigare**: Click su folder/file
- **Editare**: Modifica con syntax highlight
- **Salvare**: Ctrl+S o bottone
- **Diff**: Mostra modifiche vs HEAD
- **Commit**: Commit modifiche locali

**Endpoints**:
```
GET    /api/repos/{id}/files                 # Lista root
GET    /api/repos/{id}/files/{path}          # Contenuto file
PUT    /api/repos/{id}/files/{path}          # Salva file
DELETE /api/repos/{id}/files/{path}          # Elimina
POST   /api/repos/{id}/files                 # Crea file
GET    /api/repos/{id}/files/{path}/diff     # Git diff
```

---

### 2.11 Settings (`/settings`)

**Scopo**: Configurazione sistema

**Tab "General"**:
- Nome istanza
- Tema (light/dark/auto)
- Lingua

**Tab "API Keys"**:
- ANTHROPIC_API_KEY
- GOOGLE_API_KEY / GEMINI_API_KEY
- GITHUB_TOKEN
- LINEAR_API_KEY

**Tab "Databases"**:
- Lista database connections
- Form: host, port, user, password, database
- Test connection

**Tab "MCP Servers"**:
- Lista server MCP attivi
- Toggle enable/disable
- Configurazione per server

**Tab "Agents"**:
- Lista agenti da /agents/
- Preview contenuto
- Edit (apre in Files)
- Diagram (genera Mermaid)

**Endpoints**:
```
GET    /api/settings                         # Tutte le settings
PUT    /api/settings/{key}                   # Aggiorna singola
GET    /api/settings/agents                  # Lista agenti
GET    /api/settings/mcp-servers             # Lista MCP

# Database Connections
GET    /api/databases                        # Lista
POST   /api/databases                        # Crea
PUT    /api/databases/{id}                   # Aggiorna
DELETE /api/databases/{id}                   # Elimina
POST   /api/databases/{id}/test              # Test connection
```

---

## 3. FLOWS E PROCESSI

### 3.1 Code Review Flow

```
1. Utente seleziona repository
2. Click "Review" → POST /api/tasks
3. Sistema crea Task(type="review")
4. Orchestrator rileva repo_type (BE/FE/Fullstack)
5. Lancia reviewer agents in parallelo:
   - BE: reviewer_be_architecture, reviewer_be_quality
   - FE: reviewer_fe_architecture, reviewer_fe_quality
6. Ogni reviewer usa challenger loop:
   a. Genera issues
   b. Challenger (Gemini) valida
   c. Itera finché satisfaction > 50%
7. Issues salvate in DB
8. Task completato
9. Utente vede issues in /issues
```

### 3.2 Fix Flow

```
1. Utente seleziona issues da fixare
2. Click "Fix" → POST /api/fix/start
3. Sistema calcola workload totale:
   workload = sum(effort × files_count)
4. Raggruppa in batch (max 15 workload per batch)
5. Per ogni batch:
   a. Fixer (Claude) genera fix
   b. Challenger (Gemini) valida
   c. Se score < 95%: itera (max 3)
   d. Se SOLVED: commit su branch
6. Report finale con issues fixed/failed
7. Branch pronto per PR
```

### 3.3 Linear Analysis Flow

```
1. Import issue da Linear (sync o manual)
2. Stato: "analysis"
3. Utente click "Analizza":
   a. Fase 1: Claude genera 5-10 domande
   b. Utente risponde
   c. Fase 2: Claude analisi profonda
   d. Output: improved_description, summary
4. Stato: "repo_link"
5. Utente collega repository
6. Stato: "in_progress"
7. Sviluppo (manuale o con fix)
8. Stato: "in_review"
9. Review e merge
10. Stato: "merged"
```

### 3.4 Chat CLI Flow

```
1. Utente crea/seleziona sessione
2. Sistema genera context:
   - Info TurboWrap (questo doc)
   - Repository info (se collegato)
   - Issues attive
   - structure.xml (se presente)
3. Spawn processo CLI:
   - claude --model X --agent Y
   - gemini --model X
4. Messaggio utente → stdin processo
5. Risposta streaming → SSE → frontend
6. Messaggio salvato in DB
7. Title generato (prima interazione)
```

---

## 4. COMPONENTI RIUTILIZZABILI

### Sidebar (`components/sidebar.html`)
- Navigazione principale
- Lista chat sessions
- Quick actions
- User menu

### Chat Sidebar (`components/chat_sidebar.html`)
- Lista sessioni chat
- Drag & drop ordering
- Context menu
- New chat button

### Active Fix Banner (`components/active_fix_banner.html`)
- Mostra fix in corso
- Progress bar
- Link a live tasks

### Test Suite Details (`components/test_suite_details.html`)
- Drawer con dettagli suite
- Lista runs
- Actions: run, analyze, generate

### Operation Card (`components/operation_card.html`)
- Card per singola operazione
- Progress, duration, status
- Expandable output

---

## 5. DATABASE SCHEMA COMPLETO

### Tabelle Principali

| Tabella | Scopo |
|---------|-------|
| `repositories` | Repository GitHub clonati |
| `issues` | Issue da code review |
| `tasks` | Task execution (review, develop) |
| `agent_runs` | Singole esecuzioni agente |
| `operations` | Tracking operazioni live |
| `linear_issues` | Issue importate da Linear |
| `linear_issue_repository_links` | Link Linear ↔ Repo |
| `test_suites` | Configurazione test suites |
| `test_runs` | Esecuzioni test |
| `test_cases` | Singoli test case |
| `cli_chat_sessions` | Sessioni chat CLI |
| `cli_chat_messages` | Messaggi chat |
| `mockup_projects` | Progetti mockup |
| `mockups` | Singoli mockup HTML |
| `database_connections` | Connessioni DB esterne |
| `settings` | App settings key-value |

### Relazioni Chiave

```
Repository
    ├── issues[]
    ├── tasks[]
    ├── test_suites[]
    ├── cli_chat_sessions[]
    ├── operations[]
    └── linear_issues[] (via link table)

Task
    ├── agent_runs[]
    ├── issues[]
    └── test_runs[]

TestSuite
    └── test_runs[]
        └── test_cases[]

CLIChatSession
    └── cli_chat_messages[]

MockupProject
    └── mockups[]
```

### Task Model
```python
Task(
    id: str,
    repository_id: str,
    type: str,                    # review/develop/tree
    status: str,                  # pending/running/completed/failed/cancelled
    priority: int,
    config: JSON,                 # Task-specific config
    result: JSON,                 # Output
    error: text,
    progress: int,                # 0-100
    progress_message: str,
    started_at: datetime,
    completed_at: datetime,
)

AgentRun(
    id: str,
    task_id: str,
    agent_type: str,              # gemini_flash/claude_opus
    agent_name: str,              # reviewer_be/fixer
    prompt_tokens: int,
    completion_tokens: int,
    duration_seconds: float,
    input_hash: str,              # Per caching
    output: JSON,
    error: text,
)
```

---

## 6. AGENTS DISPONIBILI

Gli agenti sono in `/agents/*.md`. Formato:

```markdown
# Nome Agent

## Scopo
Descrizione di cosa fa

## Input
Cosa si aspetta

## Output
Cosa produce

## Istruzioni
Prompt dettagliato per l'AI
```

### Agenti Principali

| Agent | Scopo |
|-------|-------|
| `test_creator` | Crea TurboWrapTest interattivamente |
| `reviewer_be` | Review backend Python/FastAPI |
| `reviewer_be_architecture` | Review architettura BE |
| `reviewer_be_quality` | Review qualità codice BE |
| `reviewer_fe` | Review frontend React/TypeScript |
| `reviewer_fe_architecture` | Review architettura FE |
| `reviewer_fe_quality` | Review qualità codice FE |
| `fixer` | Fix automatico issue |
| `fixer-single` | Fix singola issue |
| `flash-analyzer` | Analisi veloce repo |

---

## 7. NOTE OPERATIVE

### Path e File
- Usa sempre **path assoluti** quando modifichi file
- Repository clonati in `local_path` (campo Repository)
- TurboWrapTest in `turbowrap_tests/` nella root repo

### Git Operations
- Non fare push senza conferma utente
- Crea branch per fix: `fix/{timestamp}`
- Commit message descrittivi

### Workload Calculation
```python
workload = estimated_effort × estimated_files_count
max_batch_workload = 15
```

### Token Limits
- Claude thinking: 1000-50000 tokens
- Context: ~200k tokens
- Response: vary by model

### Error Handling
- Operation fallite: status="failed", error in `error` field
- Task falliti: status="failed", error in `error` field
- Retry automatico per errori transient

---

## 8. ENUMS E COSTANTI

### Issue Severity
```python
CRITICAL = "CRITICAL"  # Rosso - Vulnerabilità, data loss
HIGH = "HIGH"          # Arancione - Bug gravi
MEDIUM = "MEDIUM"      # Giallo - Bug minori
LOW = "LOW"            # Blu - Best practices
INFO = "INFO"          # Grigio - Suggerimenti
```

### Issue Status
```python
OPEN = "OPEN"
IN_PROGRESS = "IN_PROGRESS"
SOLVED = "SOLVED"
IGNORED = "IGNORED"
WONT_FIX = "WONT_FIX"
```

### Linear TurboWrap States
```python
ANALYSIS = "analysis"
REPO_LINK = "repo_link"
IN_PROGRESS = "in_progress"
IN_REVIEW = "in_review"
MERGED = "merged"
```

### Operation Types
```python
REVIEW = "review"
FIX = "fix"
FIX_ISSUE = "fix_issue"
FIX_CLARIFICATION = "fix_clarification"
GIT_CLONE = "git_clone"
GIT_PUSH = "git_push"
GIT_COMMIT = "git_commit"
LINEAR_SYNC = "linear_sync"
LINEAR_ANALYZE = "linear_analyze"
TEST_RUN = "test_run"
```

### Test Frameworks
```python
PYTEST = "pytest"
PLAYWRIGHT = "playwright"
VITEST = "vitest"
JEST = "jest"
CYPRESS = "cypress"
```

---

## 9. API PATTERNS

### Pagination
```
GET /api/issues?page=1&per_page=20
Response: { items: [...], total: 100, page: 1, per_page: 20 }
```

### Filtering
```
GET /api/issues?severity=HIGH&status=OPEN&repository_id=xxx
```

### Sorting
```
GET /api/issues?sort_by=created_at&sort_order=desc
```

### SSE Streaming
```
GET /api/tasks/{id}/stream
Event-stream con: progress, log, error, done
```

### Error Response
```json
{
    "detail": "Error message",
    "status_code": 400,
    "error_code": "VALIDATION_ERROR"
}
```

---

## 10. HTMX PATTERNS

### Partial Updates
```html
<div hx-get="/htmx/issues/list" hx-trigger="load">
    Loading...
</div>
```

### OOB Swaps
```html
<!-- Response può contenere -->
<div id="issue-count" hx-swap-oob="innerHTML">42</div>
```

### Event Triggers
```html
<button hx-post="/api/fix/start"
        hx-trigger="click"
        hx-target="#result"
        hx-indicator="#spinner">
```

### Alpine Integration
```html
<div x-data="{ open: false }"
     @htmx:after-settle="open = true">
```

---

## 11. CLI TASKS E S3 STORAGE

I log delle esecuzioni CLI (Claude/Gemini) sono salvati su **S3 bucket `turbowrap-thinking`**.

### Struttura S3
```
turbowrap-thinking/
├── claude-cli/YYYY/MM/DD/HHMMSS/
│   ├── {agent}_prompt.md           # Prompt inviato
│   ├── {agent}_output.jsonl        # Output raw (JSON lines)
│   ├── {agent}_output_readable.md  # Output human-readable
│   └── {agent}_thinking.md         # Extended thinking (se abilitato)
└── gemini-cli/YYYY/MM/DD/HHMMSS/
    └── (stessa struttura)
```

### Comandi AWS utili
```bash
# Lista sessioni di oggi
aws s3 ls s3://turbowrap-thinking/claude-cli/2025/12/31/ --recursive

# Leggi output di una sessione
aws s3 cp s3://turbowrap-thinking/claude-cli/2025/12/31/231400/linear_question_generator_output_readable.md -

# Cerca per contenuto (scarica e grep)
aws s3 cp s3://turbowrap-thinking/claude-cli/2025/12/31/ /tmp/logs/ --recursive
grep -r "session_id" /tmp/logs/
```

### Formato output.jsonl
Il file `*_output.jsonl` contiene eventi streaming:
- `{"type": "system", "subtype": "init", "session_id": "..."}` - Inizio sessione
- `{"type": "assistant", "message": "..."}` - Risposta AI
- `{"type": "result", "tokens_in": N, "tokens_out": M}` - Token usage

### Agent comuni
| Agent | Scopo |
|-------|-------|
| `linear_question_generator` | Genera domande per Linear issue |
| `fixer_single` | Fix singola issue |
| `fix_challenger` | Valida fix (Gemini) |
| `reviewer_be_quality` | Review qualità backend |
