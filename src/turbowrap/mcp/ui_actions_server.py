#!/usr/bin/env python3
"""TurboWrap MCP Server.

This MCP server exposes tools for AI to interact with TurboWrap:

UI Actions:
- navigate: Navigate user to a specific page
- highlight: Highlight DOM elements
- show_toast: Show notification toast
- open_modal: Open a specific modal

Issues API:
- list_issues: List code review issues for a repository
- get_issue: Get details of a specific issue
- resolve_issue: Mark an issue as resolved

Tests API:
- list_test_suites: List test suites for a repository
- get_test_summary: Get test statistics
- run_test_suite: Run a specific test suite

Fix API:
- list_fixable_issues: List issues that can be auto-fixed
- start_fix: Start an AI fix session
- get_active_fix_sessions: Get currently running fix sessions
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# TurboWrap API base URL (configurable via env)
TURBOWRAP_API_URL = os.environ.get("TURBOWRAP_API_URL", "http://localhost:8000")

# Create MCP server
server = Server("turbowrap-ui")


async def execute_ui_action(action_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a UI action by calling TurboWrap API.

    Args:
        action_type: Type of action (navigate, highlight, toast, modal)
        params: Action parameters

    Returns:
        Result from API
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{TURBOWRAP_API_URL}/api/ui-actions/execute",
                json={
                    "action": action_type,
                    "params": params,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to execute UI action: {e}")
            return {"success": False, "error": str(e)}


async def api_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a GET request to TurboWrap API.

    Args:
        endpoint: API endpoint path (e.g., "/api/issues")
        params: Query parameters

    Returns:
        API response as dict, or error dict
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{TURBOWRAP_API_URL}{endpoint}",
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.HTTPError as e:
            logger.error(f"API GET {endpoint} failed: {e}")
            return {"success": False, "error": str(e)}


async def api_post(
    endpoint: str, data: dict[str, Any] | None = None, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make a POST request to TurboWrap API.

    Args:
        endpoint: API endpoint path
        data: JSON body
        params: Query parameters

    Returns:
        API response as dict, or error dict
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{TURBOWRAP_API_URL}{endpoint}",
                json=data,
                params=params,
                timeout=60.0,  # Longer timeout for operations
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.HTTPError as e:
            logger.error(f"API POST {endpoint} failed: {e}")
            return {"success": False, "error": str(e)}


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available UI action tools."""
    return [
        Tool(
            name="navigate",
            description=(
                "Navigate the user to a specific page in TurboWrap. "
                "Use this when the user asks to see a specific section or page."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "The URL path to navigate to. Examples: "
                            "'/tests' for test suites, "
                            "'/issues' for Linear issues, "
                            "'/repositories' for repo list, "
                            "'/reviews' for code reviews"
                        ),
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="highlight",
            description=(
                "Highlight one or more UI elements to draw user attention. "
                "The elements will pulse with an indigo glow for 3 seconds. "
                "Use this to point out specific buttons, sections, or components."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector for the element(s) to highlight. Examples: "
                            "'#submit-btn' for ID, "
                            "'.test-card' for class, "
                            "'button[data-action=\"run\"]' for attribute"
                        ),
                    },
                },
                "required": ["selector"],
            },
        ),
        Tool(
            name="show_toast",
            description=(
                "Show a toast notification to the user. "
                "Use this to provide feedback or confirmations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to display in the toast",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["success", "error", "warning", "info"],
                        "description": "Toast type (default: info)",
                        "default": "info",
                    },
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="open_modal",
            description=(
                "Open a specific modal dialog in the UI. "
                "Use this to trigger forms or detailed views."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "modal_id": {
                        "type": "string",
                        "description": (
                            "The ID of the modal to open. Examples: "
                            "'new-test-suite-modal', "
                            "'fix-issues-modal', "
                            "'settings-modal'"
                        ),
                    },
                },
                "required": ["modal_id"],
            },
        ),
        Tool(
            name="get_current_page",
            description=(
                "Get information about the current page the user is viewing. "
                "Returns the URL path and page title."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # ============================================================
        # Issues API Tools
        # ============================================================
        Tool(
            name="list_issues",
            description=(
                "List code review issues for a repository. "
                "Returns issues with their status, severity, and file location."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "description": "UUID of the repository",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved", "ignored", "fixing", "all"],
                        "description": "Filter by status (default: open)",
                        "default": "open",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of issues to return (default: 50)",
                        "default": 50,
                    },
                },
                "required": ["repository_id"],
            },
        ),
        Tool(
            name="get_issue",
            description="Get detailed information about a specific issue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "UUID of the issue",
                    },
                },
                "required": ["issue_id"],
            },
        ),
        Tool(
            name="get_issues_summary",
            description=(
                "Get summary statistics of issues for a repository. "
                "Returns counts by status, severity, and category."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "description": "UUID of the repository",
                    },
                },
                "required": ["repository_id"],
            },
        ),
        Tool(
            name="resolve_issue",
            description="Mark an issue as resolved.",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "UUID of the issue to resolve",
                    },
                },
                "required": ["issue_id"],
            },
        ),
        # ============================================================
        # Tests API Tools
        # ============================================================
        Tool(
            name="list_test_suites",
            description=(
                "List test suites for a repository. "
                "Returns suite names, test counts, and last run status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "description": "UUID of the repository",
                    },
                },
                "required": ["repository_id"],
            },
        ),
        Tool(
            name="get_test_summary",
            description=(
                "Get test statistics for a repository. "
                "Returns pass/fail counts, coverage, and recent run info."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "description": "UUID of the repository",
                    },
                },
                "required": ["repository_id"],
            },
        ),
        Tool(
            name="run_test_suite",
            description=(
                "Run a specific test suite. "
                "Returns immediately with run ID; tests run in background."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "suite_id": {
                        "type": "string",
                        "description": "UUID of the test suite to run",
                    },
                },
                "required": ["suite_id"],
            },
        ),
        Tool(
            name="get_test_run",
            description="Get details and results of a specific test run.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "UUID of the test run",
                    },
                },
                "required": ["run_id"],
            },
        ),
        # ============================================================
        # Fix API Tools
        # ============================================================
        Tool(
            name="list_fixable_issues",
            description=(
                "List issues that can be auto-fixed by AI for a repository. "
                "Returns open issues with fix suggestions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "description": "UUID of the repository",
                    },
                },
                "required": ["repository_id"],
            },
        ),
        Tool(
            name="start_fix",
            description=(
                "Start an AI fix session to automatically fix selected issues. "
                "The fix runs in background; use get_active_fix_sessions to monitor."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repository_id": {
                        "type": "string",
                        "description": "UUID of the repository",
                    },
                    "issue_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of issue UUIDs to fix",
                    },
                },
                "required": ["repository_id", "issue_ids"],
            },
        ),
        Tool(
            name="get_active_fix_sessions",
            description="Get list of currently running AI fix sessions.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    logger.info(f"Tool called: {name} with args: {arguments}")

    if name == "navigate":
        path = arguments.get("path", "/")
        result = await execute_ui_action("navigate", {"path": path})
        if result.get("success"):
            return [TextContent(type="text", text=f"Navigated to {path}")]
        return [TextContent(type="text", text=f"Failed to navigate: {result.get('error')}")]

    if name == "highlight":
        selector = arguments.get("selector", "")
        result = await execute_ui_action("highlight", {"selector": selector})
        if result.get("success"):
            count = result.get("count", 0)
            return [
                TextContent(
                    type="text", text=f"Highlighted {count} element(s) matching '{selector}'"
                )
            ]
        return [TextContent(type="text", text=f"Failed to highlight: {result.get('error')}")]

    if name == "show_toast":
        message = arguments.get("message", "")
        toast_type = arguments.get("type", "info")
        result = await execute_ui_action("toast", {"message": message, "type": toast_type})
        if result.get("success"):
            return [TextContent(type="text", text=f"Showed toast: {message}")]
        return [TextContent(type="text", text=f"Failed to show toast: {result.get('error')}")]

    if name == "open_modal":
        modal_id = arguments.get("modal_id", "")
        result = await execute_ui_action("modal", {"modal_id": modal_id})
        if result.get("success"):
            return [TextContent(type="text", text=f"Opened modal: {modal_id}")]
        return [TextContent(type="text", text=f"Failed to open modal: {result.get('error')}")]

    if name == "get_current_page":
        result = await execute_ui_action("get_page", {})
        if result.get("success"):
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "path": result.get("path", "/"),
                            "title": result.get("title", "TurboWrap"),
                        }
                    ),
                )
            ]
        return [TextContent(type="text", text="Could not get current page info")]

    # ================================================================
    # Issues API Handlers
    # ================================================================

    if name == "list_issues":
        repo_id = arguments.get("repository_id", "")
        status = arguments.get("status", "open")
        limit = arguments.get("limit", 50)
        params = {"repository_id": repo_id, "limit": limit}
        if status != "all":
            params["status"] = status
        result = await api_get("/api/issues", params)
        if result.get("success"):
            issues = result["data"]
            summary = [
                {
                    "id": i.get("id"),
                    "code": i.get("code"),
                    "title": i.get("title"),
                    "severity": i.get("severity"),
                    "status": i.get("status"),
                    "file": i.get("file_path"),
                    "line": i.get("line_number"),
                }
                for i in issues[:limit]
            ]
            return [TextContent(type="text", text=json.dumps(summary, indent=2))]
        return [TextContent(type="text", text=f"Failed to list issues: {result.get('error')}")]

    if name == "get_issue":
        issue_id = arguments.get("issue_id", "")
        result = await api_get(f"/api/issues/{issue_id}")
        if result.get("success"):
            return [TextContent(type="text", text=json.dumps(result["data"], indent=2))]
        return [TextContent(type="text", text=f"Failed to get issue: {result.get('error')}")]

    if name == "get_issues_summary":
        repo_id = arguments.get("repository_id", "")
        result = await api_get("/api/issues/summary", {"repository_id": repo_id})
        if result.get("success"):
            return [TextContent(type="text", text=json.dumps(result["data"], indent=2))]
        return [TextContent(type="text", text=f"Failed to get summary: {result.get('error')}")]

    if name == "resolve_issue":
        issue_id = arguments.get("issue_id", "")
        result = await api_post(f"/api/issues/{issue_id}/resolve")
        if result.get("success"):
            return [TextContent(type="text", text=f"Issue {issue_id} marked as resolved")]
        return [TextContent(type="text", text=f"Failed to resolve: {result.get('error')}")]

    # ================================================================
    # Tests API Handlers
    # ================================================================

    if name == "list_test_suites":
        repo_id = arguments.get("repository_id", "")
        result = await api_get("/api/tests/suites", {"repository_id": repo_id})
        if result.get("success"):
            suites = result["data"]
            summary = [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "framework": s.get("framework"),
                    "test_count": s.get("test_count"),
                    "last_status": s.get("last_run_status"),
                }
                for s in suites
            ]
            return [TextContent(type="text", text=json.dumps(summary, indent=2))]
        return [TextContent(type="text", text=f"Failed to list suites: {result.get('error')}")]

    if name == "get_test_summary":
        repo_id = arguments.get("repository_id", "")
        result = await api_get("/api/tests/summary", {"repository_id": repo_id})
        if result.get("success"):
            return [TextContent(type="text", text=json.dumps(result["data"], indent=2))]
        return [TextContent(type="text", text=f"Failed to get summary: {result.get('error')}")]

    if name == "run_test_suite":
        suite_id = arguments.get("suite_id", "")
        result = await api_post(f"/api/tests/run/{suite_id}")
        if result.get("success"):
            data = result["data"]
            return [
                TextContent(
                    type="text",
                    text=f"Test run started. Run ID: {data.get('run_id', 'unknown')}",
                )
            ]
        return [TextContent(type="text", text=f"Failed to run tests: {result.get('error')}")]

    if name == "get_test_run":
        run_id = arguments.get("run_id", "")
        result = await api_get(f"/api/tests/runs/{run_id}")
        if result.get("success"):
            return [TextContent(type="text", text=json.dumps(result["data"], indent=2))]
        return [TextContent(type="text", text=f"Failed to get run: {result.get('error')}")]

    # ================================================================
    # Fix API Handlers
    # ================================================================

    if name == "list_fixable_issues":
        repo_id = arguments.get("repository_id", "")
        result = await api_get(f"/api/fix/issues/{repo_id}")
        if result.get("success"):
            issues = result["data"]
            summary = [
                {
                    "id": i.get("id"),
                    "code": i.get("code"),
                    "title": i.get("title"),
                    "severity": i.get("severity"),
                    "file": i.get("file_path"),
                }
                for i in issues
            ]
            return [TextContent(type="text", text=json.dumps(summary, indent=2))]
        return [TextContent(type="text", text=f"Failed to list issues: {result.get('error')}")]

    if name == "start_fix":
        repo_id = arguments.get("repository_id", "")
        issue_ids = arguments.get("issue_ids", [])
        result = await api_post(
            "/api/fix/start",
            data={"repository_id": repo_id, "issue_ids": issue_ids},
        )
        if result.get("success"):
            return [TextContent(type="text", text="Fix session started successfully")]
        return [TextContent(type="text", text=f"Failed to start fix: {result.get('error')}")]

    if name == "get_active_fix_sessions":
        result = await api_get("/api/fix/sessions/active")
        if result.get("success"):
            return [TextContent(type="text", text=json.dumps(result["data"], indent=2))]
        return [TextContent(type="text", text=f"Failed to get sessions: {result.get('error')}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    """Run the MCP server."""
    logger.info("Starting TurboWrap UI Actions MCP Server...")
    logger.info(f"API URL: {TURBOWRAP_API_URL}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
