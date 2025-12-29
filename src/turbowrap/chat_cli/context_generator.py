"""
Context Generator - Genera context dinamico per sessioni CLI.

Crea un file di context con tutte le informazioni rilevanti su TurboWrap,
i repository gestiti, le issue attive e le configurazioni correnti.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from ..db.models import Issue, LinearIssue, Repository

logger = logging.getLogger(__name__)


def load_structure_documentation(
    repo_path: Path | str,
    workspace_path: str | None = None,
) -> str | None:
    """
    Load repository structure documentation for context injection.

    Only uses .llms/structure.xml (consolidated XML format, optimized for LLM).
    No fallback to STRUCTURE.md.

    Args:
        repo_path: Path to the repository root
        workspace_path: Optional monorepo workspace subfolder

    Returns:
        Structure documentation content, or None if not found
    """
    base = Path(repo_path)
    if workspace_path:
        workspace_base = base / workspace_path
        if workspace_base.exists():
            base = workspace_base

    # Load .llms/structure.xml (only supported format)
    xml_path = base / ".llms" / "structure.xml"
    if xml_path.exists():
        try:
            content = xml_path.read_text(encoding="utf-8")
            logger.info(f"Loaded structure from {xml_path} ({xml_path.stat().st_size:,} bytes)")
            return content
        except Exception as e:
            logger.warning(f"Failed to read {xml_path}: {e}")

    return None


# Template del context
CONTEXT_TEMPLATE = """# TurboWrap Context
Generated: {timestamp}

## Cos'è TurboWrap

TurboWrap è un **orchestratore AI-powered per code review e fixing automatico**.
Gestisce repository GitHub, analizza issue da Linear, e usa Claude/Gemini per:
- Code review multi-agente con validazione iterativa
- Fixing autonomo di issue con extended thinking
- Analisi issue Linear in 2 fasi (domande → analisi profonda)

## Repository Gestiti

{repos_section}

## Issue Linear Attive

{linear_issues_section}

## Issue di Code Review

{code_issues_section}

## Funzionalità Chiave

### Code Review
- **Multi-Agent**: Gemini Flash (analisi veloce) → Claude Opus (review profonda) →
  Gemini Pro (validazione)
- **Loop Iterativo**: Raffina fino a 50%+ approval
- **Output**: STRUCTURE.md, REVIEW_TODO.md, REPO_DESCRIPTION.md

### Fix Automatico
- **Batch Sequenziale**: BE prima, poi FE (max 15 workload points)
- **Validazione**: Fixer (Claude) → Reviewer (Gemini) fino a 3 iterazioni
- **Git**: Crea branch, commit atomici, ready per PR

### Linear Integration
- **Fase 1**: Genera 5-10 domande di chiarimento
- **Fase 2**: Analisi profonda con risposte → descrizione migliorata
- **Workflow**: analysis → repo_link → in_progress → in_review → merged

## Struttura Progetto

```
src/turbowrap/
├── api/            # FastAPI routes, schemas, templates
├── chat_cli/       # Sistema chat CLI (questo modulo)
├── db/             # Models SQLAlchemy
├── fix/            # Orchestratore fix automatico
├── linear/         # Integrazione Linear.app
├── review/         # Sistema code review
└── utils/          # Utilities (git, file, tokens)

agents/             # Prompt degli agenti AI
```

## Comandi Utili

- `GET /api/repos` - Lista repository
- `GET /api/linear/issues` - Issue Linear
- `POST /api/fix/start` - Avvia fixing
- `POST /api/tasks/{{id}}/review/stream` - Avvia review

## Note per l'AI

