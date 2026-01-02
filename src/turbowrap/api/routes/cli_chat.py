"""CLI Chat API Routes.

Endpoints per gestione chat basata su CLI (claude/gemini).
Supporta multi-chat parallele, agenti custom, MCP servers.
"""

import asyncio
import json
import logging
import time
import traceback
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ...chat_cli import (
    CLIType,
    get_agent_loader,
    get_context_for_session,
    get_mcp_manager,
    get_process_manager,
)
from ...config import get_settings
from ...db.models import CLIChatMessage, CLIChatSession, Repository
from ...utils.git_utils import checkout_branch, list_branches
from ..deps import get_db, get_or_404
from ..schemas.cli_chat import (
    AgentListResponse,
    AgentResponse,
    CLIBranchChange,
    CLIMessageCreate,
    CLIMessageResponse,
    CLISessionCreate,
    CLISessionResponse,
    CLISessionUpdate,
    MCPConfigResponse,
    MCPServerCreate,
    MCPServerResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cli-chat", tags=["cli-chat"])

# Title Generation Settings

TITLE_REFRESH_INTERVAL = 10
DEFAULT_TITLES = {"Claude Chat", "Gemini Chat", "", None}

TITLE_REQUEST_PROMPT = """

[SYSTEM: This chat needs a title. At the very end of your response, on a new line, output ONLY this JSON (nothing else after it):
{"chat_title": "Your 3-4 Word Title"}
The title should describe the main topic of this conversation. Keep it short and descriptive.]"""


def extract_title_from_response(content: str) -> tuple[str | None, str]:
    """Extract title JSON from response and return (title, cleaned_content).

    Looks for {"chat_title": "..."} at the end of the response.
    Returns the title and the content with the JSON removed.
    """
    import re

    pattern = r'\s*\{"chat_title":\s*"([^"]+)"\}\s*$'
    match = re.search(pattern, content)

    if match:
        title = match.group(1).strip()
        cleaned = content[: match.start()].rstrip()
        return title, cleaned

    return None, content


def extract_actions_from_response(content: str) -> tuple[list[dict[str, Any]], str]:
    """Extract action markers from AI response.

    Looks for [[ACTION:type:target]] markers in the response.
    Supported actions:
    - [[ACTION:navigate:/path/to/page]] - Navigate user to a page
    - [[ACTION:highlight:#element-id]] - Highlight a DOM element
    - [[ACTION:highlight:.class-name]] - Highlight elements by class

    Returns (actions_list, cleaned_content).
    """
    import re

    actions: list[dict[str, Any]] = []

    # Pattern: [[ACTION:type:target]]
    pattern = r"\[\[ACTION:(\w+):([^\]]+)\]\]"

    def extract_action(match: re.Match[str]) -> str:
        action_type = match.group(1).lower()
        target = match.group(2).strip()

        if action_type in ("navigate", "highlight"):
            actions.append(
                {
                    "type": action_type,
                    "target": target,
                }
            )
            logger.info(f"[ACTION] Extracted: {action_type} -> {target}")
        else:
            logger.warning(f"[ACTION] Unknown action type: {action_type}")

        return ""  # Remove marker from content

    cleaned = re.sub(pattern, extract_action, content)

    # Clean up extra whitespace left by removed markers
    cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned).strip()

    return actions, cleaned


async def generate_chat_title(
    cli_type: str,
    user_message: str,
    assistant_response: str,
    timeout: int = 30,
) -> str | None:
    """Generate a 3-word title for a chat conversation.

    Args:
        cli_type: "claude" or "gemini"
        user_message: First user message
        assistant_response: First assistant response
        timeout: Timeout in seconds

    Returns:
        Generated title (max 3 words) or None on error
    """
    user_summary = user_message[:300]
    assistant_summary = assistant_response[:300]

    prompt = f"""Generate a title for this conversation.
Rules:
- Maximum 3 words
- No quotes or punctuation
- Descriptive of the main topic
- Title case

User: {user_summary}
Assistant: {assistant_summary}

Respond with ONLY the title, nothing else."""

    try:
        if cli_type == "claude":
            args = [
                "claude",
                "--print",
                "--model",
                "claude-sonnet-4-5-20250929",
                "-p",
                prompt,
            ]
        else:
            args = [
                "gemini",
                "-m",
                "gemini-3-flash-preview",
                prompt,
            ]

        logger.info(f"[TITLE] Generating title with {cli_type}...")

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        title = stdout.decode().strip()

        title = title.strip("\"'`")
        words = title.split()[:3]
        final_title = " ".join(words) if words else None

        logger.info(f"[TITLE] Generated: {final_title}")
        return final_title

    except asyncio.TimeoutError:
        logger.warning("[TITLE] Title generation timed out")
        return None
    except Exception as e:
        logger.warning(f"[TITLE] Title generation failed: {e}")
        return None


