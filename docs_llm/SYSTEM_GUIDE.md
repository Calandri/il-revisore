# TurboWrap - Guida Sistema per AI

## Cos'è TurboWrap

Orchestratore AI per code review e fixing automatico di repository GitHub.
Usa Claude e Gemini in pattern dual-LLM per validazione iterativa.

---

## Pagine e Funzionalità

### 1. Dashboard (`/`)
**Cosa fa**: Overview generale del sistema
**Cosa può fare l'utente**:
- Vedere statistiche globali (repos, issues, tasks)
- Accesso rapido alle sezioni principali
- Stato dei processi attivi

### 2. Repositories (`/repositories`)
**Cosa fa**: Gestione repository GitHub
**Cosa può fare l'utente**:
- Aggiungere repository (clone da GitHub URL)
- Vedere lista repository con tipo (BE/FE/Fullstack)
- Sync con remote (pull changes)
- Lanciare code review
- Eliminare repository

**Endpoints**:
- `GET /api/repos` - Lista
- `POST /api/repos` - Crea (con clone)
- `POST /api/repos/{id}/sync` - Pull da remote
- `DELETE /api/repos/{id}` - Elimina

**DB**: `Repository(id, name, url, local_path, repo_type, project_name)`

### 3. Issues (`/issues`)
**Cosa fa**: Gestione issue trovate dal code review
**Cosa può fare l'utente**:
- Filtrare per repository, severity, status
- Vedere dettagli issue (file, linea, descrizione)
- Cambiare status (OPEN → IN_PROGRESS → SOLVED/IGNORED)
- Selezionare issue per fixing batch
- Lanciare fix automatico

**Endpoints**:
- `GET /api/issues` - Lista con filtri
- `GET /api/issues/{id}` - Dettaglio
- `PUT /api/issues/{id}` - Aggiorna status
- `POST /api/fix/start` - Avvia fixing

**DB**: `Issue(id, issue_code, title, severity, status, category, file, line, description, suggestion)`

**Severity**: CRITICAL > HIGH > MEDIUM > LOW > INFO
**Status**: OPEN → IN_PROGRESS → SOLVED / IGNORED / WONT_FIX

### 4. Tests (`/tests`)
**Cosa fa**: Gestione test suites e TurboWrapTest
**Cosa può fare l'utente**:
- Vedere test suites per repository
- Eseguire test (classic o AI-powered)
- Creare nuovi TurboWrapTest (via agente)
- Vedere risultati e coverage
- Tab "TurboWrapperAI" per test AI

**Endpoints**:
- `GET /api/tests/suites` - Lista suites
- `POST /api/tests/suites/{id}/run` - Esegui
- `GET /api/tests/turbowrap-tests/{repo_id}` - TurboWrapTest files
- `PUT /api/tests/turbowrap-tests/{repo_id}/{name}` - Salva test

**DB**: `TestSuite(id, repository_id, name, path, framework, last_run_status)`

### 5. Linear Issues (`/linear`)
**Cosa fa**: Integrazione con Linear.app
**Cosa può fare l'utente**:
- Importare issue da Linear
- Lanciare analisi AI (2 fasi: domande → analisi)
- Collegare issue a repository
- Vedere stato workflow TurboWrap
- Pushare descrizione migliorata a Linear

**Endpoints**:
- `GET /api/linear/issues` - Lista
- `POST /api/linear/issues/{id}/analyze` - Analisi AI
- `PUT /api/linear/issues/{id}/link-repo` - Collega repo

**DB**: `LinearIssue(id, linear_id, title, description, turbowrap_state, analysis_summary)`

**Stati TurboWrap**: analysis → repo_link → in_progress → in_review → merged

### 6. Live Tasks (`/live-tasks`)
**Cosa fa**: Monitoraggio processi in esecuzione
**Cosa può fare l'utente**:
- Vedere code review in corso
- Vedere fix in corso
- Streaming output in tempo reale
- Cancellare task

**Endpoints**:
- `GET /api/tasks` - Lista tasks
- `GET /api/tasks/{id}/stream` - SSE streaming
- `DELETE /api/tasks/{id}` - Cancella

### 7. Chat CLI (`/chat` o sidebar)
**Cosa fa**: Chat interattiva con Claude/Gemini
**Cosa può fare l'utente**:
- Creare sessioni chat
- Scegliere CLI (Claude/Gemini) e modello
- Selezionare agente specifico
- Collegare repository per contesto
- Usare comandi slash (/review, /fix, etc.)
- Abilitare extended thinking (Claude)

**Endpoints**:
- `POST /api/cli-chat/sessions` - Crea sessione
- `POST /api/cli-chat/sessions/{id}/message` - Invia (SSE)
- `GET /api/cli-chat/agents` - Lista agenti

**DB**: `CLIChatSession(id, cli_type, model, agent_name, repository_id)`

### 8. Mockups (`/mockups`)
**Cosa fa**: Generazione mockup HTML con AI
**Cosa può fare l'utente**:
- Creare progetti mockup
- Generare pagine HTML via chat
- Preview live nel browser
- Esportare HTML

**Endpoints**:
- `GET /api/mockups/projects` - Lista progetti
- `POST /api/mockups/projects` - Crea progetto
- `GET /api/mockups/{id}/preview` - Preview HTML

### 9. Live View (`/live-view`)
**Cosa fa**: Development server per frontend
**Cosa può fare l'utente**:
- Avviare dev server (npm run dev)
- Preview live con hot reload
- Vedere console logs
- Modificare file e vedere risultati

### 10. Files (`/files`)
**Cosa fa**: Editor file integrato
**Cosa può fare l'utente**:
- Navigare file repository
- Editare con syntax highlighting
- Salvare modifiche
- Git diff e commit

### 11. Settings (`/settings`)
**Cosa fa**: Configurazione sistema
**Cosa può fare l'utente**:
- Configurare API keys
- Gestire MCP servers
- Vedere agenti disponibili
- Configurare database connections

---

## Pattern Comuni

### Code Review Flow
1. Utente seleziona repo → clicca "Review"
2. Sistema lancia reviewer agents in parallelo
3. Challenger valida ogni issue trovata
4. Issues salvate in DB con severity
5. Utente vede risultati in `/issues`

### Fix Flow
1. Utente seleziona issues da fixare
2. Sistema raggruppa in batch (max 15 workload)
3. Per ogni issue: fixer → challenger → iterate
4. Se SOLVED: commit su branch
5. Utente fa PR

### Chat Flow
1. Utente apre chat, seleziona repo
2. Sistema genera context (repo info, docs, issues)
3. Spawn CLI process (claude/gemini)
4. Messaggi via stdin/stdout streaming
5. Risposte mostrate in tempo reale

---

## Database Schema Essenziale

```
Repository ←─┬─ Issue
             ├─ TestSuite
             ├─ CLIChatSession
             └─ LinearIssue (via link table)

Issue: status workflow (OPEN→IN_PROGRESS→SOLVED)
LinearIssue: turbowrap_state workflow
CLIChatSession: processo CLI attivo
```

---

## Files Importanti

- `src/turbowrap/api/routes/` - Tutti gli endpoint
- `src/turbowrap/api/templates/` - Template Jinja2 + HTMX
- `src/turbowrap/db/models.py` - SQLAlchemy models
- `agents/*.md` - Prompt agenti AI
- `docs/*.md` - Documentazione dettagliata
