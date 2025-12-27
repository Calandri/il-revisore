"""
Unit tests for ClaudeCLI utility.

Run with: uv run pytest tests/claude_cli/test_unit.py -v

These tests verify isolated components of ClaudeCLI with mocked dependencies:
1. Model alias resolution
2. Stream JSON parsing (NDJSON)
3. Billing/API error detection
4. Dataclass behavior (ModelUsage, ClaudeCLIResult)
5. Configuration properties
6. Constants and maps
7. Agent prompt loading and caching
8. Full prompt construction
"""

from dataclasses import asdict
from unittest.mock import patch

import pytest

from turbowrap.llm.claude_cli import (
    DEFAULT_TIMEOUT,
    MODEL_MAP,
    ClaudeCLI,
    ClaudeCLIResult,
    ModelUsage,
)

# =============================================================================
# Model Resolution
# =============================================================================


@pytest.mark.unit
class TestModelResolution:
    """Unit tests for model alias resolution."""

    def test_opus_alias_resolves(self):
        """Opus alias should resolve to full model name."""
        cli = ClaudeCLI(model="opus")
        assert cli.model == MODEL_MAP["opus"]
        assert "opus" in cli.model.lower()

    def test_sonnet_alias_resolves(self):
        """Sonnet alias should resolve to full model name."""
        cli = ClaudeCLI(model="sonnet")
        assert cli.model == MODEL_MAP["sonnet"]
        assert "sonnet" in cli.model.lower()

    def test_haiku_alias_resolves(self):
        """Haiku alias should resolve to full model name."""
        cli = ClaudeCLI(model="haiku")
        assert cli.model == MODEL_MAP["haiku"]
        assert "haiku" in cli.model.lower()

    def test_all_aliases_resolve(self):
        """All documented aliases should resolve."""
        for alias in ["opus", "sonnet", "haiku"]:
            cli = ClaudeCLI(model=alias)
            assert cli.model == MODEL_MAP[alias]

    def test_full_model_name_passthrough(self):
        """Full model names should pass through unchanged."""
        full_name = "claude-opus-4-5-20251101"
        cli = ClaudeCLI(model=full_name)
        assert cli.model == full_name

    def test_unknown_model_passthrough(self):
        """Unknown model names should pass through unchanged."""
        cli = ClaudeCLI(model="my-custom-model-v1")
        assert cli.model == "my-custom-model-v1"

    def test_case_sensitive_aliases(self):
        """Model aliases should be case-sensitive."""
        cli = ClaudeCLI(model="Opus")
        assert cli.model == "Opus"  # Passed through, not resolved

    def test_default_model_from_settings(self):
        """When no model specified, use settings default."""
        with patch("turbowrap.llm.claude_cli.get_settings") as mock_settings:
            mock_settings.return_value.agents.claude_model = "test-model"
            mock_settings.return_value.thinking.enabled = False
            mock_settings.return_value.thinking.s3_bucket = None
            mock_settings.return_value.thinking.s3_region = "eu-west-1"
            cli = ClaudeCLI(model=None)
            assert cli.model == "test-model"

    def test_model_with_version_suffix(self):
        """Models with version suffixes should work."""
        cli = ClaudeCLI(model="claude-opus-4-5-20251101")
        assert cli.model == "claude-opus-4-5-20251101"


# =============================================================================
# Stream JSON Parsing
# =============================================================================


