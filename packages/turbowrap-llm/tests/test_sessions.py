"""Tests for conversation session classes."""

import pytest

from turbowrap_llm.base import ConversationMessage, ConversationSession
from turbowrap_llm.claude import ClaudeCLI
from turbowrap_llm.claude.session import ClaudeSession
from turbowrap_llm.gemini import GeminiCLI
from turbowrap_llm.gemini.session import GeminiSession
from turbowrap_llm.grok import GrokCLI
from turbowrap_llm.grok.session import GrokSession


class TestConversationMessage:
    """Tests for ConversationMessage dataclass."""

    def test_message_creation(self) -> None:
        """Test basic message creation."""
        msg = ConversationMessage(role="user", content="Hello")

        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_assistant_message(self) -> None:
        """Test assistant message creation."""
        msg = ConversationMessage(role="assistant", content="Hi there!")

        assert msg.role == "assistant"
        assert msg.content == "Hi there!"


class TestClaudeSession:
    """Tests for ClaudeSession."""

    def test_session_creation(self) -> None:
        """Test session creation from CLI."""
        cli = ClaudeCLI(model="opus")
        session = cli.session()

        assert isinstance(session, ClaudeSession)
        assert session.session_id is not None
        assert len(session.session_id) == 36  # UUID format
        assert session.messages == []
        assert session.message_count == 0
        assert session.turn_count == 0

    def test_session_with_custom_id(self) -> None:
        """Test session with custom session ID."""
        cli = ClaudeCLI(model="sonnet")
        session = cli.session(session_id="custom-session-123")

        assert session.session_id == "custom-session-123"

    def test_session_properties(self) -> None:
        """Test session property access."""
        cli = ClaudeCLI()
        session = ClaudeSession(cli=cli)

        # Initial state
        assert session.message_count == 0
        assert session.turn_count == 0

        # Manually add messages (normally done by send())
        session._messages.append(ConversationMessage(role="user", content="Q1"))
        session._messages.append(ConversationMessage(role="assistant", content="A1"))

        assert session.message_count == 2
        assert session.turn_count == 1

    def test_messages_returns_copy(self) -> None:
        """Test that messages property returns a copy."""
        cli = ClaudeCLI()
        session = ClaudeSession(cli=cli)
        session._messages.append(ConversationMessage(role="user", content="test"))

        messages = session.messages
        messages.append(ConversationMessage(role="assistant", content="fake"))

        # Original should be unchanged
        assert len(session._messages) == 1

    @pytest.mark.asyncio
    async def test_reset_clears_state(self) -> None:
        """Test reset clears session state."""
        cli = ClaudeCLI()
        session = ClaudeSession(cli=cli)
        original_id = session.session_id

        session._messages.append(ConversationMessage(role="user", content="test"))
        session._first_message = False

        await session.reset()

        assert session.session_id != original_id
        assert session.messages == []
        assert session._first_message is True

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test session can be used as async context manager."""
        cli = ClaudeCLI()

        async with cli.session() as session:
            assert isinstance(session, ClaudeSession)

    def test_conforms_to_protocol(self) -> None:
        """Test ClaudeSession conforms to ConversationSession protocol."""
        cli = ClaudeCLI()
        session = cli.session()

        # Protocol conformance check
        assert isinstance(session, ConversationSession)


class TestGeminiSession:
    """Tests for GeminiSession."""

    def test_session_creation(self) -> None:
        """Test session creation from CLI."""
        cli = GeminiCLI(model="flash")
        session = cli.session()

        assert isinstance(session, GeminiSession)
        assert session.session_id is not None
        assert session.messages == []

    def test_session_with_custom_format(self) -> None:
        """Test session with custom context format."""
        cli = GeminiCLI(model="pro")
        session = cli.session(context_format="markdown")

        assert session._context_format == "markdown"

    def test_context_building_xml(self) -> None:
        """Test XML context building."""
        cli = GeminiCLI()
        session = GeminiSession(cli=cli, context_format="xml")

        # Empty history
        assert session._build_context() == ""

        # Add messages
        session._messages.append(ConversationMessage(role="user", content="Hello"))
        session._messages.append(ConversationMessage(role="assistant", content="Hi!"))

        context = session._build_context()

        assert "<conversation_history>" in context
        assert "<USER>Hello</USER>" in context
        assert "<ASSISTANT>Hi!</ASSISTANT>" in context
        assert "</conversation_history>" in context

    def test_context_building_markdown(self) -> None:
        """Test markdown context building."""
        cli = GeminiCLI()
        session = GeminiSession(cli=cli, context_format="markdown")

        session._messages.append(ConversationMessage(role="user", content="Hello"))
        session._messages.append(ConversationMessage(role="assistant", content="Hi!"))

        context = session._build_context()

        assert "## Previous Conversation" in context
        assert "**User:** Hello" in context
        assert "**Assistant:** Hi!" in context

    @pytest.mark.asyncio
    async def test_reset_clears_state(self) -> None:
        """Test reset clears session state."""
        cli = GeminiCLI()
        session = GeminiSession(cli=cli)
        original_id = session.session_id

        session._messages.append(ConversationMessage(role="user", content="test"))

        await session.reset()

        assert session.session_id != original_id
        assert session.messages == []

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test session can be used as async context manager."""
        cli = GeminiCLI()

        async with cli.session() as session:
            assert isinstance(session, GeminiSession)

    def test_conforms_to_protocol(self) -> None:
        """Test GeminiSession conforms to ConversationSession protocol."""
        cli = GeminiCLI()
        session = cli.session()

        assert isinstance(session, ConversationSession)


