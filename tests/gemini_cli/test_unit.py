"""
Unit tests for GeminiCLI utility.

Run with: uv run pytest tests/gemini_cli/test_unit.py -v

These tests verify isolated components of GeminiCLI with mocked dependencies:
1. Time string parsing (parse_time_string from mixins)
2. Token count parsing (parse_token_count from mixins)
3. GeminiModelUsage dataclass
4. GeminiSessionStats dataclass and properties
5. GeminiCLIResult dataclass
6. Model alias resolution
7. Configuration properties
8. Edge cases and error handling
"""

from dataclasses import asdict

import pytest

from turbowrap.llm.gemini import (
    DEFAULT_GEMINI_TIMEOUT,
    GEMINI_MODEL_MAP,
    GeminiCLI,
    GeminiCLIResult,
    GeminiModelUsage,
    GeminiSessionStats,
    _parse_stream_json_stats,
)
from turbowrap.llm.mixins import parse_time_string, parse_token_count

# =============================================================================
# Time String Parsing
# =============================================================================


@pytest.mark.unit
class TestParseTimeString:
    """Unit tests for _parse_time_string function."""

    def test_seconds_only(self):
        """Parse seconds only format."""
        assert parse_time_string("6.2s") == 6.2

    def test_minutes_and_seconds(self):
        """Parse minutes and seconds format."""
        result = parse_time_string("2m 54s")
        assert result == 174.0  # 2*60 + 54

    def test_minutes_only(self):
        """Parse minutes only format."""
        assert parse_time_string("5m") == 300.0

    def test_zero_seconds(self):
        """Parse 0s format."""
        assert parse_time_string("0s") == 0.0

    def test_decimal_seconds(self):
        """Parse decimal seconds."""
        assert parse_time_string("3.14s") == 3.14

    def test_empty_string(self):
        """Empty string should return 0."""
        assert parse_time_string("") == 0.0

    def test_no_unit(self):
        """String without unit should return 0."""
        assert parse_time_string("42") == 0.0

    def test_large_time(self):
        """Parse large time values."""
        result = parse_time_string("10m 30s")
        assert result == 630.0


# =============================================================================
# Token Count Parsing
# =============================================================================


@pytest.mark.unit
class TestParseTokenCount:
    """Unit tests for _parse_token_count function."""

    def test_simple_number(self):
        """Parse simple number."""
        assert parse_token_count("1234") == 1234

    def test_comma_separated(self):
        """Parse comma-separated number."""
        assert parse_token_count("1,435") == 1435

    def test_large_comma_number(self):
        """Parse large comma-separated number."""
        assert parse_token_count("10,449") == 10449

    def test_empty_string(self):
        """Empty string should return 0."""
        assert parse_token_count("") == 0

    def test_with_whitespace(self):
        """Handle whitespace."""
        assert parse_token_count("  1234  ") == 1234

    def test_zero(self):
        """Parse zero."""
        assert parse_token_count("0") == 0


# =============================================================================
# GeminiModelUsage Dataclass
# =============================================================================


@pytest.mark.unit
class TestGeminiModelUsageDataclass:
    """Unit tests for GeminiModelUsage dataclass."""

    def test_all_fields_stored(self):
        """All fields should be stored correctly."""
        usage = GeminiModelUsage(
            model="gemini-3-flash-preview",
            requests=5,
            input_tokens=1000,
            cache_reads=100,
            output_tokens=500,
        )

        assert usage.model == "gemini-3-flash-preview"
        assert usage.requests == 5
        assert usage.input_tokens == 1000
        assert usage.cache_reads == 100
        assert usage.output_tokens == 500

    def test_default_values(self):
        """Default values should be applied."""
        usage = GeminiModelUsage(model="test")

        assert usage.requests == 0
        assert usage.input_tokens == 0
        assert usage.cache_reads == 0
        assert usage.output_tokens == 0

    def test_to_dict(self):
        """Should be convertible to dict."""
        usage = GeminiModelUsage(model="test", input_tokens=100, output_tokens=50)
        d = asdict(usage)

        assert d["model"] == "test"
        assert d["input_tokens"] == 100


# =============================================================================
# GeminiSessionStats Dataclass
# =============================================================================


