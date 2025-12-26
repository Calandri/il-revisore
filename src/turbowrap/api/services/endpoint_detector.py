"""Endpoint detection service using Claude CLI.

Scans repository code to detect API endpoints, Swagger/OpenAPI documentation,
and extracts endpoint metadata using AI analysis.

Uses the centralized ClaudeCLI utility for Claude CLI subprocess execution.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from turbowrap.utils.claude_cli import ClaudeCLI

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
    tags: list[str] = field(default_factory=list)


@dataclass
class DetectionResult:
    """Result of endpoint detection."""

    swagger_url: str | None = None
    openapi_file: str | None = None
    detected_at: str = ""
    framework: str = ""
    routes: list[EndpointInfo] = field(default_factory=list)
    error: str | None = None


# File patterns for different frameworks
ROUTE_FILE_PATTERNS = {
    "fastapi": ["**/routes/*.py", "**/routers/*.py", "**/api/*.py", "**/endpoints/*.py"],
    "flask": ["**/routes/*.py", "**/views/*.py", "**/api/*.py", "**/*_routes.py"],
    "express": ["**/routes/*.js", "**/routes/*.ts", "**/api/*.js", "**/api/*.ts"],
    "django": ["**/urls.py", "**/views.py"],
    "spring": ["**/*Controller.java", "**/*Resource.java"],
    "gin": ["**/routes.go", "**/handlers.go", "**/api/*.go"],
    "rails": ["**/routes.rb", "**/controllers/*.rb"],
}

# OpenAPI/Swagger file patterns
OPENAPI_PATTERNS = [
    "openapi.json",
    "openapi.yaml",
    "openapi.yml",
    "swagger.json",
    "swagger.yaml",
    "swagger.yml",
    "**/openapi.json",
    "**/swagger.json",
    "**/api-docs.json",
]


def _find_openapi_files(repo_path: str) -> list[str]:
    """Find OpenAPI/Swagger files in the repository."""
    import glob

    found_files = []
    for pattern in OPENAPI_PATTERNS:
        matches = glob.glob(os.path.join(repo_path, pattern), recursive=True)
        found_files.extend(matches)
    return list(set(found_files))


def _detect_framework(repo_path: str) -> str:
    """Detect the web framework used in the repository."""
    # Check for Python frameworks
    requirements_files = ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"]
    for req_file in requirements_files:
        req_path = os.path.join(repo_path, req_file)
        if os.path.exists(req_path):
            with open(req_path, "r") as f:
                content = f.read().lower()
                if "fastapi" in content:
                    return "fastapi"
                if "flask" in content:
                    return "flask"
                if "django" in content:
                    return "django"

    # Check for Node.js frameworks
    package_json = os.path.join(repo_path, "package.json")
    if os.path.exists(package_json):
        with open(package_json, "r") as f:
            try:
                pkg = json.load(f)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "express" in deps:
                    return "express"
                if "fastify" in deps:
                    return "fastify"
                if "koa" in deps:
                    return "koa"
                if "hapi" in deps or "@hapi/hapi" in deps:
                    return "hapi"
            except json.JSONDecodeError:
                pass

    # Check for Go frameworks
    go_mod = os.path.join(repo_path, "go.mod")
    if os.path.exists(go_mod):
        with open(go_mod, "r") as f:
            content = f.read().lower()
            if "gin-gonic" in content:
                return "gin"
            if "fiber" in content:
                return "fiber"
            if "echo" in content:
                return "echo"

    # Check for Java/Spring
    pom_xml = os.path.join(repo_path, "pom.xml")
    if os.path.exists(pom_xml):
        with open(pom_xml, "r") as f:
            content = f.read().lower()
            if "spring-boot" in content or "spring-web" in content:
                return "spring"

    return "unknown"


def _find_route_files(repo_path: str, framework: str) -> list[str]:
    """Find route files based on detected framework."""
    import glob

    patterns = ROUTE_FILE_PATTERNS.get(framework, [])

    # Add generic patterns if framework unknown
    if framework == "unknown":
        patterns = [
            "**/routes/**/*.py",
            "**/routes/**/*.js",
            "**/routes/**/*.ts",
            "**/api/**/*.py",
            "**/api/**/*.js",
            "**/api/**/*.ts",
            "**/controllers/**/*.py",
            "**/controllers/**/*.js",
            "**/controllers/**/*.ts",
        ]

    found_files = []
    for pattern in patterns:
        matches = glob.glob(os.path.join(repo_path, pattern), recursive=True)
        found_files.extend(matches)

    # Filter out test files and node_modules
    filtered = [
        f
        for f in found_files
        if not any(
            exclude in f
            for exclude in ["node_modules", "__pycache__", ".git", "test_", "_test.", ".test."]
        )
    ]

    return list(set(filtered))


def _extract_routes_with_regex(file_path: str, framework: str) -> list[dict]:
    """Extract basic route info using regex patterns."""
    routes = []

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        lines = content.split("\n")

    # Framework-specific patterns
    patterns = {
        "fastapi": [
            r'@(router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            r'@(router|app)\.(get|post|put|delete|patch)\s*\(\s*path\s*=\s*["\']([^"\']+)["\']',
        ],
        "flask": [
            r'@(app|blueprint|bp)\.(route)\s*\(\s*["\']([^"\']+)["\']',
            r'@(app|blueprint|bp)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        ],
        "express": [
            r'(router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        ],
        "django": [
            r'path\s*\(\s*["\']([^"\']+)["\']',
            r're_path\s*\(\s*["\']([^"\']+)["\']',
        ],
    }

    framework_patterns = patterns.get(framework, patterns.get("fastapi", []))

    for i, line in enumerate(lines):
        for pattern in framework_patterns:
            matches = re.findall(pattern, line, re.IGNORECASE)
            for match in matches:
                if len(match) >= 3:
                    method = match[1].upper()
                    path = match[2]
                elif len(match) >= 2:
                    method = "GET"  # Default for Django path()
                    path = match[0] if match[0].startswith("/") else f"/{match[0]}"
                else:
                    continue

                routes.append(
                    {
                        "method": method if method != "ROUTE" else "GET",
                        "path": path,
                        "file": file_path,
                        "line": i + 1,
                    }
                )

    return routes


def _analyze_with_claude_cli(
    repo_path: str,
    framework: str,
    route_files: list[str],
) -> list[EndpointInfo]:
    """Use Claude CLI to analyze route files and extract endpoint details.

    Claude CLI can explore the repository autonomously, reading files as needed.
    Uses the centralized ClaudeCLI utility.
    """
    # Build the prompt for Claude CLI
    files_list = "\n".join([f"- {f}" for f in route_files[:20]])  # Limit to 20 files

    prompt = f"""You are analyzing a {framework} backend repository to extract ALL API endpoints.

