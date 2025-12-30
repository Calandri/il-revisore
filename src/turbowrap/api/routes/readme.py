"""README analysis routes."""

import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ...db.models import Repository
from ...llm.gemini import GeminiCLI
from ...review.reviewers.utils.json_extraction import parse_llm_json
from ...tools.dependency_parser import build_dependency_graph, generate_mermaid_diagrams
from ..deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/readme", tags=["readme"])


class ReadmeGenerateRequest(BaseModel):
    """Request to generate README analysis."""

    regenerate: bool = False  # Force regeneration even if cached


@router.get("/{repository_id}")
def get_readme_analysis(
    repository_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get cached README analysis for a repository."""
    repo = db.query(Repository).filter(Repository.id == repository_id).first()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not repo.readme_analysis:
        raise HTTPException(status_code=404, detail="No README analysis available")

    return {
        "repository_id": repository_id,
        "repository_name": repo.name,
        "analysis": repo.readme_analysis,
    }


@router.post("/{repository_id}/generate")
async def generate_readme_analysis(
    repository_id: str,
    request: ReadmeGenerateRequest = ReadmeGenerateRequest(),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """Generate README analysis with SSE streaming."""
    repo = db.query(Repository).filter(Repository.id == repository_id).first()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not repo.local_path:
        raise HTTPException(status_code=400, detail="Repository has no local path")

    # Check cache
    if repo.readme_analysis and not request.regenerate:
        # Return cached result as SSE
        async def cached_stream() -> AsyncGenerator[dict[str, str], None]:
            yield {"event": "cached", "data": json.dumps(repo.readme_analysis)}

        return EventSourceResponse(cached_stream())

    # Stream generation
    return EventSourceResponse(
        _generate_readme_stream(repo, db),
        media_type="text/event-stream",
    )


async def _generate_readme_stream(
    repo: Repository, db: Session
) -> AsyncGenerator[dict[str, str], None]:
    """Generator for SSE events during README analysis."""
    repo_path = Path(str(repo.local_path))

    try:
        yield {
            "event": "progress",
            "data": json.dumps({"step": "started", "message": "Avvio analisi..."}),
        }

        # Step 1: Parse dependencies
        yield {
            "event": "progress",
            "data": json.dumps({"step": "parsing", "message": "Analisi dipendenze..."}),
        }
        graph = build_dependency_graph(repo_path, repo.workspace_path)

        # Generate pre-computed diagrams from dependency graph
        pre_diagrams = generate_mermaid_diagrams(graph, repo.name)

        # Step 2: Load structure file
        yield {
            "event": "progress",
            "data": json.dumps({"step": "structure", "message": "Caricamento struttura..."}),
        }
        structure_content = _load_structure_file(repo_path)

        # Step 3: Call LLM for analysis
        yield {
            "event": "progress",
            "data": json.dumps({"step": "analyzing", "message": "Generazione con AI..."}),
        }

        analysis = await _run_readme_analyzer(repo, structure_content, pre_diagrams)

        if analysis:
            # Step 4: Save to database
            yield {
                "event": "progress",
                "data": json.dumps({"step": "saving", "message": "Salvataggio..."}),
            }

            # Add metadata
            analysis["generated_at"] = datetime.utcnow().isoformat()
            analysis["generator_model"] = "gemini-flash"

            # Merge pre-computed diagrams with LLM-generated ones
            if pre_diagrams and "diagrams" in analysis:
                # Add pre-computed diagrams if not already present
                existing_types = {d.get("type") for d in analysis.get("diagrams", [])}
                for diagram in pre_diagrams:
                    if diagram["type"] not in existing_types:
                        analysis["diagrams"].append(diagram)

            repo.readme_analysis = analysis
            db.commit()

            yield {"event": "completed", "data": json.dumps(analysis)}
        else:
            yield {"event": "error", "data": json.dumps({"message": "Failed to generate analysis"})}

    except Exception as e:
        logger.exception(f"README analysis error: {e}")
        yield {"event": "error", "data": json.dumps({"message": str(e)})}


def _load_structure_file(repo_path: Path) -> str:
    """Load structure.xml or STRUCTURE.md from repo."""
    # Try XML first (more detailed)
    xml_path = repo_path / ".llms" / "structure.xml"
    if xml_path.exists():
        try:
            content = xml_path.read_text(encoding="utf-8")
            # Truncate if too long
            if len(content) > 50000:
                content = content[:50000] + "\n... (truncated)"
            return content
        except Exception:
            pass

    # Try STRUCTURE.md
    md_path = repo_path / "STRUCTURE.md"
    if md_path.exists():
        try:
            content = md_path.read_text(encoding="utf-8")
            if len(content) > 30000:
                content = content[:30000] + "\n... (truncated)"
            return content
        except Exception:
            pass

    # Fallback: generate basic structure
    return _generate_basic_structure(repo_path)


def _generate_basic_structure(repo_path: Path) -> str:
    """Generate basic directory structure."""
    lines = [f"# Repository Structure: {repo_path.name}\n"]

    # List top-level directories
    for item in sorted(repo_path.iterdir()):
        if item.name.startswith(".") or item.name in {
            "node_modules",
            "__pycache__",
            ".git",
            "venv",
            ".venv",
        }:
            continue
        if item.is_dir():
            lines.append(f"- {item.name}/")
            # List first level of files
            for child in sorted(item.iterdir())[:10]:
                if not child.name.startswith("."):
                    suffix = "/" if child.is_dir() else ""
                    lines.append(f"  - {child.name}{suffix}")
        else:
            lines.append(f"- {item.name}")

    return "\n".join(lines[:100])  # Limit lines


async def _run_readme_analyzer(
    repo: Repository,
    structure_content: str,
    pre_diagrams: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Run README analyzer agent with Gemini CLI."""
    repo_path = Path(str(repo.local_path))

    # Load agent prompt
    agent_path = Path(__file__).parents[4] / "agents" / "readme_analyzer.md"
    if not agent_path.exists():
        logger.error(f"Agent file not found: {agent_path}")
        return None

    agent_content = agent_path.read_text(encoding="utf-8")

    # Remove YAML frontmatter
    if agent_content.startswith("---"):
        parts = agent_content.split("---", 2)
        if len(parts) >= 3:
            agent_content = parts[2].strip()

    # Build prompt
    diagrams_hint = ""
    if pre_diagrams:
        diagrams_hint = (
            "\n\n## Pre-generated Diagrams (you can include these or generate better ones)\n"
        )
        for d in pre_diagrams:
            diagrams_hint += f"\n### {d['title']} ({d['type']})\n```mermaid\n{d['code']}\n```\n"

    prompt = f"""
{agent_content}

## Repository Context

- **Name**: {repo.name}
- **Type**: {repo.repo_type or 'unknown'}
- **Workspace**: {repo.workspace_path or 'root'}

## Repository Structure

{structure_content}
{diagrams_hint}

Now analyze this repository and return the JSON response.
"""

    try:
        cli = GeminiCLI(
            working_dir=repo_path,
            model="flash",
            timeout=180,
            auto_accept=True,
        )

        result = await cli.run(
            prompt=prompt,
            operation_type="readme_analysis",
            repo_name=repo.name,
            track_operation=True,
        )

        if not result.success:
            logger.error(f"README analysis failed: {result.error}")
            return None

        # Parse JSON from output
        json_data = parse_llm_json(result.output)
        if not json_data:
            logger.error(f"Could not parse JSON from output: {result.output[:500]}")
            return None

        return json_data

    except Exception as e:
        logger.exception(f"README analyzer error: {e}")
        return None


@router.get("/{repository_id}/diagrams")
def get_diagrams_only(
    repository_id: str,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get only the Mermaid diagrams."""
    repo = db.query(Repository).filter(Repository.id == repository_id).first()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not repo.readme_analysis:
        raise HTTPException(status_code=404, detail="No analysis available")

    return repo.readme_analysis.get("diagrams", [])
