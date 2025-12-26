# TurboWrap Architecture

## Overview

TurboWrap is an AI-powered code review and fix system that uses a **dual-LLM challenger pattern** to ensure high-quality reviews and fixes. It coordinates Claude (reviewer/fixer) and Gemini (challenger/validator) in iterative loops until quality thresholds are met.

---

## High-Level Architecture

```
                                    +------------------+
                                    |    Frontend UI   |
                                    |   (Web/CLI)      |
                                    +--------+---------+
                                             |
                                             | HTTP/WebSocket
                                             v
+-----------------------------------------------------------------------------------+
|                                    API Layer                                       |
|  +-------------+  +-------------+  +-------------+  +-------------+               |
|  | /review/*   |  | /fix/*      |  | /repos/*    |  | /linear/*   |               |
|  +-------------+  +-------------+  +-------------+  +-------------+               |
+-----------------------------------------------------------------------------------+
                                             |
                    +------------------------+------------------------+
                    |                        |                        |
                    v                        v                        v
          +------------------+     +------------------+     +------------------+
          | Review           |     | Fix              |     | Linear           |
          | Orchestrator     |     | Orchestrator     |     | Analyzer         |
          +--------+---------+     +--------+---------+     +--------+---------+
                   |                        |                        |
                   v                        v                        v
          +------------------+     +------------------+     +------------------+
          | Challenger Loop  |     | Challenger Loop  |     | Phase 1/2        |
          | (Review)         |     | (Fix)            |     | Analysis         |
          +--------+---------+     +--------+---------+     +--------+---------+
                   |                        |                        |
        +----------+----------+    +--------+--------+               |
        |                     |    |                 |               |
        v                     v    v                 v               v
+---------------+    +---------------+    +---------------+    +---------------+
| Claude CLI    |    | Gemini CLI    |    | Claude CLI    |    | Gemini CLI    |
| (Reviewer)    |    | (Challenger)  |    | (Fixer)       |    | (Validator)   |
+---------------+    +---------------+    +---------------+    +---------------+
        |                     |                  |                     |
        +----------+----------+                  +----------+----------+
                   |                                        |
                   v                                        v
          +------------------+                    +------------------+
          | Final Report     |                    | Git Commit       |
          | (JSON/Markdown)  |                    | (Branch + Push)  |
          +------------------+                    +------------------+
```

---

## Review Pipeline

### Flow Diagram

```
                    +-------------------+
                    |  ReviewRequest    |
                    |  - source (dir/PR)|
                    |  - options        |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Prepare Context   |
                    | - Load structure  |
                    | - Scan files      |
                    | - Git info        |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Detect Repo Type  |
                    | BE/FE/Fullstack   |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Select Reviewers  |
                    +--------+----------+
                             |
        +--------------------+--------------------+
        |                    |                    |
        v                    v                    v
+---------------+    +---------------+    +---------------+
| BE Arch       |    | BE Quality    |    | FE Arch       |  ... (parallel)
| Challenger    |    | Challenger    |    | Challenger    |
| Loop          |    | Loop          |    | Loop          |
+-------+-------+    +-------+-------+    +-------+-------+
        |                    |                    |
        +--------------------+--------------------+
                             |
                             v
                    +-------------------+
                    | Deduplicate &     |
                    | Prioritize Issues |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Run Evaluator     |
                    | (Claude Opus)     |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Build Final       |
                    | Report            |
                    +-------------------+
```

### Reviewer Types

```
+----------------------------------+
|         Reviewer Matrix          |
+----------------------------------+
| Repo Type  | Reviewers           |
+------------+---------------------+
| BACKEND    | - reviewer_be_arch  |
|            | - reviewer_be_qual  |
|            | - analyst_func (*)  |
+------------+---------------------+
| FRONTEND   | - reviewer_fe_arch  |
|            | - reviewer_fe_qual  |
|            | - analyst_func (*)  |
+------------+---------------------+
| FULLSTACK  | - reviewer_be_arch  |
|            | - reviewer_be_qual  |
|            | - reviewer_fe_arch  |
|            | - reviewer_fe_qual  |
|            | - analyst_func (*)  |
+------------+---------------------+

(*) Only if include_functional=True
```

