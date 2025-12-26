"""CLI Chat API Routes.

Endpoints per gestione chat basata su CLI (claude/gemini).
Supporta multi-chat parallele, agenti custom, MCP servers.
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path

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
from ...db.models import CLIChatMessage, CLIChatSession
from ..deps import get_db
from ..schemas.cli_chat import (
    AgentListResponse,
    AgentResponse,
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


# ============================================================================
# Title Generation
# ============================================================================


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
    # Truncate messages to keep prompt short
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
            # Use fast model for title generation
            args = [
                "claude",
                "--print",
                "--model",
                "claude-sonnet-4-20250514",
                "-p",
                prompt,
            ]
        else:
            args = [
                "gemini",
                "-m",
                "gemini-2.5-flash",
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

        # Clean and limit to 3 words
        # Remove quotes and extra punctuation
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


# ============================================================================
# Session CRUD
# ============================================================================


@router.get("/sessions", response_model=list[CLISessionResponse])
def list_sessions(
    cli_type: str | None = None,
    repository_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List CLI chat sessions."""
    query = db.query(CLIChatSession).filter(CLIChatSession.deleted_at.is_(None))

    if cli_type:
        query = query.filter(CLIChatSession.cli_type == cli_type)

    if repository_id:
        query = query.filter(CLIChatSession.repository_id == repository_id)

    sessions = query.order_by(CLIChatSession.updated_at.desc()).limit(limit).all()

    # Add message count to response
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
):
    """Create a new CLI chat session."""
    # Set default model based on CLI type
    default_model = (
        "claude-opus-4-5-20251101" if data.cli_type == "claude" else "gemini-3-pro-preview"
    )

    session = CLIChatSession(
        cli_type=data.cli_type,
        repository_id=data.repository_id,
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
):
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
):
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

    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)

    logger.info(f"Updated CLI chat session: {session_id}")
    return session


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
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

    # Terminate process if running
    manager = get_process_manager()
    background_tasks.add_task(manager.terminate, session_id)

    # Soft delete
    session.soft_delete()
    db.commit()

    logger.info(f"Deleted CLI chat session: {session_id}")
    return {"status": "deleted", "session_id": session_id}


# ============================================================================
# Messages
# ============================================================================


@router.get("/sessions/{session_id}/messages", response_model=list[CLIMessageResponse])
def get_messages(
    session_id: str,
    limit: int = 100,
    include_thinking: bool = False,
    db: Session = Depends(get_db),
):
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
        query = query.filter(not CLIChatMessage.is_thinking)

    return query.order_by(CLIChatMessage.created_at.asc()).limit(limit).all()