@pytest.mark.unit
class TestStreamJsonParsing:
    """Unit tests for NDJSON stream-json parsing."""

    def test_parse_valid_result_event(self):
        """Parse a valid result event with model usage."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"Hello world","modelUsage":{"claude-opus-4-5-20251101":{"inputTokens":100,"outputTokens":50,"costUSD":0.005}}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Hello world"
        assert len(model_usage) == 1
        assert model_usage[0].input_tokens == 100
        assert model_usage[0].output_tokens == 50
        assert model_usage[0].cost_usd == 0.005
        assert thinking is None
        assert api_error is None

    def test_parse_api_error_event(self):
        """Parse API error from is_error=true event."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"Your credit balance is too low","is_error":true,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error == "Your credit balance is too low"
        assert output == "Your credit balance is too low"

    def test_parse_thinking_content(self):
        """Parse thinking content from assistant message."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Let me analyze this..."}]}}
{"type":"result","result":"Analysis complete","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert thinking == "Let me analyze this..."
        assert output == "Analysis complete"
        assert api_error is None

    def test_parse_empty_output_fallback(self):
        """When no result event, fallback to raw output."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"other","data":"some data"}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == raw_output
        assert api_error is None

    def test_parse_invalid_json_lines_skipped(self):
        """Invalid JSON lines should be skipped without error."""
        cli = ClaudeCLI(model="opus")
        raw_output = """invalid json here
{"type":"result","result":"Success","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Success"
        assert api_error is None

    def test_content_block_delta_text(self):
        """Parse content_block_delta with text."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"content_block_delta","delta":{"text":"Hello"}}\n{"type":"result","result":"Hello","modelUsage":{}}'

        output, _, _, _ = cli._parse_stream_json(raw)
        assert output == "Hello"

    def test_thinking_concatenation_order(self):
        """Multiple thinking blocks should be concatenated in order."""
        cli = ClaudeCLI(model="opus")
        raw = """{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"First"}]}}
{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Second"}]}}
{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Third"}]}}
{"type":"result","result":"Done","modelUsage":{}}"""

        _, _, thinking, _ = cli._parse_stream_json(raw)

        first_pos = thinking.find("First")
        second_pos = thinking.find("Second")
        third_pos = thinking.find("Third")

        assert first_pos < second_pos < third_pos

    def test_model_usage_accumulation(self):
        """Multiple model usages should accumulate."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"result","result":"Done","modelUsage":{"model-a":{"inputTokens":100,"outputTokens":50},"model-b":{"inputTokens":200,"outputTokens":100}}}'

        _, usages, _, _ = cli._parse_stream_json(raw)

        assert len(usages) == 2
        total_input = sum(u.input_tokens for u in usages)
        assert total_input == 300

    def test_is_error_true_sets_api_error(self):
        """is_error=true should set api_error."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"result","result":"Error message","is_error":true,"modelUsage":{}}'

        _, _, _, api_error = cli._parse_stream_json(raw)
        assert api_error == "Error message"

    def test_is_error_false_no_api_error(self):
        """is_error=false should not set api_error."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"result","result":"Success","is_error":false,"modelUsage":{}}'

        _, _, _, api_error = cli._parse_stream_json(raw)
        assert api_error is None

    def test_empty_raw_output(self):
        """Empty output should be handled gracefully."""
        cli = ClaudeCLI(model="opus")
        output, model_usage, thinking, api_error = cli._parse_stream_json("")

        assert output == ""
        assert model_usage == []
        assert thinking is None


# =============================================================================
# Billing/API Error Detection
# =============================================================================


@pytest.mark.unit
class TestBillingErrorDetection:
    """Unit tests for billing and API error detection."""

    def test_credit_balance_error(self):
        """Real credit balance error format."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"Your credit balance is too low to access Claude claude-opus-4-5-20251101. Please go to Plans & Billing to upgrade or purchase credits.","is_error":true,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "credit balance" in api_error.lower()

    def test_rate_limit_error_detection(self):
        """Rate limit error should be detected."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"Rate limit exceeded. Please try again later.","is_error":true,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "rate limit" in api_error.lower()

    def test_overloaded_error(self):
        """Real API overloaded error format."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"The API is temporarily overloaded. Please try again in a few moments.","is_error":true,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "overloaded" in api_error.lower()

    def test_invalid_api_key_error(self):
        """Real invalid API key error."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"Invalid API key. Please check your ANTHROPIC_API_KEY environment variable.","is_error":true,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "api key" in api_error.lower() or "invalid" in api_error.lower()

    def test_context_length_error(self):
        """Real context length exceeded error."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"This request would exceed the model\'s maximum context length of 200000 tokens. Your request used 250000 tokens.","is_error":true,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "context length" in api_error.lower() or "tokens" in api_error.lower()

    def test_successful_result_no_error(self):
        """Successful result should have no api_error."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"Task completed successfully","modelUsage":{"opus":{"inputTokens":100,"outputTokens":50}}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is None
        assert output == "Task completed successfully"


# =============================================================================
# ModelUsage Dataclass
# =============================================================================


@pytest.mark.unit
class TestModelUsageDataclass:
    """Unit tests for ModelUsage dataclass behavior."""

    def test_all_fields_stored(self):
        """All fields should be stored correctly."""
        usage = ModelUsage(
            model="test-model",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=100,
            cache_creation_tokens=50,
            cost_usd=0.05,
        )

        assert usage.model == "test-model"
        assert usage.input_tokens == 1000
        assert usage.output_tokens == 500
        assert usage.cache_read_tokens == 100
        assert usage.cache_creation_tokens == 50
        assert usage.cost_usd == 0.05

    def test_default_values(self):
        """Default values should be applied."""
        usage = ModelUsage(model="test", input_tokens=100, output_tokens=50)

        assert usage.cache_read_tokens == 0
        assert usage.cache_creation_tokens == 0
        assert usage.cost_usd == 0.0

    def test_to_dict(self):
        """Should be convertible to dict."""
        usage = ModelUsage(model="test", input_tokens=100, output_tokens=50)
        d = asdict(usage)

        assert d["model"] == "test"
        assert d["input_tokens"] == 100

    def test_total_tokens_calculation(self):
        """Total tokens = input + output."""
        usage = ModelUsage(model="test", input_tokens=1000, output_tokens=500)
        total = usage.input_tokens + usage.output_tokens

        assert total == 1500


# =============================================================================
# ClaudeCLIResult Dataclass
# =============================================================================


@pytest.mark.unit
class TestClaudeCLIResultDataclass:
    """Unit tests for ClaudeCLIResult dataclass behavior."""

    def test_successful_result(self):
        """Successful result should have correct fields."""
        result = ClaudeCLIResult(
            success=True,
            output="Hello world",
            thinking="Let me think...",
            raw_output='{"type":"result"}',
            model_usage=[ModelUsage(model="opus", input_tokens=100, output_tokens=50)],
            duration_ms=1500,
            model="claude-opus-4-5",
        )

        assert result.success is True
        assert result.output == "Hello world"
        assert result.error is None

    def test_failed_result(self):
        """Failed result should have error field."""
        result = ClaudeCLIResult(
            success=False,
            output="",
            thinking=None,
            raw_output=None,
            model_usage=[],
            duration_ms=100,
            model="opus",
            error="Timeout after 30s",
        )

        assert result.success is False
        assert result.error == "Timeout after 30s"

    def test_default_optional_fields(self):
        """Optional fields should have None defaults."""
        result = ClaudeCLIResult(
            success=True,
            output="test",
            thinking=None,
            raw_output=None,
            model_usage=[],
            duration_ms=0,
            model="opus",
        )

        assert result.error is None
        assert result.s3_prompt_url is None
        assert result.s3_output_url is None
        assert result.s3_thinking_url is None

    def test_with_s3_urls(self):
        """S3 URLs should be stored when provided."""
        result = ClaudeCLIResult(
            success=True,
            output="test",
            thinking=None,
            raw_output=None,
            model_usage=[],
            duration_ms=0,
            model="opus",
            s3_prompt_url="s3://bucket/prompt.md",
            s3_output_url="s3://bucket/output.md",
            s3_thinking_url="s3://bucket/thinking.md",
        )

        assert result.s3_prompt_url == "s3://bucket/prompt.md"


# =============================================================================
# Configuration Properties
# =============================================================================


@pytest.mark.unit
class TestCLIConfigurationProperties:
    """Unit tests for CLI configuration property storage."""

    def test_verbose_true_stored(self):
        """verbose=True should be stored."""
        cli = ClaudeCLI(model="opus", verbose=True)
        assert cli.verbose is True

    def test_verbose_false_stored(self):
        """verbose=False should be stored."""
        cli = ClaudeCLI(model="opus", verbose=False)
        assert cli.verbose is False

    def test_skip_permissions_true_stored(self):
        """skip_permissions=True should be stored."""
        cli = ClaudeCLI(model="opus", skip_permissions=True)
        assert cli.skip_permissions is True

    def test_skip_permissions_false_stored(self):
        """skip_permissions=False should be stored."""
        cli = ClaudeCLI(model="opus", skip_permissions=False)
        assert cli.skip_permissions is False

    def test_timeout_stored(self):
        """Timeout should be stored."""
        cli = ClaudeCLI(model="opus", timeout=120)
        assert cli.timeout == 120

    def test_s3_prefix_stored(self):
        """S3 prefix should be stored."""
        cli = ClaudeCLI(model="opus", s3_prefix="my-prefix")
        assert cli.s3_prefix == "my-prefix"

    def test_agent_md_path_stored(self, tmp_path):
        """Agent MD path should be stored."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("test")
        cli = ClaudeCLI(model="opus", agent_md_path=agent_file)
        assert cli.agent_md_path == agent_file

    def test_default_timeout(self):
        """Default timeout should be DEFAULT_TIMEOUT."""
        cli = ClaudeCLI(model="opus")
        assert cli.timeout == DEFAULT_TIMEOUT

    def test_default_s3_prefix(self):
        """Default S3 prefix should be 'claude-cli'."""
        cli = ClaudeCLI(model="opus")
        assert cli.s3_prefix == "claude-cli"

    def test_default_verbose_true(self):
        """Verbose should default to True."""
        cli = ClaudeCLI(model="opus")
        assert cli.verbose is True

    def test_default_skip_permissions_true(self):
        """skip_permissions should default to True."""
        cli = ClaudeCLI(model="opus")
        assert cli.skip_permissions is True

    def test_working_dir_stored(self, tmp_path):
        """Working directory should be stored."""
        cli = ClaudeCLI(model="opus", working_dir=tmp_path)
        assert cli.working_dir == tmp_path

    def test_working_dir_none_allowed(self):
        """None working directory should be allowed."""
        cli = ClaudeCLI(model="opus", working_dir=None)
        assert cli.working_dir is None