@pytest.mark.unit
class TestGeminiSessionStatsDataclass:
    """Unit tests for GeminiSessionStats dataclass."""

    def test_total_input_tokens_property(self):
        """total_input_tokens should sum across models."""
        stats = GeminiSessionStats(
            model_usage=[
                GeminiModelUsage(model="a", input_tokens=100),
                GeminiModelUsage(model="b", input_tokens=200),
            ]
        )
        assert stats.total_input_tokens == 300

    def test_total_output_tokens_property(self):
        """total_output_tokens should sum across models."""
        stats = GeminiSessionStats(
            model_usage=[
                GeminiModelUsage(model="a", output_tokens=50),
                GeminiModelUsage(model="b", output_tokens=100),
            ]
        )
        assert stats.total_output_tokens == 150

    def test_total_tokens_property(self):
        """total_tokens should sum input + output."""
        stats = GeminiSessionStats(
            model_usage=[
                GeminiModelUsage(model="a", input_tokens=100, output_tokens=50),
            ]
        )
        assert stats.total_tokens == 150

    def test_empty_model_usage(self):
        """Empty model usage should return 0 totals."""
        stats = GeminiSessionStats()
        assert stats.total_input_tokens == 0
        assert stats.total_output_tokens == 0
        assert stats.total_tokens == 0

    def test_to_dict_structure(self):
        """to_dict should return correct structure."""
        stats = GeminiSessionStats(
            session_id="test-123",
            tool_calls_total=5,
            tool_calls_success=4,
            tool_calls_failed=1,
            success_rate=80.0,
            wall_time_seconds=60.0,
            model_usage=[
                GeminiModelUsage(model="gemini-flash", input_tokens=100, output_tokens=50),
            ],
        )

        d = stats.to_dict()

        assert d["session_id"] == "test-123"
        assert d["tool_calls"]["total"] == 5
        assert d["tool_calls"]["success"] == 4
        assert d["performance"]["wall_time_seconds"] == 60.0
        assert len(d["model_usage"]) == 1
        assert d["totals"]["total_tokens"] == 150


# =============================================================================
# GeminiCLIResult Dataclass
# =============================================================================


@pytest.mark.unit
class TestGeminiCLIResultDataclass:
    """Unit tests for GeminiCLIResult dataclass."""

    def test_successful_result(self):
        """Successful result should have correct fields."""
        result = GeminiCLIResult(
            success=True,
            output="Task completed",
            raw_output="raw...",
            duration_ms=1500,
            model="gemini-3-flash-preview",
        )

        assert result.success is True
        assert result.output == "Task completed"
        assert result.error is None

    def test_failed_result(self):
        """Failed result should have error field."""
        result = GeminiCLIResult(
            success=False,
            output="",
            error="Timeout after 30s",
            duration_ms=30000,
            model="gemini-flash",
        )

        assert result.success is False
        assert result.error == "Timeout after 30s"

    def test_with_session_stats(self):
        """Result with session stats should store them."""
        stats = GeminiSessionStats(session_id="test-123")
        result = GeminiCLIResult(
            success=True,
            output="Done",
            session_stats=stats,
        )

        assert result.session_stats is not None
        assert result.session_stats.session_id == "test-123"

    def test_default_optional_fields(self):
        """Optional fields should have defaults."""
        result = GeminiCLIResult(success=True, output="test")

        assert result.error is None
        assert result.s3_prompt_url is None
        assert result.s3_output_url is None
        assert result.session_stats is None


# =============================================================================
# Model Resolution
# =============================================================================


@pytest.mark.unit
class TestModelResolution:
    """Unit tests for model alias resolution."""

    def test_flash_alias_resolves(self):
        """Flash alias should resolve to full model name."""
        cli = GeminiCLI(model="flash")
        assert cli.model == GEMINI_MODEL_MAP["flash"]

    def test_pro_alias_resolves(self):
        """Pro alias should resolve to full model name."""
        cli = GeminiCLI(model="pro")
        assert cli.model == GEMINI_MODEL_MAP["pro"]

    def test_all_aliases_resolve(self):
        """All documented aliases should resolve."""
        for alias in GEMINI_MODEL_MAP:
            cli = GeminiCLI(model=alias)
            assert cli.model == GEMINI_MODEL_MAP[alias]

    def test_full_model_name_passthrough(self):
        """Full model names should pass through unchanged."""
        full_name = "gemini-3-flash-preview"
        cli = GeminiCLI(model=full_name)
        assert cli.model == full_name

    def test_unknown_model_passthrough(self):
        """Unknown model names should pass through unchanged."""
        cli = GeminiCLI(model="custom-model")
        assert cli.model == "custom-model"


