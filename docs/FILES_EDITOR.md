# Files Editor - Integrated Code Editor

## Overview

Files Editor è un editor di codice integrato in TurboWrap con file explorer, diff view, Git operations e AI-powered commit messages.

**Features**: File tree, Edit/Diff mode, Git status, Go to Definition, AI Commit
**Filtri**: changes, md, config, py, react, html, all

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FILES PAGE                                   │
│                       /files (files.html)                            │
└─────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌──────────────────┐
│   Sidebar     │      │   Editor Panel    │      │   Git Panel      │
│   File Tree   │      │   Edit/Diff Mode  │      │   Recent Commits │
└───────────────┘      └───────────────────┘      └──────────────────┘
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌──────────────────┐
│ API Routes    │      │ File Operations   │      │ Git Operations   │
│ /api/repos/   │      │ read/write/diff   │      │ fetch/pull/push  │
└───────────────┘      └───────────────────┘      └──────────────────┘
```

---

## Layout

### Desktop (>1024px)
```
┌────────────────┬─────────────────────────────────┐
│   File Tree    │         Editor Panel            │
│   (Sidebar)    │                                 │
│                │   ┌─────────────────────────┐   │
│ ├─ src/        │   │ Tab: filename.py        │   │
│ │  ├─ main.py  │   ├─────────────────────────┤   │
│ │  └─ utils/   │   │                         │   │
│ │                  │   [Code Editor/Diff]    │   │
│ ├─ Recent      │   │                         │   │
│    Commits     │   │                         │   │
│                │   └─────────────────────────┘   │
└────────────────┴─────────────────────────────────┘
```

### Mobile (<1024px)
- **Tab Navigation**: Explorer | Editor
- Switch tra le due view

---

## File Tree Explorer

### Quick Filters

| Filtro | Estensioni | Descrizione |
|--------|------------|-------------|
| `changes` | - | File modificati/untracked (git status) |
| `md` | `.md` | Documentazione Markdown |
| `config` | `.json`, `.yaml`, `.yml`, `.toml` | File di configurazione |
| `py` | `.py` | File Python |
| `react` | `.js`, `.ts`, `.jsx`, `.tsx` | File React/TypeScript |
| `html` | `.html`, `.css` | File HTML/CSS |
| `all` | `*` | Tutti i file |

### Git Status Indicators

| Indicatore | Significato |
|------------|-------------|
| 🟠 (arancio) | File modificato (M) |
| 🟢 (verde) | File untracked (U) |
| Border blu | File correntemente aperto |

### Tree Actions

| Azione | Descrizione |
|--------|-------------|
| ▼ Expand All | Espande tutte le cartelle |
| ▶ Collapse All | Comprime tutte le cartelle |
| ↻ Reload | Ricarica il file tree |

---

## Editor Panel

### View Modes

| Mode | Descrizione |
|------|-------------|
| `edit` | Editor di testo modificabile |
| `diff` | Vista diff (unified format) |

### Tab Bar
- **Nome file** con indicatore dirty (pallino arancio)
- **M** = File modificato nel working tree
- **U** = File untracked
- **SHA** = Badge commit quando viewing commit diff

### Toolbar

| Azione | Descrizione |
|--------|-------------|
| Ricarica | Ricarica contenuto file |
| Diff/Modifica | Toggle tra edit e diff mode |
| Modifica attuale | (Solo commit view) Torna al file corrente |
| Salva | Salva modifiche |

### Diff Styling

```
┌─────────────────────────────────────────┐
│ @@ -10,5 +10,7 @@      (header - blu)  │
│ context line           (grigio)         │
│ +added line            (verde)          │
│ -removed line          (rosso)          │
└─────────────────────────────────────────┘
```

---

## Git Integration

### Recent Commits Panel

Mostra gli ultimi 20 commit del repository:

```
┌─────────────────────────────────────────┐
│ Recent Commits (20)                  ▼  │
├─────────────────────────────────────────┤
│ ▶ abc1234  feat: add login      2h ago │
│   ▲ local  (non pushato)               │
├─────────────────────────────────────────┤
│ ▼ def5678  fix: bug in api      1d ago │
│   ├─ M src/api.py        +10 -5        │
│   └─ A src/new_file.py   +50           │
└─────────────────────────────────────────┘
```

**Click su commit**: Espande lista file modificati
**Click su file**: Mostra diff del commit per quel file

### Commit File Status

| Status | Colore | Significato |
|--------|--------|-------------|
| A | Verde | Added |
| M | Giallo | Modified |
| D | Rosso | Deleted |
| R | Blu | Renamed |
| C | Viola | Copied |

### SSE Git Events

La pagina ascolta eventi Git in tempo reale:

| Event | Azione |
|-------|--------|
| `commit` | Refresh tree e commits |
| `merge` | Refresh tree e commits |
| `checkout` | Refresh tree e commits |
| `rewrite` | Refresh tree e commits |

---

## Go to Definition

**Ctrl+Click** (o Cmd+Click) su un simbolo nel codice:

1. **Ricerca simbolo** nel repository
2. **Popup** con risultati trovati
3. **Click** per navigare alla definizione

### Symbol Types

| Tipo | Icona | Colore |
|------|-------|--------|
| function | f | Viola |
| method | m | Viola |
| class | C | Arancio |
| variable | v | Blu |
| import | i | Verde |
| interface | I | Ciano |
| type | T | Ciano |
| export | E | Giallo |

---

## AI Commit

Genera automaticamente messaggi di commit con Gemini:

### Workflow

1. Click **"Commit (AI)"** button
2. Gemini analizza le modifiche
3. Genera messaggio commit (conventional commits)
4. Utente può modificare/rigenerare
5. Opzione **"Push dopo commit"**
6. Conferma commit

### UI

```
┌─────────────────────────────────────────┐
│ ⚡ Commit (AI)                      ✕   │
├─────────────────────────────────────────┤
│ [Summary from AI]                       │
│                                         │
│ Messaggio commit:                       │
│ ┌─────────────────────────────────────┐ │
│ │ feat(auth): add login validation    │ │
│ │                                     │ │
│ │ - Add email format validation       │ │
│ │ - Add password strength check       │ │
│ └─────────────────────────────────────┘ │
│ ↻ Rigenera messaggio                    │
│                                         │
│ File che verranno committati:           │
│ M src/auth/login.py                     │
│ A src/auth/validators.py                │
│                                         │
│ ☑ Push dopo commit                      │
│                      [Annulla] [Commit] │
└─────────────────────────────────────────┘
```

---

## API Endpoints

### File Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/repos/{id}/files` | Lista file (glob pattern) |
| GET | `/api/repos/{id}/files/tree-hierarchy` | Tree gerarchico con git status |
| GET | `/api/repos/{id}/files/content` | Legge contenuto file |
| PUT | `/api/repos/{id}/files/content` | Salva file (con commit opzionale) |
| GET | `/api/repos/{id}/files/diff` | Diff working tree vs HEAD |
| GET | `/api/repos/{id}/files/find-definition` | Cerca definizione simbolo |