---

## Challenger Loop (Core Pattern)

The heart of TurboWrap's quality assurance is the **Challenger Loop** - an iterative refinement pattern.

### Loop Mechanism

```
                           START
                             |
                             v
                    +-------------------+
                    | Initialize        |
                    | iteration = 0     |
                    | satisfaction = 0  |
                    +--------+----------+
                             |
            +----------------+
            |
            v
    +-------+-------+
    | iteration++   |
    | (max: 10)     |
    +-------+-------+
            |
            v
    +-------+-------+        +-------------------+
    | First         | YES    | Claude CLI        |
    | iteration?    +------->| Initial Review    |
    +-------+-------+        +--------+----------+
            | NO                      |
            v                         |
    +---------------+                 |
    | Claude CLI    |                 |
    | Refine with   |                 |
    | Feedback      |                 |
    +-------+-------+                 |
            |                         |
            +------------+------------+
                         |
                         v
                +--------+--------+
                | Gemini CLI      |
                | Challenge       |
                | (validate)      |
                +--------+--------+
                         |
                         v
                +--------+--------+
                | Parse Score &   |
                | Feedback        |
                +--------+--------+
                         |
                         v
            +------------+------------+
            |                         |
    +-------v-------+         +-------v-------+
    | satisfaction  | YES     | satisfaction  |
    | >= threshold? +-------->| < threshold?  |
    | (default 50%) |         | & iterations  |
    +---------------+         | < max?        |
            |                 +-------+-------+
            |                         | YES
            |                         |
            |                 +-------v-------+
            |                 | Stagnation    | NO
            |                 | detected?     +----+
            |                 +-------+-------+    |
            |                         | YES        |
            |                         |            |
            +------------+------------+            |
                         |                         |
                         v                         |
                +--------+--------+                |
                | Return Result   |<---------------+
                | - final_review  |
                | - iterations    |
                | - convergence   |
                +-----------------+
```

### Convergence States

```
+--------------------------------------------------+
|              Convergence Status                   |
+--------------------------------------------------+
| Status              | Condition                   |
+---------------------+-----------------------------+
| THRESHOLD_MET       | satisfaction >= threshold   |
+---------------------+-----------------------------+
| STAGNATED           | No improvement for N iters  |
|                     | (default N=3)               |
+---------------------+-----------------------------+
| FORCED_ACCEPTANCE   | Max iterations reached BUT  |
|                     | score > forced_threshold    |
+---------------------+-----------------------------+
| MAX_ITERATIONS      | Max iterations reached AND  |
| _REACHED            | score < forced_threshold    |
+---------------------+-----------------------------+

Hard Safety Limit: ABSOLUTE_MAX_ITERATIONS = 10
(Prevents infinite loops regardless of config)
```

---

## Fix Pipeline

### Flow Diagram