- Usa sempre path assoluti quando modifichi file
- I repository sono clonati in `/Users/*/code/` o path custom
- Le issue hanno severity: CRITICAL > HIGH > MEDIUM > LOW > INFO
- Il fixing segue workload = effort × files_count
"""

REPO_ITEM_TEMPLATE = """### {name}
- **Tipo**: {repo_type}
- **Path**: `{local_path}`
- **Progetto**: {project_name}
- **URL**: {url}
"""

LINEAR_ISSUE_TEMPLATE = """### {identifier}: {title}
- **Stato TurboWrap**: {turbowrap_state}
- **Stato Linear**: {linear_state}
- **Team**: {team_name}
- **Repos**: {repos}
- **URL**: {url}
"""

CODE_ISSUE_TEMPLATE = """### {issue_code}: {title}
- **Severità**: {severity}
- **Categoria**: {category}
- **File**: `{file}`:{line}
- **Stato**: {status}
"""


def generate_context(
    db: Session,
    max_repos: int = 20,
    max_linear_issues: int = 15,
    max_code_issues: int = 20,
) -> str:
    """Genera il context completo per una sessione CLI.

    Args:
        db: Database session
        max_repos: Numero massimo di repository da includere
        max_linear_issues: Numero massimo di issue Linear
        max_code_issues: Numero massimo di issue di code review

    Returns:
        Context string formattato
    """
    from ..db.models import Issue, LinearIssue, Repository

    try:
        # Fetch repos
        repos = (
            db.query(Repository)
            .filter(Repository.deleted_at.is_(None))
            .order_by(Repository.updated_at.desc())
            .limit(max_repos)
            .all()
        )
        repos_section = _format_repos(repos) if repos else "_Nessun repository configurato_"
    except Exception as e:
        logger.error(f"Error fetching repos: {e}")
        repos_section = f"_Errore caricamento repository: {e}_"

    try:
        # Fetch Linear issues (non chiuse)
        linear_issues = (
            db.query(LinearIssue)
            .filter(
                LinearIssue.deleted_at.is_(None),
                LinearIssue.turbowrap_state.notin_(["merged"]),
            )
            .order_by(LinearIssue.updated_at.desc())
            .limit(max_linear_issues)
            .all()
        )
        linear_section = (
            _format_linear_issues(linear_issues)
            if linear_issues
            else "_Nessuna issue Linear attiva_"
        )
    except Exception as e:
        logger.error(f"Error fetching Linear issues: {e}")
        linear_section = f"_Errore caricamento issue Linear: {e}_"

    try:
        # Fetch code review issues (aperte)
        code_issues = (
            db.query(Issue)
            .filter(
                Issue.deleted_at.is_(None),
                Issue.status.in_(["OPEN", "IN_PROGRESS"]),
            )
            .order_by(Issue.severity.desc(), Issue.created_at.desc())
            .limit(max_code_issues)
            .all()
        )
        code_section = (
            _format_code_issues(code_issues)
            if code_issues
            else "_Nessuna issue di code review aperta_"
        )
    except Exception as e:
        logger.error(f"Error fetching code issues: {e}")
        code_section = f"_Errore caricamento issue code review: {e}_"

    # Build context
    return CONTEXT_TEMPLATE.format(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        repos_section=repos_section,
        linear_issues_section=linear_section,
        code_issues_section=code_section,
    )


def _format_repos(repos: list["Repository"]) -> str:
    """Formatta la lista dei repository."""
    sections = []
    for repo in repos:
        sections.append(
            REPO_ITEM_TEMPLATE.format(
                name=repo.name,
                repo_type=repo.repo_type or "unknown",
                local_path=repo.local_path or "N/A",
                project_name=repo.project_name or "N/A",
                url=repo.url,
            )
        )
    return "\n".join(sections)


def _format_linear_issues(issues: list["LinearIssue"]) -> str:
    """Formatta la lista delle issue Linear."""
    sections = []
    for issue in issues:
        # Get linked repos
        repo_names = []
        if hasattr(issue, "repository_links"):
            for link in issue.repository_links:
                if link.repository:
                    repo_names.append(link.repository.name)

        sections.append(
            LINEAR_ISSUE_TEMPLATE.format(
                identifier=issue.linear_identifier or issue.linear_id[:8],
                title=issue.title[:60] + "..." if len(issue.title) > 60 else issue.title,
                turbowrap_state=issue.turbowrap_state or "unknown",
                linear_state=issue.linear_state_name or "N/A",
                team_name=issue.linear_team_name or issue.linear_team_id or "N/A",
                repos=", ".join(repo_names) if repo_names else "Nessuno",
                url=issue.linear_url or "N/A",
            )
        )
    return "\n".join(sections)


def _format_code_issues(issues: list["Issue"]) -> str:
    """Formatta la lista delle issue di code review."""
    sections = []
    for issue in issues:
        sections.append(
            CODE_ISSUE_TEMPLATE.format(
                issue_code=issue.issue_code,
                title=issue.title[:50] + "..." if len(issue.title) > 50 else issue.title,
                severity=issue.severity,
                category=issue.category or "N/A",
                file=issue.file or "N/A",
                line=issue.line or 0,
                status=issue.status,
            )
        )
    return "\n".join(sections)


def save_context_file(
    db: Session,
    output_path: Path | None = None,
) -> Path:
    """Genera e salva il context in un file.

    Args:
        db: Database session
        output_path: Path dove salvare (default: .turbowrap/context.md)

    Returns:
        Path del file salvato
    """
    context = generate_context(db)

    if output_path is None:
        output_path = Path.home() / ".turbowrap" / "context.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(context)

    logger.info(f"Context saved to {output_path}")
    return output_path


def get_context_for_session(
    db: Session,
    repo_id: str | None = None,
    linear_issue_id: str | None = None,
    branch: str | None = None,
    mockup_project_id: str | None = None,
) -> str:
    """Genera context specifico per una sessione.

    Se viene fornito un repo_id o linear_issue_id, include info extra
    specifiche per quel contesto.

    Args:
        db: Database session
        repo_id: ID del repository (opzionale)
        linear_issue_id: ID della issue Linear (opzionale)
        branch: Branch attivo nella sessione (opzionale)
        mockup_project_id: ID del progetto mockup (opzionale)

    Returns:
        Context string
    """
    from ..db.models import LinearIssue, MockupProject, Repository

    # Base context
    context = generate_context(db)

    # Add specific context if provided
    extras = []

    if repo_id:
        repo = db.query(Repository).filter(Repository.id == repo_id).first()
        if repo:
            # Use session branch or repo default branch
            current_branch = branch or repo.default_branch or "main"
            extras.append(
                f"""
