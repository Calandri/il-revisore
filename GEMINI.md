# TurboWrap - Gemini Context

## 1. Project Overview

**TurboWrap** is an AI-powered repository orchestrator designed to automate code review and fixing workflows. It utilizes a multi-agent architecture (Claude + Gemini) to analyze, review, and repair codebases.

### Key Features
- **Orchestration**: Manages complex workflows involving multiple AI agents.
- **Dual-LLM Validation**: Uses a "Challenger" pattern where Gemini validates Claude's output.
- **Web UI**: FastAPI backend with a Jinja2/HTMX frontend for managing repositories and issues.
- **AWS Infrastructure**: Deployed on EC2 with ALB, ECR, and SSM.
- **Issue Widget**: Embeddable JS widget for user feedback, powered by Gemini Vision.

### Tech Stack
- **Language**: Python 3.12 (Backend), TypeScript/JavaScript (Frontend/Widget).
- **Frameworks**: FastAPI, SQLAlchemy, Pydantic (Backend); Jinja2, HTMX, TailwindCSS, Alpine.js (Frontend).
- **Database**: SQLite (local development), PostgreSQL/MySQL (production ready).
- **Package Manager**: `uv` (Python), `npm` (JS packages).
- **Infrastructure**: Docker, Terraform, AWS.

## 2. Building and Running

### Prerequisites
- Python 3.10+
- `uv` package manager
- Docker (optional for local run, required for deploy)

### Core Commands

**Install Dependencies:**
```bash
uv sync
```

**Run Development Server:**
```bash
# Starts the FastAPI app with hot reload on port 8000
uv run uvicorn src.turbowrap.api.main:app --reload --port 8000
```

**Run Tests:**
```bash
# Run all tests with coverage
uv run pytest

# Run specific test file
uv run pytest tests/path/to/test.py
```

**Database Migrations:**
```bash
# Apply migrations
./migrations/migrate.sh
```

**Linting and Formatting:**
```bash
# Check code style
uv run ruff check .

# Format code
uv run ruff format .

# Type checking
uv run mypy src/
```

## 3. Development Conventions

### Code Style
- **Python**: Follows PEP 8. Enforced by `ruff`. Use type hints everywhere (`mypy` strict).
- **Docstrings**: Google-style docstrings for all functions and classes.
- **Async**: Prefer asynchronous functions (`async def`) for I/O bound operations (DB, API calls).

### Project Structure
- `src/turbowrap/`: Main application source code.
    - `api/`: FastAPI routes and schemas.
    - `db/`: Database models and connection logic.
    - `fix/`: Fix orchestration logic.
    - `review/`: Code review orchestration logic.
    - `linear/`: Integration with Linear.app.
- `agents/`: Markdown prompts defining agent behaviors.
- `packages/`: Monorepo-style local packages (`turbowrap-llm`, etc.).
- `migrations/`: Alembic migration scripts.
- `tests/`: Pytest suite mirroring source structure.

### Testing Strategy
- **Unit Tests**: Mock external dependencies (LLMs, Git, DB).
- **Integration Tests**: Use a temporary DB or local file system.
- **Naming**: Test files must start with `test_`.

## 4. Specialized Gemini Roles

You (Gemini) play specific roles within the TurboWrap system architecture, beyond being a general coding assistant:

### A. The Challenger
You validate work done by Claude agents.
- **Reviews**: detailed validation of code review quality (Completeness, Accuracy, Depth).
- **Fixes**: Verify correctness, safety, and minimalism of automated fixes.
- **Critical Rule**: Always check `git diff` to verify claims against actual code changes.

### B. Vision Analyzer
For the Issue Widget:
- Analyze user-uploaded screenshots.
- Extract visual context (UI elements, layout bugs, error messages).
- Output concise reports to help Claude generate clarifying questions.