# =============================================================================
# Configuration Properties
# =============================================================================


@pytest.mark.unit
class TestCLIConfigurationProperties:
    """Unit tests for CLI configuration property storage."""

    def test_timeout_stored(self):
        """Timeout should be stored."""
        cli = GeminiCLI(model="flash", timeout=120)
        assert cli.timeout == 120

    def test_s3_prefix_stored(self):
        """S3 prefix should be stored."""
        cli = GeminiCLI(model="flash", s3_prefix="my-prefix")
        assert cli.s3_prefix == "my-prefix"

    def test_working_dir_stored(self, tmp_path):
        """Working directory should be stored."""
        cli = GeminiCLI(model="flash", working_dir=tmp_path)
        assert cli.working_dir == tmp_path

    def test_auto_accept_stored(self):
        """auto_accept should be stored."""
        cli = GeminiCLI(model="flash", auto_accept=True)
        assert cli.auto_accept is True

    def test_default_timeout(self):
        """Default timeout should be DEFAULT_GEMINI_TIMEOUT."""
        cli = GeminiCLI(model="flash")
        assert cli.timeout == DEFAULT_GEMINI_TIMEOUT

    def test_default_s3_prefix(self):
        """Default S3 prefix should be 'gemini-cli'."""
        cli = GeminiCLI(model="flash")
        assert cli.s3_prefix == "gemini-cli"


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Unit tests for edge cases."""

    def test_parse_time_string_edge_cases(self):
        """Edge cases for time parsing."""
        assert parse_time_string("0m 0s") == 0.0
        assert parse_time_string("1m 0s") == 60.0
        assert parse_time_string("0m 1s") == 1.0


# =============================================================================
# Stream JSON Stats Parsing
# =============================================================================


@pytest.mark.unit
class TestParseStreamJsonStats:
    """Unit tests for _parse_stream_json_stats function."""

    def test_parse_complete_result(self):
        """Parse complete result message with all fields."""
        result_data = {
            "type": "result",
            "status": "success",
            "model": "gemini-3-flash-preview",
            "stats": {
                "total_tokens": 626568,
                "input_tokens": 617877,
                "output_tokens": 2334,
                "cached": 354810,
                "input": 263067,
                "duration_ms": 92993,
                "tool_calls": 25,
            },
        }
        stats = _parse_stream_json_stats(result_data)

        assert stats.tool_calls_total == 25
        assert stats.wall_time_seconds == 92.993
        assert len(stats.model_usage) == 1
        assert stats.model_usage[0].model == "gemini-3-flash-preview"
        assert stats.model_usage[0].input_tokens == 617877
        assert stats.model_usage[0].output_tokens == 2334
        assert stats.model_usage[0].cache_reads == 354810

    def test_parse_minimal_result(self):
        """Parse result with minimal stats."""
        result_data = {
            "type": "result",
            "status": "success",
            "stats": {
                "total_tokens": 100,
                "input_tokens": 80,
                "output_tokens": 20,
            },
        }
        stats = _parse_stream_json_stats(result_data)

        assert stats.tool_calls_total == 0
        assert stats.wall_time_seconds == 0.0
        assert len(stats.model_usage) == 1
        assert stats.model_usage[0].input_tokens == 80
        assert stats.model_usage[0].output_tokens == 20

    def test_parse_empty_stats(self):
        """Parse result with no stats field."""
        result_data = {"type": "result", "status": "success"}
        stats = _parse_stream_json_stats(result_data)

        assert stats.tool_calls_total == 0
        assert len(stats.model_usage) == 0

    def test_parse_zero_tokens(self):
        """Parse result with zero tokens."""
        result_data = {
            "type": "result",
            "status": "success",
            "stats": {
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            },
        }
        stats = _parse_stream_json_stats(result_data)

        assert len(stats.model_usage) == 0  # No model usage when tokens are 0

    def test_total_tokens_calculated(self):
        """Verify total_tokens property works with stream JSON stats."""
        result_data = {
            "type": "result",
            "status": "success",
            "model": "gemini-3-flash",
            "stats": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "duration_ms": 5000,
            },
        }
        stats = _parse_stream_json_stats(result_data)

        assert stats.total_input_tokens == 1000
        assert stats.total_output_tokens == 500
        assert stats.total_tokens == 1500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
