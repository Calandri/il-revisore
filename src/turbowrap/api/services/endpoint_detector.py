"""Endpoint detection service using Gemini CLI.

Simple approach: let Gemini explore the repo and find ALL endpoints.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from turbowrap_llm import GeminiCLI

from turbowrap.review.reviewers.utils.json_extraction import parse_llm_json

logger = logging.getLogger(__name__)


@dataclass
class EndpointParameter:
    """API endpoint parameter."""

    name: str
    param_type: str  # query, path, body, header
    data_type: str  # int, str, bool, etc.
    required: bool = False
    description: str = ""


@dataclass
class EndpointInfo:
    """Information about a detected API endpoint."""

    method: str  # GET, POST, PUT, DELETE, PATCH
    path: str
    file: str
    line: int | None = None
    description: str = ""
    parameters: list[EndpointParameter] = field(default_factory=list)
    response_type: str = ""
    auth_required: bool = False
    visibility: str = "private"  # public, private, internal
    auth_type: str = ""  # Bearer, Basic, API-Key, OAuth2, etc.
    tags: list[str] = field(default_factory=list)
    source: str = "served"  # served (backend exposes), consumed (frontend calls)


@dataclass
class DetectionResult:
    """Result of endpoint detection."""

    detected_at: str = ""
    framework: str = ""
    frontend_framework: str | None = None
    routes: list[EndpointInfo] = field(default_factory=list)
    error: str | None = None


PROMPT = """You are a senior full-stack architect. Analyze this repository and find ALL API endpoints.

## Your Task

1. First, read .llms/structure.xml to understand the project structure
2. Find ALL endpoints in two categories:

### SERVED ENDPOINTS (source: "served")
API routes EXPOSED/SERVED by this repository's backend. Look for:
- FastAPI/Flask/Express/Django route decorators
- Lambda handlers, serverless functions
- Any HTTP endpoint definitions

### CONSUMED ENDPOINTS (source: "consumed")
API calls CONSUMED/USED by frontend code. Look for:
- fetch() calls
- axios requests
- useSWR, useQuery, React Query hooks
- $fetch (Nuxt), ofetch
- Any HTTP client calls

## Output Format

Return ONLY a valid JSON object (no markdown, no explanations):

{
  "framework": "fastapi",
  "frontend_framework": "react",
  "endpoints": [
    {
      "method": "GET",
      "path": "/api/users",
      "file": "src/routes/users.py",
      "line": 45,
      "description": "List all users",
      "source": "served",
      "parameters": [
        {"name": "page", "param_type": "query", "data_type": "int", "required": false, "description": "Page number"}
      ],
      "response_type": "List[User]",
      "auth_required": true,
      "visibility": "private",
      "auth_type": "Bearer",
      "tags": ["users"]
    },
    {
      "method": "POST",
      "path": "/api/login",
      "file": "src/components/Login.tsx",
      "line": 23,
      "description": "Login API call from frontend",
      "source": "consumed",
      "parameters": [],
      "response_type": "",
      "auth_required": false,
      "visibility": "public",
      "auth_type": "",
      "tags": ["auth"]
    }
  ]
}

