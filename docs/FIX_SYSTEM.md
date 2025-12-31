# Fix System - Automated Issue Remediation

## Overview

The Fix System is the automated remediation engine for issues found during code review.
It uses **Claude CLI** (fixer) and **Gemini CLI** (challenger) in an iterative loop to ensure high-quality fixes.

**Fixer**: Claude Opus (advanced reasoning for complex fixes)
**Challenger**: Gemini Flash (fast, economical evaluation)
**Threshold**: Score >= 90 to mark an issue as SOLVED

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FIX ORCHESTRATOR                            │
│                    (src/turbowrap/fix/orchestrator.py)              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ONE CLI call to fixer.md
                                   │
                                   ▼
              ┌─────────────────────────────────────────┐
              │          Claude CLI (fixer.md)          │
              │                                          │
              │  Reads: master_todo.json                 │
              │                                          │
              │  Internally launches via Task tool:      │
              │  ┌─────────────────────────────────────┐ │
              │  │ Task(git-branch-creator) → Branch   │ │
              │  └─────────────────────────────────────┘ │
              │                    ↓                     │
              │  ┌─────────────────────────────────────┐ │
              │  │ Step 1: PARALLEL (same message)     │ │
              │  │  Task(fixer-single) → Issue 1       │ │
              │  │  Task(fixer-single) → Issue 2       │ │
              │  └─────────────────────────────────────┘ │
              │                    ↓                     │
              │  ┌─────────────────────────────────────┐ │
              │  │ Step 2: SERIAL (after step 1)       │ │
              │  │  Task(fixer-single) → Issue 3       │ │
              │  └─────────────────────────────────────┘ │
              │                    ↓                     │
              │           Aggregate Results              │
              └─────────────────────────────────────────┘
                                   │
                                   ▼
              ┌─────────────────────────────────────────┐
              │         Gemini CLI (Challenger)          │
              │         Per-issue evaluation             │
              └─────────────────────────────────────────┘
                                   │
                                   ▼
              ┌─────────────────────────────────────────┐
              │             Git Repository               │
              │           (Branch + Commits)             │
              └─────────────────────────────────────────┘
```

### Key Principle: ONE CLI Call with Multi-Agent

The Python orchestrator makes **ONE** call to Claude CLI with the `fixer.md` agent.
The `fixer.md` agent then uses the **Task tool** internally to spawn sub-agents:

- **Parallel execution**: Multiple `Task()` calls in ONE message
- **Serial execution**: `Task()` calls in separate messages (wait between)

This leverages Claude CLI's native multi-agent architecture instead of launching multiple CLI processes from Python.

---

## Complete Workflow

### Phase 1: Clarify (Optional)

Before fixing, the user can enable a clarification phase where Claude analyzes issues and asks questions to clarify ambiguities.

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
  "questions_by_issue": [
    {
      "issue_code": "BE-001",
      "questions": [
        {
          "id": "BE-001-q1",
          "question": "How should the null case be handled?",
          "context": "Need to decide error handling strategy"
        }
      ]
    }
  ],
  "session_id": "clarify_abc123",
  "ready_to_plan": false
}
```

Continue until `ready_to_plan: true`, then proceed to Planning phase.

### Phase 2: Plan

The planner generates:
1. **master_todo.json** - Execution plan with steps (parallel/serial)
2. **fix_todo_{code}.json** - Detailed TODO for each issue

```
POST /api/fix/plan
{
  "repository_id": "uuid",
  "issue_ids": ["id1", "id2", ...],
  "clarify_session_id": "clarify_abc123"  // Resume session
}
```

**Generated Files:**
```
/tmp/fix_session_{session_id}/
├── master_todo.json              # Execution plan
├── fix_todo_BE-001.json          # Issue 1 details + clarifications + plan
├── fix_todo_BE-002.json          # Issue 2 details
└── fix_todo_FE-001.json          # Issue 3 details
```

### Phase 3: Fix Execution

ONE CLI call to `fixer.md` orchestrator:

```
POST /api/fix/start
{
  "repository_id": "uuid",
  "task_id": "uuid",
  "issue_ids": ["id1", "id2", "id3"],
  "master_todo_path": "/tmp/fix_session_abc123/master_todo.json",
  "clarify_session_id": "clarify_abc123"  // Resume session
}
```

**Execution Flow:**

1. **fixer.md** reads `master_todo.json`
2. Creates branch via `Task(git-branch-creator)`
3. For each step in `execution_steps`:
   - Launches ALL issues in the step in ONE message (parallel)
   - Waits for step completion before next step (serial between steps)
4. Each `fixer-single` sub-agent reads its own `fix_todo_{code}.json`
5. Aggregates results and returns JSON

### Phase 4: Challenger Evaluation

After fix execution, Gemini evaluates EACH issue individually:

```json
{
  "issues": {
    "BE-001": {
      "score": 95,
      "status": "SOLVED",
      "feedback": "Fix correct, null check implemented properly",
      "quality_scores": {
        "correctness": 100,
        "safety": 90,
        "style": 95
      }
    },
    "BE-002": {
      "score": 70,
      "status": "IN_PROGRESS",
      "feedback": "Partial fix, missing edge case handling",
      "improvements_needed": ["Handle empty array case"]
    }
  }
}
```

**Threshold**: Score >= 90 = **SOLVED**

### Phase 5: Re-Fix (if needed)

If challenger score < 90:
1. Feedback sent to `re_fixer.md` agent
2. Re-fix with problem context
3. New challenger round
4. Max 2 iterations (1 fix + 1 re-fix)

### Phase 6: Commit

After all fixes complete:
- **Agent**: `git-committer` (Haiku)
- **Commit message**: Auto-generated with issue codes
- **No automatic push**: User decides when to push

---

## TODO File Formats

### master_todo.json

```json
{
  "session_id": "abc123",
  "branch_name": "fix/abc123",
  "execution_steps": [
    {
      "step": 1,
      "reason": "Issues on different files - can run in parallel",
      "issues": [
        {
          "code": "BE-001",
          "todo_file": "/tmp/fix_session_abc123/fix_todo_BE-001.json",
          "agent_type": "fixer-single"
        },
        {
          "code": "BE-002",
          "todo_file": "/tmp/fix_session_abc123/fix_todo_BE-002.json",
          "agent_type": "fixer-single"
        }
      ]
    },
    {
      "step": 2,
      "reason": "Issues on same file - must run after step 1",
      "issues": [
        {
          "code": "BE-003",
          "todo_file": "/tmp/fix_session_abc123/fix_todo_BE-003.json",
          "agent_type": "fixer-single"
        }
      ]
    }
  ],
  "summary": {
    "total_issues": 3,
    "total_steps": 2
  }
}
```

### fix_todo_{code}.json

```json
{
  "issue_code": "BE-001",
  "issue_id": "uuid",
  "file": "src/api/routes.py",
  "line": 42,
  "title": "Missing null check causes crash",
  "clarifications": [
    {
      "question_id": "BE-001-q1",
      "question": "How should the null case be handled?",
      "answer": "Return 404 with error message",
      "context": "Need to decide error handling strategy"
    }
  ],
  "context": {
    "file_content_snippet": "def get_user(user_id):\n    return db.query(User)...",
    "related_files": [
      {"path": "src/models/user.py", "reason": "User model definition"}
    ],
    "existing_patterns": ["Other endpoints return 404 for not found"]
  },
  "plan": {
    "approach": "patch",
    "steps": [
      "Add null check at line 42",
      "Return 404 response if null"
    ],
    "estimated_lines_changed": 5,
    "risks": [],
    "verification": "Call endpoint with non-existent user_id, expect 404"
  }
}
```

---

## Agents

### fixer.md (Orchestrator)
- **Model**: Opus
- **Role**: Coordinates branch creation and parallel/serial fixes
- **Input**: `master_todo.json` path
- **Output**: Aggregated results JSON
- **Uses**: Task tool to spawn sub-agents

