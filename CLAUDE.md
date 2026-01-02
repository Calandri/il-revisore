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
├── linear/                 # Linear integration
│   └── analyzer.py         # Issue analysis with Claude
└── scripts/                # CLI tools

agents/                     # Agent prompt files (36 agents)
├── fixer.md                # Fix orchestrator
├── fix_challenger.md       # Validates fixes
├── reviewer_*.md           # Code reviewers
├── linear_question_generator.md  # Widget question generation
├── linear_finalizer.md     # Widget description finalization
└── engineering_principles.md

packages/
├── turbowrap-issue-widget/ # Embeddable issue reporting widget
└── turbowrap-llm/          # LLM integration library

terraform/                  # AWS infrastructure
deploy/                     # Deployment scripts
```

## Issue Widget System

TurboWrap includes an embeddable JavaScript widget (`@turbowrap/issue-widget`) that allows users to report bugs and request features directly from any website.

### Widget Features

1. **Element Picker ("Seleziona Componente")**: Users can click on any DOM element to report issues about it. The widget extracts:
   - Element tag name, ID, classes
   - CSS selector
   - `data-test-id` attributes
   - Visual context via screenshot

2. **AI Analysis Pipeline**:
   - **Gemini Vision**: Analyzes screenshots to extract visual context
   - **Claude**: Generates 3-4 clarifying questions
   - **Claude**: Creates comprehensive issue description from user answers

3. **Issue Routing**: Based on user selection, creates:
   - **Bug** → `Issue` table → appears in `/issues`
   - **Suggestion** → `Feature` table → appears in `/features`
   - **Question** → `Feature` table → appears in `/features`

### Installation

```html
<script>
  window.IssueWidgetConfig = {
    apiUrl: 'https://your-api.turbowrap.io',
    apiKey: 'your_api_key',
    teamId: 'your-linear-team-uuid'
  };
</script>
<script src="https://cdn.jsdelivr.net/npm/@turbowrap/issue-widget@latest/dist/issue-widget.min.js"></script>
```

### Widget vs LinearIssue

| Source | Saves To | Purpose |
|--------|----------|---------|
| Widget | `Issue` or `Feature` | New user-reported bugs/features |
| `/linear/sync` | `LinearIssue` | Import existing issues from Linear |
| Code Review | `Issue` | Automated code analysis findings |

### Widget API Flow

1. `POST /linear/create/analyze` - Gemini analyzes screenshot, Claude generates questions
2. User answers questions in widget
3. `POST /linear/create/finalize` - Claude generates final description, creates on Linear, saves to DB

### Related Files
- Widget source: `packages/turbowrap-issue-widget/`
- Widget README: `packages/turbowrap-issue-widget/README.md`
- Backend routes: `src/turbowrap/api/routes/linear.py`
- Agents: `agents/linear_question_generator.md`, `agents/linear_finalizer.md`

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
