"""Tests for Gemini CLI wrapper and models."""

import pytest

from turbowrap_llm.gemini import GeminiCLI
from turbowrap_llm.gemini.models import (
    GEMINI_MODEL_MAP,
    GeminiCLIResult,
    GeminiModelUsage,
    GeminiSessionStats,
    calculate_gemini_cost,
)


class TestGeminiModelUsage:
    """Tests for GeminiModelUsage dataclass."""

    def test_default_values(self) -> None:
        """Test GeminiModelUsage default values."""
        usage = GeminiModelUsage(model="gemini-3-flash")

        assert usage.model == "gemini-3-flash"
        assert usage.requests == 0
        assert usage.input_tokens == 0
        assert usage.cache_reads == 0
        assert usage.output_tokens == 0
        assert usage.cost_usd == 0.0

    def test_with_all_values(self) -> None:
        """Test GeminiModelUsage with all values set."""
        usage = GeminiModelUsage(
            model="gemini-3-pro",
            requests=5,
            input_tokens=1000,
            cache_reads=200,
            output_tokens=300,
            cost_usd=0.025,
        )

        assert usage.requests == 5
        assert usage.input_tokens == 1000
        assert usage.cache_reads == 200
        assert usage.output_tokens == 300
        assert usage.cost_usd == 0.025


class TestGeminiSessionStats:
    """Tests for GeminiSessionStats dataclass."""

    def test_default_values(self) -> None:
        """Test GeminiSessionStats default values."""
        stats = GeminiSessionStats()

        assert stats.session_id is None
        assert stats.tool_calls_total == 0
        assert stats.model_usage == []
        assert stats.total_tokens == 0

    def test_aggregated_properties(self) -> None:
        """Test aggregated token properties."""
        usage1 = GeminiModelUsage(model="flash", input_tokens=100, output_tokens=20)
        usage2 = GeminiModelUsage(model="pro", input_tokens=50, output_tokens=10)

        stats = GeminiSessionStats(model_usage=[usage1, usage2])

        assert stats.total_input_tokens == 150
        assert stats.total_output_tokens == 30
        assert stats.total_tokens == 180

    def test_total_cost(self) -> None:
        """Test total cost aggregation."""
        usage1 = GeminiModelUsage(model="flash", cost_usd=0.02)
        usage2 = GeminiModelUsage(model="pro", cost_usd=0.05)

        stats = GeminiSessionStats(model_usage=[usage1, usage2])

        assert stats.total_cost_usd == pytest.approx(0.07)

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        usage = GeminiModelUsage(
            model="gemini-3-flash",
            requests=2,
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.01,
        )
        stats = GeminiSessionStats(
            session_id="sess-123",
            tool_calls_total=5,
            tool_calls_success=4,
            tool_calls_failed=1,
            success_rate=0.8,
            model_usage=[usage],
        )

        d = stats.to_dict()

        assert d["session_id"] == "sess-123"
        assert d["tool_calls"]["total"] == 5
        assert d["tool_calls"]["success_rate"] == 0.8
        assert len(d["model_usage"]) == 1
        assert d["totals"]["total_tokens"] == 120