TASK: Find and document every API endpoint in this repository.

INSTRUCTIONS:
1. First, explore the route/api files to understand the structure
2. Look for router prefix declarations (e.g., `router = APIRouter(prefix="/api/v1/tickets")`)
3. For each endpoint, extract the FULL path (prefix + route path)
4. Read docstrings and function bodies to understand what each endpoint does
5. Check for authentication requirements (Depends, decorators, middleware)
6. Extract parameter details from function signatures

Key files to analyze:
{files_list}

Also look for:
- Main app file that registers routers (to find prefixes)
- Any OpenAPI/Swagger configuration
- Authentication middleware or decorators

OUTPUT FORMAT - Return ONLY a valid JSON array (no markdown, no explanation):
[
  {{
    "method": "GET",
    "path": "/api/v1/users",
    "file": "src/routes/users.py",
    "line": 45,
    "description": "Detailed description of what this endpoint does",
    "parameters": [
      {{"name": "page", "param_type": "query", "data_type": "int", "required": false, "description": "Page number"}}
    ],
    "response_type": "List[User]",
    "auth_required": true,
    "tags": ["users"]
  }}
]

CRITICAL:
- Each method+path combination must appear exactly ONCE
- Include the FULL path with all prefixes
- Do not invent endpoints that don't exist in the code

