# Fix System Architecture

## Overview

The system uses **Claude CLI** and **Gemini CLI** as autonomous agents.
Both have full system access (files, git, terminal).
**No direct communication between models** to avoid influences.

---

## Fix Issue Flow (ONE CLI Call with Multi-Agent)

```
┌─────────────────────────────────────────────────────────────────┐
│           FIX ISSUE FLOW (ONE CLI + TASK TOOL)                   │
└─────────────────────────────────────────────────────────────────┘

     Issues (from DB)
          │
          ▼
    ┌─────────────────┐
    │   Plan Phase    │ → master_todo.json + fix_todo_{code}.json files
    │   (TodoManager) │
    └─────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ONE CLI CALL TO FIXER.MD                       │
│                                                                   │
│   orchestrator.py → _run_claude_cli(agent_type="fixer")          │
│                                                                   │
│   fixer.md internally uses Task tool:                            │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ 1. Read master_todo.json                                 │   │
│   │ 2. Task(git-branch-creator) → create branch              │   │
│   │ 3. For each step in execution_steps:                     │   │
│   │    - Step 1: Task(fixer-single) × N in ONE message      │   │
│   │      → PARALLEL (issues on different files)              │   │
│   │    - Step 2: Task(fixer-single) × M in separate msgs    │   │
│   │      → SERIAL (issues on same file, after step 1)        │   │
│   │ 4. Aggregate results → JSON output                       │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
    ┌─────────────────────┐
    │   Gemini CLI        │  ← Pro + Thinking
    │   (Challenger)      │
    │                     │
    │   - git diff ALL    │
    │   - Score 0-100     │
    │   - Per-issue status│
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
    │ < max (2)?  │           │   ALL fixes │
    └─────────────┘           └─────────────┘
          │ YES                      │
          │                          ▼
          └──► re-fix with feedback  DONE

⚠️ CRITICAL: Only issues with files in commit are marked RESOLVED
   Issues where CLI crashed or file not committed stay OPEN/FAILED
```

### Why ONE CLI Call Instead of Parallel?

Previous approach launched N parallel CLI processes from Python using `asyncio.gather()`.
This was **wrong** because it bypassed Claude CLI's native multi-agent architecture.

**Correct approach**: ONE CLI call to `fixer.md` which uses the **Task tool** internally
to spawn sub-agents. Parallelism is achieved by sending multiple `Task()` calls in
a single message.

---

## TODO File Structure

```
/tmp/fix_session_{session_id}/
├── master_todo.json              # Execution plan (steps, parallel/serial)
├── fix_todo_BE-001.json          # Issue 1: details + clarifications + plan
├── fix_todo_BE-002.json          # Issue 2: details + clarifications + plan
└── fix_todo_FE-001.json          # Issue 3: details + clarifications + plan
```

### master_todo.json

Contains `execution_steps` array. Each step has issues that run in parallel.
Steps run sequentially (step 1 completes before step 2 starts).

### fix_todo_{code}.json

Contains everything a sub-agent needs:
- Issue details (title, file, line, description)
- Clarifications (Q&A from user)
- Context (code snippets, related files, existing patterns)
- Plan (approach, steps, verification)

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

## Session Continuity

All phases share ONE Claude session via resume:

```
/clarify → CREATE session A
    ↓ resume
/plan → RESUME session A → A'
    ↓ resume
/start → RESUME session A' → A''
    ↓ resume
/re-fix → RESUME session A'' → A'''
```

Benefits:
- Clarifications preserved throughout
- Context accumulates (no repetition)
- Token efficiency

---

## Models Used

| Role | Model | Agent File |
|------|-------|------------|
| Fix Orchestrator | Claude Opus | `fixer.md` |
| Fix Sub-Agent | Claude Opus | `fixer-single.md` |
| Branch Creator | Claude Haiku | `git-branch-creator.md` |
| Committer | Claude Haiku | `git-committer.md` |
| Challenger | Gemini Flash | `fix_challenger.md` |
| Re-Fixer | Claude Opus | `re_fixer.md` |

---

## Agent Files

```
agents/
├── fixer.md                 # Orchestrator (reads master_todo.json, spawns sub-agents)
├── fixer_single.md          # Sub-agent (reads fix_todo_{code}.json, fixes ONE issue)
├── fix_challenger.md        # Gemini challenger (evaluates fixes per-issue)
├── re_fixer.md              # Re-fix agent (uses challenger feedback)
├── git-branch-creator.md    # Creates git branch (Haiku)
├── git-committer.md         # Commits changes (Haiku)
├── dev_be.md                # Backend guidelines (Python, FastAPI)
└── dev_fe.md                # Frontend guidelines (React, Next.js)
```

---

## Configuration

```yaml
fix_challenger:
  enabled: true
  max_iterations: 2              # 1 fix + 1 re-fix max
  satisfaction_threshold: 95.0   # Score required to pass
```

---

## Key Principles

1. **ONE CLI Call**: Never launch parallel CLI processes from Python
2. **Task Tool for Parallelism**: Let Claude handle parallel execution internally
3. **Full Autonomy**: CLIs have complete system access
4. **No Cross-Talk**: Models never communicate directly
5. **Independent Reviews**: Challenger validates fixer independently
6. **Session Resume**: All phases share one Claude session
