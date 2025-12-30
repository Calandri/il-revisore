# Review System - Multi-Agent Code Review

## Overview

Il Review System è il cuore di TurboWrap: un sistema di code review multi-agente che utilizza specialisti diversificati coordinati da un challenger loop iterativo.

**Reviewer**: Claude CLI (Opus) - Specialisti per dominio
**Challenger**: Gemini CLI - Valutazione qualità review
**Modalità**: Challenger Loop (iterativo) o Triple-LLM (parallelo)

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                                │
│                (src/turbowrap/review/orchestrator.py)               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           │                       │                       │
           ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Repo Detection │    │ Reviewer Select │    │  Final Report   │
│  (BE/FE/Full)   │    │ (per repo type) │    │   Generation    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ Challenger    │      │ Challenger    │      │ Challenger    │
│ Loop (BE)     │      │ Loop (FE)     │      │ Loop (Func)   │
└───────────────┘      └───────────────┘      └───────────────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ Claude CLI    │◄────►│ Claude CLI    │◄────►│ Claude CLI    │
│ (Reviewer)    │      │ (Reviewer)    │      │ (Analyst)     │
└───────────────┘      └───────────────┘      └───────────────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ Gemini CLI    │      │ Gemini CLI    │      │ Gemini CLI    │
│ (Challenger)  │      │ (Challenger)  │      │ (Challenger)  │
└───────────────┘      └───────────────┘      └───────────────┘
```

---

## Workflow Completo

### 1. Repository Detection

L'orchestrator analizza il repository per determinare il tipo:

| Tipo | Indicatori | Reviewers Attivati |
|------|------------|-------------------|
| **BACKEND** | `*.py`, `requirements.txt`, `pyproject.toml` | BE Quality, BE Architecture, BE Dedup |
| **FRONTEND** | `*.tsx`, `*.ts`, `package.json`, `tsconfig.json` | FE Quality, FE Architecture, FE Dedup |
| **FULLSTACK** | Entrambi | Tutti i reviewers |

### 2. Reviewer Selection

In base al tipo di repository, vengono selezionati gli specialisti:

**Backend Reviewers:**
- `reviewer_be_quality` - Linting, security, type safety
- `reviewer_be_architecture` - SOLID, patterns, layer separation
- `reviewer_dedup_be` - Code duplication, centralization

**Frontend Reviewers:**
- `reviewer_fe_quality` - ESLint, TypeScript, React best practices
- `reviewer_fe_architecture` - Component organization, state management
- `reviewer_dedup_fe` - Duplication, repeated patterns

**Cross-Stack:**
- `analyst_func` - Functional analysis (opzionale)

### 3. Challenger Loop

Ogni reviewer esegue un loop iterativo con challenger:

```
┌──────────────────────────────────────────────────────────────┐
│                    CHALLENGER LOOP                           │
│                                                              │
│  Iteration 1:                                                │
│    Claude CLI (Reviewer) → Initial Review                    │
│    Gemini CLI (Challenger) → Score: 65%                     │
│                                                              │
│  Iteration 2:                                                │
│    Claude CLI (Reviewer) → Refined Review (with feedback)   │
│    Gemini CLI (Challenger) → Score: 85%                     │
│                                                              │
│  Iteration 3:                                                │
│    Claude CLI (Reviewer) → Final Refinement                 │
│    Gemini CLI (Challenger) → Score: 92% ✓ (threshold met)   │
│                                                              │
│  Exit: Threshold 90% reached                                │
└──────────────────────────────────────────────────────────────┘
```

**Condizioni di uscita:**
1. `satisfaction_threshold` raggiunta (default: 90%)
2. `max_iterations` raggiunto (default: 3, max: 10)
3. Stagnazione rilevata (no improvement)
4. `forced_acceptance_threshold` (se > 70% dopo max iterations)

### 4. Issue Aggregation

Dopo tutti i challenger loops:
1. **Deduplicazione** - Merge issue duplicate da reviewers diversi
2. **Prioritizzazione** - Ordinamento per severity/impact
3. **Score Calculation** - Overall score (0-10)
4. **Recommendation** - APPROVE, APPROVE_WITH_CHANGES, REQUEST_CHANGES

### 5. Report Generation

Output finale con:
- Summary esecutivo
- Issue per severity
- Checklist results
- Metrics (complexity, coverage)
- Next steps prioritizzati
- Repository evaluation scores

---

## Specialisti (Agents)

### reviewer_be_quality.md
- **Model**: Opus
- **Focus**: Code quality, linting, security
- **Linters**: Ruff, Bandit, mypy
- **Checks**:
  - Pyflakes (F), pycodestyle (E/W)
  - flake8-bugbear (B), comprehensions (C4)
  - OWASP Top 10 security
  - Type annotations
  - Async best practices

### reviewer_be_architecture.md
- **Model**: Opus
- **Focus**: Architecture, SOLID, patterns
- **Checks**:
  - Layer separation (routes → services → repos)
  - Dependency injection
  - Single responsibility
  - Domain boundaries

### reviewer_fe_quality.md
- **Model**: Opus
- **Focus**: TypeScript, React, performance
- **Checks**:
  - ESLint rules
  - TypeScript strict mode
  - React hooks rules
  - Web Vitals
  - Accessibility (a11y)

### reviewer_fe_architecture.md
- **Model**: Opus
- **Focus**: Component design, state management
- **Checks**:
  - Component organization
  - Props/state patterns
  - Context usage
  - Code splitting

### reviewer_dedup_be.md / reviewer_dedup_fe.md
- **Model**: Opus
- **Focus**: Code duplication
- **Checks**:
  - Repeated logic
  - Copy-paste code
  - Centralization opportunities
  - Utility extraction

### analyst_func.md
- **Model**: Opus
- **Focus**: Functional correctness
- **Checks**:
  - Business logic implementation
  - Edge cases
  - Requirements coverage
  - Integration points

---

## Models

### Issue
```python
class Issue(BaseModel):
    id: str                    # e.g., "BE-CRIT-001"
    severity: IssueSeverity    # CRITICAL, HIGH, MEDIUM, LOW
    category: IssueCategory    # security, performance, architecture, etc.
    file: str                  # File path
    line: int | None           # Line number
    title: str                 # Brief title
    description: str           # Detailed description
    current_code: str | None   # Problematic code
    suggested_fix: str | None  # Fix suggestion
    estimated_effort: int | None  # 1-5 scale
    flagged_by: list[str]      # Reviewers that found this