Return ONLY the JSON array, nothing else."""

    try:
        # Use centralized ClaudeCLI utility
        cli = ClaudeCLI(
            working_dir=Path(repo_path),
            model="opus",  # Use Opus for better accuracy
            timeout=180,
            s3_prefix="endpoint-detection",
        )

        logger.info(f"Running Claude CLI for endpoint detection in {repo_path}")

        # Run synchronously since this is called from non-async context
        result = cli.run_sync(
            prompt,
            context_id=f"endpoints_{Path(repo_path).name}",
            save_prompt=True,
            save_output=True,
            save_thinking=False,  # Not needed for this task
        )

        if not result.success:
            logger.error(f"Claude CLI failed: {result.error}")
            return []

        response_text = result.output.strip()

        # Clean up response - remove markdown code blocks if present
        cleaned = response_text
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        # Try to extract JSON from the response
        # Sometimes Claude adds text before/after the JSON
        json_match = re.search(r"\[[\s\S]*\]", cleaned)
        if json_match:
            cleaned = json_match.group(0)

        # Parse JSON response
        endpoints_data = json.loads(cleaned)

        # Deduplicate by method+path
        seen = set()
        endpoints = []
        for ep in endpoints_data:
            key = (ep.get("method", "GET").upper(), ep.get("path", ""))
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

            endpoints.append(
                EndpointInfo(
                    method=ep.get("method", "GET").upper(),
                    path=ep.get("path", ""),
                    file=ep.get("file", ""),
                    line=ep.get("line"),
                    description=ep.get("description", ""),
                    parameters=params,
                    response_type=ep.get("response_type", ""),
                    auth_required=ep.get("auth_required", False),
                    tags=ep.get("tags", []),
                )
            )

        logger.info(f"Claude CLI detected {len(endpoints)} unique endpoints")
        return endpoints

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude CLI response as JSON: {e}")
        logger.debug(f"Response was: {response_text[:1000] if 'response_text' in dir() else 'N/A'}")
        return []
    except Exception as e:
        logger.error(f"Claude CLI analysis failed: {e}")
        return []


def _analyze_with_gemini(
    route_files_content: dict[str, str],
    framework: str,
) -> list[EndpointInfo]:
    """Fallback: Use Gemini Flash to analyze route files (faster but less accurate)."""
    from turbowrap.llm.gemini import GeminiClient

    # Build the prompt
    files_text = ""
    for filepath, content in route_files_content.items():
        files_text += f"\n\n### File: {filepath}\n```\n{content[:8000]}\n```"

    system_prompt = """You are an API documentation expert. Analyze the provided code files and extract all API endpoints.
For each endpoint, identify:
- HTTP method (GET, POST, PUT, DELETE, PATCH)
- URL path (include router prefix!)
- Description of what the endpoint does
- Parameters (path params, query params, body params)
- Response type
- Whether authentication is required (look for auth decorators, middleware, etc.)

IMPORTANT: Do not duplicate endpoints. Each method+path should appear only once.

Return your response as a valid JSON array. Do not include any markdown code blocks or extra text, ONLY the JSON array."""

    user_prompt = f"""Analyze these {framework} route files and extract all API endpoints:

{files_text}

Return a JSON array with this structure for each endpoint:
[
  {{
    "method": "GET",
    "path": "/api/users",
    "file": "src/routes/users.py",
    "line": 45,
    "description": "List all users with pagination support",
    "parameters": [
      {{"name": "page", "param_type": "query", "data_type": "int", "required": false, "description": "Page number"}}
    ],
    "response_type": "List[User]",
    "auth_required": true,
    "tags": ["users", "admin"]
  }}
]

