"""UI Actions API routes.

This module handles UI action requests from the MCP server
and broadcasts them to connected frontends via WebSocket.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui-actions", tags=["UI Actions"])


# ============================================================================
# WebSocket Connection Manager
# ============================================================================


class ConnectionManager:
    """Manages WebSocket connections for UI action broadcasting."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._current_page: dict[str, str] = {"path": "/", "title": "TurboWrap"}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict[str, Any]) -> int:
        """Broadcast a message to all connected clients.

        Returns the number of clients that received the message.
        """
        if not self.active_connections:
            logger.warning("No WebSocket connections to broadcast to")
            return 0

        sent_count = 0
        disconnected: list[WebSocket] = []

        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                    sent_count += 1
                except Exception as e:
                    logger.warning(f"Failed to send to WebSocket: {e}")
                    disconnected.append(connection)

            # Clean up disconnected sockets
            for conn in disconnected:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)

        return sent_count

    def update_current_page(self, path: str, title: str) -> None:
        """Update the current page info (called when frontend navigates)."""
        self._current_page = {"path": path, "title": title}

    def get_current_page(self) -> dict[str, str]:
        """Get the current page info."""
        return self._current_page.copy()


# Global connection manager
manager = ConnectionManager()


# ============================================================================
# Schemas
# ============================================================================


class UIActionRequest(BaseModel):
    """Request to execute a UI action."""

    action: str  # navigate, highlight, toast, modal, get_page
    params: dict[str, Any]


class UIActionResponse(BaseModel):
    """Response from UI action execution."""

    success: bool
    error: str | None = None
    count: int | None = None  # For highlight action
    path: str | None = None  # For get_page action
    title: str | None = None  # For get_page action


# ============================================================================
# WebSocket Endpoint
# ============================================================================


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for UI action broadcasting.

    Frontend connects to this to receive UI actions from the AI.
    Frontend can also send messages:
    - {"type": "page_update", "path": "/tests", "title": "Test Suites"}
    """
    await manager.connect(websocket)

    try:
        while True:
            # Receive messages from frontend
            data = await websocket.receive_json()

            if data.get("type") == "page_update":
                # Frontend is reporting current page
                manager.update_current_page(
                    path=data.get("path", "/"),
                    title=data.get("title", "TurboWrap"),
                )
                logger.debug(f"Page updated: {data.get('path')}")

            elif data.get("type") == "ping":
                # Keepalive ping
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)


# ============================================================================
# API Endpoints (called by MCP server)
# ============================================================================


@router.post("/execute", response_model=UIActionResponse)
async def execute_action(request: UIActionRequest) -> UIActionResponse:
    """Execute a UI action.

    This endpoint is called by the MCP server when the AI
    calls a UI action tool. It broadcasts the action to all
    connected frontends via WebSocket.
    """
    logger.info(f"Executing UI action: {request.action} with params: {request.params}")

    action = request.action
    params = request.params

    if action == "navigate":
        path = params.get("path", "/")
        count = await manager.broadcast(
            {
                "type": "action",
                "action": "navigate",
                "path": path,
            }
        )
        if count > 0:
            return UIActionResponse(success=True)
        return UIActionResponse(success=False, error="No connected frontends")

    if action == "highlight":
        selector = params.get("selector", "")
        count = await manager.broadcast(
            {
                "type": "action",
                "action": "highlight",
                "selector": selector,
            }
        )
        if count > 0:
            # We report 1 as count since we don't know actual elements matched
            # The frontend will report the actual count
            return UIActionResponse(success=True, count=1)
        return UIActionResponse(success=False, error="No connected frontends")

    if action == "toast":
        message = params.get("message", "")
        toast_type = params.get("type", "info")
        count = await manager.broadcast(
            {
                "type": "action",
                "action": "toast",
                "message": message,
                "toast_type": toast_type,
            }
        )
        if count > 0:
            return UIActionResponse(success=True)
        return UIActionResponse(success=False, error="No connected frontends")

    if action == "modal":
        modal_id = params.get("modal_id", "")
        count = await manager.broadcast(
            {
                "type": "action",
                "action": "modal",
                "modal_id": modal_id,
            }
        )
        if count > 0:
            return UIActionResponse(success=True)
        return UIActionResponse(success=False, error="No connected frontends")

    if action == "get_page":
        page_info = manager.get_current_page()
        return UIActionResponse(
            success=True,
            path=page_info["path"],
            title=page_info["title"],
        )

    return UIActionResponse(success=False, error=f"Unknown action: {action}")


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Get the status of UI action connections."""
    return {
        "connected_clients": len(manager.active_connections),
        "current_page": manager.get_current_page(),
    }
