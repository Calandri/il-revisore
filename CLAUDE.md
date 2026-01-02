# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TurboWrap is an AI-powered code review and automated fix system using multi-agent orchestration. It reviews code using Claude Opus with Gemini challenger validation, fixes issues automatically using parallel agent execution, and tracks issues through OPEN → IN_PROGRESS → RESOLVED → MERGED lifecycle.

## Development Commands

```bash
# Install dependencies
uv sync

# Run server (development)
uv run uvicorn src.turbowrap.api.main:app --reload --port 8000

# Run all tests with coverage
uv run pytest

# Run specific test file
uv run pytest tests/path/to/test.py

# Run single test
uv run pytest tests/path/to/test.py::test_function_name -v

# Type check
uv run mypy src/

# Lint and format
uv run ruff check .
uv run ruff format .

# Database migrations
./migrations/migrate.sh
```

## Architecture

```
src/turbowrap/
├── api/                    # FastAPI backend (routes/, services/, main.py)
├── fix/                    # Fix system (orchestrator.py, fix_challenger.py, models.py)
├── review/orchestration/   # Multi-agent review coordination
├── linear/                 # Linear.app integration
└── scripts/                # CLI tools

agents/                     # Agent prompt files (Markdown with YAML frontmatter)
packages/                   # Local packages (turbowrap-llm, turbowrap-issue-widget)
terraform/                  # AWS infrastructure (EC2, ALB, ECR)
```

### Agent Prompt Structure

```yaml
---
name: agent-name
description: What this agent does
tools: Read, Grep, Glob, Edit
model: opus
---
# Agent Title
[Prompt content]
```

## Key Architectural Patterns

### Challenger Loop
All reviews go through iterative validation:
```
Reviewer (Claude) → Challenger (Gemini) → Score < threshold → Refine → Repeat
```
- Review threshold: 99%
- Fix threshold: 95%
- Max iterations: 5 (hard cap: 10)

### Parallel Execution via Task Tool
- **ONE CLI call** to `fixer.md` orchestrator
- **Different files**: Fixed in parallel (multiple Task() calls in ONE message)
- **Same file**: Fixed serially (Task() calls in separate messages)
- BE + FE: Processed in separate batches

### Session Caching
Claude CLI sessions are reused across batches (~33% cost savings). All fix phases share one session via resume.

### Red-Flagging
Fix-Challenger verifies actual git diff before trusting fixer claims:
- Empty diff → Score 0
- Wrong file modified → Score 0
- Claimed fix not in diff → Score 0

## Anti-patterns

### Code Changes
- Never modify files outside the issue scope
- Never add dead code or unused imports
- Never over-engineer (YAGNI principle)
- Never commit without challenger verification

### Git Operations
- Never use `git add -A` or `--add-all`
- Never commit unrelated files
- Never force push to main
- Always verify staged files before commit

### Agent Development
- Never ignore challenger feedback blindly
- Never skip verification of suggested_fix
- Never create files without checking existing patterns
- Always return structured JSON output

## Issue Lifecycle

```
OPEN → IN_PROGRESS → RESOLVED → MERGED
         ↘ FAILED (if CLI crashes)
         ↘ SKIPPED (false positive)
         ↘ IGNORED (by user)
```

### Workload Estimation
- `estimated_effort`: 1-5 (trivial to major refactor)
- `estimated_files_count`: number of files
- Workload = effort × files
- Max per batch: 15 points or 5 issues

## Issue Widget System

The embeddable widget (`@turbowrap/issue-widget`) reports bugs/features from any website:

| Source | Saves To | Purpose |
|--------|----------|---------|
| Widget | `Issue` or `Feature` | New user-reported bugs/features |
| `/linear/sync` | `LinearIssue` | Import existing issues from Linear |
| Code Review | `Issue` | Automated code analysis findings |

Widget API flow:
1. `POST /linear/create/analyze` - Gemini analyzes screenshot, Claude generates questions
2. User answers questions in widget
3. `POST /linear/create/finalize` - Claude generates final description, creates on Linear

## Environment Variables

```bash
ANTHROPIC_API_KEY=...      # Required
GOOGLE_API_KEY=...         # Required
GITHUB_TOKEN=...           # For private repos
TURBOWRAP_REPOS_DIR=...    # Default: ~/.turbowrap/repos
```

## Code Style

- **Python**: Ruff for linting/formatting, mypy strict mode, Google docstrings, 100 char line length
- **TypeScript**: ESLint + Prettier, strict TypeScript, React functional components
- **Async**: Prefer `async def` for I/O bound operations (DB, API calls)

## Related Documentation

- [AGENTS.md](AGENTS.md) - Agent registry with capability matrix
- [GEMINI.md](GEMINI.md) - Context for Gemini Challenger
- [src/turbowrap/fix/README.md](src/turbowrap/fix/README.md) - Fix system details