```

### IssueSeverity
```python
class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"  # Security vulnerabilities, data loss
    HIGH = "HIGH"          # Bugs, performance issues
    MEDIUM = "MEDIUM"      # Code quality, maintainability
    LOW = "LOW"            # Style, minor improvements
```

### IssueCategory
```python
class IssueCategory(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    STYLE = "style"
    LOGIC = "logic"
    UX = "ux"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
```

### ReviewOutput
```python
class ReviewOutput(BaseModel):
    reviewer: str              # Reviewer identifier
    timestamp: datetime
    duration_seconds: float
    iteration: int             # Challenger iteration
    summary: ReviewSummary
    issues: list[Issue]
    checklists: dict[str, ChecklistResult]
    metrics: ReviewMetrics
    model_usage: list[ModelUsageInfo]
```

### FinalReport
```python
class FinalReport(BaseModel):
    id: str                    # Report ID (rev_xxx)
    timestamp: datetime
    repository: RepositoryInfo
    summary: ReportSummary
    reviewers: list[ReviewerResult]
    challenger: ChallengerMetadata
    issues: list[Issue]        # Deduplicated
    checklists: dict[str, ChecklistResult]
    metrics: ReviewMetrics
    next_steps: list[NextStep]
    evaluation: RepositoryEvaluation | None
```

### Recommendation
```python
class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CHANGES = "APPROVE_WITH_CHANGES"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    NEEDS_DISCUSSION = "NEEDS_DISCUSSION"
```

### ConvergenceStatus
```python
class ConvergenceStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    THRESHOLD_MET = "THRESHOLD_MET"
    MAX_ITERATIONS_REACHED = "MAX_ITERATIONS_REACHED"
    STAGNATED = "STAGNATED"
    FORCED_ACCEPTANCE = "FORCED_ACCEPTANCE"
```

---

## API Endpoints

### Start Review (SSE)
```
POST /api/tasks
Content-Type: application/json

{
  "task_type": "review",
  "repository_id": "uuid",
  "config": {
    "mode": "diff",
    "include_functional": true,
    "challenger_enabled": true,
    "satisfaction_threshold": 90
  }
}
```

### Review Request
```python
class ReviewRequest(BaseModel):
    type: str                  # "pr", "commit", "files", "directory"
    source: ReviewRequestSource
    requirements: ReviewRequirements | None
    options: ReviewOptions
```

### Review Modes
```python
class ReviewMode(str, Enum):
    INITIAL = "initial"  # Full repo via STRUCTURE.md
    DIFF = "diff"        # Only changed files
```

---

## SSE Events

Durante la review, il frontend riceve eventi in tempo reale:

| Event | Description |
|-------|-------------|
| `review_started` | Review iniziata |
| `reviewer_started` | Singolo reviewer iniziato |
| `reviewer_streaming` | Streaming output Claude |
| `reviewer_completed` | Reviewer completato |
| `reviewer_error` | Errore reviewer |
| `challenger_started` | Challenger evaluation iniziata |
| `challenger_iteration` | Iterazione challenger |
| `review_completed` | Review completata |
| `review_error` | Errore globale |

**Event payload:**
```json
{
  "type": "reviewer_completed",
  "review_id": "rev_abc123",
  "reviewer_name": "reviewer_be_quality",
  "reviewer_display_name": "Backend Quality",
  "iteration": 2,
  "satisfaction_score": 92.5,
  "issues_found": 15,
  "message": "Backend Quality completed with 15 issues"
}
```

---

## Configuration

### ChallengerSettings (config.py)
```python
class ChallengerSettings:
    satisfaction_threshold: float = 90.0    # Score minimo per passare
    max_iterations: int = 3                 # Max iterazioni per reviewer
    min_improvement_threshold: float = 2.0  # Improvement minimo per iterazione
    stagnation_window: int = 2              # Iterazioni per detect stagnazione
    forced_acceptance_threshold: float = 70.0  # Accept se > dopo max iter
```

### Timeouts
```python
DEFAULT_CLI_TIMEOUT = 600  # 10 minutes per reviewer
ABSOLUTE_MAX_ITERATIONS = 10  # Safety cap
```

---

## Modalità Alternative

### Triple-LLM Mode (Parallel)

Invece del challenger loop, 3 LLM lavorano in parallelo:

```
┌─────────────────────────────────────────────────────────────┐
│                    TRIPLE-LLM MODE                          │
│                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │ Claude    │  │ Gemini    │  │ Grok      │               │
│  │ (All      │  │ (All      │  │ (All      │               │
│  │ Specs)    │  │ Specs)    │  │ Specs)    │               │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │
│        │              │              │                      │
│        └──────────────┼──────────────┘                      │
│                       ▼                                     │
│              ┌───────────────┐                              │
│              │   Aggregate   │                              │
│              │   & Dedup     │                              │
│              └───────────────┘                              │
└─────────────────────────────────────────────────────────────┘
```

**Vantaggi:**
- ~80% cost reduction (cache sharing within each LLM)
- Parallel execution (faster)
- Multi-perspective review

**Attivazione:**
```python
options = ReviewOptions(challenger_enabled=False)
```

---

## Challenger Feedback

Il challenger (Gemini) fornisce feedback strutturato:

```python
class ChallengerFeedback(BaseModel):
    satisfaction_score: float    # 0-100
    missed_issues: list[MissedIssue]
    challenges: list[Challenge]
    dimension_scores: DimensionScores
    positive_feedback: list[str]
    summary: str
```

### DimensionScores
```python
class DimensionScores(BaseModel):
    coverage: float      # Copertura del codice
    accuracy: float      # Precisione issue
    severity_calibration: float  # Severity appropriate
    actionability: float # Fix suggestions useful
    style: float         # Report quality
```

---

## Checkpoints (Resume)

Il sistema supporta resume da checkpoint:

1. **Salvataggio**: Dopo ogni reviewer completato
2. **Dati salvati**: Issues, satisfaction score, iterations, model usage
3. **Resume**: Skip reviewers già completati

```python
await orchestrator.review(
    request=request,
    completed_checkpoints={
        "reviewer_be_quality": {
            "issues_data": [...],
            "final_satisfaction": 92.5,
            "iterations": 2,
            "model_usage": [...]
        }
    }
)
```

---

## Storage

### S3
- **Bucket**: `turbowrap-thinking`
- **Prefixes**:
  - `reviews/{reviewer_name}/` - Review outputs
  - `prompts/` - Prompts inviati
  - `thinking/` - Thinking logs (extended thinking)

### Database
- **Tabella `tasks`**: Task di review
- **Tabella `issues`**: Issues trovate
- **Tabella `review_checkpoints`**: Checkpoint per resume

---

## Issue Output Format

I reviewers devono outputtare JSON nel seguente formato:

```json
{
  "summary": {
    "files_reviewed": 15,
    "critical_issues": 2,
    "high_issues": 5,
    "medium_issues": 10,
    "low_issues": 3,
    "score": 6.5
  },
  "issues": [
    {
      "id": "BE-CRIT-001",
      "severity": "CRITICAL",
      "category": "security",
      "rule": "B608",
      "file": "src/api/routes.py",
      "line": 42,
      "title": "SQL Injection Vulnerability",
      "description": "User input concatenated directly in SQL query",
      "current_code": "query = f\"SELECT * FROM users WHERE id = {user_id}\"",
      "suggested_fix": "query = \"SELECT * FROM users WHERE id = %s\"\ncursor.execute(query, (user_id,))",
      "estimated_effort": 2,
      "estimated_files_count": 1
    }
  ],
  "checklists": {
    "security": {"passed": 8, "failed": 2, "skipped": 0},
    "performance": {"passed": 5, "failed": 1, "skipped": 0}
  }
}
```

---

## Evaluation Scores

Il sistema calcola 6 dimensioni di qualità (0-100):

```python
class RepositoryEvaluation(BaseModel):
    code_quality: float      # Linting, best practices
    architecture: float      # Design patterns, SOLID
    security: float          # Vulnerabilities, OWASP
    performance: float       # Optimization, async
    maintainability: float   # Readability, documentation
    test_coverage: float     # Test quality and coverage

    @property
    def overall(self) -> float:
        # Weighted average
```

---

## Best Practices

### Per i Reviewers (Agents)

1. **Run linters first** - Sempre eseguire ruff/bandit/mypy prima
2. **Show code** - Sempre includere current_code e suggested_fix
3. **Be specific** - Descrizioni precise per l'AI fixer
4. **Estimate effort** - Aiuta il batching del fixer

### Per gli Utenti

1. **Usa DIFF mode** - Per PR/commits (più veloce)
2. **Abilita challenger** - Migliora qualità review
3. **Check resume** - Se review interrotta, riprende da checkpoint

### Per lo Sviluppo

1. **Agent modulari** - Un dominio per agent
2. **JSON output** - Sempre parsabile
3. **Checklist** - Ogni agent ha la sua checklist

---

## Troubleshooting

### Review bloccata
- Check logs S3 per errori CLI
- Verifica timeout settings
- Usa checkpoint resume se parziale

### Score sempre basso
- Il challenger è troppo strict? Abbassa threshold
- Reviewer non trova issue? Check agent prompt

### Duplicati nelle issue
- La deduplicazione è automatica
- Check `flagged_by` per vedere chi ha trovato l'issue

### Out of Memory
- Usa DIFF mode invece di INITIAL
- Limita files con `workspace_path`
