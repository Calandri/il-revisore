# Fix System Architecture

## Overview

Il sistema usa **Claude CLI** e **Gemini CLI** come agenti autonomi.
Entrambi hanno accesso completo al sistema (file, git, terminal).
**Nessuna comunicazione diretta tra i modelli** per evitare influenze.

---

## Fix Issue Flow (Sequential with Dynamic Batching)

```
┌─────────────────────────────────────────────────────────────────┐
│              FIX ISSUE FLOW (SEQUENTIAL + BATCHING)             │
└─────────────────────────────────────────────────────────────────┘

     Issues (from DB)
          │
          ▼
    ┌─────────────┐
    │  Classify   │ → be_issues[], fe_issues[]
    │  by file    │
    │  extension  │
    └─────────────┘
          │
          ▼
    ┌─────────────────────────────────────────────────────────┐
    │              DYNAMIC BATCHING BY WORKLOAD                │
    │                                                          │
    │  workload = estimated_effort × estimated_files_count     │
    │  Max 15 workload points per batch OR max 5 issues        │
    │                                                          │
    │  If no estimates: default effort=3, files=1 (3 points)   │
    └─────────────────────────────────────────────────────────┘
          │
          │
          ▼ SEQUENTIAL: First ALL BE batches, then ALL FE batches
          │
┌─────────────────────────────────────────────────────────────────┐
│   BE Batch 1/N    │   BE Batch 2/N    │   ...   │   BE Batch N  │
│   Claude CLI      │   Claude CLI      │         │   Claude CLI  │
│   fixer.md        │   fixer.md        │         │   fixer.md    │
│   + dev_be.md     │   + dev_be.md     │         │   + dev_be.md │
│   workload=12     │   workload=9      │         │   workload=6  │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼ (after all BE complete)
          │
┌─────────────────────────────────────────────────────────────────┐
│   FE Batch 1/M    │   FE Batch 2/M    │   ...   │   FE Batch M  │
│   Claude CLI      │   Claude CLI      │         │   Claude CLI  │
│   fixer.md        │   fixer.md        │         │   fixer.md    │
│   + dev_fe.md     │   + dev_fe.md     │         │   + dev_fe.md │
│   workload=10     │   workload=14     │         │   workload=5  │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
    ┌─────────────────────┐
    │   Gemini CLI        │  ← Pro + Thinking
    │   (Reviewer)        │
    │                     │
    │   - git diff ALL    │
    │   - Score 0-100     │
    │   - Feedback        │
    └─────────────────────┘
          │
          ▼
    ┌─────────────┐
    │ Score >= N% │──────────────────┐
    │ (threshold) │                  │
    └─────────────┘                  │
          │ NO                       │ YES
          ▼                          ▼
    ┌─────────────┐           ┌─────────────┐
    │ iteration   │           │   COMMIT    │
    │ < max (3)?  │           │   ALL fixes │
    └─────────────┘           └─────────────┘
          │ YES                      │
          │                          ▼
          └──► retry with feedback  DONE

⚠️ CRITICAL: Only issues with files in commit are marked RESOLVED
   Issues where CLI crashed or file not committed stay OPEN/FAILED
```

### Why Sequential Instead of Parallel?

macOS has a limit on file watchers. Running multiple Claude CLI processes
in parallel caused `EOPNOTSUPP` errors when the limit was exhausted.
Sequential execution avoids this issue.

---

## Issue Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                      ISSUE STATUS LIFECYCLE                      │
└─────────────────────────────────────────────────────────────────┘

    ┌──────────┐
    │   OPEN   │ ◄── Created by reviewer
    └────┬─────┘
         │
         │ Fix started
         ▼
    ┌──────────────┐
    │ IN_PROGRESS  │ ◄── Being worked on
    └──────┬───────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
┌──────────┐  ┌──────────┐
│ RESOLVED │  │  FAILED  │ ◄── CLI crashed / file not in commit
└────┬─────┘  └──────────┘
     │
     │ PR merged
     ▼
┌──────────┐
│  MERGED  │ ◄── Automatically set when PR is merged
└──────────┘

Other statuses:
  - IGNORED: False positive or won't fix
  - DUPLICATE: Duplicate of another issue
