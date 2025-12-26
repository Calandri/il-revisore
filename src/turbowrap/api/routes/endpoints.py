"""API endpoint management routes."""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import Repository
from ..deps import get_db
from ..services.endpoint_detector import detect_endpoints, result_to_dict

router = APIRouter(prefix="/endpoints", tags=["endpoints"])
logger = logging.getLogger(__name__)


# --- Pydantic Schemas ---


class EndpointParameter(BaseModel):
    """API endpoint parameter."""

    name: str
    param_type: str  # query, path, body, header
    data_type: str
    required: bool = False
    description: str = ""


class EndpointInfo(BaseModel):
    """Information about a detected API endpoint."""

    method: str
    path: str
    file: str
    line: int | None = None
    description: str = ""
    parameters: list[EndpointParameter] = []
    response_type: str = ""
    auth_required: bool = False
    tags: list[str] = []


class EndpointsData(BaseModel):
    """Endpoints metadata stored in Repository."""

    swagger_url: str | None = None
    openapi_file: str | None = None
    detected_at: str | None = None
    framework: str = ""
    routes: list[EndpointInfo] = []
    error: str | None = None


class RepoWithEndpoints(BaseModel):
    """Repository with endpoint information."""

    id: str
    name: str
    repo_type: str | None
    local_path: str | None
    has_endpoints: bool
    endpoint_count: int
    framework: str | None
    swagger_url: str | None
    openapi_file: str | None
    detected_at: str | None


class DetectionResponse(BaseModel):
    """Response from endpoint detection."""

    status: str  # success, error, in_progress
    message: str
    endpoint_count: int = 0


class AIInstructionsRequest(BaseModel):
    """Request for AI instructions on calling an endpoint."""

    method: str
    path: str
    description: str = ""
    parameters: list[EndpointParameter] = []
    base_url: str = "http://localhost:8000"


class AIInstructionsResponse(BaseModel):
    """AI-generated instructions for calling an endpoint."""

    curl_example: str
    python_example: str
    javascript_example: str
    description: str


# --- Helper Functions ---


def _get_endpoints_from_metadata(repo: Repository) -> EndpointsData | None:
    """Extract endpoints data from repository metadata."""
    if not repo.metadata_:
        return None

    endpoints_data = repo.metadata_.get("endpoints")
    if not endpoints_data:
        return None

    try:
        return EndpointsData(**endpoints_data)
    except Exception:
        return None


def _save_endpoints_to_metadata(
    repo: Repository, endpoints_data: dict[str, Any], db: Session
) -> None:
    """Save endpoints data to repository metadata."""
    if repo.metadata_ is None:
        repo.metadata_ = {}

    # Create a new dict to trigger SQLAlchemy change detection
    new_metadata = dict(repo.metadata_)
    new_metadata["endpoints"] = endpoints_data
    repo.metadata_ = new_metadata  # type: ignore[assignment]
    repo.updated_at = datetime.utcnow()  # type: ignore[assignment]
    db.commit()


# --- Routes ---


@router.get("", response_model=list[RepoWithEndpoints])
def list_repos_with_endpoints(
    include_without_endpoints: bool = False,
    db: Session = Depends(get_db),
) -> list[RepoWithEndpoints]:
    """List all repositories with their endpoint information.

    Args:
        include_without_endpoints: Include repos that haven't been scanned yet.
    """
    repos = db.query(Repository).filter(Repository.status != "deleted").all()

    result: list[RepoWithEndpoints] = []
    for repo in repos:
        endpoints_data = _get_endpoints_from_metadata(repo)

        has_endpoints = bool(endpoints_data and endpoints_data.routes)
        endpoint_count = len(endpoints_data.routes) if endpoints_data else 0

        if not include_without_endpoints and not has_endpoints:
            continue

        result.append(
            RepoWithEndpoints(
                id=str(repo.id),
                name=str(repo.name),
                repo_type=str(repo.repo_type) if repo.repo_type else None,
                local_path=str(repo.local_path) if repo.local_path else None,
                has_endpoints=has_endpoints,
                endpoint_count=endpoint_count,
                framework=endpoints_data.framework if endpoints_data else None,
                swagger_url=endpoints_data.swagger_url if endpoints_data else None,
                openapi_file=endpoints_data.openapi_file if endpoints_data else None,
                detected_at=endpoints_data.detected_at if endpoints_data else None,
            )
        )

    # Sort by endpoint count descending
    result.sort(key=lambda x: x.endpoint_count, reverse=True)
    return result


