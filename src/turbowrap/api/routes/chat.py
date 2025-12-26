"""Chat routes."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ...db.models import ChatMessage, ChatSession
from ..deps import get_db
from ..schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_sessions(
    repository_id: str | None = None,
    status: str = "active",
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List chat sessions."""
    query = db.query(ChatSession).filter(ChatSession.status == status)

    if repository_id:
        query = query.filter(ChatSession.repository_id == repository_id)

    return query.order_by(ChatSession.updated_at.desc()).limit(limit).all()


@router.post("/sessions", response_model=ChatSessionResponse)
def create_session(
    data: ChatSessionCreate,
    db: Session = Depends(get_db),
):
    """Create a new chat session."""
    session = ChatSession(
        repository_id=data.repository_id,
        task_id=data.task_id,
        title=data.title,
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
):
    """Get chat session details."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
def get_messages(
    session_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get messages for a chat session."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .all()
    )


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
def send_message(
    session_id: str,
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
):
    """Send a message in a chat session (non-streaming)."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message
    user_message = ChatMessage(
        session_id=session_id,
        role="user",
        content=data.content,
    )
    db.add(user_message)
    db.commit()

    # Generate response with Claude
    from ...llm import ClaudeClient

    try:
        claude = ClaudeClient()

        # Build context from previous messages
        previous = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(10)
            .all()
        )
        previous.reverse()

        context = "\n".join([f"{m.role}: {m.content}" for m in previous])

        prompt = f"""Previous conversation:
{context}

User: {data.content}

Respond helpfully as an AI assistant for code development."""

        response = claude.generate(prompt)

        # Save assistant message
        assistant_message = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=response,
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)

        return assistant_message

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {e}")


@router.delete("/sessions/{session_id}")
def archive_session(
    session_id: str,
    db: Session = Depends(get_db),
):
    """Archive a chat session."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = "archived"
    db.commit()

    return {"status": "archived", "id": session_id}


@router.post("/sessions/{session_id}/stream")
async def stream_message(
    session_id: str,
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
):
    """Send a message and stream the response via SSE."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message
    user_message = ChatMessage(
        session_id=session_id,
        role="user",
        content=data.content,
    )
    db.add(user_message)
    db.commit()

    async def generate():
        from ...llm import ClaudeClient

        claude = ClaudeClient()
        full_response = ""

        # Build context from previous messages
        previous = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(10)
            .all()
        )
        previous.reverse()

        context = "\n".join([f"{m.role}: {m.content}" for m in previous])

        prompt = f"""Previous conversation:
{context}

User: {data.content}

Respond helpfully as an AI assistant for code development."""

        try:
            # Stream event: start
            yield {"event": "start", "data": json.dumps({"session_id": session_id})}

            # Stream tokens
            async for chunk in claude.astream(prompt):
                full_response += chunk
                yield {"event": "token", "data": json.dumps({"content": chunk})}

            # Save complete response
            assistant_message = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_response,
            )
            db.add(assistant_message)
            db.commit()

            # Stream event: done
            yield {
                "event": "done",
                "data": json.dumps(
                    {"message_id": assistant_message.id, "total_length": len(full_response)}
                ),
            }

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(generate())