```
                    +-------------------+
                    |    FixRequest     |
                    | - task_id         |
                    | - repository_id   |
                    | - issues[]        |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Classify Issues   |
                    | BE vs FE          |
                    +--------+----------+
                             |
            +----------------+----------------+
            |                                 |
            v                                 v
    +---------------+                 +---------------+
    | BE Issues     |                 | FE Issues     |
    +-------+-------+                 +-------+-------+
            |                                 |
            v                                 v
    +---------------+                 +---------------+
    | Batch by      |                 | Batch by      |
    | Workload      |                 | Workload      |
    | (max 15 pts)  |                 | (max 15 pts)  |
    +-------+-------+                 +-------+-------+
            |                                 |
            +----------------+----------------+
                             |
                             v
                    +-------------------+
                    | Create/Checkout   |
                    | Branch            |
                    +--------+----------+
                             |
            +================+================+
            |     FOR EACH BATCH             |
            +================================+
                             |
                             v
                    +-------------------+
                    | Claude CLI Fix    |
                    | (dev_be/dev_fe)   |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Gemini CLI Review |
                    | (per batch)       |
                    +--------+----------+
                             |
                             v
                +------------+------------+
                |                         |
        +-------v-------+         +-------v-------+
        | Score >= 95%  |         | Score < 95%   |
        | PASSED        |         | RETRY         |
        +---------------+         +-------+-------+
                                          |
                                  (max 3 iterations)
            +================================+
                             |
                             v
                    +-------------------+
                    | Workspace Scope   |
                    | Validation        |
                    | (monorepo only)   |
                    +--------+----------+
                             |
                 +-----------+-----------+
                 |                       |
         +-------v-------+       +-------v-------+
         | Valid         |       | Violations!   |
         | Commit All    |       | REVERT ALL    |
         +---------------+       +---------------+
```

### Issue Batching

```
+------------------------------------------+
|           Batching Algorithm             |
+------------------------------------------+
| Constraint          | Value              |
+---------------------+--------------------+
| MAX_ISSUES_PER_BATCH| 5                  |
+---------------------+--------------------+
| MAX_WORKLOAD_POINTS | 15                 |
+---------------------+--------------------+
| Workload Formula    | effort * files     |
|                     | (default: 3 * 1)   |
+---------------------+--------------------+

Example:
  Issue A: effort=2, files=1 -> workload=2
  Issue B: effort=5, files=3 -> workload=15 (own batch!)
  Issue C: effort=1, files=1 -> workload=1

  Batch 1: [A, C] (total=3)
  Batch 2: [B]    (total=15)
```

---

## Issue Processing Pipeline

### Deduplication & Prioritization

```
                    +-------------------+
                    | Raw Issues        |
                    | (from all         |
                    | reviewers)        |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Deduplicate       |
                    | Key: file+line+   |
                    |      category     |
                    +--------+----------+
                             |
                    When merging:
                    - Keep HIGHEST severity
                    - Merge flagged_by lists
                    - Keep longest message
                             |
                             v
                    +-------------------+
                    | Calculate         |
                    | Priority Score    |
                    +--------+----------+
                             |
        +--------------------+--------------------+
        |                    |                    |
        v                    v                    v
+---------------+    +---------------+    +---------------+
| Severity      |    | Category      |    | Reviewer      |
| Base Score    |    | Multiplier    |    | Bonus         |
+---------------+    +---------------+    +---------------+
| CRITICAL: 40  |    | SECURITY: 1.5 |    | +5 per extra  |
| HIGH: 30      |    | PERFORMANCE:  |    | reviewer      |
| MEDIUM: 20    |    |   1.2         |    | (consensus)   |
| LOW: 10       |    | Other: 1.0    |    |               |
+---------------+    +---------------+    +---------------+
        |                    |                    |
        +--------------------+--------------------+
                             |
                    Score = min(100, base * mult + bonus)
                             |
                             v
                    +-------------------+
                    | Sort by           |
                    | Priority Score    |
                    | (descending)      |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Prioritized       |
                    | Issues            |
                    +-------------------+
```

### Overall Score Calculation

```
+------------------------------------------+
|        Severity Deductions               |
+------------------------------------------+
| Severity  | Deduction from 10.0          |
+-----------+------------------------------+
| CRITICAL  | -2.0                         |
| HIGH      | -1.0                         |
| MEDIUM    | -0.5                         |
| LOW       | -0.1                         |
+------------------------------------------+

Formula: score = max(0.0, 10.0 - sum(deductions))

Examples:
  - 0 issues        -> 10.0
  - 1 CRITICAL      -> 8.0
  - 2 HIGH + 3 LOW  -> 10 - 2 - 0.3 = 7.7
  - 5 CRITICAL      -> 0.0 (capped)
```

