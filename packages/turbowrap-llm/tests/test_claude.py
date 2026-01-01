"""Tests for Claude CLI wrapper and models."""

import pytest

from turbowrap_llm.claude import ClaudeCLI
from turbowrap_llm.claude.models import (
    MODEL_MAP,
    ClaudeCLIResult,
    ModelUsage,
)


class TestModelUsage:
    """Tests for ModelUsage dataclass."""

    def test_default_values(self) -> None:
        """Test ModelUsage default values."""
        usage = ModelUsage(model="claude-opus-4-5-20251101")

        assert usage.model == "claude-opus-4-5-20251101"
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cache_read_tokens == 0
        assert usage.cache_creation_tokens == 0
        assert usage.cost_usd == 0.0
        assert usage.web_search_requests == 0
        assert usage.context_window == 0

    def test_with_all_values(self) -> None:
        """Test ModelUsage with all values set."""
        usage = ModelUsage(
            model="claude-opus-4-5-20251101",
            input_tokens=1000,
            output_tokens=200,
            cache_read_tokens=500,
            cache_creation_tokens=100,
            cost_usd=0.05,
            web_search_requests=2,
            context_window=200000,
        )

        assert usage.input_tokens == 1000
        assert usage.output_tokens == 200
        assert usage.cache_read_tokens == 500
        assert usage.cache_creation_tokens == 100
        assert usage.cost_usd == 0.05
        assert usage.web_search_requests == 2
        assert usage.context_window == 200000


class TestClaudeCLIResult:
    """Tests for ClaudeCLIResult dataclass."""

    def test_minimal_result(self) -> None:
        """Test minimal ClaudeCLIResult."""
        result = ClaudeCLIResult(
            success=True,
            output="Hello",
            operation_id="op-123",
            session_id="sess-456",
        )

        assert result.success is True
        assert result.output == "Hello"
        assert result.operation_id == "op-123"
        assert result.session_id == "sess-456"
        assert result.thinking is None
        assert result.error is None
        assert result.model_usage == []
        assert result.duration_ms == 0
        assert result.duration_api_ms == 0
        assert result.num_turns == 0

    def test_total_tokens_property(self) -> None:
        """Test total_tokens property aggregates across models."""
        usage1 = ModelUsage(model="opus", input_tokens=100, output_tokens=20)
        usage2 = ModelUsage(model="haiku", input_tokens=50, output_tokens=10)

        result = ClaudeCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            model_usage=[usage1, usage2],
        )

        assert result.total_tokens == 180  # (100+20) + (50+10)
        assert result.input_tokens == 150  # 100 + 50
        assert result.output_tokens == 30  # 20 + 10

    def test_total_cost_usd_property(self) -> None:
        """Test total_cost_usd aggregates across models."""
        usage1 = ModelUsage(model="opus", cost_usd=0.05)
        usage2 = ModelUsage(model="haiku", cost_usd=0.01)

        result = ClaudeCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            model_usage=[usage1, usage2],
        )

        assert result.total_cost_usd == pytest.approx(0.06)

    def test_models_used_property(self) -> None:
        """Test models_used returns list of model names."""
        usage1 = ModelUsage(model="claude-opus-4-5-20251101")
        usage2 = ModelUsage(model="claude-haiku-4-5-20251001")

        result = ClaudeCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            model_usage=[usage1, usage2],
        )

        assert result.models_used == [
            "claude-opus-4-5-20251101",
            "claude-haiku-4-5-20251001",
        ]

    def test_cost_by_model_property(self) -> None:
        """Test cost_by_model returns dict mapping model to cost."""
        usage1 = ModelUsage(model="opus", cost_usd=0.05)
        usage2 = ModelUsage(model="haiku", cost_usd=0.01)

        result = ClaudeCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            model_usage=[usage1, usage2],
        )

        assert result.cost_by_model == {"opus": 0.05, "haiku": 0.01}

    def test_new_fields(self) -> None:
        """Test new duration_api_ms and num_turns fields."""
        result = ClaudeCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            duration_ms=1500,
            duration_api_ms=1200,
            num_turns=3,
        )

        assert result.duration_ms == 1500
        assert result.duration_api_ms == 1200
        assert result.num_turns == 3


