# Issue System

Sistema di tracciamento issue per code review. Le issue vengono create dal sistema di Review e gestite attraverso il ciclo di Fix.

## Panoramica

```
┌─────────────────────────────────────────────────────────────────┐
│                        ISSUE LIFECYCLE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌────────┐     ┌─────────────┐     ┌──────────┐              │
│   │  OPEN  │────▶│ IN_PROGRESS │────▶│ RESOLVED │              │
│   └────────┘     └─────────────┘     └──────────┘              │
│       │                │                   │                    │
│       │                │                   │ (reopen)           │
│       ▼                ▼                   ▼                    │
│   ┌─────────┐    ┌───────────┐       ┌────────┐                │
│   │ IGNORED │    │ DUPLICATE │       │  OPEN  │                │
│   └─────────┘    └───────────┘       └────────┘                │
│                                                                 │
│   Status: open → in_progress → resolved/merged/ignored          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Modello Issue

### Campi Principali

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `id` | UUID | Identificativo univoco |
| `issue_code` | String | Codice issue (es: BE-CRIT-001) |
| `repository_id` | UUID | Repository associato |
| `task_id` | UUID | Task di review che ha creato l'issue |

### Severity

```python
class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"  # Security vulnerabilities, data loss
    HIGH = "HIGH"          # Bugs, performance issues
    MEDIUM = "MEDIUM"      # Code quality, maintainability
    LOW = "LOW"            # Style, minor improvements
```

### Status

```python
class IssueStatus(str, Enum):
    OPEN = "open"              # Nuova issue, da risolvere
    IN_PROGRESS = "in_progress" # In fase di fix
    RESOLVED = "resolved"       # Fixata ma non ancora merged
    MERGED = "merged"           # Merged in main
    IGNORED = "ignored"         # False positive o won't fix
    DUPLICATE = "duplicate"     # Duplicato di altra issue
