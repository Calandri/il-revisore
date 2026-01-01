"""Grok conversational session for multi-turn interactions.

Uses context prepending since Grok CLI doesn't support native session resume.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ..base import ConversationMessage

if TYPE_CHECKING:
    from .cli import GrokCLI
    from .models import GrokCLIResult


class GrokSession:
    """Multi-turn conversation session for Grok CLI.

    Since Grok CLI doesn't support native session resume, this implementation
    prepends the conversation history to each new message.

    Usage:
        cli = GrokCLI(model="grok-4-1-fast-reasoning")

        # Option 1: Context manager (recommended)
        async with cli.session() as session:
            r1 = await session.send("What is Python?")
            r2 = await session.send("Show me an example")  # Remembers context

        # Option 2: Manual management
        session = cli.session()
        r1 = await session.send("Hello")
        r2 = await session.send("Follow up")
        await session.reset()  # Start fresh
    """

    def __init__(
        self,
        cli: "GrokCLI",
        session_id: str | None = None,
        context_format: str = "xml",
    ):
        """Initialize a conversation session.

        Args:
            cli: The GrokCLI instance to use.
            session_id: Optional session ID. If not provided, generates a new one.
            context_format: Format for context prepending ("xml" or "markdown").
        """
        self._cli = cli
        self._session_id = session_id or str(uuid.uuid4())
        self._messages: list[ConversationMessage] = []
        self._context_format = context_format
        self._operation_count = 0

    @property
    def session_id(self) -> str:
        """Get the unique session identifier."""
        return self._session_id

    @property
    def messages(self) -> list[ConversationMessage]:
        """Get all messages in this conversation."""
        return self._messages.copy()

    @property
    def message_count(self) -> int:
        """Get the number of messages in this conversation."""
        return len(self._messages)

    @property
    def turn_count(self) -> int:
        """Get the number of complete turns (user + assistant pairs)."""
        return len(self._messages) // 2

    def _build_context(self) -> str:
        """Build context string from conversation history."""
        if not self._messages:
            return ""

        if self._context_format == "xml":
            lines = ["<conversation_history>"]
            for msg in self._messages:
                role = msg.role.upper()
                lines.append(f"  <{role}>{msg.content}</{role}>")
            lines.append("</conversation_history>")
            lines.append("")
            lines.append(
                "Continue the conversation. Respond to the user's latest message:"
            )
            lines.append("")
            return "\n".join(lines)
        else:
            # Markdown format
            lines = ["## Previous Conversation", ""]
            for msg in self._messages:
                prefix = "**User:**" if msg.role == "user" else "**Assistant:**"
                lines.append(f"{prefix} {msg.content}")
                lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("Continue the conversation:")
            lines.append("")
            return "\n".join(lines)

    async def send(
        self,
        message: str,
        *,
        operation_id: str | None = None,
        save_artifacts: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        headless: bool = True,
        publish_delay_ms: int = 0,
        **kwargs: Any,
    ) -> "GrokCLIResult":
        """Send a message and get a response.

        Args:
            message: The user message to send.
            operation_id: Optional operation ID for tracking.
            save_artifacts: Save prompt/output to artifact saver.
            on_chunk: Callback for streaming output chunks.
            headless: Run in headless mode.
            publish_delay_ms: SSE publish delay.
            **kwargs: Additional arguments passed to CLI.run().

        Returns:
            GrokCLIResult with output, IDs, and stats.
        """
        self._operation_count += 1

        # Build full prompt with context
        context = self._build_context()
        full_prompt = f"{context}{message}" if context else message

        result = await self._cli.run(
            prompt=full_prompt,
            operation_id=operation_id,
            session_id=self._session_id,
            save_artifacts=save_artifacts,
            on_chunk=on_chunk,
            headless=headless,
            publish_delay_ms=publish_delay_ms,
        )

        # Record messages
        self._messages.append(ConversationMessage(role="user", content=message))
        self._messages.append(
            ConversationMessage(role="assistant", content=result.output)
        )

        return result

    async def reset(self) -> None:
        """Reset the conversation, starting fresh with a new session ID."""
        self._session_id = str(uuid.uuid4())
        self._messages = []
        self._operation_count = 0

    async def __aenter__(self) -> "GrokSession":
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager."""
        pass