@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: str,
    data: CLIMessageCreate,
    db: Session = Depends(get_db),
):
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
    is_first_message = session.total_messages == 0

    # Save user message
    user_message = CLIChatMessage(
        session_id=session_id,
        role="user",
        content=data.content,
    )
    db.add(user_message)
    db.commit()

    async def event_generator():
        """Generate SSE events for streaming response."""
        manager = get_process_manager()
        loader = get_agent_loader()

        try:
            # Start event
            yield {
                "event": "start",
                "data": json.dumps({"session_id": session_id}),
            }

            # Get or spawn CLI process
            proc = manager.get_process(session_id)

            if not proc:
                # Spawn new process
                cli_type = CLIType(session.cli_type)

                # Generate context for this session
                context = get_context_for_session(
                    db,
                    repo_id=session.repository_id,
                    linear_issue_id=None,  # TODO: support linear issue context
                )
                logger.info(f"Generated context: {len(context)} chars")

                if cli_type == CLIType.CLAUDE:
                    agent_path = None
                    if session.agent_name:
                        agent_path = loader.get_agent_path(session.agent_name)

                    proc = await manager.spawn_claude(
                        session_id=session_id,
                        working_dir=Path(
                            session.repository.local_path if session.repository else "."
                        ),
                        model=session.model or "claude-opus-4-5-20251101",
                        agent_path=agent_path,
                        thinking_budget=(
                            session.thinking_budget if session.thinking_enabled else None
                        ),
                        context=context,
                    )
                else:
                    proc = await manager.spawn_gemini(
                        session_id=session_id,
                        working_dir=Path(
                            session.repository.local_path if session.repository else "."
                        ),
                        model=session.model or "gemini-3-pro-preview",
                        reasoning=session.reasoning_enabled,
                        context=context,
                    )

            # Stream response - parse stream-json line by line
            full_content = []
            system_events = []

            async for line in manager.send_message(session_id, data.content):
                line = line.strip()
                if not line:
                    continue

                logger.debug(f"[STREAM] Line: {line[:100]}...")

                # Try to parse as JSON (stream-json format)
                try:
                    event = json.loads(line)
                    event_type = event.get("type", "unknown")

                    # Collect system events separately
                    if event_type == "system":
                        system_events.append(event)
                        yield {
                            "event": "system",
                            "data": json.dumps(event),
                        }
                        continue

                    # Extract content from different event types
                    content = None

                    if event_type == "assistant":
                        # Assistant message with content blocks
                        if "message" in event and "content" in event["message"]:
                            for block in event["message"]["content"]:
                                if block.get("type") == "text":
                                    content = block.get("text", "")
                                    break

                    elif event_type == "content_block_delta":
                        # Streaming delta - this is the main streaming event!
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            content = delta.get("text", "")

                    elif event_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "text":
                            content = block.get("text", "")

                    elif event_type == "result":
                        # Final result (--print mode)
                        if "result" in event:
                            content = event["result"]

                    # Yield content immediately
                    if content:
                        full_content.append(content)
                        yield {
                            "event": "chunk",
                            "data": json.dumps({"content": content}),
                        }

                except json.JSONDecodeError:
                    # Not JSON - raw text (gemini)
                    if line:
                        full_content.append(line + "\n")
                        yield {
                            "event": "chunk",
                            "data": json.dumps({"content": line + "\n"}),
                        }

            logger.info(
                f"[STREAM] Done. System: {len(system_events)}, Content: {len(''.join(full_content))} chars"
            )

            # Save assistant message
            content = "".join(full_content)
            assistant_message = CLIChatMessage(
                session_id=session_id,
                role="assistant",
                content=content,
                model_used=session.model,
                agent_used=session.agent_name,
            )
            db.add(assistant_message)

            # Update session stats
            session.total_messages += 2
            session.last_message_at = datetime.utcnow()
            session.updated_at = datetime.utcnow()
            db.commit()

            # Done event
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "message_id": assistant_message.id,
                        "total_length": len(content),
                    }
                ),
            }

            # Generate title for first message
            if is_first_message and not session.display_name:
                title = await generate_chat_title(
                    cli_type=session.cli_type,
                    user_message=data.content,
                    assistant_response=content,
                )
                if title:
                    session.display_name = title
                    session.updated_at = datetime.utcnow()
                    db.commit()

                    # Send title update event
                    yield {
                        "event": "title_updated",
                        "data": json.dumps({"title": title}),
                    }

        except Exception as e:
            logger.error(f"Error in stream: {e}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


# ============================================================================
# Process Control
# ============================================================================


@router.post("/sessions/{session_id}/start")
async def start_cli(
    session_id: str,
    db: Session = Depends(get_db),
):
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
        cli_type = CLIType(session.cli_type)

        # Generate context for this session
        context = get_context_for_session(
            db,
            repo_id=session.repository_id,
            linear_issue_id=None,
        )
        logger.info(f"[START] Generated context: {len(context)} chars")

        if cli_type == CLIType.CLAUDE:
            agent_path = None
            if session.agent_name:
                agent_path = loader.get_agent_path(session.agent_name)

            proc = await manager.spawn_claude(
                session_id=session_id,
                working_dir=Path(session.repository.local_path if session.repository else "."),
                model=session.model or "claude-opus-4-5-20251101",
                agent_path=agent_path,
                thinking_budget=session.thinking_budget if session.thinking_enabled else None,
                context=context,
            )
        else:
            proc = await manager.spawn_gemini(
                session_id=session_id,
                working_dir=Path(session.repository.local_path if session.repository else "."),
                model=session.model or "gemini-3-pro-preview",
                reasoning=session.reasoning_enabled,
                context=context,
            )

        session.status = "running"
        session.process_pid = proc.pid
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
):
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
        session.status = "idle"
        session.process_pid = None
        db.commit()

    return {
        "status": "stopped" if terminated else "not_running",
        "session_id": session_id,
    }


# ============================================================================
# Agents
# ============================================================================


@router.get("/agents", response_model=AgentListResponse)
def list_agents():
    """List available Claude agents."""
    loader = get_agent_loader()
    agents = loader.list_agents()

    return AgentListResponse(
        agents=[AgentResponse(**a) for a in agents],
        total=len(agents),
    )


@router.get("/agents/{agent_name}", response_model=AgentResponse)
def get_agent(agent_name: str):
    """Get agent details by name."""
    loader = get_agent_loader()
    agent = loader.get_agent(agent_name)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    return AgentResponse(**agent.info)


# ============================================================================
# Active Processes
# ============================================================================


@router.get("/active")
def list_active_processes():
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
async def terminate_all():
    """Terminate all running CLI processes."""
    manager = get_process_manager()
    count = await manager.terminate_all()

    return {"terminated": count}


@router.get("/process-stats")
def get_process_stats():
    """Get detailed statistics about running CLI processes.

    Returns process count, max allowed, and details for each process
    including age in hours.
    """
    manager = get_process_manager()
    return manager.get_process_stats()


@router.post("/cleanup-stale")
async def cleanup_stale_processes(max_age_hours: float = 3.0):
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


# ============================================================================
# MCP Servers
# ============================================================================


@router.get("/mcp", response_model=MCPConfigResponse)
def get_mcp_config():
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
def list_mcp_servers(include_defaults: bool = True):
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
def add_mcp_server(data: MCPServerCreate):
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
def enable_mcp_server(name: str):
    """Enable an MCP server (add from defaults if needed)."""
    manager = get_mcp_manager()

    # Check if it's a known server
    server = manager.get_server(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    if server["enabled"]:
        return {"status": "already_enabled", "name": name}

    # Enable (add from defaults)
    success = manager.enable_servers([name])
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to enable MCP server '{name}'")

    return {"status": "enabled", "name": name}


@router.delete("/mcp/servers/{name}")
def remove_mcp_server(name: str):
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
def get_default_mcp_servers():
    """Get list of available default MCP servers."""
    manager = get_mcp_manager()
    defaults = manager.get_available_defaults()

    return {"defaults": defaults}