```

### Transizioni Valide

```python
ISSUE_STATUS_TRANSITIONS = {
    IssueStatus.OPEN: [
        IssueStatus.IN_PROGRESS,
        IssueStatus.RESOLVED,
        IssueStatus.IGNORED,
        IssueStatus.DUPLICATE,
    ],
    IssueStatus.IN_PROGRESS: [
        IssueStatus.RESOLVED,
        IssueStatus.IGNORED,
        IssueStatus.OPEN,  # Reset se fix fallisce
    ],
    IssueStatus.RESOLVED: [
        IssueStatus.OPEN,   # Reopen
        IssueStatus.MERGED,
    ],
    IssueStatus.MERGED: [],  # Stato finale
    IssueStatus.IGNORED: [IssueStatus.OPEN],  # Reopen
    IssueStatus.DUPLICATE: [IssueStatus.OPEN],  # Reopen
}
```

### Location

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `file` | String | Path del file |
| `line` | Integer | Linea di inizio |
| `end_line` | Integer | Linea di fine |
| `category` | String | security, performance, architecture, etc. |
| `rule` | String | Codice regola linting (se applicabile) |

### Content

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `title` | String | Titolo breve dell'issue |
| `description` | Text | Descrizione dettagliata |
| `current_code` | Text | Codice problematico attuale |
| `suggested_fix` | Text | Fix suggerito dal reviewer |
| `references` | JSON | Lista di URL/documentazione |
| `flagged_by` | JSON | Lista agenti che hanno segnalato |

### Linear Integration

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `linear_id` | String | UUID Linear |
| `linear_identifier` | String | Identificativo (es: TEAM-123) |
| `linear_url` | String | URL completo Linear |

### Fix Tracking

Campi popolati quando l'issue viene fixata:

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `fix_code` | Text | Snippet del codice fixato |
| `fix_explanation` | Text | Spiegazione PR-style del fix |
| `fix_files_modified` | JSON | Lista file modificati |
| `fix_commit_sha` | String | SHA del commit |
| `fix_branch` | String | Branch del fix (es: fix/1234567890) |
| `fix_session_id` | UUID | ID sessione per log S3 |
| `fixed_at` | DateTime | Timestamp del fix |
| `fixed_by` | String | Agent che ha fixato |
| `fix_self_score` | Integer | Self-evaluation (0-100) |
| `fix_gemini_score` | Integer | Gemini challenger score (0-100) |

### Effort Estimation

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `estimated_effort` | Integer | Scala 1-5 (1=trivial, 5=major refactor) |
| `estimated_files_count` | Integer | Numero file da modificare |

### Discussion

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `comments` | JSON | Lista commenti [{id, author, content, created_at, type}] |
| `attachments` | JSON | Lista allegati [{filename, s3_key, type, uploaded_at}] |

---

## API Endpoints

Base URL: `/api/issues`

### List Issues

```http
GET /api/issues?repository_id={id}&severity=HIGH&status=open
```

**Query Parameters:**
- `repository_id` - Filtra per repository
- `task_id` - Filtra per task
- `severity` - CRITICAL, HIGH, MEDIUM, LOW
- `status` - open, in_progress, resolved, ignored, duplicate
- `category` - security, performance, architecture, etc.
- `file` - Filtra per path file (partial match)
- `linear_linked` - "linked" o "unlinked"
- `search` - Cerca in title, description, file, issue_code
- `order_by` - severity (default), updated_at, created_at
- `limit` - Max risultati (default: 100, max: 500)
- `offset` - Paginazione

**Response:**
```json
[
  {
    "id": "uuid",
    "issue_code": "BE-CRIT-001",
    "severity": "CRITICAL",
    "status": "open",
    "title": "SQL Injection vulnerability",
    "file": "src/api/routes/users.py",
    "line": 42,
    "category": "security",
    "flagged_by": ["reviewer_be_quality", "reviewer_be_architecture"],
    "created_at": "2025-12-30T10:00:00Z"
  }
]
```

### Get Summary

```http
GET /api/issues/summary?repository_id={id}&status=open
```

**Response:**
```json
{
  "total": 25,
  "by_severity": {
    "CRITICAL": 2,
    "HIGH": 5,
    "MEDIUM": 10,
    "LOW": 8
  },
  "by_status": {
    "open": 15,
    "in_progress": 3,
    "resolved": 5,
    "ignored": 2
  },
  "by_category": {
    "security": 3,
    "performance": 5,
    "architecture": 8,
    "code_quality": 9
  },
  "linear_linked": 5
}
```

### Get Issue Detail

```http
GET /api/issues/{issue_id}
```

### Update Issue

```http
PATCH /api/issues/{issue_id}
Content-Type: application/json

{
  "status": "in_progress",
  "resolution_note": "Working on fix"
}
```

**Query Parameters:**
- `force=true` - Bypassa validazione transizioni (pericoloso)

### Quick Actions

```http
POST /api/issues/{issue_id}/resolve?note=Merged%20in%20PR%20123
POST /api/issues/{issue_id}/ignore?note=False%20positive
POST /api/issues/{issue_id}/reopen
POST /api/issues/{issue_id}/toggle-viewed?viewed=true
```

### Linear Integration

```http
# Link a Linear
POST /api/issues/{issue_id}/link-linear
Content-Type: application/json

{
  "linear_identifier": "TEAM-123"
}

# Unlink from Linear
DELETE /api/issues/{issue_id}/link-linear
```

### Comments

```http
# Add comment
POST /api/issues/{issue_id}/comments
Content-Type: application/json

{
  "content": "This needs review from security team",
  "author": "user",
  "comment_type": "human"
}

# Delete comment
DELETE /api/issues/{issue_id}/comments/{comment_id}
```

### Fix Log

```http
GET /api/issues/{issue_id}/fix-log
```

**Response:**
```json
{
  "session_id": "uuid",
  "timestamp": "2025-12-30T10:00:00Z",
  "status": "completed",
  "branch_name": "fix/1234567890",
  "issues_requested": 5,
  "issues_fixed": 5,
  "claude_prompts": [
    {
      "type": "fix",
      "batch": 1,
      "issues": ["BE-CRIT-001", "BE-HIGH-002"],
      "prompt": "Fix the following issues..."
    }
  ],
  "gemini_prompt": "Review the following fixes...",
  "gemini_review": "All fixes are correct..."
}
```

### Create from Error

```http
POST /api/issues/from-error
Content-Type: application/json