@router.get("/{repo_id}", response_model=EndpointsData)
def get_repo_endpoints(repo_id: str, db: Session = Depends(get_db)) -> EndpointsData:
    """Get detected endpoints for a specific repository."""
    repo = (
        db.query(Repository)
        .filter(Repository.id == repo_id, Repository.status != "deleted")
        .first()
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    endpoints_data = _get_endpoints_from_metadata(repo)
    if not endpoints_data:
        return EndpointsData()

    return endpoints_data


@router.post("/{repo_id}/detect", response_model=DetectionResponse)
def trigger_endpoint_detection(
    repo_id: str,
    background_tasks: BackgroundTasks,
    use_ai: bool = True,
    db: Session = Depends(get_db),
) -> DetectionResponse:
    """Trigger endpoint detection for a repository.

    Args:
        repo_id: Repository ID.
        use_ai: Use Gemini Flash for enhanced analysis.
    """
    repo = (
        db.query(Repository)
        .filter(Repository.id == repo_id, Repository.status != "deleted")
        .first()
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if not repo.local_path:
        raise HTTPException(status_code=400, detail="Repository has no local path")

    # Run detection synchronously for now (could be async with background_tasks)
    try:
        result = detect_endpoints(str(repo.local_path), use_ai=use_ai)
        result_dict = result_to_dict(result)

        _save_endpoints_to_metadata(repo, result_dict, db)

        if result.error:
            return DetectionResponse(
                status="error",
                message=result.error,
                endpoint_count=0,
            )

        return DetectionResponse(
            status="success",
            message=f"Detected {len(result.routes)} endpoints using {result.framework} framework",
            endpoint_count=len(result.routes),
        )

    except Exception as e:
        logger.error(f"Endpoint detection failed for {repo_id}: {e}")
        return DetectionResponse(
            status="error",
            message=str(e),
            endpoint_count=0,
        )


@router.delete("/{repo_id}")
def clear_repo_endpoints(repo_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """Clear detected endpoints for a repository."""
    repo = (
        db.query(Repository)
        .filter(Repository.id == repo_id, Repository.status != "deleted")
        .first()
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo.metadata_ and "endpoints" in repo.metadata_:
        new_metadata = dict(repo.metadata_)
        del new_metadata["endpoints"]
        repo.metadata_ = new_metadata  # type: ignore[assignment]
        repo.updated_at = datetime.utcnow()  # type: ignore[assignment]
        db.commit()

    return {"status": "cleared", "repo_id": repo_id}


@router.post("/ai-instructions", response_model=AIInstructionsResponse)
def generate_ai_instructions(req: AIInstructionsRequest) -> AIInstructionsResponse:
    """Generate AI-powered instructions for calling an endpoint."""
    from ...llm.gemini import GeminiClient

    # Build parameter info
    params_text = ""
    if req.parameters:
        params_text = "\n".join(
            [
                f"  - {p.name} ({p.param_type}): {p.data_type}"
                + (" [required]" if p.required else "")
                + (f" - {p.description}" if p.description else "")
                for p in req.parameters
            ]
        )

    prompt = f"""Generate code examples for calling this API endpoint:

Method: {req.method}
Path: {req.path}
Base URL: {req.base_url}
Description: {req.description or "No description available"}

Parameters:
{params_text or "No parameters"}

Please provide:
1. A curl command example
2. A Python requests example
3. A JavaScript fetch example

Return as JSON:
{{
  "curl_example": "curl ...",
  "python_example": "import requests\\n...",
  "javascript_example": "fetch(...)...",
  "description": "Brief explanation of how to use this endpoint"
}}

Return ONLY the JSON, no markdown or extra text."""

    try:
        client = GeminiClient()
        response = client.generate(prompt)

        # Clean response
        cleaned = response.strip()
        if cleaned.startswith("```"):
            import re

            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        data = json.loads(cleaned)

        return AIInstructionsResponse(
            curl_example=data.get("curl_example", ""),
            python_example=data.get("python_example", ""),
            javascript_example=data.get("javascript_example", ""),
            description=data.get("description", ""),
        )

    except Exception as e:
        logger.error(f"AI instructions generation failed: {e}")
        # Return basic fallback examples
        full_url = f"{req.base_url}{req.path}"

        return AIInstructionsResponse(
            curl_example=f"curl -X {req.method} '{full_url}'",
            python_example=(
                f"import requests\n\n"
                f"response = requests.{req.method.lower()}('{full_url}')\n"
                f"print(response.json())"
            ),
            javascript_example=(
                f"const response = await fetch('{full_url}', "
                f"{{ method: '{req.method}' }});\n"
                f"const data = await response.json();"
            ),
            description=req.description or f"{req.method} request to {req.path}",
        )
