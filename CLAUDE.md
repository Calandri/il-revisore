# TurboWrap

AI-powered code review and automated fix system using multi-agent orchestration.

## Project Overview

TurboWrap is a platform that:
1. **Reviews code** using Claude Opus with Gemini challenger validation
2. **Fixes issues** automatically using parallel agent execution
3. **Tracks issues** through OPEN → IN_PROGRESS → RESOLVED → MERGED lifecycle

## Architecture

```
src/turbowrap/
├── api/                    # FastAPI backend
│   ├── routes/             # API endpoints
│   ├── services/           # Business logic
│   └── main.py             # App entry point
├── fix/                    # Fix system
│   ├── orchestrator.py     # Main fix engine (3k lines)
│   ├── fix_challenger.py   # Gemini integration
│   └── models.py           # Pydantic models
├── review/                 # Review system
│   └── orchestration/      # Multi-agent coordination
└── scripts/                # CLI tools

agents/                     # Agent prompt files (36 agents)
├── fixer.md                # Fix orchestrator
├── fix_challenger.md       # Validates fixes
├── reviewer_*.md           # Code reviewers
└── engineering_principles.md

terraform/                  # AWS infrastructure
deploy/                     # Deployment scripts
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Frontend | Jinja2 + HTMX + TailwindCSS |
| AI | Claude (Opus/Sonnet/Haiku) + Gemini (Flash/Pro) |
| Auth | AWS Cognito |
| Infrastructure | AWS EC2 + ALB + ECR + Route53 |

## Development Commands

```bash
# Install dependencies
uv sync

# Run server
uv run uvicorn src.turbowrap.api.main:app --reload --port 8000

# Run tests
uv run pytest

# Type check
uv run mypy src/

# Lint
uv run ruff check .
uv run ruff format .

# Database migrations
./migrations/migrate.sh
```

## Environment Variables

```bash
ANTHROPIC_API_KEY=...      # Required
GOOGLE_API_KEY=...         # Required
GITHUB_TOKEN=...           # For private repos
TURBOWRAP_REPOS_DIR=...    # Default: ~/.turbowrap/repos
```

## Code Style

### Python
- **Linter:** Ruff (replaces flake8, isort, black)
- **Types:** mypy with strict mode
- **Style:** Google docstrings, 88 char line length

### TypeScript
- **Linter:** ESLint + Prettier
- **Types:** Strict TypeScript
- **Style:** React functional components, custom hooks

### Agent Prompts
- **Format:** Markdown with YAML frontmatter
- **Location:** `agents/*.md`
- **Structure:**
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

## Key Patterns

### Challenger Loop
All reviews go through iterative validation:
```
Reviewer (Claude) → Challenger (Gemini) → Score < threshold → Refine → Repeat
```
- Review threshold: 99%
- Fix threshold: 95%
- Max iterations: 5 (hard cap: 10)

### Parallel Execution (via Task Tool)
- **ONE CLI call** to `fixer.md` orchestrator
- **Different files**: Fixed in parallel (multiple Task() calls in ONE message)
- **Same file**: Fixed serially (Task() calls in separate messages)
- BE + FE: Still processed in separate batches

### Session Caching
Claude CLI sessions reused across batches (~33% cost savings)

### Red-Flagging
Fix-Challenger verifies actual git diff before trusting fixer claims:
- Empty diff → Score 0
- Wrong file modified → Score 0
- Claimed fix not in diff → Score 0

## Anti-patterns to Avoid

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

## Workload Estimation

Issues are batched by workload:
- `estimated_effort`: 1-5 (trivial to major refactor)
- `estimated_files_count`: number of files
- Workload = effort × files
- Max per batch: 15 points or 5 issues

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/repos` | List repositories |
| POST | `/api/repos` | Clone repository |
| POST | `/api/tasks/{id}/review/stream` | Start review (SSE) |
| POST | `/fix/start` | Start fixing issues (SSE) |
| GET | `/fix/sessions/active` | List active fix sessions |

## Debugging

### Logs
- Fix session logs saved to S3: `s3://{bucket}/fix-logs/`
- Review logs in `.reviews/` directory

### Common Issues

1. **Context limit exceeded**: Triggers `/compact` automatically
2. **Scope violation**: Prompts user to allow/disallow extra files
3. **Stale branch**: Auto-fetches and rebases

## Related Files

- [AGENTS.md](AGENTS.md) - Agent registry with capability matrix
- [GEMINI.md](GEMINI.md) - Context for Gemini Challenger
- [README.md](README.md) - Full documentation
- [src/turbowrap/fix/README.md](src/turbowrap/fix/README.md) - Fix system details