{
  "title": "TypeError in user authentication",
  "description": "Error occurs when user has no email",
  "error_message": "TypeError: Cannot read property 'email' of undefined",
  "error_stack": "...",
  "file_path": "src/auth/login.ts",
  "line_number": 42,
  "suggested_fix": "Add null check before accessing email",
  "severity": "high",
  "repository_id": "uuid"
}
```

### Cleanup

```http
# Reset issues stuck in_progress for >1 hour
POST /api/issues/cleanup/reset-stuck?max_age_hours=1&repository_id={id}
```

---

## Flusso Operativo

### 1. Creazione Issue (Review)

```
Review Task → Reviewer Agents → Issue Creation
                                     │
                                     ▼
                              ┌──────────┐
                              │   OPEN   │
                              └──────────┘
```

Le issue vengono create automaticamente dal sistema di review:
- Ogni reviewer agent identifica problemi nel codice
- Il deduplicatore rimuove duplicati
- Le issue vengono salvate con `flagged_by` che lista gli agenti

### 2. Triage (Manuale)

```
┌──────────┐     ┌─────────────┐
│   OPEN   │────▶│   IGNORED   │  (False positive)
└──────────┘     └─────────────┘
     │
     ▼
┌─────────────┐
│  DUPLICATE  │  (Già segnalata)
└─────────────┘
```

L'utente può:
- Marcare come `ignored` se false positive
- Marcare come `duplicate` se già segnalata
- Linkare a Linear per tracking esterno
- Aggiungere commenti

### 3. Fix (Automatico)

```
┌──────────┐     ┌─────────────┐     ┌──────────┐
│   OPEN   │────▶│ IN_PROGRESS │────▶│ RESOLVED │
└──────────┘     └─────────────┘     └──────────┘
                       │
                       ▼
                 Fix System
                 (fixer agents)
```

Il Fix System:
1. Seleziona issue OPEN
2. Le passa al fixer agent
3. Aggiorna status a IN_PROGRESS
4. Salva fix_code, fix_branch, fix_commit_sha
5. Aggiorna status a RESOLVED

### 4. Merge (Manuale)

```
┌──────────┐     ┌────────┐
│ RESOLVED │────▶│ MERGED │
└──────────┘     └────────┘
```

Dopo PR merge manuale, l'issue viene marcata MERGED.

### 5. Reopen

```
┌──────────┐     ┌────────┐
│ RESOLVED │────▶│  OPEN  │
└──────────┘     └────────┘
     │
     ▼