class TestClaudeCLIParser:
    """Tests for ClaudeCLI stream-json parsing."""

    def test_parse_stream_json_basic(self, claude_stream_json: str) -> None:
        """Test parsing basic stream-json output."""
        cli = ClaudeCLI(model="opus")
        (
            output,
            model_usage,
            thinking,
            api_error,
            tools_used,
            agents_launched,
            duration_api_ms,
            num_turns,
        ) = cli._parse_stream_json(claude_stream_json)

        assert output == "Hello! How can I help you today?"
        assert len(model_usage) == 2
        assert thinking is None
        assert api_error is None
        assert duration_api_ms == 1200
        assert num_turns == 1

    def test_parse_model_usage_details(self, claude_stream_json: str) -> None:
        """Test parsing detailed model usage."""
        cli = ClaudeCLI(model="opus")
        _, model_usage, _, _, _, _, _, _ = cli._parse_stream_json(claude_stream_json)

        # First model (opus)
        opus = next(u for u in model_usage if "opus" in u.model)
        assert opus.input_tokens == 100
        assert opus.output_tokens == 20
        assert opus.cache_read_tokens == 50
        assert opus.cost_usd == 0.03
        assert opus.context_window == 200000
        assert opus.web_search_requests == 1

        # Second model (haiku)
        haiku = next(u for u in model_usage if "haiku" in u.model)
        assert haiku.input_tokens == 200
        assert haiku.output_tokens == 30
        assert haiku.cache_creation_tokens == 100
        assert haiku.cost_usd == 0.02
        assert haiku.context_window == 100000

    def test_parse_tool_use(self, claude_tool_use_json: str) -> None:
        """Test parsing tool use from output."""
        cli = ClaudeCLI(model="opus")
        _, _, _, _, tools_used, agents_launched, _, _ = cli._parse_stream_json(
            claude_tool_use_json
        )

        assert "Read" in tools_used
        assert "Task" in tools_used
        assert agents_launched == 2  # Two Task tool calls

    def test_parse_thinking(self, claude_thinking_json: str) -> None:
        """Test parsing thinking blocks."""
        cli = ClaudeCLI(model="opus")
        _, _, thinking, _, _, _, _, _ = cli._parse_stream_json(claude_thinking_json)

        assert thinking == "Let me analyze this..."

    def test_parse_error(self, claude_error_json: str) -> None:
        """Test parsing error response."""
        cli = ClaudeCLI(model="opus")
        output, _, _, api_error, _, _, _, _ = cli._parse_stream_json(claude_error_json)

        assert api_error == "API rate limit exceeded"
        assert output == "API rate limit exceeded"


class TestClaudeCLIConfig:
    """Tests for ClaudeCLI configuration."""

    def test_model_map(self) -> None:
        """Test model map contains expected models."""
        assert "opus" in MODEL_MAP
        assert "sonnet" in MODEL_MAP
        assert "haiku" in MODEL_MAP
        assert MODEL_MAP["opus"] == "claude-opus-4-5-20251101"

    def test_default_config(self) -> None:
        """Test default CLI configuration."""
        cli = ClaudeCLI()

        # Default model is sonnet
        assert cli.model == "claude-sonnet-4-5-20250929"
        assert cli.timeout == 180
        assert cli.working_dir is None

    def test_custom_config(self) -> None:
        """Test custom CLI configuration."""
        from pathlib import Path

        cli = ClaudeCLI(
            model="opus",
            timeout=300,
            working_dir=Path("/tmp"),
            github_token="ghp_test",
        )

        assert cli.model == "claude-opus-4-5-20251101"
        assert cli.timeout == 300
        assert cli.working_dir == Path("/tmp")
        assert cli.github_token == "ghp_test"

    def test_tools_preset_expanded(self) -> None:
        """Test tools preset is expanded to full tool list."""
        from turbowrap_llm.claude.models import TOOL_PRESETS

        cli = ClaudeCLI(model="opus", tools="fix")
        # Tools preset gets expanded
        assert cli.tools == TOOL_PRESETS["fix"]
        assert "Read" in cli.tools
        assert "Edit" in cli.tools

    def test_build_full_prompt(self) -> None:
        """Test _build_full_prompt returns prompt unchanged without agent_md."""
        cli = ClaudeCLI(model="opus")

        full_prompt = cli._build_full_prompt("Review this code")
        assert full_prompt == "Review this code"