### Git Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/repos/{id}/status` | Git status (modified, untracked) |
| POST | `/api/git/repositories/{id}/fetch` | Git fetch |
| POST | `/api/git/repositories/{id}/pull` | Git pull |
| POST | `/api/git/repositories/{id}/push` | Git push |
| POST | `/api/git/repositories/{id}/commit` | Crea commit |
| POST | `/api/git/repositories/{id}/commit/generate-message` | AI commit message |
| GET | `/api/git/repositories/{id}/commits` | Lista commits |
| GET | `/api/git/repositories/{id}/commits/{sha}/files` | File in un commit |
| GET | `/api/git/repositories/{id}/commits/{sha}/files/diff` | Diff file in commit |

### SSE Events

| Endpoint | Description |
|----------|-------------|
| GET `/api/git/events` | Stream eventi git (commit, merge, checkout, rewrite) |

---

## State Management

### Alpine.js State

```javascript
fileEditor() {
    return {
        // Tab state (mobile)
        activeTab: 'files',  // 'files' | 'editor'

        // Sidebar
        sidebarCollapsed: false,

        // Repository context
        selectedRepoId: '',
        selectedBranch: '',
        fileExtension: 'changes',
        fileTree: null,
        expandedFolders: {},
        changedFiles: [],

        // Git status
        gitStatus: null,

        // Current file
        currentFilePath: '',
        content: '',
        originalContent: '',
        isDirty: false,

        // View mode
        viewMode: 'diff',  // 'edit' | 'diff'
        diffContent: '',
        diffLines: [],
        viewingCommitSha: null,

        // Commits
        commits: [],
        expandedCommit: null,
        commitFiles: [],

        // AI Commit
        showAiCommitModal: false,
        aiCommitMessage: '',
        pushAfterCommit: false,
    }
}
```

### Global Context Sync

La pagina si sincronizza con `Alpine.store('globalContext')`:
- Cambio repository → Reset tutto e ricarica
- Cambio branch → Ricarica tree e commits

---

## File Save Flow

### Senza Commit

```
1. Utente modifica file
2. Click "Salva"
3. Modal: "Messaggio commit (opzionale)"
4. Lascia vuoto → PUT /files/content
5. File salvato su disco (no commit)
```

### Con Commit

```
1. Utente modifica file
2. Click "Salva"
3. Modal: inserisce messaggio
4. PUT /files/content con commit_message
5. File salvato + git add + git commit
```

### Risposta API

```json
{
  "path": "src/main.py",
  "saved": true,
  "committed": true,  // false se no messaggio
  "sha": "abc123"     // null se non committato
}
```

---

## Keyboard Shortcuts

| Shortcut | Azione |
|----------|--------|
| Ctrl/Cmd + Click | Go to Definition |

---

## Best Practices

### Per gli Utenti

1. **Usa filtro "changes"** - Vedi subito cosa hai modificato
2. **Controlla commit locali** - Badge "local" indica non pushato
3. **AI Commit** - Usa per messaggi consistenti
4. **Diff prima di salvare** - Verifica le modifiche

### Per lo Sviluppo

1. **SSE per real-time** - Eventi git per refresh automatico
2. **Dirty state** - Avvisa prima di perdere modifiche
3. **Context sync** - Repository/branch dal globalContext

---

## Troubleshooting

### File non si carica

1. Verifica permessi file system
2. Controlla che il repository esista
3. Verifica path relativo corretto

### Diff non funziona

1. File deve essere tracked da git
2. Verifica git status
3. File binari non supportati

### AI Commit fallisce

1. Verifica API key Gemini configurata
2. Controlla che ci siano modifiche
3. Timeout dopo 30 secondi

### Go to Definition non trova

1. Simbolo deve essere definito nel repository
2. Supporta: Python, JavaScript, TypeScript
3. Ricerca basata su pattern, non AST
