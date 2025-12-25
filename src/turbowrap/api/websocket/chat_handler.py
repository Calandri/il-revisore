"""WebSocket chat handler for streaming responses."""

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ...db.models import ChatMessage, ChatSession
from ...llm import ClaudeClient


class SessionInvalidatedError(Exception):
    """Raised when a chat session is deleted or invalidated during operation."""
    pass


class ChatWebSocketHandler:
    """Handles WebSocket chat connections with session validation."""

    def __init__(self, websocket: WebSocket, session_id: str, db: Session):
        """Initialize handler.

        Args:
            websocket: WebSocket connection.
            session_id: Chat session ID.
            db: Database session.
        """
        self.websocket = websocket
        self.session_id = session_id
        self.db = db
        self._claude: ClaudeClient | None = None

    @property
    def claude(self) -> ClaudeClient:
        """Get or create Claude client."""
        if self._claude is None:
            self._claude = ClaudeClient()
        return self._claude

    def _validate_session(self) -> ChatSession:
        """Validate that the session still exists and is active.

        Returns:
            The valid ChatSession object.

        Raises:
            SessionInvalidatedError: If session was deleted or invalidated.
        """
        # Refresh the session to get latest state from DB
        self.db.expire_all()

        session = self.db.query(ChatSession).filter(
            ChatSession.id == self.session_id
        ).first()

        if not session:
            raise SessionInvalidatedError(
                f"Session {self.session_id} was deleted during operation"
            )

        return session

    async def handle(self):
        """Main handler loop with session validation."""
        await self.websocket.accept()

        # Verify session exists at connection time
        try:
            self._validate_session()
        except SessionInvalidatedError:
            await self.send_error("Session not found")
            await self.websocket.close()
            return

        try:
            while True:
                # Receive message
                data = await self.websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "message":
                    await self.handle_message(message.get("content", ""))
                elif message.get("type") == "ping":
                    await self.send_json({"type": "pong"})

        except WebSocketDisconnect:
            pass
        except SessionInvalidatedError as e:
            # Session was deleted during operation - close gracefully
            await self.send_error(str(e))
            await self.websocket.close(code=4001, reason="Session invalidated")
        except Exception as e:
            await self.send_error(str(e))

    async def handle_message(self, content: str):
        """Handle incoming chat message with session validation.

        Validates session before each critical operation to handle
        concurrent deletion/invalidation.

        Args:
            content: Message content.

        Raises:
            SessionInvalidatedError: If session was deleted during operation.
        """
        if not content.strip():
            return

        # Validate session before saving user message
        self._validate_session()

        # Save user message with transaction safety
        try:
            user_message = ChatMessage(
                session_id=self.session_id,
                role="user",
                content=content,
            )
            self.db.add(user_message)
            self.db.commit()
        except Exception:
            self.db.rollback()
            # Check if session was deleted (foreign key constraint)
            self._validate_session()  # Will raise if session gone
            raise  # Re-raise original error if session exists

        # Send acknowledgment
        await self.send_json({
            "type": "message_received",
            "message_id": user_message.id,
        })

        # Validate session before querying context
        self._validate_session()

        # Get context from previous messages
        previous = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == self.session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(10)
            .all()
        )
        previous.reverse()

        context = "\n".join([
            f"{m.role}: {m.content}" for m in previous
        ])

        prompt = f"""Previous conversation:
{context}

User: {content}

Respond helpfully as an AI assistant for code development."""

        # Generate response
        await self.send_json({"type": "generating"})

        try:
            # Run Claude in thread pool to not block
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.claude.generate(prompt)
            )

            # Validate session before saving response
            # (session could be deleted during AI generation)
            self._validate_session()

            # Save assistant message with transaction safety
            try:
                assistant_message = ChatMessage(
                    session_id=self.session_id,
                    role="assistant",
                    content=response,
                )
                self.db.add(assistant_message)
                self.db.commit()
            except Exception:
                self.db.rollback()
                # Check if session was deleted
                self._validate_session()
                raise

            # Send response
            await self.send_json({
                "type": "message",
                "role": "assistant",
                "content": response,
                "message_id": assistant_message.id,
            })

        except SessionInvalidatedError:
            # Re-raise to be handled by main loop
            raise
        except Exception as e:
            await self.send_error(f"AI error: {e}")

    async def send_json(self, data: dict[str, Any]):
        """Send JSON message."""
        await self.websocket.send_text(json.dumps(data))

    async def send_error(self, message: str):
        """Send error message."""
        await self.send_json({
            "type": "error",
            "message": message,
        })