class TestGeminiCLIResult:
    """Tests for GeminiCLIResult dataclass."""

    def test_minimal_result(self) -> None:
        """Test minimal GeminiCLIResult."""
        result = GeminiCLIResult(
            success=True,
            output="Hello",
            operation_id="op-123",
            session_id="sess-456",
        )

        assert result.success is True
        assert result.output == "Hello"
        assert result.operation_id == "op-123"
        assert result.session_id == "sess-456"
        assert result.error is None
        assert result.session_stats is None

    def test_token_properties_without_stats(self) -> None:
        """Test token properties return 0 without stats."""
        result = GeminiCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
        )

        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.total_tokens == 0
        assert result.total_cost_usd == 0.0

    def test_token_properties_with_stats(self) -> None:
        """Test token properties delegate to session_stats."""
        usage = GeminiModelUsage(
            model="flash",
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.02,
        )
        stats = GeminiSessionStats(model_usage=[usage])

        result = GeminiCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            session_stats=stats,
        )

        assert result.input_tokens == 100
        assert result.output_tokens == 20
        assert result.total_tokens == 120
        assert result.total_cost_usd == 0.02

    def test_models_used_property(self) -> None:
        """Test models_used returns list of model names."""
        usage1 = GeminiModelUsage(model="gemini-3-flash")
        usage2 = GeminiModelUsage(model="gemini-3-pro")
        stats = GeminiSessionStats(model_usage=[usage1, usage2])

        result = GeminiCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            session_stats=stats,
        )

        assert result.models_used == ["gemini-3-flash", "gemini-3-pro"]

    def test_models_used_without_stats(self) -> None:
        """Test models_used returns empty list without stats."""
        result = GeminiCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
        )

        assert result.models_used == []

    def test_cost_by_model_property(self) -> None:
        """Test cost_by_model returns dict mapping model to cost."""
        usage1 = GeminiModelUsage(model="flash", cost_usd=0.02)
        usage2 = GeminiModelUsage(model="pro", cost_usd=0.05)
        stats = GeminiSessionStats(model_usage=[usage1, usage2])

        result = GeminiCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
            session_stats=stats,
        )

        assert result.cost_by_model == {"flash": 0.02, "pro": 0.05}

    def test_cost_by_model_without_stats(self) -> None:
        """Test cost_by_model returns empty dict without stats."""
        result = GeminiCLIResult(
            success=True,
            output="",
            operation_id="op",
            session_id="sess",
        )

        assert result.cost_by_model == {}


class TestGeminiPricing:
    """Tests for Gemini pricing calculations."""

    def test_calculate_cost_known_model(self) -> None:
        """Test cost calculation for known model."""
        cost = calculate_gemini_cost(
            model="gemini-3-pro-preview",
            input_tokens=1_000_000,
            output_tokens=100_000,
            cached_tokens=0,
        )

        # 1M input @ $1.25 + 100K output @ $10.00
        expected = 1.25 + 1.0
        assert cost == pytest.approx(expected)

    def test_calculate_cost_with_cache(self) -> None:
        """Test cost calculation with cached tokens."""
        cost = calculate_gemini_cost(
            model="gemini-3-pro-preview",
            input_tokens=500_000,
            output_tokens=100_000,
            cached_tokens=500_000,
        )

        # 500K input @ $1.25/M + 100K output @ $10.00/M + 500K cached @ $0.3125/M
        input_cost = 0.5 * 1.25
        output_cost = 0.1 * 10.0
        cached_cost = 0.5 * 0.3125
        expected = input_cost + output_cost + cached_cost
        assert cost == pytest.approx(expected)

    def test_calculate_cost_unknown_model(self) -> None:
        """Test cost calculation uses defaults for unknown model."""
        cost = calculate_gemini_cost(
            model="gemini-unknown",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cached_tokens=0,
        )

        # Default: 1M input @ $0.15 + 1M output @ $0.60
        expected = 0.15 + 0.60
        assert cost == pytest.approx(expected)


class TestGeminiCLIConfig:
    """Tests for GeminiCLI configuration."""

    def test_model_map(self) -> None:
        """Test model map contains expected models."""
        assert "flash" in GEMINI_MODEL_MAP
        assert "pro" in GEMINI_MODEL_MAP
        assert GEMINI_MODEL_MAP["flash"] == "gemini-3-flash-preview"

    def test_default_config(self) -> None:
        """Test default CLI configuration."""
        cli = GeminiCLI()

        assert cli.model == "gemini-3-flash-preview"
        assert cli.timeout == 300
        assert cli.auto_accept is True

    def test_custom_config(self) -> None:
        """Test custom CLI configuration."""
        from pathlib import Path

        cli = GeminiCLI(
            model="pro",
            timeout=600,
            working_dir=Path("/tmp"),
            auto_accept=False,
        )

        assert cli.model == "gemini-3-pro-preview"
        assert cli.timeout == 600
        assert cli.working_dir == Path("/tmp")
        assert cli.auto_accept is False
