"""Tests for Grok CLI wrapper and models."""

from turbowrap_llm.grok import GrokCLI
from turbowrap_llm.grok.models import (
    DEFAULT_GROK_MODEL,
    GrokCLIMessage,
    GrokCLIResult,
    GrokSessionStats,
)


class TestGrokCLIMessage:
    """Tests for GrokCLIMessage dataclass."""

    def test_basic_message(self) -> None:
        """Test basic message creation."""
        msg = GrokCLIMessage(role="assistant", content="Hello!")

        assert msg.role == "assistant"
        assert msg.content == "Hello!"
        assert msg.tool_calls is None
        assert msg.tool_call_id is None

    def test_message_with_tool_calls(self) -> None:
        """Test message with tool calls."""
        tool_calls = [{"name": "read_file", "arguments": {"path": "test.py"}}]
        msg = GrokCLIMessage(
            role="assistant",
            content="Let me read that file.",
            tool_calls=tool_calls,
        )

        assert msg.tool_calls == tool_calls
        assert len(msg.tool_calls) == 1

    def test_tool_response_message(self) -> None:
        """Test tool response message."""
        msg = GrokCLIMessage(
            role="tool",
            content="file content here",
            tool_call_id="call_123",
        )

        assert msg.role == "tool"
        assert msg.tool_call_id == "call_123"


class TestGrokSessionStats:
    """Tests for GrokSessionStats dataclass."""

    def test_default_values(self) -> None:
        """Test GrokSessionStats default values."""
        stats = GrokSessionStats()

        assert stats.session_id is None
        assert stats.total_messages == 0
        assert stats.assistant_messages == 0
        assert stats.tool_calls == 0
        assert stats.duration_ms == 0
        assert stats.model == ""
        assert stats.input_tokens == 0
        assert stats.output_tokens == 0

    def test_total_tokens_property(self) -> None:
        """Test total_tokens computed property."""
        stats = GrokSessionStats(input_tokens=100, output_tokens=20)

        assert stats.total_tokens == 120

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        stats = GrokSessionStats(
            session_id="sess-123",
            total_messages=10,
            assistant_messages=5,
            tool_calls=3,
            duration_ms=5000,
            model="grok-4-1-fast-reasoning",
            input_tokens=1000,
            output_tokens=200,
        )

        d = stats.to_dict()

        assert d["session_id"] == "sess-123"
        assert d["total_messages"] == 10
        assert d["assistant_messages"] == 5
        assert d["tool_calls"] == 3
        assert d["duration_ms"] == 5000
        assert d["model"] == "grok-4-1-fast-reasoning"
        assert d["total_tokens"] == 1200


class TestGrokCLIResult:
    """Tests for GrokCLIResult dataclass."""

    def test_minimal_result(self) -> None:
        """Test minimal GrokCLIResult."""
        result = GrokCLIResult(
            success=True,
            output="Hello",
            operation_id="op-123",
            session_id="sess-456",
        )

        assert result.success is True
        assert result.output == "Hello"
        assert result.operation_id == "op-123"
        assert result.session_id == "sess-456"
        assert result.messages == []
        assert result.error is None
        assert result.session_stats is None
        assert result.tools_used == set()

    def test_token_properties_without_stats(self) -> None:
        """Test token properties return 0 without stats."""
        result = GrokCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
        )

        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.total_tokens == 0

    def test_token_properties_with_stats(self) -> None:
        """Test token properties delegate to session_stats."""
        stats = GrokSessionStats(input_tokens=100, output_tokens=20)

        result = GrokCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            session_stats=stats,
        )

        assert result.input_tokens == 100
        assert result.output_tokens == 20
        assert result.total_tokens == 120

    def test_result_with_messages(self) -> None:
        """Test result with parsed messages."""
        messages = [
            GrokCLIMessage(role="user", content="Hello"),
            GrokCLIMessage(role="assistant", content="Hi there!"),
            GrokCLIMessage(
                role="assistant",
                content="",
                tool_calls=[{"name": "read"}],
            ),
        ]

        result = GrokCLIResult(
            success=True,
            output="Hi there!",
            operation_id="op",
            session_id="sess",
            messages=messages,
            tools_used={"read"},
        )

        assert len(result.messages) == 3
        assert "read" in result.tools_used

    def test_failed_result(self) -> None:
        """Test failed result."""
        result = GrokCLIResult(
            success=False,
            output="",
            operation_id="op",
            session_id="sess",
            error="Connection timeout",
        )

        assert result.success is False
        assert result.error == "Connection timeout"


class TestGrokCLIConfig:
    """Tests for GrokCLI configuration."""

    def test_default_model(self) -> None:
        """Test default model constant."""
        assert DEFAULT_GROK_MODEL == "grok-4-1-fast-reasoning"

    def test_default_config(self) -> None:
        """Test default CLI configuration."""
        cli = GrokCLI()

        assert cli.model == DEFAULT_GROK_MODEL
        assert cli.timeout == 120
        assert cli.max_tool_rounds == 400
        assert cli.working_dir is None

    def test_custom_config(self) -> None:
        """Test custom CLI configuration."""
        from pathlib import Path

        cli = GrokCLI(
            model="grok-custom",
            timeout=300,
            working_dir=Path("/tmp"),
            max_tool_rounds=100,
            api_key="test-key",
        )

        assert cli.model == "grok-custom"
        assert cli.timeout == 300
        assert cli.working_dir == Path("/tmp")
        assert cli.max_tool_rounds == 100
        assert cli.api_key == "test-key"
