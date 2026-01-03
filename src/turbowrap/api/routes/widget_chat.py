"""Widget Chat API - Ephemeral chat sessions for issue widget.

Lightweight chat endpoint for the issue reporting widget.
Features:
- In-memory sessions (no DB persistence)
- Auto-cleanup after 30 min inactivity
- SSE streaming responses
- Action marker parsing for issue creation
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ...chat_cli import get_process_manager
from ...config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget-chat", tags=["widget-chat"])


# --- Models ---


class WidgetChatContext(BaseModel):
    """Context for widget chat session."""

    repository_id: str | None = None
    page_url: str | None = None
    page_title: str | None = None
    selected_element: dict[str, Any] | None = None


class WidgetChatRequest(BaseModel):
    """Request to send a chat message."""

    message: str
    session_id: str
    context: WidgetChatContext | None = None


class WidgetChatStartRequest(BaseModel):
    """Request to start a new chat session."""

    context: WidgetChatContext | None = None
    model: str | None = None  # Claude model override (e.g., "claude-haiku-4-20250514")
    agent: str | None = None  # Agent name override (e.g., "widget_form_analyzer")


# --- In-Memory Session Store ---


@dataclass
class WidgetChatSession:
    """Ephemeral widget chat session."""

    session_id: str
    claude_session_id: str  # For --resume
    context: WidgetChatContext | None
    model: str | None = None  # Claude model override
    agent: str | None = None  # Agent name override
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    message_count: int = 0
    first_message_sent: bool = False


class WidgetSessionManager:
    """In-memory session manager with auto-cleanup."""

    def __init__(self, session_timeout_minutes: int = 30):
        self._sessions: dict[str, WidgetChatSession] = {}
        self._lock = asyncio.Lock()
        self._timeout = session_timeout_minutes * 60  # Convert to seconds
        self._cleanup_task: asyncio.Task[None] | None = None

    def start_cleanup_task(self) -> None:
        """Start background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically clean up stale sessions."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_stale()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WIDGET] Cleanup error: {e}")

    async def _cleanup_stale(self) -> None:
        """Remove sessions inactive for too long."""
        now = datetime.utcnow()
        async with self._lock:
            stale = [
                sid
                for sid, session in self._sessions.items()
                if (now - session.last_activity).total_seconds() > self._timeout
            ]
            for sid in stale:
                del self._sessions[sid]
                logger.info(f"[WIDGET] Cleaned up stale session: {sid}")

    async def create_session(
        self,
        context: WidgetChatContext | None = None,
        model: str | None = None,
        agent: str | None = None,
    ) -> WidgetChatSession:
        """Create a new ephemeral session."""
        self.start_cleanup_task()

        session_id = str(uuid.uuid4())
        claude_session_id = str(uuid.uuid4())

        session = WidgetChatSession(
            session_id=session_id,
            claude_session_id=claude_session_id,
            context=context,
            model=model,
            agent=agent,
        )

        async with self._lock:
            self._sessions[session_id] = session

        logger.info(f"[WIDGET] Created session: {session_id} (model={model}, agent={agent})")
        return session

    async def get_session(self, session_id: str) -> WidgetChatSession | None:
        """Get session by ID."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.last_activity = datetime.utcnow()
            return session

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"[WIDGET] Deleted session: {session_id}")
                return True
            return False


# Global session manager
_widget_session_manager: WidgetSessionManager | None = None


def get_widget_session_manager() -> WidgetSessionManager:
    """Get or create the widget session manager."""
    global _widget_session_manager
    if _widget_session_manager is None:
        _widget_session_manager = WidgetSessionManager()
    return _widget_session_manager


# --- Action Extraction ---


def extract_create_issue_action(
    content: str,
) -> tuple[dict[str, Any] | None, str]:
    """Extract [[ACTION:create_issue:{...}]] from content.

    Returns (action_data, cleaned_content).
    """
    pattern = r"\[\[ACTION:create_issue:(\{[^}]+\})\]\]"
    match = re.search(pattern, content)

    if match:
        try:
            action_data = json.loads(match.group(1))
            cleaned = content[: match.start()].rstrip()
            return action_data, cleaned
        except json.JSONDecodeError:
            logger.warning(f"[WIDGET] Failed to parse action JSON: {match.group(1)}")

    return None, content


def build_system_context(context: WidgetChatContext | None) -> str:
    """Build system prompt context for Claude."""
    parts = ["# Widget Chat Context\n"]

    if context:
        if context.page_url:
            parts.append(f"- **Page URL**: {context.page_url}")
        if context.page_title:
            parts.append(f"- **Page Title**: {context.page_title}")
        if context.selected_element:
            elem = context.selected_element
            parts.append(f"- **Selected Element**: {elem.get('tagName', 'unknown')}")
            if elem.get("id"):
                parts.append(f"  - ID: #{elem['id']}")
            if elem.get("classes"):
                parts.append(f"  - Classes: .{'.'.join(elem['classes'])}")
            if elem.get("selector"):
                parts.append(f"  - Selector: `{elem['selector']}`")

    parts.append("\n---\n")
    return "\n".join(parts)


# --- API Endpoints ---


DEFAULT_WIDGET_MODEL = "claude-haiku-4-5-20251001"


@router.post("/sessions")
async def create_chat_session(
    data: WidgetChatStartRequest | None = None,
) -> dict[str, str]:
    """Create a new widget chat session.

    Args:
        data.context: Page context (url, title, selected element)
        data.model: Claude model override (default: claude-haiku-4-5-20251001)
        data.agent: Agent name override (default: widget_chat_collector)

    Returns session_id for subsequent messages.
    """
    manager = get_widget_session_manager()
    context = data.context if data else None
    model = data.model if data else None
    agent = data.agent if data else None
    session = await manager.create_session(context, model=model, agent=agent)

    return {
        "session_id": session.session_id,
        "model": session.model or DEFAULT_WIDGET_MODEL,
        "agent": session.agent or "widget_chat_collector",
        "message": "Session created. Send your first message to start chatting.",
    }


@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: str,
    data: WidgetChatRequest,
) -> EventSourceResponse:
    """Send a message and stream response via SSE.

    Events:
    - start: Stream started
    - chunk: Content chunk
    - action: Action marker detected (create_issue)
    - done: Stream completed
    - error: Error occurred
    """
    manager = get_widget_session_manager()
    session = await manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
        """Generate SSE events."""
        process_manager = get_process_manager()
        settings = get_settings()

        try:
            yield {
                "event": "start",
                "data": json.dumps({"session_id": session_id}),
            }

            # Check if we need to spawn a new Claude process
            proc = process_manager.get_process(session_id)

            if not proc:
                # Build context for first message
                context_text = build_system_context(session.context)

                # Use session model/agent or defaults
                model = session.model or DEFAULT_WIDGET_MODEL
                agent_name = session.agent or "widget_chat_collector"

                # Load agent file
                agent_path = (
                    Path(__file__).parent.parent.parent.parent.parent
                    / "agents"
                    / f"{agent_name}.md"
                )

                proc = await process_manager.spawn_claude(
                    session_id=session_id,
                    working_dir=settings.repos_dir,
                    model=model,
                    agent_path=agent_path if agent_path.exists() else None,
                    context=context_text if context_text.strip() else None,
                )
                logger.info(
                    f"[WIDGET] Spawned Claude for session {session_id} "
                    f"(model={model}, agent={agent_name})"
                )

            # Send message and stream response
            full_content: list[str] = []

            async for line in process_manager.send_message(session_id, data.message):
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    event_type = event.get("type", "unknown")

                    # Unwrap stream_event wrapper if present
                    if event_type == "stream_event":
                        inner_event = event.get("event", {})
                        event = inner_event
                        event_type = event.get("type", "unknown")

                    # Skip system events for widget
                    if event_type == "system":
                        continue

                    # Extract content from delta events
                    content: str | None = None

                    if event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            content = delta.get("text", "")

                    elif event_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "text":
                            content = block.get("text", "")

                    elif event_type == "result":
                        if "result" in event:
                            content = event["result"]

                    if content:
                        full_content.append(content)

                        # Check for action marker in accumulated content
                        accumulated = "".join(full_content)
                        action_data, cleaned = extract_create_issue_action(accumulated)

                        if action_data:
                            # Found action - emit action event
                            yield {
                                "event": "action",
                                "data": json.dumps(
                                    {
                                        "type": "create_issue",
                                        "data": action_data,
                                    }
                                ),
                            }
                            # Reset content to cleaned version
                            full_content.clear()
                            full_content.append(cleaned)

                        yield {
                            "event": "chunk",
                            "data": json.dumps({"content": content}),
                        }

                except json.JSONDecodeError:
                    # Raw text line
                    if line:
                        full_content.append(line + "\n")
                        yield {
                            "event": "chunk",
                            "data": json.dumps({"content": line + "\n"}),
                        }

            # Update session state
            session.message_count += 1
            session.first_message_sent = True

            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "session_id": session_id,
                        "message_count": session.message_count,
                    }
                ),
            }

        except Exception as e:
            logger.error(f"[WIDGET] Error in session {session_id}: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete a chat session and terminate any running process."""
    manager = get_widget_session_manager()
    process_manager = get_process_manager()

    # Terminate CLI process if running
    await process_manager.terminate(session_id)

    # Delete session
    deleted = await manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"message": "Session deleted"}


@router.get("/sessions/{session_id}")
async def get_session_status(session_id: str) -> dict[str, Any]:
    """Get session status."""
    manager = get_widget_session_manager()
    session = await manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    return {
        "session_id": session.session_id,
        "message_count": session.message_count,
        "created_at": session.created_at.isoformat(),
        "last_activity": session.last_activity.isoformat(),
    }