Return ONLY the JSON array, no other text."""

    try:
        client = GeminiClient()
        response = client.generate(user_prompt, system_prompt)

        # Clean up response - remove markdown code blocks if present
        cleaned = response.strip()
        if cleaned.startswith("```"):
            # Remove code block markers
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        # Parse JSON response
        endpoints_data = json.loads(cleaned)

        # Deduplicate by method+path
        seen = set()
        endpoints = []
        for ep in endpoints_data:
            key = (ep.get("method", "GET").upper(), ep.get("path", ""))
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

            endpoints.append(
                EndpointInfo(
                    method=ep.get("method", "GET").upper(),
                    path=ep.get("path", ""),
                    file=ep.get("file", ""),
                    line=ep.get("line"),
                    description=ep.get("description", ""),
                    parameters=params,
                    response_type=ep.get("response_type", ""),
                    auth_required=ep.get("auth_required", False),
                    tags=ep.get("tags", []),
                )
            )

        return endpoints

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        logger.debug(f"Response was: {response[:500] if response else 'empty'}")
        return []
    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}")
        return []


def detect_endpoints(
    repo_path: str,
    use_ai: bool = True,
    use_claude: bool = True,
) -> DetectionResult:
    """Detect API endpoints in a repository.

    Args:
        repo_path: Path to the repository root.
        use_ai: Whether to use AI for enhanced analysis.
        use_claude: Whether to use Claude CLI (True) or Gemini Flash (False) for AI analysis.

    Returns:
        DetectionResult with detected endpoints and metadata.
    """
    result = DetectionResult(detected_at=datetime.utcnow().isoformat())

    if not os.path.isdir(repo_path):
        result.error = f"Repository path not found: {repo_path}"
        return result

    # 1. Look for OpenAPI/Swagger files
    openapi_files = _find_openapi_files(repo_path)
    if openapi_files:
        result.openapi_file = openapi_files[0].replace(repo_path, "").lstrip("/")
        logger.info(f"Found OpenAPI file: {result.openapi_file}")

    # 2. Detect framework
    framework = _detect_framework(repo_path)
    result.framework = framework
    logger.info(f"Detected framework: {framework}")

    # 3. Find route files
    route_files = _find_route_files(repo_path, framework)
    logger.info(f"Found {len(route_files)} route files")

    if not route_files:
        # No route files found
        return result

    # 4. Extract routes using AI
    if use_ai:
        if use_claude:
            # Primary: Use Claude CLI for autonomous exploration
            logger.info("Using Claude CLI for endpoint detection (autonomous exploration)")
            endpoints = _analyze_with_claude_cli(repo_path, framework, route_files)
            result.routes = endpoints
        else:
            # Fallback: Use Gemini Flash (requires passing file contents)
            logger.info("Using Gemini Flash for endpoint detection")
            route_files_content = {}
            total_chars = 0
            max_chars = 50000  # Limit total content to avoid token limits

            for filepath in route_files[:10]:  # Limit to 10 files
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if total_chars + len(content) < max_chars:
                            route_files_content[filepath.replace(repo_path, "").lstrip("/")] = content
                            total_chars += len(content)
                except Exception as e:
                    logger.warning(f"Could not read {filepath}: {e}")

            if route_files_content:
                endpoints = _analyze_with_gemini(route_files_content, framework)
                result.routes = endpoints
    else:
        # Fallback to regex-based extraction
        all_routes = []
        for filepath in route_files:
            routes = _extract_routes_with_regex(filepath, framework)
            for r in routes:
                r["file"] = r["file"].replace(repo_path, "").lstrip("/")
                all_routes.append(
                    EndpointInfo(
                        method=r["method"],
                        path=r["path"],
                        file=r["file"],
                        line=r.get("line"),
                    )
                )
        result.routes = all_routes

    return result


def result_to_dict(result: DetectionResult) -> dict:
    """Convert DetectionResult to a JSON-serializable dict."""
    return {
        "swagger_url": result.swagger_url,
        "openapi_file": result.openapi_file,
        "detected_at": result.detected_at,
        "framework": result.framework,
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
                "tags": ep.tags,
            }
            for ep in result.routes
        ],
    }
