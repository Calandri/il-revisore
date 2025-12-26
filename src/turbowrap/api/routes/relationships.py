"""Repository relationship analysis routes."""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.repo_manager import RepoManager
from ...db.models import LinkType, Repository, RepositoryLink
from ...llm import GeminiClient
from ..deps import get_db, require_auth

router = APIRouter(prefix="/relationships", tags=["relationships"])


# --- Schemas ---


class RepoStructure(BaseModel):
    """Repository structure summary."""

    id: str
    name: str
    repo_type: str | None
    structure_content: str


class IdentifiedConnection(BaseModel):
    """A connection identified by AI analysis."""

    source_repo_id: str
    source_repo_name: str
    target_repo_id: str
    target_repo_name: str
    link_type: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class AnalysisResult(BaseModel):
    """Result of relationship analysis."""

    total_repos: int
    repos_analyzed: int
    connections_found: list[IdentifiedConnection]
    analysis_summary: str


class ApplyConnectionsRequest(BaseModel):
    """Request to apply identified connections."""

    connections: list[IdentifiedConnection]
    overwrite_existing: bool = False


class ApplyConnectionsResult(BaseModel):
    """Result of applying connections."""

    created: int
    skipped: int
    errors: list[str]


# --- Prompts ---

ANALYSIS_SYSTEM_PROMPT = """Sei un esperto analista di architetture software. Il tuo compito è analizzare
i file STRUCTURE.md di diversi repository per identificare connessioni e dipendenze tra di essi.

Devi identificare:
1. Frontend che consumano API di Backend specifici
2. Backend che servono specifici Frontend
3. Librerie condivise tra progetti
4. Microservizi correlati
5. Moduli di monorepo
6. Altre relazioni tecniche

Tipi di link possibili:
- frontend_for: Un frontend che consuma API di un backend
- backend_for: Un backend che serve un frontend
- shared_lib: Una libreria condivisa usata da altri progetti
- microservice: Un microservizio correlato
- monorepo_module: Un modulo dello stesso monorepo
- related: Relazione generica

IMPORTANTE:
- Indica il confidence score (0.0-1.0) per ogni connessione
- Fornisci una spiegazione chiara del perché hai identificato la connessione
- Non inventare connessioni se non ci sono evidenze
- Cerca riferimenti a API endpoints, import, package names, URL, etc."""


def build_analysis_prompt(repos: list[RepoStructure]) -> str:
    """Build the prompt for relationship analysis."""
    prompt = """Analizza i seguenti repository e identifica le connessioni tra di essi.

## Repository da analizzare:

"""
    for repo in repos:
        prompt += f"""
### Repository: {repo.name}
- ID: {repo.id}
- Tipo: {repo.repo_type or 'unknown'}

**STRUCTURE.md:**
```
{repo.structure_content[:8000]}
```

---
"""

    prompt += """

## Formato risposta

Rispondi SOLO con un JSON valido nel seguente formato (senza markdown, senza ```json):
{
    "connections": [
        {
            "source_repo_id": "uuid-source",
            "source_repo_name": "name",
            "target_repo_id": "uuid-target",
            "target_repo_name": "name",
            "link_type": "frontend_for|backend_for|shared_lib|microservice|monorepo_module|related",
            "confidence": 0.85,
            "reason": "Spiegazione dettagliata"
        }
    ],
    "summary": "Riepilogo generale dell'analisi"
}

Se non trovi connessioni, rispondi con connections: [] e un summary esplicativo.
"""
    return prompt


# --- Helper functions ---


def load_structure_content(repo: Repository) -> str | None:
    """Load the main STRUCTURE.md content for a repository."""
    repo_path = Path(repo.local_path)

    # Try root STRUCTURE.md first
    structure_file = repo_path / "STRUCTURE.md"
    if structure_file.exists():
        try:
            return structure_file.read_text(encoding="utf-8")
        except Exception:
            pass

    # Try to find any STRUCTURE.md
    for f in repo_path.rglob("STRUCTURE.md"):
        rel_path = f.relative_to(repo_path)
        # Skip hidden directories
        if any(part.startswith(".") for part in rel_path.parts):
            continue
        try:
            return f.read_text(encoding="utf-8")
        except Exception:
            continue

    return None