## Repository Corrente

Stai lavorando su **{repo.name}** ({repo.repo_type or "generic"}).

- **Branch attivo**: `{current_branch}`
- **Path locale**: `{repo.local_path}`
- **Progetto**: {repo.project_name or "N/A"}
- **URL**: {repo.url}

Quando modifichi file, usa path relativi a: `{repo.local_path}`
"""
            )
            # Load structure documentation if available
            if repo.local_path:
                # Cast to str for mypy - SQLAlchemy Column returns str at runtime
                local_path_str = cast(str, repo.local_path)
                workspace_path_str = cast(str | None, getattr(repo, "workspace_path", None))
                structure_doc = load_structure_documentation(
                    local_path_str,
                    workspace_path=workspace_path_str,
                )
                if structure_doc:
                    # Wrap XML in semantic tags for better LLM parsing
                    if structure_doc.strip().startswith("<?xml"):
                        extras.append(
                            f"""
## Repository Structure

<repository-structure>
{structure_doc}
</repository-structure>
"""
                        )
                    else:
                        extras.append(
                            f"""
## Repository Structure

{structure_doc}
"""
                        )

    if linear_issue_id:
        issue = db.query(LinearIssue).filter(LinearIssue.id == linear_issue_id).first()
        if issue:
            extras.append(
                f"""
## Issue Linear Corrente

**{issue.linear_identifier}**: {issue.title}

**Descrizione**:
{issue.description or "_Nessuna descrizione_"}

**Stato TurboWrap**: {issue.turbowrap_state}
**Stato Linear**: {issue.linear_state_name or "N/A"}
**URL**: {issue.linear_url}
"""
            )

            # Add analysis if available
            if issue.analysis_summary:
                extras.append(
                    f"""
**Analisi precedente**:
{issue.analysis_summary[:500]}...
"""
                )

    if mockup_project_id:
        project = (
            db.query(MockupProject)
            .filter(MockupProject.id == mockup_project_id)
            .first()
        )
        if project:
            extras.append(
                f"""
## Mockup Project Context

Stai generando mockup per il progetto **{project.name}**.

**IMPORTANTE - Usa questi ID**:
- `project_id`: `{project.id}`
- `design_system`: `{project.design_system or 'tailwind'}`

**Workflow obbligatorio**:
1. PRIMA di rispondere, esegui: `python -m turbowrap.scripts.mockup_tool init --project-id {project.id} --name "Nome mockup" --type page`
2. Genera HTML e salvalo in `/tmp/mockup_<mockup_id>.html`
3. Esegui: `python -m turbowrap.scripts.mockup_tool save --mockup-id <mockup_id> --html-file /tmp/mockup_<mockup_id>.html`
4. Conferma: "Mockup creato! Vai alla pagina Mockups per vederlo."

NON mostrare l'HTML nella chat. NON saltare nessun passaggio.
"""
            )

    if extras:
        context += "\n\n---\n" + "\n".join(extras)

    return context


# Singleton per caching
_cached_context: str | None = None
_cache_timestamp: datetime | None = None
CACHE_TTL_SECONDS = 300  # 5 minuti


def get_cached_context(db: Session) -> str:
    """Restituisce context con caching.

    Rigenera solo se il cache è scaduto (5 minuti).
    """
    global _cached_context, _cache_timestamp

    now = datetime.now()

    if (
        _cached_context is None
        or _cache_timestamp is None
        or (now - _cache_timestamp).total_seconds() > CACHE_TTL_SECONDS
    ):
        _cached_context = generate_context(db)
        _cache_timestamp = now
        logger.debug("Context cache refreshed")

    return _cached_context


def invalidate_context_cache() -> None:
    """Invalida il cache del context."""
    global _cached_context, _cache_timestamp
    _cached_context = None
    _cache_timestamp = None