### Recommendation Logic

```
+------------------------------------------+
|          Recommendation Matrix           |
+------------------------------------------+
| Condition                | Recommendation |
+--------------------------+---------------+
| critical > 0             | REQUEST_CHANGES|
+--------------------------+---------------+
| high > 3                 | REQUEST_CHANGES|
+--------------------------+---------------+
| high > 0 (1-3)           | APPROVE_WITH_  |
|                          | CHANGES        |
+--------------------------+---------------+
| Only medium/low          | APPROVE        |
+--------------------------+---------------+
| No issues                | APPROVE        |
+------------------------------------------+
```

---

## Task Queue System

```
                    +-------------------+
                    |    Task Queue     |
                    |   (Singleton)     |
                    +--------+----------+
                             |
            +----------------+----------------+
            |                                 |
            v                                 v
    +---------------+                 +---------------+
    | Priority      |                 | Processing    |
    | Heap          |                 | Set           |
    +---------------+                 +---------------+
    | Higher prio   |                 | Tasks being   |
    | dequeued      |                 | worked on     |
    | first         |                 |               |
    +---------------+                 +---------------+
                                              |
                                              v
                                      +---------------+
                                      | Zombie        |
                                      | Detection     |
                                      +---------------+
                                      | Task stuck    |
                                      | > 30 minutes  |
                                      | = ZOMBIE      |
                                      +---------------+
                                              |
                                              v
                                      +---------------+
                                      | Cleanup       |
                                      | Options       |
                                      +---------------+
                                      | - Requeue     |
                                      | - Mark failed |
                                      +---------------+
```

### Task States

```
    PENDING ----enqueue----> IN_QUEUE
                                |
                            dequeue
                                |
                                v
                           PROCESSING
                                |
            +-------------------+-------------------+
            |                                       |
        complete                                  fail
            |                                       |
            v                                       v
        COMPLETED                               FAILED
```

---

## Checkpoint System

Enables resuming interrupted reviews.

```
                    +-------------------+
                    | Review Started    |
                    +--------+----------+
                             |
            FOR EACH REVIEWER:
                             |
                             v
                    +-------------------+
                    | Challenger Loop   |
                    +--------+----------+
                             |
                             v
                    +-------------------+
                    | Save Checkpoint   |
                    | - reviewer_name   |
                    | - status          |
                    | - issues_data     |
                    | - satisfaction    |
                    | - iterations      |
                    +--------+----------+
                             |
            IF INTERRUPTED:
                             |
                             v
                    +-------------------+
                    | Resume Review     |
                    | with checkpoints  |
                    +--------+----------+
                             |
            FOR EACH REVIEWER:
                             |
            +----------------+----------------+
            |                                 |
    +-------v-------+                 +-------v-------+
    | In checkpoint?|                 | Not in        |
    | SKIP (restore |                 | checkpoint?   |
    | from data)    |                 | RUN normally  |
    +---------------+                 +---------------+
```

---

## Data Models

### Review Models

```
ReviewRequest
├── source: ReviewRequestSource
│   ├── pr_url: str?
│   ├── commit_sha: str?
│   ├── files: list[str]
│   ├── directory: str?
│   └── workspace_path: str?  (monorepo)
├── requirements: ReviewRequirements?
└── options: ReviewOptions
    ├── mode: INITIAL | DIFF
    ├── include_functional: bool
    ├── challenger_enabled: bool
    └── satisfaction_threshold: int

FinalReport
├── id: str
├── timestamp: datetime
├── repository: RepositoryInfo
├── summary: ReportSummary
│   ├── repo_type: BE/FE/FULLSTACK
│   ├── files_reviewed: int
│   ├── total_issues: int
│   ├── by_severity: SeveritySummary
│   ├── overall_score: float (0-10)
│   └── recommendation: APPROVE|APPROVE_WITH_CHANGES|REQUEST_CHANGES
├── reviewers: list[ReviewerResult]
├── challenger: ChallengerMetadata
├── issues: list[Issue]
├── next_steps: list[NextStep]
└── evaluation: RepositoryEvaluation?
```