```

---

## Workload Estimation

Reviewers estimate fix complexity for dynamic batching:

| Field | Range | Description |
|-------|-------|-------------|
| `estimated_effort` | 1-5 | Fix complexity (1=trivial, 5=major refactor) |
| `estimated_files_count` | 1+ | Number of files to modify |

### Workload Formula

```
workload_points = estimated_effort × estimated_files_count
```

### Batching Rules

- Max **15 workload points** per batch
- Max **5 issues** per batch (hard limit)
- If no estimates: defaults to effort=3, files=1 (3 points)

### Examples

| Issue | Effort | Files | Workload | Batch Decision |
|-------|--------|-------|----------|----------------|
| Typo fix | 1 | 1 | 1 | Can fit many in one batch |
| Add validation | 2 | 1 | 2 | ~7 per batch |
| Refactor service | 4 | 3 | 12 | 1 per batch |
| Architectural change | 5 | 5 | 25 | Split across batches |

---

## PR Review Flow (Coming Soon)

```
┌─────────────────────────────────────────────────────────────────┐
│                        PR REVIEW FLOW                           │
└─────────────────────────────────────────────────────────────────┘

     Pull Request
          │
          ├────────────────────┬────────────────────┐
          │                    │                    │
          ▼                    ▼                    │
┌─────────────────┐  ┌─────────────────┐           │
│   Claude CLI    │  │   Gemini CLI    │           │
│   (Opus)        │  │   (Pro)         │           │
│                 │  │                 │           │
│   + Thinking    │  │   + Thinking    │           │
│                 │  │                 │           │
│   - Legge diff  │  │   - Legge diff  │           │
│   - Analizza    │  │   - Analizza    │           │
│   - Voto 0-100  │  │   - Voto 0-100  │           │
│   - Feedback    │  │   - Feedback    │           │
└─────────────────┘  └─────────────────┘           │
          │                    │                    │
          ▼                    ▼                    │
    ┌─────────────────────────────────────┐        │
    │      2 VOTI INDIPENDENTI            │        │
    │                                     │        │
    │   Claude: 85/100 - "Good but..."    │        │
    │   Gemini: 78/100 - "Needs..."       │        │
    │                                     │        │
    │   Average: 81.5/100                 │        │
    └─────────────────────────────────────┘        │
                      │                            │
                      ▼                            │
              ┌───────────────┐                    │
              │   APPROVED?   │                    │
              │  avg >= 80%   │                    │
              └───────────────┘                    │
                                                   │
     ⚠️ NO COMMUNICATION BETWEEN MODELS ⚠️         │
     Each reviews independently                    │
                                                   │
└──────────────────────────────────────────────────┘
```

---

## Configuration

Settings in `config/settings.yaml`:

```yaml
fix_challenger:
  enabled: true
  max_iterations: 3              # Max retry loops
  satisfaction_threshold: 95.0   # N% required to approve

  # Gemini settings
  model: "gemini-2.5-pro"
  thinking_budget: 10000         # Thinking tokens for Gemini
```

---

## Key Principles

1. **Full Autonomy**: Both CLIs have complete system access
2. **No Cross-Talk**: Models never communicate directly
3. **Always Thinking**: Both use extended thinking mode
4. **Independent Reviews**: For PR review, 2 separate votes
5. **Iterative Fix**: Up to 3 attempts with feedback loop

---

## CLI Commands

### Claude CLI (Fixer)
```bash
claude --print --dangerously-skip-permissions
```
- Reads prompt from stdin
- Has full file/git access
- Uses Opus model with thinking

### Gemini CLI (Reviewer)
```bash
gemini
```
- Reads prompt from stdin
- Has full file/git access
- Uses Pro model with thinking

---

## Models Used

| Role | Model | Thinking | Agent Files |
|------|-------|----------|-------------|
| Fixer | Claude Opus 4.5 | Extended (20k tokens) | `fixer.md` + `dev_be.md`/`dev_fe.md` |
| Reviewer | Gemini 2.5 Pro | Enabled (10k tokens) | `fix_challenger.md` |
| PR Review (Claude) | Claude Opus 4.5 | Extended (20k tokens) | `reviewer_be_*.md` / `reviewer_fe_*.md` |
| PR Review (Gemini) | Gemini 2.5 Pro | Enabled (10k tokens) | `reviewer_be_*.md` / `reviewer_fe_*.md` |

---

## Agent Files

I file agent in `agents/` vengono caricati automaticamente:

```
agents/
├── fixer.md                 # Prompt base per Claude fixer
├── fix_challenger.md        # Prompt per Gemini reviewer
├── dev_be.md                # Guidelines backend (Python, FastAPI)
├── dev_fe.md                # Guidelines frontend (React, Next.js)
├── engineering_principles.md # Principi di ingegneria generali
├── reviewer_be_*.md         # Reviewer backend (architecture, quality)
└── reviewer_fe_*.md         # Reviewer frontend (architecture, quality)
```

### Selezione Automatica Agent

L'orchestrator seleziona automaticamente l'agent giusto in base all'estensione del file:

| Estensione | Agent |
|------------|-------|
| `.py`, `.go`, `.java`, `.rb`, `.php`, `.rs`, `.c`, `.cpp` | `dev_be.md` |
| `.tsx`, `.ts`, `.jsx`, `.js`, `.css`, `.scss`, `.vue`, `.svelte` | `dev_fe.md` |