@router.get("/sessions", response_model=list[CLISessionResponse])
def list_sessions(
    cli_type: str | None = None,
    repository_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[CLISessionResponse]:
    """List CLI chat sessions."""
    query = db.query(CLIChatSession).filter(CLIChatSession.deleted_at.is_(None))

    if cli_type:
        query = query.filter(CLIChatSession.cli_type == cli_type)

    if repository_id:
        query = query.filter(CLIChatSession.repository_id == repository_id)

    sessions = query.order_by(CLIChatSession.updated_at.desc()).limit(limit).all()

    result = []
    for s in sessions:
        response = CLISessionResponse.model_validate(s)
        response.total_messages = len(s.messages) if s.messages else 0
        result.append(response)

    return result


@router.post("/sessions", response_model=CLISessionResponse)
def create_session(
    data: CLISessionCreate,
    db: Session = Depends(get_db),
) -> CLIChatSession:
    """Create a new CLI chat session."""
    # Set default model based on CLI type
    default_model = (
        "claude-opus-4-5-20251101" if data.cli_type == "claude" else "gemini-3-pro-preview"
    )

    # Get default branch from repository if linked
    current_branch = None
    if data.repository_id:
        repo = db.query(Repository).filter(Repository.id == data.repository_id).first()
        if repo:
            current_branch = repo.default_branch or "main"

    session = CLIChatSession(
        cli_type=data.cli_type,
        repository_id=data.repository_id,
        current_branch=current_branch,
        display_name=data.display_name,
        icon=data.icon,
        color=data.color,
        model=default_model,
        status="idle",
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(f"Created CLI chat session: {session.id} ({session.cli_type})")
    return session


@router.get("/sessions/{session_id}", response_model=CLISessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
) -> CLIChatSession:
    """Get CLI chat session details."""
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


@router.put("/sessions/{session_id}", response_model=CLISessionResponse)
def update_session(
    session_id: str,
    data: CLISessionUpdate,
    db: Session = Depends(get_db),
) -> CLIChatSession:
    """Update CLI chat session settings."""
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update only provided fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(session, key, value)

    session.updated_at = datetime.utcnow()  # type: ignore[assignment]
    db.commit()
    db.refresh(session)

    logger.info(f"Updated CLI chat session: {session_id}")
    return session


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete (soft-delete) a CLI chat session."""
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    manager = get_process_manager()
    background_tasks.add_task(manager.terminate, session_id)

    session.soft_delete()
    db.commit()

    logger.info(f"Deleted CLI chat session: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@router.post("/sessions/{session_id}/fork", response_model=CLISessionResponse)
def fork_session(
    session_id: str,
    db: Session = Depends(get_db),
) -> CLIChatSession:
    """Fork a CLI chat session with all messages.

    Creates a new session with:
    - Same settings (model, agent, thinking, etc.)
    - Copy of all messages
    - For Claude: shares claude_session_id for --resume support

    Returns the new forked session.
    """
    original = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not original:
        raise HTTPException(status_code=404, detail="Session not found")

    # Create new session with same settings
    forked = CLIChatSession(
        display_name=f"{original.display_name or 'Chat'} (fork)",
        cli_type=original.cli_type,
        model=original.model,
        agent_name=original.agent_name,
        thinking_enabled=original.thinking_enabled,
        thinking_budget=original.thinking_budget,
        reasoning_enabled=original.reasoning_enabled,
        mcp_servers=original.mcp_servers,
        repository_id=original.repository_id,
        current_branch=original.current_branch,
        icon=original.icon,
        color=original.color,
        status="idle",
        total_messages=0,
        total_tokens_in=0,
        total_tokens_out=0,
    )
    db.add(forked)
    db.flush()  # Get ID before adding messages

    message_count = 0
    total_tokens_in = 0
    total_tokens_out = 0
    for msg in original.messages:
        forked_msg = CLIChatMessage(
            session_id=forked.id,
            role=msg.role,
            content=msg.content,
            tokens_in=msg.tokens_in,
            tokens_out=msg.tokens_out,
            model_used=msg.model_used,
            agent_used=msg.agent_used,
            is_thinking=msg.is_thinking,
            duration_ms=msg.duration_ms,
        )
        db.add(forked_msg)
        message_count += 1

        total_tokens_in += cast(int, msg.tokens_in) or 0
        total_tokens_out += cast(int, msg.tokens_out) or 0

    forked.total_messages = message_count  # type: ignore[assignment]
    forked.total_tokens_in = total_tokens_in  # type: ignore[assignment]
    forked.total_tokens_out = total_tokens_out  # type: ignore[assignment]

    db.commit()
    db.refresh(forked)

    manager = get_process_manager()
    original_proc = manager.get_process(session_id)
    if original_proc and original_proc.cli_type == CLIType.CLAUDE:
        forked_id = cast(str, forked.id)
        if original_proc.claude_session_id:
            manager.set_shared_resume_id(forked_id, original_proc.claude_session_id)
            logger.info(
                f"[FORK] Sharing claude_session_id {original_proc.claude_session_id} "
                f"from {session_id} to {forked.id}"
            )

    logger.info(f"[FORK] Created fork {forked.id} from {session_id} with {message_count} messages")

    return forked


@router.get("/sessions/{session_id}/branches")
def get_session_branches(
    session_id: str,
    db: Session = Depends(get_db),
) -> list[str]:
    """List available branches for the session's repository.

    Returns a list of branch names from the associated repository.
    """
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.repository_id:
        raise HTTPException(
            status_code=400,
            detail="Session is not linked to a repository",
        )

    repo = get_or_404(db, Repository, session.repository_id)

    try:
        return list_branches(Path(repo.local_path))
    except Exception as e:
        logger.error(f"Failed to list branches: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list branches: {e}") from e


@router.post("/sessions/{session_id}/branch", response_model=CLISessionResponse)
async def change_session_branch(
    session_id: str,
    data: CLIBranchChange,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> CLIChatSession:
    """Change the active branch for a chat session.

    Performs git checkout to the specified branch, updates the session's
    current_branch field, and terminates any running CLI process so it
    can be restarted with the new branch context.
    """
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.repository_id:
        raise HTTPException(
            status_code=400,
            detail="Session is not linked to a repository",
        )

    repo = get_or_404(db, Repository, session.repository_id)

    # Git checkout
    try:
        checkout_branch(Path(repo.local_path), data.branch)
        logger.info(f"[BRANCH] Checked out branch '{data.branch}' in {repo.local_path}")
    except Exception as e:
        logger.error(f"Failed to checkout branch: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to checkout branch '{data.branch}': {e}",
        ) from e

    # Update session
    session.current_branch = data.branch  # type: ignore[assignment]
    session.updated_at = datetime.utcnow()  # type: ignore[assignment]
    db.commit()
    db.refresh(session)

    manager = get_process_manager()
    proc = manager.get_process(session_id)
    if proc:
        logger.info(
            f"[BRANCH] Terminating CLI process for session {session_id} to apply new branch"
        )
        background_tasks.add_task(manager.terminate, session_id)

    logger.info(f"[BRANCH] Session {session_id} switched to branch '{data.branch}'")

    return session


@router.get("/sessions/{session_id}/messages", response_model=list[CLIMessageResponse])
def get_messages(
    session_id: str,
    limit: int = 100,
    include_thinking: bool = False,
    db: Session = Depends(get_db),
) -> list[CLIChatMessage]:
    """Get messages for a CLI chat session."""
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    query = db.query(CLIChatMessage).filter(CLIChatMessage.session_id == session_id)

    if not include_thinking:
        query = query.filter(CLIChatMessage.is_thinking == False)  # noqa: E712

    messages = query.order_by(CLIChatMessage.created_at.asc()).limit(limit).all()
    logger.info(f"[MESSAGES] Session {session_id}: loaded {len(messages)} messages")
    return messages


@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: str,
    data: CLIMessageCreate,
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """Send a message and stream response via SSE.

    Returns an EventSource response with events:
    - start: Stream started
    - chunk: Content chunk
    - thinking: Extended thinking content (Claude)
    - done: Stream completed with message_id
    - error: Error occurred
    """
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check if this is the first message (for title generation)
    actual_message_count = (
        db.query(CLIChatMessage).filter(CLIChatMessage.session_id == session_id).count()
    )
    is_first_message = actual_message_count == 0
    logger.info(
        f"[MESSAGE] Session {session_id}: actual_count={actual_message_count}, "
        f"is_first={is_first_message}, total_messages={session.total_messages}"
    )

    # Save user message
    user_message = CLIChatMessage(
        session_id=session_id,
        role="user",
        content=data.content,
    )
    db.add(user_message)
    db.commit()

    # Extract session attributes as proper Python types for use in async generator
    session_cli_type = cast(str, session.cli_type)
    session_repository_id = cast(str | None, session.repository_id)
    session_current_branch = cast(str | None, session.current_branch)
    session_agent_name = cast(str | None, session.agent_name)
    session_model = data.model_override or cast(str | None, session.model)
    session_thinking_enabled = cast(bool, session.thinking_enabled)
    session_thinking_budget = cast(int | None, session.thinking_budget)
    session_reasoning_enabled = cast(bool, session.reasoning_enabled)
    session_display_name = cast(str | None, session.display_name)
    session_repository = session.repository
    session_claude_session_id = cast(str | None, session.claude_session_id)

    if data.model_override:
        logger.info(f"[MESSAGE] Using model override: {data.model_override}")

    async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
        """Generate SSE events for streaming response."""
        manager = get_process_manager()
        loader = get_agent_loader()

        try:
            yield {
                "event": "start",
                "data": json.dumps({"session_id": session_id}),
            }

            # Get or spawn CLI process
            proc = manager.get_process(session_id)

            if not proc:
                cli_type = CLIType(session_cli_type)

                context = get_context_for_session(
                    db,
                    repo_id=session_repository_id,
                    linear_issue_id=None,  # TODO: support linear issue context
                    branch=session_current_branch,
                )
                logger.info(f"Generated context: {len(context)} chars")

                if cli_type == CLIType.CLAUDE:
                    agent_path = None
                    if session_agent_name:
                        agent_path = loader.get_agent_path(session_agent_name)

                    # Create callback to load message history on-demand (only if --resume fails)
                    def load_message_history() -> str:
                        """Load message history from DB - called only if --resume fails."""
                        from ...db.session import get_session_local

                        history_db = get_session_local()()
                        try:
                            messages = (
                                history_db.query(CLIChatMessage)
                                .filter(CLIChatMessage.session_id == session_id)
                                .filter(CLIChatMessage.is_thinking == False)  # noqa: E712
                                .order_by(CLIChatMessage.created_at.asc())
                                .all()
                            )
                            if not messages:
                                return ""

                            history_parts = []
                            for msg in messages:
                                role_label = "User" if msg.role == "user" else "Assistant"
                                history_parts.append(f"[{role_label}]: {msg.content}")

                            logger.info(
                                f"[RECOVERY] Loaded {len(messages)} messages from DB for session {session_id}"
                            )
                            return "\n\n".join(history_parts)
                        finally:
                            history_db.close()

                    settings = get_settings()
                    proc = await manager.spawn_claude(
                        session_id=session_id,
                        working_dir=Path(
                            session_repository.local_path
                            if session_repository
                            else settings.repos_dir
                        ),
                        model=session_model or "claude-opus-4-5-20251101",
                        agent_path=agent_path,
                        thinking_budget=(
                            session_thinking_budget if session_thinking_enabled else None
                        ),
                        context=context,
                        mcp_config=settings.mcp_config if settings.mcp_config.exists() else None,
                        existing_session_id=session_claude_session_id,
                        message_history_callback=(
                            load_message_history if session_claude_session_id else None
                        ),
                    )

                    # Save claude_session_id to DB for persistence across process restarts
                    if (
                        proc.claude_session_id
                        and proc.claude_session_id != session_claude_session_id
                    ):
                        from ...db.session import get_session_local

                        save_db = get_session_local()()
                        try:
                            db_session = (
                                save_db.query(CLIChatSession)
                                .filter(CLIChatSession.id == session_id)
                                .first()
                            )
                            if db_session:
                                db_session.claude_session_id = proc.claude_session_id
                                save_db.commit()
                                logger.info(
                                    f"[SESSION] Saved claude_session_id to DB: {proc.claude_session_id}"
                                )
                        finally:
                            save_db.close()
                else:
                    proc = await manager.spawn_gemini(
                        session_id=session_id,
                        working_dir=Path(
                            session_repository.local_path
                            if session_repository
                            else get_settings().repos_dir
                        ),
                        model=session_model or "gemini-3-pro-preview",
                        reasoning=session_reasoning_enabled,
                        context=context,
                    )

            # Check if we should request a title refresh
            should_request_title = (
                actual_message_count > 0
                and actual_message_count % TITLE_REFRESH_INTERVAL == 0
                and session_display_name in DEFAULT_TITLES
            )

            # Build message with optional title request
            message_to_send = data.content
            if should_request_title:
                message_to_send = data.content + TITLE_REQUEST_PROMPT
                logger.info(f"[TITLE] Requesting title refresh at message #{actual_message_count}")

            full_content: list[str] = []
            system_events: list[dict[str, Any]] = []

            # Incremental save tracking
            assistant_message: CLIChatMessage | None = None  # DB record (created on first save)
            last_save_time = time.time()  # Track when we last saved
            SAVE_INTERVAL_SECONDS = 5  # Save every 5 seconds

            # Tool/block tracking for UI visibility
            current_block_type: str = ""
            current_tool_name: str = ""
            current_tool_input: list[str] = []

            async for line in manager.send_message(session_id, message_to_send):
                line = line.strip()
                if not line:
                    continue

                logger.info(f"[STREAM] Line: {line[:200]}...")

                try:
                    event = json.loads(line)
                    event_type = event.get("type", "unknown")

                    if event_type == "stream_event":
                        inner_event = event.get("event", {})
                        event = inner_event
                        event_type = event.get("type", "unknown")
                        logger.info(f"[STREAM] Unwrapped stream_event -> {event_type}")

                    if event_type == "system":
                        if event.get("subtype") == "init" and not is_first_message:
                            logger.debug("[STREAM] Skipping duplicate INIT event")
                            continue
                        system_events.append(event)
                        yield {
                            "event": "system",
                            "data": json.dumps(event),
                        }
                        continue

                    # Extract content from different event types
                    content: str | None = None

                    # NOTE: Skip "assistant" events - they contain the FULL accumulated

                    if event_type == "content_block_delta":
                        # Streaming delta - this is the main streaming event!
                        delta = event.get("delta", {})
                        delta_type = delta.get("type", "")
                        if delta_type == "text_delta":
                            content = delta.get("text", "")
                        elif delta_type == "input_json_delta" and current_block_type == "tool_use":
                            # Tool input streaming - accumulate for display
                            partial_json = delta.get("partial_json", "")
                            if partial_json:
                                current_tool_input.append(partial_json)

                    elif event_type == "content_block_start":
                        block = event.get("content_block", {})
                        block_type = block.get("type", "")
                        current_block_type = block_type

                        if block_type == "text":
                            content = block.get("text", "")
                        elif block_type == "tool_use":
                            # Tool invocation started - emit event to frontend
                            current_tool_name = block.get("name", "unknown")
                            current_tool_input = []
                            tool_id = block.get("id", "")

                            # Task tool = agent launch, emit separately
                            # We'll emit agent_start on tool_end when we have the input params
                            if current_tool_name != "Task":
                                logger.info(f"[TOOL] Started: {current_tool_name} (id={tool_id})")
                                yield {
                                    "event": "tool_start",
                                    "data": json.dumps(
                                        {
                                            "tool_name": current_tool_name,
                                            "tool_id": tool_id,
                                        }
                                    ),
                                }

                    elif event_type == "content_block_stop":
                        # Block ended - check if it was a tool
                        if current_block_type == "tool_use":
                            # Parse accumulated tool input for display
                            tool_input_str = "".join(current_tool_input)
                            try:
                                tool_input = json.loads(tool_input_str) if tool_input_str else {}
                            except json.JSONDecodeError:
                                tool_input = {"raw": tool_input_str}

                            # Task tool = agent launch, emit agent events
                            if current_tool_name == "Task":
                                agent_type = tool_input.get("subagent_type", "unknown")
                                agent_model = tool_input.get("model", "default")
                                agent_desc = tool_input.get("description", "")
                                logger.info(f"[AGENT] Launched: {agent_type} (model={agent_model})")
                                yield {
                                    "event": "agent_start",
                                    "data": json.dumps(
                                        {
                                            "agent_type": agent_type,
                                            "agent_model": agent_model,
                                            "description": agent_desc,
                                        }
                                    ),
                                }
                            else:
                                logger.info(f"[TOOL] Completed: {current_tool_name}")
                                yield {
                                    "event": "tool_end",
                                    "data": json.dumps(
                                        {
                                            "tool_name": current_tool_name,
                                            "tool_input": tool_input,
                                        }
                                    ),
                                }
                        current_block_type = ""
                        current_tool_name = ""
                        current_tool_input = []

                    elif event_type == "result":
                        if "result" in event:
                            content = event["result"]

                    elif event_type == "error":
                        # Error event from Claude CLI (process_manager.py)
                        error_info = event.get("error", {})
                        error_msg = error_info.get("message", "Unknown CLI error")
                        error_type = error_info.get("type", "cli_error")
                        logger.error(f"[STREAM] CLI error: {error_type} - {error_msg}")
                        yield {
                            "event": "error",
                            "data": json.dumps(
                                {
                                    "error": error_msg,
                                    "error_type": error_type,
                                }
                            ),
                        }
                        # Continue processing in case there's more to come

                    if content:
                        full_content.append(content)

                        # Incremental save logic: save every SAVE_INTERVAL_SECONDS
                        current_time = time.time()
                        if current_time - last_save_time >= SAVE_INTERVAL_SECONDS:
                            try:
                                if assistant_message is None:
                                    # First save: Create message record
                                    assistant_message = CLIChatMessage(
                                        session_id=session_id,
                                        role="assistant",
                                        content="".join(
                                            full_content
                                        ),  # Current accumulated content
                                        model_used=session_model,
                                        agent_used=session_agent_name,
                                    )
                                    db.add(assistant_message)
                                    db.flush()  # Get ID without full commit
                                    logger.info(
                                        f"[INCREMENTAL] Created assistant message for session {session_id}"
                                    )
                                else:
                                    # Subsequent saves: Update existing message
                                    assistant_message.content = "".join(full_content)
                                    logger.debug(
                                        f"[INCREMENTAL] Updated message {assistant_message.id}: {len(''.join(full_content))} chars"
                                    )

                                db.commit()  # Persist incremental progress
                                last_save_time = current_time
                            except Exception as e:
                                logger.error(f"[INCREMENTAL] Save failed: {e}")
                                db.rollback()
                                # Continue streaming - will retry next interval

                        yield {
                            "event": "chunk",
                            "data": json.dumps({"content": content}),
                        }

                except json.JSONDecodeError:
                    if line:
                        full_content.append(line + "\n")

                        # Incremental save for raw text (same logic as JSON content)
                        current_time = time.time()
                        if current_time - last_save_time >= SAVE_INTERVAL_SECONDS:
                            try:
                                if assistant_message is None:
                                    assistant_message = CLIChatMessage(
                                        session_id=session_id,
                                        role="assistant",
                                        content="".join(full_content),
                                        model_used=session_model,
                                        agent_used=session_agent_name,
                                    )
                                    db.add(assistant_message)
                                    db.flush()
                                    logger.info(
                                        f"[INCREMENTAL] Created assistant message for session {session_id}"
                                    )
                                else:
                                    assistant_message.content = "".join(full_content)
                                    logger.debug(
                                        f"[INCREMENTAL] Updated message {assistant_message.id}: {len(''.join(full_content))} chars"
                                    )

                                db.commit()
                                last_save_time = current_time
                            except Exception as e:
                                logger.error(f"[INCREMENTAL] Save failed: {e}")
                                db.rollback()

                        yield {
                            "event": "chunk",
                            "data": json.dumps({"content": line + "\n"}),
                        }

            # Check if stream ended with incomplete content
            content_chars = len("".join(full_content))
            if content_chars > 0 and not full_content[-1].endswith((".", "!", "?", "\n")):
                logger.warning(
                    f"[STREAM] Stream may have ended mid-sentence. "
                    f"Last content: {full_content[-1][-50:] if full_content else 'empty'}"
                )

            logger.info(
                f"[STREAM] Done. System: {len(system_events)}, " f"Content: {content_chars} chars"
            )

            # Save assistant message
            response_content = "".join(full_content)

            # Extract actions from response (navigate, highlight)
            extracted_actions, response_content = extract_actions_from_response(response_content)

            # Emit action events to frontend
            for action in extracted_actions:
                yield {
                    "event": "action",
                    "data": json.dumps(action),
                }

            # Extract title if we requested one (inline in the response)
            extracted_title: str | None = None
            if should_request_title:
                extracted_title, response_content = extract_title_from_response(response_content)
                if extracted_title:
                    logger.info(f"[TITLE] Extracted inline title: {extracted_title}")
                else:
                    logger.warning("[TITLE] Title request was added but no title found in response")

            if assistant_message is None:
                # Edge case: Stream completed before 5 seconds (no incremental save)
                assistant_message = CLIChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=response_content,  # Use cleaned content (without JSON)
                    model_used=session_model,
                    agent_used=session_agent_name,
                )
                db.add(assistant_message)
                logger.info("[FINAL] Created assistant message (no incremental saves)")
            else:
                # Update existing message with cleaned content (actions/title removed)
                assistant_message.content = response_content
                logger.info(f"[FINAL] Updated message {assistant_message.id} with cleaned content")

            # Update session stats
            session.total_messages = cast(int, session.total_messages) + 2  # type: ignore[assignment]
            session.last_message_at = datetime.utcnow()  # type: ignore[assignment]
            session.updated_at = datetime.utcnow()  # type: ignore[assignment]

            # Save extracted title if found
            if extracted_title:
                session.display_name = extracted_title  # type: ignore[assignment]

            # Update claude_session_id if it changed during streaming (e.g., after retry)
            current_proc = manager.get_process(session_id)
            if (
                current_proc
                and session_cli_type == "claude"
                and current_proc.claude_session_id
                and current_proc.claude_session_id != session_claude_session_id
            ):
                session.claude_session_id = current_proc.claude_session_id  # type: ignore[assignment]
                logger.info(
                    f"[SESSION] Updated claude_session_id after streaming: "
                    f"{current_proc.claude_session_id}"
                )

            db.commit()

            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "message_id": assistant_message.id,
                        "total_length": len(response_content),
                    }
                ),
            }

            # Handle title generation/update
            if extracted_title:
                # Title was extracted inline - already saved above, just emit event
                logger.info(f"[TITLE] Session {session_id} title updated to: {extracted_title}")
                yield {
                    "event": "title_updated",
                    "data": json.dumps({"title": extracted_title}),
                }
            elif is_first_message and session_display_name in DEFAULT_TITLES:
                logger.info(f"[TITLE] Generating title for session {session_id}")
                title = await generate_chat_title(
                    cli_type=session_cli_type,
                    user_message=data.content,
                    assistant_response=response_content,
                )
                if title:
                    session.display_name = title  # type: ignore[assignment]
                    session.updated_at = datetime.utcnow()  # type: ignore[assignment]
                    db.commit()
                    logger.info(f"[TITLE] Session {session_id} title set to: {title}")

                    yield {
                        "event": "title_updated",
                        "data": json.dumps({"title": title}),
                    }
                else:
                    logger.warning(f"[TITLE] Session {session_id}: title generation returned None")
            else:
                logger.debug(
                    f"[TITLE] Skipping title generation: is_first={is_first_message}, "
                    f"display_name={session_display_name}"
                )

        except Exception as e:
            logger.error(f"Error in stream: {e}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    headers = {
        "X-Accel-Buffering": "no",  # Disable Nginx buffering
        "Cache-Control": "no-cache, no-transform",
    }
    return EventSourceResponse(event_generator(), headers=headers, ping=15)


@router.post("/sessions/{session_id}/start")
async def start_cli(
    session_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start the CLI process for a session."""
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    manager = get_process_manager()
    loader = get_agent_loader()

    try:
        cli_type = CLIType(cast(str, session.cli_type))

        context = get_context_for_session(
            db,
            repo_id=cast(str | None, session.repository_id),
            linear_issue_id=None,
            branch=cast(str | None, session.current_branch),
        )
        logger.info(f"[START] Generated context: {len(context)} chars")

        if cli_type == CLIType.CLAUDE:
            agent_path = None
            agent_name = cast(str | None, session.agent_name)
            if agent_name:
                agent_path = loader.get_agent_path(agent_name)

            settings = get_settings()
            proc = await manager.spawn_claude(
                session_id=session_id,
                working_dir=Path(
                    session.repository.local_path if session.repository else settings.repos_dir
                ),
                model=cast(str, session.model) or "claude-opus-4-5-20251101",
                agent_path=agent_path,
                thinking_budget=(
                    cast(int, session.thinking_budget) if session.thinking_enabled else None
                ),
                context=context,
                mcp_config=settings.mcp_config if settings.mcp_config.exists() else None,
            )
        else:
            proc = await manager.spawn_gemini(
                session_id=session_id,
                working_dir=Path(
                    session.repository.local_path
                    if session.repository
                    else get_settings().repos_dir
                ),
                model=cast(str, session.model) or "gemini-3-pro-preview",
                reasoning=bool(session.reasoning_enabled),
                context=context,
            )

        session.status = "running"  # type: ignore[assignment]
        session.process_pid = proc.pid  # type: ignore[assignment]
        db.commit()

        return {
            "status": "started",
            "session_id": session_id,
            "pid": proc.pid,
        }

    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/stop")
async def stop_cli(
    session_id: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Stop the CLI process for a session."""
    session = (
        db.query(CLIChatSession)
        .filter(
            CLIChatSession.id == session_id,
            CLIChatSession.deleted_at.is_(None),
        )
        .first()
    )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    manager = get_process_manager()
    terminated = await manager.terminate(session_id)

    if terminated:
        session.status = "idle"  # type: ignore[assignment]
        session.process_pid = None  # type: ignore[assignment]
        db.commit()

    return {
        "status": "stopped" if terminated else "not_running",
        "session_id": session_id,
    }


@router.get("/agents", response_model=AgentListResponse)
def list_agents() -> AgentListResponse:
    """List available Claude agents."""
    loader = get_agent_loader()
    agents = loader.list_agents()

    return AgentListResponse(
        agents=[AgentResponse(**a) for a in agents],
        total=len(agents),
    )


@router.get("/agents/{agent_name}", response_model=AgentResponse)
def get_agent(agent_name: str) -> AgentResponse:
    """Get agent details by name."""
    loader = get_agent_loader()
    agent = loader.get_agent(agent_name)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    return AgentResponse(**agent.info)


@router.get("/active")
def list_active_processes() -> dict[str, Any]:
    """List all active CLI processes."""
    manager = get_process_manager()
    sessions = manager.get_active_sessions()

    result = []
    for sid in sessions:
        proc = manager.get_process(sid)
        if proc:
            result.append(
                {
                    "session_id": sid,
                    "cli_type": proc.cli_type.value,
                    "pid": proc.pid,
                    "status": proc.status.value,
                    "started_at": proc.started_at.isoformat(),
                }
            )

    return {"active": result, "count": len(result)}


@router.post("/terminate-all")
async def terminate_all() -> dict[str, int]:
    """Terminate all running CLI processes."""
    manager = get_process_manager()
    count = await manager.terminate_all()

    return {"terminated": count}


@router.post("/kill/{pid}")
async def kill_process_by_pid(pid: int) -> dict[str, Any]:
    """Kill a CLI process by its PID.

    First tries to find the process in the managed sessions and terminate gracefully.
    If not found in sessions, forcefully kills the process by PID.

    Args:
        pid: Process ID to kill

    Returns:
        Status of the kill operation
    """
    import psutil

    manager = get_process_manager()

    # First, try to find this PID in our managed processes
    for session_id, proc in list(manager._processes.items()):
        if proc.pid == pid:
            # Found it - terminate via manager for proper cleanup
            terminated = await manager.terminate(session_id)
            return {
                "success": terminated,
                "pid": pid,
                "session_id": session_id,
                "method": "managed",
            }

    # Not in managed processes - try direct kill
    try:
        process = psutil.Process(pid)
        cmdline = " ".join(process.cmdline()).lower()

        # Safety check: only kill claude/gemini processes
        if "claude" not in cmdline and "gemini" not in cmdline:
            return {
                "success": False,
                "pid": pid,
                "error": "Not a CLI process (claude/gemini)",
            }

        process.terminate()
        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            process.kill()

        return {"success": True, "pid": pid, "method": "direct"}
    except psutil.NoSuchProcess:
        return {"success": False, "pid": pid, "error": "Process not found"}
    except psutil.AccessDenied:
        return {"success": False, "pid": pid, "error": "Access denied"}
    except Exception as e:
        return {"success": False, "pid": pid, "error": str(e)}


@router.get("/process-stats")
def get_process_stats() -> dict[str, Any]:
    """Get detailed statistics about running CLI processes.

    Returns process count, max allowed, and details for each process
    including age in hours.
    """
    manager = get_process_manager()
    return manager.get_process_stats()


@router.post("/cleanup-stale")
async def cleanup_stale_processes(max_age_hours: float = 3.0) -> dict[str, Any]:
    """Manually trigger cleanup of stale processes.

    Args:
        max_age_hours: Kill processes older than this many hours (default: 3)

    Returns:
        Number of processes terminated
    """
    manager = get_process_manager()
    terminated = await manager.cleanup_stale_processes(max_age_hours)

    return {
        "terminated": terminated,
        "max_age_hours": max_age_hours,
        "message": f"Terminated {terminated} processes older than {max_age_hours}h",
    }


@router.get("/mcp", response_model=MCPConfigResponse)
def get_mcp_config() -> MCPConfigResponse:
    """Get MCP server configuration."""
    manager = get_mcp_manager()
    servers = manager.list_servers(include_defaults=True)

    return MCPConfigResponse(
        servers=[
            MCPServerResponse(
                name=s["name"],
                command=s["command"],
                args=s["args"],
                enabled=s["enabled"],
            )
            for s in servers
        ],
        config_path=str(manager.config_path),
    )


@router.get("/mcp/servers", response_model=list[MCPServerResponse])
def list_mcp_servers(include_defaults: bool = True) -> list[MCPServerResponse]:
    """List all MCP servers (configured + defaults)."""
    manager = get_mcp_manager()
    servers = manager.list_servers(include_defaults=include_defaults)

    return [
        MCPServerResponse(
            name=s["name"],
            command=s["command"],
            args=s["args"],
            enabled=s["enabled"],
        )
        for s in servers
    ]


@router.post("/mcp/servers", response_model=MCPServerResponse)
def add_mcp_server(data: MCPServerCreate) -> MCPServerResponse:
    """Add or update an MCP server."""
    manager = get_mcp_manager()

    success = manager.add_server(
        name=data.name,
        command=data.command,
        args=data.args,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to add MCP server")

    server = manager.get_server(data.name)
    if not server:
        raise HTTPException(status_code=500, detail="Failed to retrieve added server")

    return MCPServerResponse(
        name=server["name"],
        command=server["command"],
        args=server["args"],
        enabled=server["enabled"],
    )


@router.post("/mcp/servers/{name}/enable")
def enable_mcp_server(name: str) -> dict[str, str]:
    """Enable an MCP server (add from defaults if needed)."""
    manager = get_mcp_manager()

    # Check if it's a known server
    server = manager.get_server(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    if server["enabled"]:
        return {"status": "already_enabled", "name": name}

    success = manager.enable_servers([name])
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to enable MCP server '{name}'")

    return {"status": "enabled", "name": name}


@router.delete("/mcp/servers/{name}")
def remove_mcp_server(name: str) -> dict[str, str]:
    """Remove an MCP server from configuration."""
    manager = get_mcp_manager()

    server = manager.get_server(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    if not server["enabled"]:
        return {"status": "not_configured", "name": name}

    success = manager.remove_server(name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to remove MCP server '{name}'")

    return {"status": "removed", "name": name}


@router.get("/mcp/defaults")
def get_default_mcp_servers() -> dict[str, list[str]]:
    """Get list of available default MCP servers."""
    manager = get_mcp_manager()
    defaults = manager.get_available_defaults()

    return {"defaults": defaults}


COMMANDS_DIR = Path(__file__).parent.parent.parent.parent.parent / "commands"


@router.get("/commands")
def list_slash_commands() -> dict[str, Any]:
    """List all available slash commands.

    Returns list of commands with their names and descriptions.
    """
    commands = []

    if COMMANDS_DIR.exists():
        for md_file in COMMANDS_DIR.glob("*.md"):
            command_name = md_file.stem
            try:
                content = md_file.read_text()
                first_line = content.split("\n")[0].strip()
                description = first_line.lstrip("# ").strip()
            except Exception:
                description = command_name

            commands.append(
                {
                    "name": command_name,
                    "description": description,
                    "path": str(md_file),
                }
            )

    return {"commands": commands, "total": len(commands)}


@router.get("/commands/{command_name}")
def get_slash_command(command_name: str) -> dict[str, str]:
    """Get a slash command prompt by name.

    Args:
        command_name: Command name without slash (e.g., 'test')

    Returns:
        Command prompt content from the MD file
    """
    safe_name = "".join(c for c in command_name if c.isalnum() or c in "-_")
    md_file = COMMANDS_DIR / f"{safe_name}.md"

    if not md_file.exists():
        raise HTTPException(status_code=404, detail=f"Slash command '/{command_name}' not found")

    try:
        content = md_file.read_text()

        lines = content.split("\n")
        if lines and lines[0].startswith("#"):
            prompt = "\n".join(lines[1:]).strip()
        else:
            prompt = content.strip()

        return {
            "name": command_name,
            "prompt": prompt,
            "path": str(md_file),
        }
    except Exception as e:
        logger.error(f"Error reading slash command '{command_name}': {e}")
        raise HTTPException(status_code=500, detail=f"Error reading slash command: {e}") from e


@router.get("/server-logs")
async def fetch_server_logs(
    minutes: int = 30,
    log_group: str | None = None,
) -> dict[str, Any]:
    """
    Fetch server logs from CloudWatch.

    Returns logs organized by level (ERROR, WARNING, INFO).
    The markdown output can be inserted directly into chat for analysis.
    """
    from ...utils.cloudwatch_logs import get_logs_fetcher

    fetcher = get_logs_fetcher()

    if not fetcher.enabled:
        raise HTTPException(
            status_code=503,
            detail="CloudWatch logs fetching is not configured",
        )

    result = await fetcher.fetch_logs(minutes=minutes, log_group=log_group)

    return {
        "log_group": result.log_group,
        "time_range_minutes": result.time_range_minutes,
        "fetched_at": result.fetched_at.isoformat(),
        "summary": {
            "total": len(result.entries),
            "errors": result.error_count,
            "warnings": result.warning_count,
            "info": result.info_count,
            "debug": result.debug_count,
        },
        "markdown": result.to_markdown(),
    }


# ==================== Mermaid Generation ====================

MERMAID_SYSTEM_PROMPT = """You are an expert at creating Mermaid diagrams from documentation.
Your task is to analyze the provided content and generate a clear, well-structured Mermaid diagram.

Guidelines:
1. Use the appropriate diagram type (flowchart, sequence, class, etc.) based on the content
2. Keep node labels concise but descriptive
3. Use appropriate styling and subgraphs to group related elements
4. Ensure the diagram is syntactically correct Mermaid code
5. For agent/workflow documentation, use flowchart TD (top-down) or LR (left-right)
6. Use meaningful node IDs and descriptive edge labels

Output ONLY the Mermaid code, nothing else. No markdown fences, no explanations."""


@router.post("/generate-mermaid")
async def generate_mermaid_diagram(
    request: dict[str, Any],
) -> dict[str, str]:
    """Generate a Mermaid diagram from content using AI.

    Args:
        request: Dict with 'content', optional 'type', and optional 'context'

    Returns:
        Dict with 'mermaid_code' containing the generated diagram
    """
    content = request.get("content", "")
    diagram_type = request.get("type", "flowchart")
    context_name = request.get("context", "document")

    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    # Build the prompt
    prompt = f"""Analyze this {context_name} and create a {diagram_type} Mermaid diagram that visualizes its structure, flow, or key relationships.

CONTENT:
```
{content[:8000]}
```

Generate a Mermaid {diagram_type} diagram. Output ONLY the Mermaid code."""

    try:
        from ...llm import GeminiClient

        client = GeminiClient()
        response = await asyncio.to_thread(client.generate, prompt, MERMAID_SYSTEM_PROMPT)

        # Clean the response - remove any markdown fences if present
        mermaid_code = response.strip()
        if mermaid_code.startswith("```mermaid"):
            mermaid_code = mermaid_code[10:]
        if mermaid_code.startswith("```"):
            mermaid_code = mermaid_code[3:]
        if mermaid_code.endswith("```"):
            mermaid_code = mermaid_code[:-3]
        mermaid_code = mermaid_code.strip()

        return {"mermaid_code": mermaid_code}

    except Exception as e:
        logger.error(f"Error generating Mermaid diagram: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate diagram: {e!s}",
        ) from e
