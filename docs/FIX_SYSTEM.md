# Fix System - Automated Issue Remediation

## Overview

Il Fix System è il motore di correzione automatica delle issue trovate durante la code review.
Utilizza **Claude CLI** (fixer) e **Gemini CLI** (challenger) in un loop iterativo per garantire fix di alta qualità.

**Fixer**: Claude Opus (reasoning avanzato per fix complessi)
**Challenger**: Gemini Flash (valutazione rapida ed economica)
**Threshold**: Score >= 90 per marcare un issue come SOLVED

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FIX ORCHESTRATOR                            │
│                    (src/turbowrap/fix/orchestrator.py)              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌──────────────────┐
│ Pre-Fix       │      │ Claude CLI        │      │ Gemini CLI       │
│ Clarification │      │ (Fixer Agent)     │      │ (Challenger)     │
│ (Optional)    │      │                   │      │                  │
└───────────────┘      └───────────────────┘      └──────────────────┘
        │                          │                          │
        │                          ▼                          │
        │              ┌───────────────────┐                  │
        │              │ Sub-Agents:       │                  │
        │              │ - git-branch-creator (haiku)         │
        │              │ - fixer-single (opus)                │
        │              │ - git-committer (haiku)              │
        │              └───────────────────┘                  │
        │                          │                          │
        └──────────────────────────┼──────────────────────────┘
                                   ▼
                        ┌───────────────────┐
                        │   Git Repository  │
                        │   (Branch + Commits)
                        └───────────────────┘
```

---

## Workflow Completo

### 1. Pre-Fix Clarification (Opzionale)

Prima di iniziare il fix, l'utente può attivare una fase di clarification dove Claude Opus analizza le issue e fa domande per chiarire ambiguità.

```
POST /api/fix/clarify
{
  "repository_id": "uuid",
  "issue_ids": ["id1", "id2", ...]
}
```

**Response Loop:**
```json
{
  "has_questions": true,
  "questions": [
    {
      "id": "q1",
      "question": "Per l'issue sulla validazione email, preferisci regex strict o permissivo?",
      "context": "La validazione attuale accetta email con underscore..."
    }
  ],
  "message": "Ho alcune domande prima di procedere",
  "session_id": "clarify_abc123",
  "ready_to_fix": false
}
```

Continua fino a `ready_to_fix: true`, poi passa a `/start` con `clarify_session_id`.

### 2. Branch Creation

Il Fix Orchestrator crea un branch dal main:
- Nome auto-generato: `fix/<slug-from-issue-title>`
- Esempio: `fix/missing-null-check-and-2-more`

**Agent utilizzato**: `git-branch-creator` (Haiku - veloce ed economico)

### 3. Issue Batching

Le issue vengono raggruppate per ottimizzare l'esecuzione:

| Tipo | File | Esecuzione |
|------|------|------------|
| **Parallel** | File diversi | Tutti insieme in un messaggio |
| **Serial** | Stesso file | Uno alla volta (evita conflitti) |

**Suddivisione BE/FE:**
- Backend: `.py`, `.go`, `.java`, `.rb`, `.php`, `.rs`, `.c`, `.cpp`
- Frontend: `.tsx`, `.ts`, `.jsx`, `.js`, `.css`, `.scss`, `.vue`, `.svelte`

### 4. Fix Execution

Per ogni batch, il `fixer.md` orchestrator:

1. **Legge il TODO List** (JSON con issue raggruppate)
2. **Lancia sub-agent paralleli** per file diversi
3. **Lancia sub-agent seriali** per stesso file
4. **Aggrega risultati** in JSON finale

**Agent `fixer-single`** (per ogni issue):
```markdown
Input:
- issue_code: FUNC-001
- file: src/services.py
- title: Missing null check
- description: get_user crashes on None
- suggested_fix: Add null check

