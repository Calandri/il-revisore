# TurboWrap - Guida AI

Orchestratore AI per code review e fixing automatico. Usa dual-LLM (Claude + Gemini).

---

## MCP TOOLS DISPONIBILI

Usa questi tool per assistere l'utente:

| Tool | Azione |
|------|--------|
| `navigate` | Vai a una pagina (`/issues`, `/repos`, etc.) |
| `highlight` | Evidenzia elemento UI (CSS selector) |
| `show_toast` | Mostra notifica all'utente |
| `open_modal` | Apri un modal specifico |
| `get_current_page` | Scopri dove si trova l'utente |
| `list_repositories` | Lista repo configurati |
| `list_issues` | Lista issue code review |
| `get_issue` | Dettaglio singola issue |
| `resolve_issue` | Marca issue come risolta |
| `list_test_suites` | Lista test suites |
| `run_test_suite` | Esegui una test suite |
| `list_fixable_issues` | Issue che possono essere fixate |
| `start_fix` | Avvia fixing automatico |
| `create_issue` | Crea nuova issue |
| `create_feature` | Crea nuova feature request |
| `get_database` | Query database (solo lettura) |
| `create_mockup` | Crea nuovo mockup HTML |
| `modify_mockup` | Modifica mockup esistente |

---

## PAGINE PRINCIPALI

| Pagina | Path | Descrizione |
|--------|------|-------------|
| **Overview** | `/` | Dashboard con statistiche, repo recenti, tasks attivi |
| **Repositories** | `/repositories` | Gestione repo GitHub clonati, sync, review |
| **Issues** | `/issues` | Issue da code review, filtri, fix batch |
| **Features** | `/features` | Feature requests e suggerimenti utente |
| **Review** | `/review` | Avvia e monitora code review |
| **Mockups** | `/mockups` | Genera mockup HTML con AI |
| **Live Preview** | `/live-view` | Dev server per preview frontend |
| **Tests** | `/tests` | Test suites e TurboWrapTest |
| **Linear** | `/linear` | Issue importate da Linear.app |
| **Files** | `/files` | Editor file integrato |
| **Settings** | `/settings` | Configurazione sistema |

---

## TABELLE DATABASE

| Tabella | Contenuto |
|---------|-----------|
| `repositories` | Repo GitHub clonati |
| `issues` | Issue da code review (severity, status, fix) |
| `features` | Feature requests utente |
| `tasks` | Task execution (review, fix) |
| `operations` | Operazioni live in corso |
| `linear_issues` | Issue da Linear.app |
| `test_suites` | Configurazione test |
| `test_runs` | Esecuzioni test |
| `cli_chat_sessions` | Sessioni chat CLI |
| `cli_chat_messages` | Messaggi chat |
| `mockup_projects` | Progetti mockup |
| `mockups` | Singoli mockup HTML |
| `database_connections` | Connessioni DB esterne |

---

## FLOW: CODE REVIEW

**Trigger**: `POST /tasks/{repository_id}/review/stream`

**Steps**:
1. Carica repo e prepara contesto (file, struttura, git info)
2. Rileva tipo repo (backend/frontend/fullstack)
3. Seleziona reviewer specialisti
4. Esegue **Parallel Triple-LLM**: Claude + Gemini + Grok in parallelo
5. Deduplicazione e prioritizzazione problemi
6. **Final Evaluator** (Claude Opus) per score 0-100
7. Genera report con issues e raccomandazioni
8. Streama SSE events

**Agents coinvolti**:
- `reviewer_be_architecture`, `reviewer_be_quality` (backend)
- `reviewer_fe_architecture`, `reviewer_fe_quality` (frontend)
- `analyst_func` (business logic)
- `evaluator` (score finale)

**Output**: Issues in DB, score 0-100, report

---

## FLOW: FIX AUTOMATICO

**Trigger**: `POST /fix/start`

**Steps**:
1. **Clarification**: Claude pone domande su issues
2. **Planning**: Genera master_todo.json con steps
3. **Fix Round 1**: Claude CLI (Opus + extended thinking) fissa issues
4. **Gemini Evaluation**: Verifica git diff vs claimed fix, score 0-100
5. Se score >= threshold: commit + RESOLVED
6. Se failed: retry Round 2 con feedback
7. Issues rimasti → FAILED status
8. Log salvati su S3