class TestGrokSession:
    """Tests for GrokSession."""

    def test_session_creation(self) -> None:
        """Test session creation from CLI."""
        cli = GrokCLI()
        session = cli.session()

        assert isinstance(session, GrokSession)
        assert session.session_id is not None
        assert session.messages == []

    def test_session_with_custom_format(self) -> None:
        """Test session with custom context format."""
        cli = GrokCLI()
        session = cli.session(context_format="markdown")

        assert session._context_format == "markdown"

    def test_context_building_xml(self) -> None:
        """Test XML context building."""
        cli = GrokCLI()
        session = GrokSession(cli=cli, context_format="xml")

        # Empty history
        assert session._build_context() == ""

        # Add messages
        session._messages.append(ConversationMessage(role="user", content="Hello"))
        session._messages.append(ConversationMessage(role="assistant", content="Hi!"))

        context = session._build_context()

        assert "<conversation_history>" in context
        assert "<USER>Hello</USER>" in context
        assert "<ASSISTANT>Hi!</ASSISTANT>" in context

    @pytest.mark.asyncio
    async def test_reset_clears_state(self) -> None:
        """Test reset clears session state."""
        cli = GrokCLI()
        session = GrokSession(cli=cli)
        original_id = session.session_id

        session._messages.append(ConversationMessage(role="user", content="test"))

        await session.reset()

        assert session.session_id != original_id
        assert session.messages == []

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test session can be used as async context manager."""
        cli = GrokCLI()

        async with cli.session() as session:
            assert isinstance(session, GrokSession)

    def test_conforms_to_protocol(self) -> None:
        """Test GrokSession conforms to ConversationSession protocol."""
        cli = GrokCLI()
        session = cli.session()

        assert isinstance(session, ConversationSession)


class TestSessionInteroperability:
    """Tests for session class interoperability."""

    def test_all_sessions_share_same_interface(self) -> None:
        """Test all session classes have the same interface."""
        claude_cli = ClaudeCLI()
        gemini_cli = GeminiCLI()
        grok_cli = GrokCLI()

        sessions = [
            claude_cli.session(),
            gemini_cli.session(),
            grok_cli.session(),
        ]

        for session in sessions:
            # All should have these properties
            assert hasattr(session, "session_id")
            assert hasattr(session, "messages")
            assert hasattr(session, "message_count")
            assert hasattr(session, "turn_count")

            # All should have these methods
            assert hasattr(session, "send")
            assert hasattr(session, "reset")
            assert hasattr(session, "__aenter__")
            assert hasattr(session, "__aexit__")

            # All should conform to protocol
            assert isinstance(session, ConversationSession)