def check_existing_link(db: Session, source_id: str, target_id: str) -> bool:
    """Check if a link already exists between two repos."""
    existing = (
        db.query(RepositoryLink)
        .filter(
            (
                (RepositoryLink.source_repo_id == source_id)
                & (RepositoryLink.target_repo_id == target_id)
            )
            | (
                (RepositoryLink.source_repo_id == target_id)
                & (RepositoryLink.target_repo_id == source_id)
            )
        )
        .first()
    )
    return existing is not None


# --- Routes ---


@router.post("/analyze", response_model=AnalysisResult)
async def analyze_relationships(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Analyze all repositories to identify connections between them.

    Uses AI to analyze STRUCTURE.md files and identify:
    - Frontend/Backend relationships
    - Shared libraries
    - Microservices
    - Related projects
    """
    manager = RepoManager(db)
    repos = manager.list(status="active")

    if len(repos) < 2:
        raise HTTPException(
            status_code=400, detail="Servono almeno 2 repository per analizzare le relazioni"
        )

    # Load structure content for each repo
    repo_structures: list[RepoStructure] = []
    for repo in repos:
        content = load_structure_content(repo)
        if content:
            repo_structures.append(
                RepoStructure(
                    id=repo.id,
                    name=repo.name,
                    repo_type=repo.repo_type,
                    structure_content=content,
                )
            )

    if len(repo_structures) < 2:
        raise HTTPException(
            status_code=400, detail="Servono almeno 2 repository con STRUCTURE.md per l'analisi"
        )

    # Use Gemini Flash for fast analysis
    try:
        client = GeminiClient()
        prompt = build_analysis_prompt(repo_structures)

        response = await asyncio.to_thread(client.generate, prompt, ANALYSIS_SYSTEM_PROMPT)

        # Parse the JSON response
        # Clean up response - remove markdown code blocks if present
        response_clean = response.strip()
        if response_clean.startswith("```"):
            lines = response_clean.split("\n")
            # Remove first and last lines (```json and ```)
            response_clean = "\n".join(lines[1:-1])

        try:
            result = json.loads(response_clean)
        except json.JSONDecodeError as e:
            # Try to find JSON in the response
            import re

            json_match = re.search(r"\{[\s\S]*\}", response)
            if json_match:
                result = json.loads(json_match.group())
            else:
                raise HTTPException(status_code=500, detail=f"Errore parsing risposta AI: {str(e)}")

        connections = []
        for conn in result.get("connections", []):
            connections.append(
                IdentifiedConnection(
                    source_repo_id=conn["source_repo_id"],
                    source_repo_name=conn["source_repo_name"],
                    target_repo_id=conn["target_repo_id"],
                    target_repo_name=conn["target_repo_name"],
                    link_type=conn["link_type"],
                    confidence=conn.get("confidence", 0.5),
                    reason=conn.get("reason", ""),
                )
            )

        return AnalysisResult(
            total_repos=len(repos),
            repos_analyzed=len(repo_structures),
            connections_found=connections,
            analysis_summary=result.get("summary", ""),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante l'analisi: {str(e)}")


@router.post("/analyze/stream")
async def analyze_relationships_stream(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Stream the relationship analysis progress."""

    async def generate():
        yield f"event: started\ndata: {json.dumps({'message': 'Avvio analisi relazioni...'})}\n\n"

        manager = RepoManager(db)
        repos = manager.list(status="active")

        yield f"event: progress\ndata: {json.dumps({'message': f'Trovati {len(repos)} repository'})}\n\n"

        if len(repos) < 2:
            yield f"event: error\ndata: {json.dumps({'error': 'Servono almeno 2 repository'})}\n\n"
            return

        # Load structures
        yield f"event: progress\ndata: {json.dumps({'message': 'Caricamento STRUCTURE.md...'})}\n\n"

        repo_structures: list[RepoStructure] = []
        for repo in repos:
            content = load_structure_content(repo)
            if content:
                repo_structures.append(
                    RepoStructure(
                        id=repo.id,
                        name=repo.name,
                        repo_type=repo.repo_type,
                        structure_content=content,
                    )
                )
                yield f"event: progress\ndata: {json.dumps({'message': f'Caricato: {repo.name}'})}\n\n"

        if len(repo_structures) < 2:
            yield f"event: error\ndata: {json.dumps({'error': 'Servono almeno 2 repository con STRUCTURE.md'})}\n\n"
            return

        yield f"event: progress\ndata: {json.dumps({'message': 'Analisi con Gemini Flash...'})}\n\n"

        try:
            client = GeminiClient()
            prompt = build_analysis_prompt(repo_structures)

            response = await asyncio.to_thread(client.generate, prompt, ANALYSIS_SYSTEM_PROMPT)

            # Parse response
            response_clean = response.strip()
            if response_clean.startswith("```"):
                lines = response_clean.split("\n")
                response_clean = "\n".join(lines[1:-1])

            try:
                result = json.loads(response_clean)
            except json.JSONDecodeError:
                import re

                json_match = re.search(r"\{[\s\S]*\}", response)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    yield f"event: error\ndata: {json.dumps({'error': 'Errore parsing risposta AI'})}\n\n"
                    return

            connections = []
            for conn in result.get("connections", []):
                connections.append(
                    {
                        "source_repo_id": conn["source_repo_id"],
                        "source_repo_name": conn["source_repo_name"],
                        "target_repo_id": conn["target_repo_id"],
                        "target_repo_name": conn["target_repo_name"],
                        "link_type": conn["link_type"],
                        "confidence": conn.get("confidence", 0.5),
                        "reason": conn.get("reason", ""),
                    }
                )

            completed_data = json.dumps(
                {
                    "total_repos": len(repos),
                    "repos_analyzed": len(repo_structures),
                    "connections": connections,
                    "summary": result.get("summary", ""),
                }
            )
            yield f"event: completed\ndata: {completed_data}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/apply", response_model=ApplyConnectionsResult)
