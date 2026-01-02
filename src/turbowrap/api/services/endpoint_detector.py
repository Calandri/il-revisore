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
    source: str = "backend"  # backend, frontend - where this endpoint was detected


@dataclass
class DetectionResult:
    """Result of endpoint detection."""

    swagger_url: str | None = None
    openapi_file: str | None = None
    detected_at: str = ""
    framework: str = ""  # Backend framework (fastapi, flask, etc.)
    frontend_framework: str | None = None  # Frontend framework (react, vue, etc.)
    routes: list[EndpointInfo] = field(default_factory=list)
    error: str | None = None


ROUTE_FILE_PATTERNS: dict[str, list[str]] = {
    "fastapi": [
        "**/routes/*.py",
        "**/routers/*.py",
        "**/api/*.py",
        "**/endpoints/*.py",
        "**/apis.py",
        "**/*_api.py",
        "**/*_apis.py",
    ],
    "flask": ["**/routes/*.py", "**/views/*.py", "**/api/*.py", "**/*_routes.py"],
    "express": ["**/routes/*.js", "**/routes/*.ts", "**/api/*.js", "**/api/*.ts"],
    "django": ["**/urls.py", "**/views.py"],
    "spring": ["**/*Controller.java", "**/*Resource.java"],
    "gin": ["**/routes.go", "**/handlers.go", "**/api/*.go"],
    "rails": ["**/routes.rb", "**/controllers/*.rb"],
    "lambda": [
        "**/handler.py",
        "**/handlers/*.py",
        "**/lambda_function.py",
        "**/*_handler.py",
        "**/functions/*.py",
        "**/lambdas/*.py",
    ],
    "chalice": ["**/app.py", "**/chalicelib/*.py"],
    "serverless": ["**/serverless.yml", "**/serverless.yaml", "**/handler.js", "**/handler.ts"],
}