Output:
{
  "issue_code": "FUNC-001",
  "status": "fixed",
  "file_modified": "src/services.py",
  "changes_summary": "Added early return with None check",
  "self_evaluation": {
    "confidence": 98,
    "completeness": "full",
    "risks": []
  }
}
```

### 5. Challenger Evaluation

Dopo ogni batch, Gemini CLI valuta OGNI issue individualmente:

```json
{
  "issues": {
    "FUNC-001": {
      "score": 95,
      "status": "SOLVED",
      "feedback": "Fix corretto, null check implementato",
      "quality_scores": {
        "correctness": 100,
        "safety": 90,
        "style": 95
      },
      "improvements_needed": []
    },
    "FUNC-002": {
      "score": 70,
      "status": "IN_PROGRESS",
      "feedback": "Fix parziale, manca gestione edge case",
      "improvements_needed": ["Handle empty array case"]
    }
  }
}
```

**Soglia**: Score >= 90 = **SOLVED**

### 6. Re-Fix (se necessario)

Se challenger score < 90:
1. Feedback inviato al `re_fixer.md` agent
2. Re-fix con contesto del problema
3. Nuovo round di challenger
4. Max 2 iterazioni (1 fix + 1 re-fix)

### 7. Commit

Dopo ogni batch completato:
- **Agent**: `git-committer` (Haiku)
- **Commit message**: Auto-generato con issue codes
- **Non push automatico**: L'utente decide quando pushare

---

## Agents

### fixer.md (Orchestrator)
- **Model**: Opus
- **Role**: Coordina branch creation e fix paralleli/seriali
- **Input**: TODO List JSON
- **Output**: Aggregated results JSON

### fixer-single.md (Sub-Agent)
- **Model**: Opus
- **Role**: Corregge UNA singola issue
- **Input**: Issue details
- **Output**: Fix result JSON
- **Rules**:
  - Fix SOLO l'issue assegnata
  - NO git commands
  - Usa Edit tool per salvare
  - Verifica suggested_fix prima di applicare

### fix_challenger.md (Evaluator)
- **Model**: Sonnet
- **Role**: Valuta qualità fix per-issue
- **Input**: Git diff + Issue list + Fixer output
- **Output**: Per-issue scores e status

### re_fixer.md (Re-Fix Agent)
- **Model**: Opus
- **Role**: Corregge issue basandosi su feedback challenger
- **Input**: Issue + Previous fix + Challenger feedback
- **Output**: Improved fix

### git-branch-creator.md
- **Model**: Haiku
- **Role**: Crea branch git
- **Input**: Branch name
- **Output**: Branch created confirmation

### git-committer.md
- **Model**: Haiku
- **Role**: Committa modifiche
- **Input**: Files modified + commit message
- **Output**: Commit SHA

---

## Models (Pydantic)

### FixStatus
```python
class FixStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    ANALYZING = "analyzing"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    GENERATING = "generating"
    APPLYING = "applying"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
```

### FixQualityScores
```python
class FixQualityScores(BaseModel):
    correctness: float  # 0-100 - Fix risolve il problema?
    safety: float       # 0-100 - Introduce bug/vulnerabilità?
    minimality: float   # 0-100 - Fix minimale e focalizzato?
    style_consistency: float  # 0-100 - Stile coerente?

    @property
    def weighted_score(self) -> float:
        # correctness: 40%, safety: 30%, minimality: 15%, style: 15%
```

### IssueFixResult
```python
class IssueFixResult(BaseModel):
    issue_id: str
    issue_code: str
    status: FixStatus
    commit_sha: str | None
    commit_message: str | None
    changes_made: str | None
    error: str | None
    fix_code: str | None  # Snippet (max 500 chars)
    fix_explanation: str | None
    fix_files_modified: list[str]
    false_positive: bool
    fix_self_score: int | None  # Claude self-eval
    fix_gemini_score: int | None  # Challenger score
```

### FixSessionResult
```python
class FixSessionResult(BaseModel):
    session_id: str
    repository_id: str
    task_id: str
    branch_name: str
    status: FixStatus
    issues_requested: int
    issues_fixed: int
    issues_failed: int
    issues_skipped: int
    results: list[IssueFixResult]
```

---

## API Endpoints

### Start Fix Session (SSE)
```
POST /api/fix/start
Content-Type: application/json

{
  "repository_id": "uuid",
  "task_id": "uuid",
  "issue_ids": ["id1", "id2", "id3"],
  "use_existing_branch": false,
  "user_notes": "Usa il nuovo endpoint /api/v2/users"
}
```

**Response**: Server-Sent Events stream

### Pre-Fix Clarification
```
POST /api/fix/clarify
{
  "repository_id": "uuid",
  "issue_ids": ["id1", "id2"],
  "session_id": null,  // First call
  "answers": null
}
```

### List Issues
```
GET /api/fix/issues/{repository_id}?status=open&severity=CRITICAL&task_id=uuid
```

### Update Issue Status
```
PATCH /api/fix/issues/{issue_id}
{
  "status": "resolved",
  "resolution_note": "Fixed in PR #123"
}
```

---

## SSE Events

Durante l'esecuzione, il frontend riceve eventi in tempo reale:

| Event | Description |
|-------|-------------|
| `fix_session_started` | Sessione iniziata |
| `fix_issue_started` | Fix singola issue iniziato |
| `fix_issue_validating` | Validazione issue in corso |
| `fix_issue_generating` | Generazione fix in corso |
| `fix_issue_streaming` | Streaming output Claude |
| `fix_challenger_evaluating` | Challenger sta valutando |
| `fix_challenger_result` | Risultato challenger |
| `fix_issue_committed` | Issue committata |
| `fix_session_completed` | Sessione completata |
| `fix_session_error` | Errore sessione |

**Event payload esempio:**
```json
{
  "type": "fix_issue_completed",
  "timestamp": "2025-01-15T10:30:00Z",
  "session_id": "abc123",
  "issue_id": "uuid",
  "issue_code": "FUNC-001",
  "issue_index": 1,
  "total_issues": 5,
  "message": "Issue fixed successfully",
  "commit_sha": "a1b2c3d"
}
```

---

## Configuration

### Settings (config.py)
```python
class FixChallengerSettings:
    max_iterations: int = 2  # 1 fix + 1 re-fix
    satisfaction_threshold: float = 95.0  # Score minimo per SOLVED