async def apply_connections(
    request: ApplyConnectionsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Apply identified connections as repository links.

    Creates RepositoryLink records for the identified connections.
    """
    created = 0
    skipped = 0
    errors = []

    for conn in request.connections:
        try:
            # Check if link already exists
            if not request.overwrite_existing:
                if check_existing_link(db, conn.source_repo_id, conn.target_repo_id):
                    skipped += 1
                    continue
            else:
                # Delete existing links between these repos
                db.query(RepositoryLink).filter(
                    (
                        (RepositoryLink.source_repo_id == conn.source_repo_id)
                        & (RepositoryLink.target_repo_id == conn.target_repo_id)
                    )
                    | (
                        (RepositoryLink.source_repo_id == conn.target_repo_id)
                        & (RepositoryLink.target_repo_id == conn.source_repo_id)
                    )
                ).delete()

            # Validate link type
            try:
                link_type = LinkType(conn.link_type)
            except ValueError:
                link_type = LinkType.RELATED

            # Create the link
            link = RepositoryLink(
                source_repo_id=conn.source_repo_id,
                target_repo_id=conn.target_repo_id,
                link_type=link_type.value,
                metadata_={
                    "confidence": conn.confidence,
                    "reason": conn.reason,
                    "auto_detected": True,
                },
            )
            db.add(link)
            created += 1

        except Exception as e:
            errors.append(f"{conn.source_repo_name} -> {conn.target_repo_name}: {str(e)}")

    db.commit()

    return ApplyConnectionsResult(
        created=created,
        skipped=skipped,
        errors=errors,
    )


@router.get("/existing")
async def get_existing_relationships(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Get all existing repository links with details."""
    links = db.query(RepositoryLink).all()

    result = []
    for link in links:
        source_repo = db.query(Repository).get(link.source_repo_id)
        target_repo = db.query(Repository).get(link.target_repo_id)

        if source_repo and target_repo:
            result.append(
                {
                    "id": link.id,
                    "source_repo_id": link.source_repo_id,
                    "source_repo_name": source_repo.name,
                    "target_repo_id": link.target_repo_id,
                    "target_repo_name": target_repo.name,
                    "link_type": link.link_type,
                    "metadata": link.metadata_,
                    "created_at": link.created_at.isoformat() if link.created_at else None,
                }
            )

    return result


@router.delete("/clear")
async def clear_all_relationships(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Clear all repository links (for re-analysis)."""
    deleted = db.query(RepositoryLink).delete()
    db.commit()
    return {"deleted": deleted}