### Issue Model

```
Issue
├── file: str
├── line: int?
├── end_line: int?
├── severity: CRITICAL|HIGH|MEDIUM|LOW
├── category: IssueCategory
│   ├── SECURITY
│   ├── PERFORMANCE
│   ├── ARCHITECTURE
│   ├── QUALITY
│   ├── STYLE
│   ├── TESTING
│   └── DOCUMENTATION
├── message: str
├── suggestion: str?
├── current_code: str?
├── suggested_code: str?
└── flagged_by: list[str]  (reviewers)
```

---

## External Integrations

```
+------------------+     +------------------+     +------------------+
|    GitHub        |     |    Linear        |     |    AWS S3        |
+------------------+     +------------------+     +------------------+
| - PR info        |     | - Issue analysis |     | - Thinking logs  |
| - Diff content   |     | - Questions gen  |     | - Fix logs       |
| - Commit info    |     | - State mgmt     |     | - Checkpoints    |
+------------------+     +------------------+     +------------------+
        |                        |                        |
        v                        v                        v
+------------------------------------------------------------------+
|                        TurboWrap Core                             |
+------------------------------------------------------------------+
        |                        |                        |
        v                        v                        v
+------------------+     +------------------+     +------------------+
|   Claude CLI     |     |   Gemini CLI     |     |   Database       |
+------------------+     +------------------+     +------------------+
| - claude-code    |     | - gemini         |     | - SQLite/MySQL   |
| - Opus/Sonnet    |     | - Flash/Pro      |     | - Repos          |
| - Extended       |     | - Fast inference |     | - Issues         |
|   thinking       |     |                  |     | - Tasks          |
+------------------+     +------------------+     +------------------+
```

---

## Configuration

```yaml
# Key settings in config.yaml

challenger:
  satisfaction_threshold: 50    # % required to pass
  max_iterations: 5             # soft limit
  min_improvement_threshold: 2  # % improvement for stagnation
  stagnation_window: 3          # iterations to detect stagnation
  forced_acceptance_threshold: 40  # accept if > this after max

fix_challenger:
  satisfaction_threshold: 95    # higher bar for fixes
  max_iterations: 3

thinking:
  enabled: true
  budget_tokens: 8000           # extended thinking budget
  s3_bucket: "turbowrap-thinking"

agents:
  claude_model: "claude-opus-4-5-20251101"
  agents_dir: "./agents"
```

---

## Agent Files

```
agents/
├── reviewer_be_architecture.md   # BE architecture review
├── reviewer_be_quality.md        # BE quality/linting
├── reviewer_fe_architecture.md   # FE architecture review
├── reviewer_fe_quality.md        # FE quality/performance
├── analyst_func.md               # Functional analysis
├── fixer.md                      # Fix agent base
├── dev_be.md                     # BE dev guidelines
├── dev_fe.md                     # FE dev guidelines
├── fix_challenger.md             # Fix validation
├── git_branch_creator.md         # Branch creation
├── git_committer.md              # Commit creation
├── evaluator.md                  # Final evaluation
└── engineering_principles.md     # Shared principles
```

---

## Summary

TurboWrap implements a **robust dual-LLM quality assurance pattern**:

1. **Review**: Claude reviews, Gemini challenges until satisfaction threshold
2. **Fix**: Claude fixes, Gemini validates each batch until 95% score
3. **Safety**: Hard limits, workspace scope validation, checkpoint resume
4. **Quality**: Deduplication, prioritization, consensus scoring

The iterative challenger pattern ensures that neither reviewer nor fixer can produce substandard output - every result must pass the challenger's validation.
