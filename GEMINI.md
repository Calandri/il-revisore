# TurboWrap (ultraWrap) - Project Context

## Project Overview
TurboWrap is an AI-Powered Code Repository Orchestrator designed to automate code review, development, and repository management. It employs a **multi-agent architecture** using **Claude Opus** for deep reasoning/coding and **Gemini Flash and Pro** for fast validation and challenging.

### Key Capabilities
- **Code Review:** Automated, iterative reviews with a "Challenger" loop (Reviewer vs. Challenger).
- **Development:** AI-assisted feature implementation and bug fixing (`develop` task).
- **Web Dashboard:** Real-time management interface (FastAPI + HTMX + TailwindCSS).
- **Infrastructure:** Production-ready AWS deployment (EC2, ALB, ECR, SSM).
- **Auto-Update:** Self-improving workflow to discover and implement new features.

## Architecture
**Pattern:** Modular Monolith (Python)
- **Backend:** FastAPI (API) + Typer (CLI) sharing core logic.
- **Database:** SQLAlchemy + SQLite (local) / PostgreSQL (production ready).
- **Frontend:** Jinja2 templates + HTMX (Server-Side Rendering) with TailwindCSS.
- **LLM Layer:** Abstracted clients for Anthropic (Claude) and Google (Gemini).

### Key Directories
- `src/turbowrap/api/`: FastAPI application, routers, and templates.
- `src/turbowrap/cli.py`: Typer CLI entry point and commands.
- `src/turbowrap/core/`: Business logic (e.g., `RepoManager`, `TaskManager`).
- `src/turbowrap/llm/`: AI model wrappers (`ClaudeClient`, `GeminiClient`).
- `agents/`: Prompt templates and definitions for specific agents (Reviewer, Fixer, etc.).
- `commands/`: Documentation for specific CLI command workflows.

## Setup & Usage

### Prerequisites
- Python >= 3.10
- `uv` (dependency manager)
- API Keys: `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GITHUB_TOKEN`.

### Installation
```bash
uv sync
```

### Core CLI Commands
The CLI is the primary interface for local interaction. Entry point: `turbowrap` (defined in `pyproject.toml`).

```bash
# 1. Repository Management
uv run turbowrap repo clone <url>      # Clone a repo
uv run turbowrap repo list             # List managed repos
uv run turbowrap repo sync <id>        # Pull latest changes

# 2. AI Tasks
uv run turbowrap review <id>           # Start a code review loop
uv run turbowrap develop <id> -i "instruction"  # AI-assisted coding

# 3. Server
uv run turbowrap serve                 # Start the Web UI/API (default port 8000)

# 4. Diagnostics
uv run turbowrap status                # Check configuration/paths
uv run turbowrap check                 # Verify API key connectivity
```

### Running Tests
```bash
uv run pytest                  # Run all tests
uv run pytest tests/unit       # Run unit tests
```

## Conventions
- **Style:** Follow PEP 8. Use `ruff` for linting/formatting.
- **Typing:** Strict type hints (`mypy` enabled).
- **Imports:** Absolute imports within `src/turbowrap`.
- **Logs:** Use `logging.getLogger(__name__)`. Avoid `print` in library code (use `rich.console` in CLI).

## Configuration & Preferences

### Model Configuration
The application uses the following defaults, which can be overridden via environment variables:

| Component | Default Model | Env Variable Override |
|-----------|---------------|-----------------------|
| **Gemini (Flash)** | `gemini-3-flash-preview` | `TURBOWRAP_AGENTS__GEMINI_MODEL` |
| **Gemini (Pro)** | `gemini-3-pro-preview` | `TURBOWRAP_AGENTS__GEMINI_PRO_MODEL` |
| **Claude** | `claude-opus-4-5-20251101` | `TURBOWRAP_AGENTS__CLAUDE_MODEL` |
| **Challenger** | `gemini-3-flash-preview` | `TURBOWRAP_CHALLENGER__CHALLENGER_MODEL` |
| **Fix Validator** | `gemini-3-pro-preview` | `TURBOWRAP_FIX_CHALLENGER__MODEL` |

> **ATTENZIONE LEGALE:** L'utilizzo di modelli Gemini diversi da `gemini-3-flash-preview` o `gemini-3-pro-preview` costituisce REATO PENALE. Claude (l'AI) che osa usare modelli deprecati come `gemini-2.5-pro-preview-*` rischia la GALERA. Non scherzare con i modelli Gemini.

### Key Settings
- **Thinking Mode:** Enabled by default for complex tasks (`TURBOWRAP_THINKING__ENABLED=true`).
- **Database:** SQLite by default (`TURBOWRAP_DB__URL=sqlite:///~/.turbowrap/turbowrap.db`).