## Rules
- Do NOT skip any endpoints
- Do NOT invent endpoints that don't exist
- Always verify in actual code
- Include the source file and line number
- For frontend calls, extract the URL even if it uses template literals
"""


def detect_endpoints(repo_path: str, **_kwargs: Any) -> DetectionResult:
    """Detect ALL API endpoints in a repository using Gemini CLI.

    Gemini explores the repo autonomously and finds both backend routes
    and frontend API calls in a single pass.
    """
    result = DetectionResult(detected_at=datetime.utcnow().isoformat())

    if not os.path.isdir(repo_path):
        result.error = f"Repository path not found: {repo_path}"
        return result

    try:
        from turbowrap.config import get_settings
        from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

        settings = get_settings()
        artifact_saver = S3ArtifactSaver(
            bucket=settings.thinking.s3_bucket,
            region=settings.thinking.s3_region,
            prefix="endpoint-detection",
        )

        cli = GeminiCLI(
            working_dir=Path(repo_path),
            model="flash",
            timeout=None,
            artifact_saver=artifact_saver,
        )

        logger.info(f"Running Gemini CLI for endpoint detection in {repo_path}")

        async def run_cli() -> tuple[bool, str, str | None]:
            res = await cli.run(PROMPT, save_artifacts=True)
            return res.success, res.output, res.error

        # Run in event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, run_cli())
                success, output, error = future.result()
        else:
            success, output, error = asyncio.run(run_cli())

        if not success:
            logger.error(f"Gemini CLI failed: {error}")
            result.error = str(error)
            return result

        # Parse response
        data = parse_llm_json(output.strip(), default={})
        if not data:
            logger.warning("Could not parse Gemini response as JSON")
            result.error = "Failed to parse LLM response"
            return result

        result.framework = data.get("framework", "")
        result.frontend_framework = data.get("frontend_framework")

        # Parse endpoints
        seen: set[tuple[str, str, str]] = set()  # (method, path, source)
        for ep in data.get("endpoints", []):
            key = (ep.get("method", "GET").upper(), ep.get("path", ""), ep.get("source", "served"))
            if key in seen:
                continue
            seen.add(key)

            params = [
                EndpointParameter(
                    name=p.get("name", ""),
                    param_type=p.get("param_type", "query"),
                    data_type=p.get("data_type", "str"),
                    required=p.get("required", False),
                    description=p.get("description", ""),
                )
                for p in ep.get("parameters", [])
            ]

            result.routes.append(
                EndpointInfo(
                    method=ep.get("method", "GET").upper(),
                    path=ep.get("path", ""),
                    file=ep.get("file", ""),
                    line=ep.get("line"),
                    description=ep.get("description", ""),
                    parameters=params,
                    response_type=ep.get("response_type", ""),
                    auth_required=ep.get("auth_required", False),
                    visibility=ep.get("visibility", "private"),
                    auth_type=ep.get("auth_type", ""),
                    tags=ep.get("tags", []),
                    source=ep.get("source", "served"),
                )
            )

        logger.info(
            f"Detected {len(result.routes)} endpoints "
            f"(served: {sum(1 for e in result.routes if e.source == 'served')}, "
            f"consumed: {sum(1 for e in result.routes if e.source == 'consumed')})"
        )
        return result

    except Exception as e:
        logger.error(f"Endpoint detection failed: {e}")
        result.error = str(e)
        return result


def save_endpoints_to_db(
    db_session: Any,
    repository_id: str,
    result: DetectionResult,
) -> int:
    """Save detected endpoints to database."""
    from turbowrap.db.models import Endpoint

    if not result.routes:
        return 0

    count = 0
    for ep in result.routes:
        existing = (
            db_session.query(Endpoint)
            .filter(
                Endpoint.repository_id == repository_id,
                Endpoint.method == ep.method.upper(),
                Endpoint.path == ep.path,
            )
            .first()
        )

        params_list = [
            {
                "name": p.name,
                "param_type": p.param_type,
                "data_type": p.data_type,
                "required": p.required,
                "description": p.description,
            }
            for p in ep.parameters
        ]

        framework = result.framework if ep.source == "served" else result.frontend_framework

        if existing:
            existing.file = ep.file
            existing.line = ep.line
            existing.description = ep.description
            existing.parameters = params_list
            existing.response_type = ep.response_type
            existing.requires_auth = ep.auth_required
            existing.visibility = ep.visibility
            existing.auth_type = ep.auth_type
            existing.tags = ep.tags
            existing.detected_at = datetime.utcnow()
            existing.framework = framework
            existing.source = ep.source
            existing.updated_at = datetime.utcnow()
        else:
            db_session.add(
                Endpoint(
                    repository_id=repository_id,
                    method=ep.method.upper(),
                    path=ep.path,
                    file=ep.file,
                    line=ep.line,
                    description=ep.description,
                    parameters=params_list,
                    response_type=ep.response_type,
                    requires_auth=ep.auth_required,
                    visibility=ep.visibility,
                    auth_type=ep.auth_type,
                    tags=ep.tags,
                    detected_at=datetime.utcnow(),
                    framework=framework,
                    source=ep.source,
                )
            )

        count += 1

    db_session.commit()
    logger.info(f"Saved {count} endpoints for repository {repository_id}")
    return count


def result_to_dict(result: DetectionResult) -> dict[str, Any]:
    """Convert DetectionResult to JSON-serializable dict."""
    return {
        "detected_at": result.detected_at,
        "framework": result.framework,
        "frontend_framework": result.frontend_framework,
        "error": result.error,
        "routes": [
            {
                "method": ep.method,
                "path": ep.path,
                "file": ep.file,
                "line": ep.line,
                "description": ep.description,
                "parameters": [
                    {
                        "name": p.name,
                        "param_type": p.param_type,
                        "data_type": p.data_type,
                        "required": p.required,
                        "description": p.description,
                    }
                    for p in ep.parameters
                ],
                "response_type": ep.response_type,
                "auth_required": ep.auth_required,
                "visibility": ep.visibility,
                "auth_type": ep.auth_type,
                "tags": ep.tags,
                "source": ep.source,
            }
            for ep in result.routes
        ],
    }
