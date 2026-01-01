"""Claude conversational session for multi-turn interactions.

Uses Claude CLI's native --resume flag for maintaining conversation context.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ..base import ConversationMessage

if TYPE_CHECKING:
    from .cli import ClaudeCLI
    from .models import ClaudeCLIResult


class ClaudeSession:
    """Multi-turn conversation session for Claude CLI.

    Uses Claude CLI's native --resume flag to maintain conversation context
    across multiple messages.

    Usage:
        cli = ClaudeCLI(model="opus")

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
        cli: "ClaudeCLI",
        session_id: str | None = None,
        resume: bool = False,
    ):
        """Initialize a conversation session.

        Args:
            cli: The ClaudeCLI instance to use.
            session_id: Optional session ID. If not provided, generates a new one.
            resume: If True and session_id is provided, resume existing session
                (use --resume instead of --session-id on first message).
        """
        self._cli = cli
        self._session_id = session_id or str(uuid.uuid4())
        self._messages: list[ConversationMessage] = []
        # If resuming an existing session, skip the first message flag
        self._first_message = not (resume and session_id)
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

    async def send(
        self,
        message: str,
        *,
        operation_id: str | None = None,
        thinking_budget: int | None = None,
        save_artifacts: bool = True,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_thinking: Callable[[str], Awaitable[None]] | None = None,
        on_stderr: Callable[[str], Awaitable[None]] | None = None,
        publish_delay_ms: int = 0,
        **kwargs: Any,
    ) -> "ClaudeCLIResult":
        """Send a message and get a response.

        Args:
            message: The user message to send.
            operation_id: Optional operation ID for tracking.
            thinking_budget: Override thinking budget.
            save_artifacts: Save prompt/output to artifact saver.
            on_chunk: Callback for streaming output chunks.
            on_thinking: Callback for streaming thinking chunks.
            on_stderr: Callback for streaming stderr.
            publish_delay_ms: SSE publish delay.
            **kwargs: Additional arguments passed to CLI.run().

        Returns:
            ClaudeCLIResult with output, IDs, usage info, and S3 URLs.
        """
        self._operation_count += 1

        if self._first_message:
            # First message: use session_id
            result = await self._cli.run(
                prompt=message,
                operation_id=operation_id,
                session_id=self._session_id,
                resume_id=None,
                thinking_budget=thinking_budget,
                save_artifacts=save_artifacts,
                on_chunk=on_chunk,
                on_thinking=on_thinking,
                on_stderr=on_stderr,
                publish_delay_ms=publish_delay_ms,
            )
            self._first_message = False
        else:
            # Follow-up messages: use resume_id
            result = await self._cli.run(
                prompt=message,
                operation_id=operation_id,
                session_id=self._session_id,  # Keep same session_id for tracking
                resume_id=self._session_id,  # Resume from previous conversation
                thinking_budget=thinking_budget,
                save_artifacts=save_artifacts,
                on_chunk=on_chunk,
                on_thinking=on_thinking,
                on_stderr=on_stderr,
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
        self._first_message = True
        self._operation_count = 0

    async def __aenter__(self) -> "ClaudeSession":
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager.

        Note: Claude CLI sessions persist on disk, so no explicit cleanup
        is needed. The session can be resumed later using the session_id.
        """
        pass