# Frontend file patterns - where API calls are typically made
FRONTEND_FILE_PATTERNS: dict[str, list[str]] = {
    "react": [
        "**/src/**/*.tsx",
        "**/src/**/*.ts",
        "**/src/**/*.jsx",
        "**/src/**/*.js",
        "**/app/**/*.tsx",
        "**/app/**/*.ts",
        "**/pages/**/*.tsx",
        "**/pages/**/*.ts",
        "**/components/**/*.tsx",
        "**/components/**/*.ts",
        "**/hooks/**/*.ts",
        "**/hooks/**/*.tsx",
        "**/services/**/*.ts",
        "**/api/**/*.ts",
        "**/lib/**/*.ts",
    ],
    "vue": [
        "**/src/**/*.vue",
        "**/src/**/*.ts",
        "**/src/**/*.js",
        "**/composables/**/*.ts",
        "**/stores/**/*.ts",
    ],
    "angular": [
        "**/src/**/*.ts",
        "**/src/**/*.service.ts",
        "**/services/**/*.ts",
    ],
    "svelte": [
        "**/src/**/*.svelte",
        "**/src/**/*.ts",
        "**/lib/**/*.ts",
    ],
    "nextjs": [
        "**/app/**/*.tsx",
        "**/app/**/*.ts",
        "**/pages/**/*.tsx",
        "**/pages/**/*.ts",
        "**/lib/**/*.ts",
        "**/utils/**/*.ts",
    ],
    "nuxt": [
        "**/pages/**/*.vue",
        "**/composables/**/*.ts",
        "**/utils/**/*.ts",
    ],
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
    # Check for Serverless/Lambda frameworks first (more specific)
    serverless_yml = os.path.join(repo_path, "serverless.yml")
    serverless_yaml = os.path.join(repo_path, "serverless.yaml")
    if os.path.exists(serverless_yml) or os.path.exists(serverless_yaml):
        return "serverless"

    # Check for AWS SAM (template.yaml)
    sam_template = os.path.join(repo_path, "template.yaml")
    sam_template_yml = os.path.join(repo_path, "template.yml")
    if os.path.exists(sam_template) or os.path.exists(sam_template_yml):
        return "lambda"

    # Check for Chalice
    chalice_dir = os.path.join(repo_path, ".chalice")
    if os.path.exists(chalice_dir):
        return "chalice"

    # Check for Python frameworks
    requirements_files = ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"]
    for req_file in requirements_files:
        req_path = os.path.join(repo_path, req_file)
        if os.path.exists(req_path):
            with open(req_path) as f:
                content = f.read().lower()
                if "chalice" in content:
                    return "chalice"
                if "fastapi" in content:
                    return "fastapi"
                if "flask" in content:
                    return "flask"
                if "django" in content:
                    return "django"

    # Check for Node.js frameworks
    package_json = os.path.join(repo_path, "package.json")
    if os.path.exists(package_json):
        with open(package_json) as f:
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
        with open(go_mod) as f:
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
        with open(pom_xml) as f:
            content = f.read().lower()
            if "spring-boot" in content or "spring-web" in content:
                return "spring"

    return "unknown"


def _detect_frontend_framework(repo_path: str) -> str | None:
    """Detect frontend framework used in the repository."""
    package_json = os.path.join(repo_path, "package.json")
    if not os.path.exists(package_json):
        return None

    try:
        with open(package_json) as f:
            pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            # Next.js (check before React)
            if "next" in deps:
                return "nextjs"
            # Nuxt.js (check before Vue)
            if "nuxt" in deps or "nuxt3" in deps:
                return "nuxt"
            # React
            if "react" in deps:
                return "react"
            # Vue
            if "vue" in deps:
                return "vue"
            # Angular
            if "@angular/core" in deps:
                return "angular"
            # Svelte
            if "svelte" in deps:
                return "svelte"
    except (json.JSONDecodeError, OSError):
        pass

    return None


def _find_frontend_files(repo_path: str, framework: str) -> list[str]:
    """Find frontend files that may contain API calls."""
    import glob

    patterns = FRONTEND_FILE_PATTERNS.get(framework, [])

    # If framework not recognized, use generic patterns
    if not patterns:
        patterns = [
            "**/src/**/*.ts",
            "**/src/**/*.tsx",
            "**/src/**/*.js",
            "**/src/**/*.jsx",
            "**/src/**/*.vue",
            "**/src/**/*.svelte",
            "**/app/**/*.ts",
            "**/app/**/*.tsx",
            "**/pages/**/*.ts",
            "**/pages/**/*.tsx",
            "**/components/**/*.ts",
            "**/components/**/*.tsx",
            "**/hooks/**/*.ts",
            "**/services/**/*.ts",
            "**/api/**/*.ts",
        ]

    found_files = []
    for pattern in patterns:
        matches = glob.glob(os.path.join(repo_path, pattern), recursive=True)
        found_files.extend(matches)

    # Filter out test files, node_modules, etc.
    filtered = [
        f
        for f in found_files
        if not any(
            exclude in f
            for exclude in [
                "node_modules",
                "__pycache__",
                ".git",
                ".test.",
                ".spec.",
                "test_",
                "_test.",
                "__tests__",
                ".d.ts",  # Exclude type definitions
            ]
        )
    ]

    return list(set(filtered))


def _extract_frontend_api_calls(file_path: str) -> list[dict[str, Any]]:
    """Extract API calls from frontend files using regex patterns."""
    routes: list[dict[str, Any]] = []

    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception:
        return routes

    # Patterns to detect frontend API calls
    patterns = [
        # fetch() calls
        (r'fetch\s*\(\s*[`"\']([^`"\']+)[`"\']', "GET"),
        (r'fetch\s*\(\s*[`"\']([^`"\']+)[`"\']\s*,\s*\{\s*method\s*:\s*["\'](\w+)["\']', None),
        # axios calls
        (r'axios\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[`"\']([^`"\']+)[`"\']', None),
        (r'axios\s*\(\s*\{\s*[^}]*url\s*:\s*[`"\']([^`"\']+)[`"\']', "GET"),
        # useSWR / useQuery (React Query / SWR)
        (r'useSWR\s*\(\s*[`"\']([^`"\']+)[`"\']', "GET"),
        (
            r'useQuery\s*\(\s*\[[^\]]*\]\s*,\s*\(\)\s*=>\s*fetch\s*\(\s*[`"\']([^`"\']+)[`"\']',
            "GET",
        ),
        (r'useQuery\s*\(\s*[`"\']([^`"\']+)[`"\']', "GET"),
        # $fetch (Nuxt)
        (r'\$fetch\s*\(\s*[`"\']([^`"\']+)[`"\']', "GET"),
        (r'\$fetch\s*\(\s*[`"\']([^`"\']+)[`"\']\s*,\s*\{\s*method\s*:\s*["\'](\w+)["\']', None),
        # Generic API client patterns
        (r'api\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[`"\']([^`"\']+)[`"\']', None),
        (r'client\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[`"\']([^`"\']+)[`"\']', None),
        (r'http\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[`"\']([^`"\']+)[`"\']', None),
        # ky (HTTP client)
        (r'ky\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[`"\']([^`"\']+)[`"\']', None),
        # ofetch / $fetch
        (r'ofetch\s*\(\s*[`"\']([^`"\']+)[`"\']', "GET"),
    ]

    for i, line in enumerate(lines):
        for pattern, default_method in patterns:
            matches = re.findall(pattern, line, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    if default_method is None:
                        # Method is in the match
                        if len(match) == 2:
                            method_or_path, path_or_method = match
                            # Determine which is method and which is path
                            if method_or_path.upper() in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                                method = method_or_path.upper()
                                path = path_or_method
                            else:
                                method = (
                                    path_or_method.upper()
                                    if path_or_method.upper()
                                    in ["GET", "POST", "PUT", "DELETE", "PATCH"]
                                    else "GET"
                                )
                                path = method_or_path
                        else:
                            continue
                    else:
                        method = default_method
                        path = match[0] if len(match) == 1 else match[0]
                else:
                    method = default_method or "GET"
                    path = match

                # Skip if path contains template variables that look broken
                if not path or path.startswith("$") or path.startswith("{"):
                    continue

                # Normalize path
                if not path.startswith("/") and not path.startswith("http"):
                    path = "/" + path

                routes.append(
                    {
                        "method": method,
                        "path": path,
                        "file": file_path,
                        "line": i + 1,
                        "source": "frontend",
                    }
                )

    return routes


def _find_route_files(repo_path: str, framework: str) -> list[str]:
    """Find route files based on detected framework."""
    import glob

    patterns = ROUTE_FILE_PATTERNS.get(framework, [])

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
            # Lambda/Serverless patterns
            "**/handler.py",
            "**/handlers/*.py",
            "**/lambda_function.py",
            "**/*_handler.py",
            "**/functions/*.py",
            "**/handler.js",
            "**/handler.ts",
        ]

    found_files = []
    for pattern in patterns:
        matches = glob.glob(os.path.join(repo_path, pattern), recursive=True)
        found_files.extend(matches)

    filtered = [
        f
        for f in found_files
        if not any(
            exclude in f
            for exclude in ["node_modules", "__pycache__", ".git", "test_", "_test.", ".test."]
        )
    ]

    return list(set(filtered))


def _extract_routes_with_regex(file_path: str, framework: str) -> list[dict[str, Any]]:
    """Extract basic route info using regex patterns."""
    routes: list[dict[str, Any]] = []

    with open(file_path, encoding="utf-8", errors="ignore") as f:
        content = f.read()
        lines = content.split("\n")

    patterns: dict[str, list[str]] = {
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


def _analyze_with_gemini_cli(
    repo_path: str,
    framework: str,
) -> list[EndpointInfo]:
    """Use Gemini CLI to analyze repository and extract endpoint details.

    Gemini CLI explores the repository autonomously using .llms/structure.xml as context.
    Uses Gemini Flash for fast endpoint detection.
    """
    import asyncio

    from turbowrap.config import get_settings
    from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

    prompt = f"""You are a senior backend architect. Your task is to thoroughly and completely document ALL REST API endpoints in this {framework} repository.

First, read .llms/structure.xml to get an overview of the project structure. Then explore each route/API file, analyze the source code, and document every single endpoint.

For each endpoint, you must identify:
- The HTTP method and complete path (including router prefixes)
- A clear description of what it does
- Parameters (path, query, body, header) with type and whether required
- The response type
- Whether it requires authentication and what type (Bearer, API-Key, Basic, OAuth2)
- Visibility: "public" (no auth), "private" (user auth), "internal" (admin/system)

Be meticulous: do not skip any endpoints, do not invent endpoints that don't exist, always verify in the code.

Respond ONLY with a valid JSON array (no markdown, no explanations):
[
  {{
    "method": "GET",
    "path": "/api/v1/users",
    "file": "src/routes/users.py",
    "line": 45,
    "description": "Returns paginated list of users",
    "parameters": [
      {{"name": "page", "param_type": "query", "data_type": "int", "required": false, "description": "Page number"}},
      {{"name": "limit", "param_type": "query", "data_type": "int", "required": false, "description": "Items per page"}}
    ],
    "response_type": "List[User]",
    "auth_required": true,
    "visibility": "private",
    "auth_type": "Bearer",
    "tags": ["users"]
  }}
]"""

    response_text = ""
    try:
        settings = get_settings()
        artifact_saver = S3ArtifactSaver(
            bucket=settings.thinking.s3_bucket,
            region=settings.thinking.s3_region,
            prefix="endpoint-detection",
        )

        cli = GeminiCLI(
            working_dir=Path(repo_path),
            model="flash",  # Use Flash for fast analysis
            timeout=None,  # No timeout - let it complete
            artifact_saver=artifact_saver,
        )

        logger.info(f"Running Gemini CLI (flash) for endpoint detection in {repo_path}")

        # Run async - need to handle from sync context
        async def run_cli() -> tuple[bool, str, str | None]:
            result = await cli.run(
                prompt,
                save_artifacts=True,
            )
            return result.success, result.output, result.error

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
            return []

        response_text = output.strip()

        # Parse JSON array from LLM response
        endpoints_data = parse_llm_json(response_text, default=[])
        if not endpoints_data:
            logger.warning("Could not parse endpoints JSON from Gemini CLI response")
            return []

        seen: set[tuple[str, str]] = set()
        endpoints: list[EndpointInfo] = []
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
                    visibility=ep.get("visibility", "private"),
                    auth_type=ep.get("auth_type", ""),
                    tags=ep.get("tags", []),
                )
            )

        logger.info(f"Gemini CLI detected {len(endpoints)} unique endpoints")
        return endpoints

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini CLI response as JSON: {e}")
        logger.debug(f"Response was: {response_text[:1000] if response_text else 'N/A'}")
        return []
    except Exception as e:
        logger.error(f"Gemini CLI analysis failed: {e}")
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

    system_prompt = """You are an API documentation expert. Analyze the \
provided code files and extract all API endpoints.
For each endpoint, identify:
- HTTP method (GET, POST, PUT, DELETE, PATCH)
- URL path (include router prefix!)
- Description of what the endpoint does
- Parameters (path params, query params, body params)
- Response type
- Whether authentication is required (look for auth decorators, middleware, etc.)
- Visibility level (public/private/internal)
- Authentication type (Bearer, Basic, API-Key, Cookie, OAuth2)

IMPORTANT: Do not duplicate endpoints. Each method+path should appear only once.

Return your response as a valid JSON array. Do not include any markdown code \
blocks or extra text, ONLY the JSON array."""

    user_prompt = f"""Analyze these {framework} route files and extract all API endpoints:

{files_text}

VISIBILITY RULES:
- "public" = No auth required (login, register, health, public APIs)
- "private" = Auth required for authenticated users
- "internal" = Auth required + admin-only or internal service endpoints

AUTH TYPE OPTIONS: Bearer, Basic, API-Key, Cookie, OAuth2, or "" for public

Return a JSON array with this structure for each endpoint:
[
  {{
    "method": "GET",
    "path": "/api/users",
    "file": "src/routes/users.py",
    "line": 45,
    "description": "List all users with pagination support",
    "parameters": [
      {{"name": "page", "param_type": "query", "data_type": "int", \
       "required": false, "description": "Page number"}}
    ],
    "response_type": "List[User]",
    "auth_required": true,
    "visibility": "private",
    "auth_type": "Bearer",
    "tags": ["users", "admin"]
  }}
]

Return ONLY the JSON array, no other text."""

    response = ""
    try:
        client = GeminiClient()
        response = client.generate(user_prompt, system_prompt)

        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        endpoints_data = json.loads(cleaned)

        seen: set[tuple[str, str]] = set()
        endpoints: list[EndpointInfo] = []
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
                    visibility=ep.get("visibility", "private"),
                    auth_type=ep.get("auth_type", ""),
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
    include_frontend: bool = True,
) -> DetectionResult:
    """Detect API endpoints in a repository.

    Args:
        repo_path: Path to the repository root.
        use_ai: Whether to use AI for enhanced analysis.
        use_claude: Whether to use Claude CLI (True) or Gemini Flash (False) for AI analysis.
        include_frontend: Whether to also detect frontend API calls (fetch, axios, etc.).

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

    # 2. Detect backend framework
    framework = _detect_framework(repo_path)
    result.framework = framework
    logger.info(f"Detected backend framework: {framework}")

    # 3. Detect frontend framework
    frontend_framework = _detect_frontend_framework(repo_path)
    result.frontend_framework = frontend_framework
    if frontend_framework:
        logger.info(f"Detected frontend framework: {frontend_framework}")

    route_files = _find_route_files(repo_path, framework)
    logger.info(f"Found {len(route_files)} backend route files")

    all_endpoints: list[EndpointInfo] = []

    # 4. Extract backend routes using AI
    if route_files:
        if use_ai:
            if use_claude:
                logger.info("Using Gemini CLI (flash) for backend endpoint detection")
                endpoints = _analyze_with_gemini_cli(repo_path, framework)
                all_endpoints.extend(endpoints)
            else:
                # Fallback: Use Gemini Flash (requires passing file contents)
                logger.info("Using Gemini Flash for backend endpoint detection")
                route_files_content: dict[str, str] = {}
                total_chars = 0
                max_chars = 50000  # Limit total content to avoid token limits

                for filepath in route_files[:10]:  # Limit to 10 files
                    try:
                        with open(filepath, encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            if total_chars + len(content) < max_chars:
                                route_files_content[filepath.replace(repo_path, "").lstrip("/")] = (
                                    content
                                )
                                total_chars += len(content)
                    except Exception as e:
                        logger.warning(f"Could not read {filepath}: {e}")

                if route_files_content:
                    endpoints = _analyze_with_gemini(route_files_content, framework)
                    all_endpoints.extend(endpoints)
        else:
            # Fallback to regex-based extraction for backend
            for filepath in route_files:
                routes = _extract_routes_with_regex(filepath, framework)
                for r in routes:
                    r["file"] = r["file"].replace(repo_path, "").lstrip("/")
                    all_endpoints.append(
                        EndpointInfo(
                            method=r["method"],
                            path=r["path"],
                            file=r["file"],
                            line=r.get("line"),
                            source="backend",
                        )
                    )

    # 5. Extract frontend API calls if requested
    if include_frontend and frontend_framework:
        logger.info(f"Scanning frontend files for API calls ({frontend_framework})")
        frontend_files = _find_frontend_files(repo_path, frontend_framework)
        logger.info(f"Found {len(frontend_files)} frontend files to scan")

        frontend_routes: list[EndpointInfo] = []
        seen_frontend: set[tuple[str, str, str]] = set()  # (method, path, file) to avoid duplicates

        for filepath in frontend_files[:50]:  # Limit to 50 files
            api_calls = _extract_frontend_api_calls(filepath)
            for call in api_calls:
                # Deduplicate by method+path+file
                key = (call["method"], call["path"], call["file"])
                if key in seen_frontend:
                    continue
                seen_frontend.add(key)

                frontend_routes.append(
                    EndpointInfo(
                        method=call["method"],
                        path=call["path"],
                        file=call["file"].replace(repo_path, "").lstrip("/"),
                        line=call.get("line"),
                        source="frontend",
                        description=f"API call from {frontend_framework} frontend",
                    )
                )

        logger.info(f"Found {len(frontend_routes)} frontend API calls")
        all_endpoints.extend(frontend_routes)

    result.routes = all_endpoints
    return result


def save_endpoints_to_db(
    db_session: Any,
    repository_id: str,
    result: DetectionResult,
) -> int:
    """Save detected endpoints to database with upsert logic.

    Uses INSERT ON DUPLICATE KEY UPDATE to avoid duplicates.
    Endpoints are identified uniquely by (repository_id, method, path).

    Args:
        db_session: SQLAlchemy session.
        repository_id: Repository UUID.
        result: DetectionResult with endpoints.

    Returns:
        Number of endpoints saved/updated.
    """
    from datetime import datetime

    from turbowrap.db.models import Endpoint

    if not result.routes:
        return 0

    count = 0
    for ep in result.routes:
        # Check if endpoint exists
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

        if existing:
            # Update existing endpoint
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
            existing.framework = (
                result.framework if ep.source == "backend" else result.frontend_framework
            )
            existing.source = ep.source
            existing.updated_at = datetime.utcnow()
        else:
            # Create new endpoint
            new_endpoint = Endpoint(
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
                framework=result.framework if ep.source == "backend" else result.frontend_framework,
                source=ep.source,
            )
            db_session.add(new_endpoint)

        count += 1

    db_session.commit()
    logger.info(f"Saved {count} endpoints to database for repository {repository_id}")
    return count


def result_to_dict(result: DetectionResult) -> dict[str, Any]:
    """Convert DetectionResult to a JSON-serializable dict."""
    return {
        "swagger_url": result.swagger_url,
        "openapi_file": result.openapi_file,
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