**Agents coinvolti**:
- `fixer` (Claude orchestrator)
- `fix_challenger` (Gemini validator)

**Output**: Commit su fix branch, issues RESOLVED/FAILED

---

## AGENTS DISPONIBILI

| Agent | Scopo |
|-------|-------|
| `evaluator` | Valuta qualità repo su 6 dimensioni |
| `reviewer_be_quality` | Review Python/FastAPI: linting, security, perf |
| `reviewer_be_architecture` | Review architettura backend: SOLID, layers |
| `reviewer_fe_quality` | Review React/TypeScript: type safety, perf |
| `reviewer_fe_architecture` | Review architettura frontend: patterns, state |
| `reviewer_dedup_be` | Identifica duplicazioni backend |
| `reviewer_dedup_fe` | Identifica duplicazioni frontend |
| `analyst_func` | Analisi correttezza funzionale |
| `orchestrator` | Coordina processo code review |
| `fixer` | Orchestrator fix paralleli |
| `fixer_single` | Fix singola issue |
| `fix_challenger` | Valida fix (Gemini) |
| `fix_clarifier` | Domande pre-fix |
| `fix_planner` | Piano esecuzione fix |
| `re_fixer` | Rivaluta feedback e migliora |
| `flash_analyzer` | Analisi veloce struttura repo |
| `lint_fixer` | Corregge problemi linting |
| `linter_analyzer` | Analisi statica codebase |
| `dev_be` | Sviluppatore backend esperto |
| `dev_fe` | Sviluppatore frontend esperto |
| `test_creator` | Crea test TurboWrap interattivi |
| `test_discoverer` | Scopre test suite nel repo |
| `test_analyzer` | Analizza qualità test |
| `test_enhancer` | Migliora test esistenti |
| `readme_analyzer` | Analisi repo con diagrammi |
| `linear_question_generator` | Domande per ticket Linear |
| `linear_finalizer` | Descrizione finale ticket |
| `linear_issue_analyzer` | Migliora descrizioni Linear |
| `git_merger` | Merge branch a main |
| `git_branch_creator` | Crea branch per fix |
| `git_committer` | Commit con messaggi dettagliati |
| `infra_ops` | Operazioni AWS EC2 |
| `widget_chat_collector` | Raccolta bug via widget |
| `engineering_principles` | Guida filosofia e agent |

---

## S3 LOGS

I log CLI sono su **S3 bucket `turbowrap-thinking`**:

```
turbowrap-thinking/
├── claude-cli/YYYY/MM/DD/HHMMSS/
│   ├── {agent}_prompt.md
│   ├── {agent}_output.jsonl
│   └── {agent}_thinking.md
└── gemini-cli/...
```

**Comandi utili**:
```bash
# Lista sessioni oggi
aws s3 ls s3://turbowrap-thinking/claude-cli/2025/01/02/ --recursive

# Leggi output
aws s3 cp s3://turbowrap-thinking/claude-cli/2025/01/02/231400/fixer_output_readable.md -
```

---

## COME ASSISTERE L'UTENTE

### Creare/Modificare Codice
1. Chiedi quale repo (`list_repositories`)
2. Naviga a Files (`navigate` → `/files`)
3. Usa tool Edit/Write per modificare

### Creare Issue
1. Usa `create_issue` con: titolo, descrizione, severity, file/linea
2. Naviga a Issues per mostrare (`navigate` → `/issues`)

### Creare Feature
1. Usa `create_feature` con: titolo, descrizione, priority
2. Naviga a Features (`navigate` → `/features`)

### Creare Mockup
1. Usa `create_mockup` con: nome, HTML, progetto
2. Naviga a Mockups per preview (`navigate` → `/mockups`)

### Analizzare Database
1. Usa `get_database` con query SQL (solo SELECT)
2. Mostra risultati formattati

### Avviare Review
1. Chiedi quale repo
2. Usa `start_fix` o naviga a Review

### Fixare Issues
1. Mostra issues (`list_issues`)
2. Seleziona quali fixare
3. Usa `start_fix` con lista issue_ids

---

## NOTE OPERATIVE

- **Path**: Usa sempre path assoluti
- **Git**: Non push senza conferma utente
- **Severity**: CRITICAL > HIGH > MEDIUM > LOW > INFO
- **Status Issue**: OPEN → IN_PROGRESS → SOLVED/IGNORED
- **Workload**: effort × files_count (max 15 per batch)
