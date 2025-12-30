#!/usr/bin/env python3
"""TurboWrap UI Actions MCP Server.

This MCP server exposes tools for AI to interact with the TurboWrap UI:
- navigate: Navigate user to a specific page
- highlight: Highlight DOM elements
- show_toast: Show notification toast
- open_modal: Open a specific modal

The server communicates with the TurboWrap API which broadcasts
actions to connected frontends via WebSocket.
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

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    """Run the MCP server."""
    logger.info("Starting TurboWrap UI Actions MCP Server...")
    logger.info(f"API URL: {TURBOWRAP_API_URL}")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