```

### Timeouts
```python
CLAUDE_CLI_TIMEOUT = 900  # 15 minutes per fix
GEMINI_CLI_TIMEOUT = 120  # 2 minutes per review
```

### Batching Limits
```python
MAX_ISSUES_PER_CLI_CALL = 5  # Fallback se no estimates
MAX_WORKLOAD_POINTS_PER_BATCH = 15  # Basato su effort
DEFAULT_EFFORT = 3  # Se effort non stimato
```

### Session Token Management
```python
MAX_SESSION_TOKENS = 150_000  # Limit before /compact
```

Quando il context supera questo limite, viene triggerato `/compact` per comprimere la sessione Claude.

---

## Storage

### S3
- **Bucket**: `turbowrap-thinking`
- **Prefix**: `fix-logs/`
- **Contenuto**: Thinking logs, TODO lists, artifacts
- **Lifecycle**: 10 giorni retention

### Database
- **Tabella `issues`**: Issue con stato fix
  - `status`: open, in_progress, resolved, ignored
  - `fix_code`: Snippet del fix
  - `fix_explanation`: Spiegazione PR-style
  - `fix_files_modified`: Lista file modificati
  - `fix_commit_sha`: SHA del commit
  - `fix_branch`: Nome branch

---

## Scope Validation (Monorepo)

Per monorepo, è possibile limitare i fix a una sottocartella:

```json
{
  "workspace_path": "packages/frontend",
  "allowed_extra_paths": ["packages/shared"]
}
```

Se Claude modifica file fuori scope:
1. Viene sollevato `ScopeValidationError`
2. UI mostra prompt all'utente
3. Utente può approvare o rifiutare
4. Se rifiutato, tutte le modifiche vengono revertate

---

## Idempotency

Il sistema previene duplicati usando idempotency key:
- **Key**: Hash di `repository_id + task_id + sorted(issue_ids)`
- **TTL**: 1 ora
- **Bypass**: `force: true` per sessioni bloccate

---

## Error Handling

### BillingError
Se Claude ritorna errore di crediti insufficienti:
- Evento `fix_billing_error` inviato
- Sessione terminata con errore
- UI mostra messaggio appropriato

### Scope Violation
Se fix modifica file fuori workspace:
- `ScopeValidationError` raised
- Prompt interattivo all'utente
- Possibilità di approvare o revertare

### CLI Timeout
Se Claude/Gemini CLI non risponde:
- Timeout configurabile per CLI
- Issue marcata come `failed`
- Sessione continua con altre issue

---

## Best Practices

### Per gli utenti

1. **Seleziona issue correlate** - Fix insieme issue che hanno senso insieme
2. **Usa clarification** - Per issue complesse, la fase di clarification migliora i risultati
3. **Fornisci user_notes** - Contesto aggiuntivo aiuta Claude
4. **Review prima di push** - Il fix non pusha automaticamente

### Per lo sviluppo

1. **Agent minimali** - Ogni agent fa UNA cosa
2. **JSON output** - Sempre JSON parsabile per automazione
3. **Self-evaluation** - Fixer valuta la propria confidence
4. **Challenger indipendente** - Non fidarsi mai solo del fixer

---

## Troubleshooting

### Fix bloccato
- Usa `force: true` per bypassare idempotency
- Controlla logs S3 per dettagli
- Verifica timeout settings

### Score sempre basso
- Verifica che suggested_fix sia corretto
- Controlla se issue è troppo vaga
- Considera di splittare in issue più piccole

### Commit fallito
- Verifica permessi git
- Controlla se branch esiste già
- Verifica conflitti con main

### Scope violation frequente
- Rivedi `workspace_path` configuration
- Aggiungi paths necessari a `allowed_extra_paths`
- Considera se issue richiede cross-package changes