### fixer-single.md (Sub-Agent)
- **Model**: Opus
- **Role**: Fixes ONE single issue
- **Input**: `fix_todo_{code}.json` path
- **Output**: Fix result JSON
- **Rules**:
  - Read TODO file first (has clarifications and context)
  - Fix ONLY the assigned issue
  - NO git commands
  - Use Edit tool to save changes
  - Follow the plan from TODO file
  - Respect user clarifications

### fix_challenger.md (Evaluator)
- **Model**: Sonnet
- **Role**: Evaluates fix quality per-issue
- **Input**: Git diff + Issue list + Fixer output
- **Output**: Per-issue scores and status

### re_fixer.md (Re-Fix Agent)
- **Model**: Opus
- **Role**: Fixes issues based on challenger feedback
- **Input**: Issue + Previous fix + Challenger feedback
- **Output**: Improved fix

### git-branch-creator.md
- **Model**: Haiku
- **Role**: Creates git branch
- **Input**: Branch name
- **Output**: Branch created confirmation

### git-committer.md
- **Model**: Haiku
- **Role**: Commits changes
- **Input**: Files modified + commit message
- **Output**: Commit SHA

---

## Session Continuity

The fix system maintains session continuity across phases using Claude CLI's resume feature:

```
Clarify (creates session A)
    ↓ resume
Plan (continues session A → A')
    ↓ resume
Fix (continues session A' → A'')
    ↓ resume
Re-Fix (if needed, continues A'' → A''')
```

This ensures:
- Clarifications are preserved throughout
- Context accumulates (no repetition)
- Token efficiency (reuses existing context)

---

## API Endpoints

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

### Planning Phase
```
POST /api/fix/plan
{
  "repository_id": "uuid",
  "issue_ids": ["id1", "id2"],
  "clarify_session_id": "abc123"
}
```

### Start Fix Session (SSE)
```
POST /api/fix/start
{
  "repository_id": "uuid",
  "task_id": "uuid",
  "issue_ids": ["id1", "id2", "id3"],
  "master_todo_path": "/tmp/fix_session_abc123/master_todo.json",
  "clarify_session_id": "abc123"
}
```

**Response**: Server-Sent Events stream

---

## SSE Events

| Event | Description |
|-------|-------------|
| `fix_session_started` | Session started |
| `fix_step_started` | Step started (with step number) |
| `fix_issue_streaming` | Streaming output from Claude |
| `fix_step_completed` | Step completed |
| `fix_challenger_evaluating` | Challenger is evaluating |
| `fix_challenger_result` | Challenger result |
| `fix_session_completed` | Session completed |
| `fix_session_error` | Session error |

---

## Configuration

### Settings (config.py)
```python
class FixChallengerSettings:
    max_iterations: int = 2  # 1 fix + 1 re-fix
    satisfaction_threshold: float = 95.0  # Minimum score for SOLVED
```

### Timeouts
```python
CLAUDE_CLI_TIMEOUT = 900  # 15 minutes per fix
GEMINI_CLI_TIMEOUT = 120  # 2 minutes per review
```

---

## Storage

### S3
- **Bucket**: `turbowrap-thinking`
- **Prefix**: `fix-todos/`
- **Content**: TODO files, thinking logs, artifacts
- **Lifecycle**: 10 days retention

### Local
- **Path**: `/tmp/fix_session_{session_id}/`
- **Content**: master_todo.json, fix_todo_{code}.json files
- **Cleanup**: After session completion

---

## Best Practices

### For Users

1. **Use clarification** - For complex issues, the clarification phase improves results
2. **Group related issues** - Fix issues that make sense together
3. **Provide user_notes** - Additional context helps Claude
4. **Review before push** - Fixes don't push automatically

### For Development

1. **One CLI call** - Never launch parallel CLI processes from Python
2. **Task tool for parallelism** - Let Claude handle parallel execution internally
3. **JSON output** - Always parseable JSON for automation
4. **Self-evaluation** - Fixer evaluates its own confidence
5. **Independent challenger** - Never trust only the fixer