# =============================================================================
# Constants and Maps
# =============================================================================


@pytest.mark.unit
class TestConstantsAndMaps:
    """Unit tests for constants and model maps."""

    def test_model_map_has_opus(self):
        """MODEL_MAP should have opus."""
        assert "opus" in MODEL_MAP
        assert "opus" in MODEL_MAP["opus"].lower()

    def test_model_map_has_sonnet(self):
        """MODEL_MAP should have sonnet."""
        assert "sonnet" in MODEL_MAP
        assert "sonnet" in MODEL_MAP["sonnet"].lower()

    def test_model_map_has_haiku(self):
        """MODEL_MAP should have haiku."""
        assert "haiku" in MODEL_MAP
        assert "haiku" in MODEL_MAP["haiku"].lower()

    def test_default_timeout_is_positive(self):
        """DEFAULT_TIMEOUT should be positive."""
        assert DEFAULT_TIMEOUT > 0

    def test_model_map_values_are_strings(self):
        """All MODEL_MAP values should be strings."""
        for alias, model in MODEL_MAP.items():
            assert isinstance(model, str), f"{alias} value is not string"


# =============================================================================
# Agent Prompt Loading
# =============================================================================


@pytest.mark.unit
class TestAgentPromptLoading:
    """Unit tests for agent MD file loading."""

    def test_load_existing_agent_file(self, tmp_path):
        """Load agent prompt from existing MD file."""
        agent_file = tmp_path / "test_agent.md"
        agent_file.write_text("# Test Agent\n\nYou are a test agent.")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        prompt = cli.load_agent_prompt()

        assert prompt == "# Test Agent\n\nYou are a test agent."

    def test_missing_agent_file_returns_none(self, tmp_path):
        """Missing agent file should return None without error."""
        missing_file = tmp_path / "nonexistent.md"

        cli = ClaudeCLI(agent_md_path=missing_file, model="opus")
        prompt = cli.load_agent_prompt()

        assert prompt is None

    def test_agent_prompt_cached(self, tmp_path):
        """Agent prompt should be cached after first load."""
        agent_file = tmp_path / "test_agent.md"
        agent_file.write_text("Original content")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")

        prompt1 = cli.load_agent_prompt()
        assert prompt1 == "Original content"

        agent_file.write_text("Modified content")
        prompt2 = cli.load_agent_prompt()
        assert prompt2 == "Original content"  # Cached

    def test_cache_is_per_instance(self, tmp_path):
        """Each CLI instance should have its own cache."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("Content A")

        cli1 = ClaudeCLI(agent_md_path=agent_file, model="opus")
        p1 = cli1.load_agent_prompt()

        agent_file.write_text("Content B")

        cli2 = ClaudeCLI(agent_md_path=agent_file, model="opus")
        p2 = cli2.load_agent_prompt()

        assert p1 == "Content A"
        assert p2 == "Content B"

    def test_no_agent_path_returns_none(self):
        """No agent path should return None."""
        cli = ClaudeCLI(model="opus", agent_md_path=None)
        assert cli.load_agent_prompt() is None

    def test_empty_agent_file(self, tmp_path):
        """Handle empty agent MD file."""
        agent_file = tmp_path / "empty.md"
        agent_file.write_text("")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        prompt = cli.load_agent_prompt()

        assert prompt == ""


# =============================================================================
# Full Prompt Construction
# =============================================================================


@pytest.mark.unit
class TestFullPromptConstruction:
    """Unit tests for full prompt building."""

    def test_prompt_without_agent(self):
        """Without agent, prompt should be user prompt only."""
        cli = ClaudeCLI(model="opus")
        full = cli._build_full_prompt("User question here")

        assert "User question here" in full
        assert "---" not in full  # No separator without agent

    def test_prompt_with_agent(self, tmp_path):
        """With agent, prompt should include agent instructions."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("# Agent\n\nYou are a test agent.")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        full = cli._build_full_prompt("User question")

        assert "# Agent" in full
        assert "You are a test agent" in full
        assert "User question" in full
        assert "---" in full

    def test_agent_comes_before_user_prompt(self, tmp_path):
        """Agent instructions should come before user prompt."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("AGENT_MARKER")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        full = cli._build_full_prompt("USER_MARKER")

        agent_pos = full.find("AGENT_MARKER")
        user_pos = full.find("USER_MARKER")

        assert agent_pos < user_pos

    def test_empty_user_prompt(self, tmp_path):
        """Empty user prompt should still work."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("# Agent")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        full = cli._build_full_prompt("")

        assert "# Agent" in full

    def test_multiline_user_prompt(self):
        """Multiline user prompts should be preserved."""
        cli = ClaudeCLI(model="opus")
        prompt = "Line 1\nLine 2\nLine 3"
        full = cli._build_full_prompt(prompt)

        assert "Line 1\nLine 2\nLine 3" in full