Clears: fix_commit_sha, fix_branch
```

Se il fix non è corretto, l'issue può essere riaperta.

---

## UI - Pagina Issues

### Filtri

- **Severity**: CRITICAL, HIGH, MEDIUM, LOW
- **Status**: Open, In Progress, Resolved, Ignored
- **Category**: Security, Performance, Architecture, etc.
- **Linear**: Linked, Unlinked
- **Search**: Full-text search

### Card Issue

```
┌─────────────────────────────────────────────────────────────┐
│ [CRITICAL] BE-CRIT-001                          [TEAM-123] │
│ SQL Injection in user query                                 │
├─────────────────────────────────────────────────────────────┤
│ 📁 src/api/routes/users.py:42                              │
│ 🏷️ security                                                 │
│ 👥 reviewer_be_quality, reviewer_be_architecture           │
├─────────────────────────────────────────────────────────────┤
│ Raw SQL query with user input without sanitization...      │
├─────────────────────────────────────────────────────────────┤
│ [Fix] [Ignore] [Link Linear] [Comments (3)]                │
└─────────────────────────────────────────────────────────────┘
```

### Detail View

- **Preview**: Markdown rendered della descrizione
- **Code**: Current code e suggested fix side-by-side
- **Fix Log**: Prompts e risposte del fix (se fixata)
- **Comments**: Thread di discussione
- **Timeline**: Storia delle transizioni

---

## Database Schema

```sql
CREATE TABLE issues (
    id VARCHAR(36) PRIMARY KEY,
    task_id VARCHAR(36) REFERENCES tasks(id),
    repository_id VARCHAR(36) NOT NULL REFERENCES repositories(id),

    -- Linear integration
    linear_id VARCHAR(100) UNIQUE,
    linear_identifier VARCHAR(50),
    linear_url VARCHAR(512),

    -- Issue identification
    issue_code VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    category VARCHAR(50) NOT NULL,
    rule VARCHAR(100),

    -- Location
    file VARCHAR(500) NOT NULL,
    line INTEGER,
    end_line INTEGER,

    -- Content
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    current_code TEXT,
    suggested_fix TEXT,
    references JSON,
    flagged_by JSON,
    attachments JSON,
    comments JSON,

    -- Effort estimation
    estimated_effort INTEGER,
    estimated_files_count INTEGER,

    -- Status tracking
    status VARCHAR(20) DEFAULT 'open',
    phase_started_at DATETIME,
    is_active BOOLEAN DEFAULT FALSE,
    is_viewed BOOLEAN DEFAULT FALSE,
    resolution_note TEXT,
    resolved_at DATETIME,

    -- Fix result
    fix_code TEXT,
    fix_explanation TEXT,
    fix_files_modified JSON,
    fix_commit_sha VARCHAR(40),
    fix_branch VARCHAR(100),
    fix_session_id VARCHAR(36),
    fixed_at DATETIME,
    fixed_by VARCHAR(50),
    fix_self_score INTEGER,
    fix_gemini_score INTEGER,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME,

    -- Indexes
    INDEX idx_issues_repository (repository_id),
    INDEX idx_issues_task (task_id),
    INDEX idx_issues_severity (severity),
    INDEX idx_issues_category (category),
    INDEX idx_issues_file (file),
    INDEX idx_issues_status (status),
    INDEX idx_issues_linear_id (linear_id),
    INDEX idx_issues_linear_identifier (linear_identifier),
    INDEX idx_issues_is_active (is_active),
    INDEX idx_issues_is_viewed (is_viewed),
    INDEX idx_issues_fix_session_id (fix_session_id)
);
```

---

## Auto-Cleanup

Il sistema automaticamente resetta le issue bloccate:

```python
# Issue in_progress da >1 ora vengono resettate a open
reset_stuck_in_progress_issues(db, max_age_hours=1)
```

Questo viene eseguito automaticamente alla chiamata di `list_issues`.

---

## Integrazione con Altri Sistemi

### Review System

Le issue vengono create dal Review System dopo la code review:
- Ogni reviewer agent produce una lista di issue
- Il deduplicatore unifica le issue duplicate
- Le issue vengono salvate con `task_id` della review

### Fix System

Il Fix System processa le issue OPEN:
- Seleziona issue per severity (CRITICAL first)
- Crea branch di fix
- Esegue fix con Claude
- Valida con Gemini challenger
- Aggiorna issue con risultati

### Linear

Integrazione bidirezionale con Linear:
- Link manuale issue → Linear ticket
- Sync status (futuro)
- Comments sync (futuro)

---

## File Correlati

| File | Descrizione |
|------|-------------|
| `src/turbowrap/db/models/issue.py` | Modello SQLAlchemy |
| `src/turbowrap/db/models/base.py` | Enum IssueStatus, IssueSeverity |
| `src/turbowrap/api/routes/issues.py` | API endpoints |
| `src/turbowrap/api/templates/pages/issues.html` | UI template |
| `agents/fixer_single.md` | Agent che fixa le issue |
| `agents/fix_challenger.md` | Agent che valida i fix |