# =============================================================================
# Input Validation
# =============================================================================


@pytest.mark.unit
class TestInputValidation:
    """Unit tests for input validation behavior."""

    def test_empty_prompt_allowed(self):
        """Empty prompt should be allowed."""
        cli = ClaudeCLI(model="opus")
        full = cli._build_full_prompt("")
        assert full == ""

    def test_whitespace_only_prompt(self):
        """Whitespace-only prompt should be preserved."""
        cli = ClaudeCLI(model="opus")
        full = cli._build_full_prompt("   \n\t  ")
        assert full == "   \n\t  "

    def test_very_long_prompt(self):
        """Very long prompts should work."""
        cli = ClaudeCLI(model="opus")
        long_prompt = "x" * 100000
        full = cli._build_full_prompt(long_prompt)
        assert len(full) == 100000


# =============================================================================
# Special Characters in Prompts
# =============================================================================


@pytest.mark.unit
class TestSpecialCharactersInPrompts:
    """Unit tests for special characters in prompts."""

    def test_unicode_in_prompt(self):
        """Unicode should be preserved in prompts."""
        cli = ClaudeCLI(model="opus")
        prompt = "Hello 世界 مرحبا"
        full = cli._build_full_prompt(prompt)
        assert prompt in full

    def test_newlines_preserved(self):
        """Newlines should be preserved."""
        cli = ClaudeCLI(model="opus")
        prompt = "Line1\nLine2\r\nLine3"
        full = cli._build_full_prompt(prompt)
        assert "Line1\nLine2\r\nLine3" in full

    def test_tabs_preserved(self):
        """Tabs should be preserved."""
        cli = ClaudeCLI(model="opus")
        prompt = "Col1\tCol2\tCol3"
        full = cli._build_full_prompt(prompt)
        assert "Col1\tCol2\tCol3" in full

    def test_quotes_preserved(self):
        """Quotes should be preserved."""
        cli = ClaudeCLI(model="opus")
        prompt = "He said \"hello\" and 'goodbye'"
        full = cli._build_full_prompt(prompt)
        assert 'He said "hello"' in full


# =============================================================================
# Token Count Edge Cases
# =============================================================================


@pytest.mark.unit
class TestTokenCountEdgeCases:
    """Unit tests for token count parsing edge cases."""

    def test_very_large_token_counts(self):
        """Very large token counts should work."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"result","result":"Done","modelUsage":{"model":{"inputTokens":999999999,"outputTokens":888888888}}}'

        _, usages, _, _ = cli._parse_stream_json(raw)
        assert usages[0].input_tokens == 999999999
        assert usages[0].output_tokens == 888888888

    def test_missing_token_fields(self):
        """Missing token fields should use defaults."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"result","result":"Done","modelUsage":{"model":{}}}'

        _, usages, _, _ = cli._parse_stream_json(raw)
        assert usages[0].input_tokens == 0
        assert usages[0].output_tokens == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
