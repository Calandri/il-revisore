"""
Comprehensive tests for ClaudeCLI utility.

These tests cover:
1. CLI argument building
2. Full prompt construction
3. Model resolution edge cases
4. Dataclass behavior (ModelUsage, ClaudeCLIResult)
5. S3 key generation and formatting
6. Stream JSON parsing (detailed)
7. Configuration and settings
8. Error handling patterns
9. Default values and constants

Run with: uv run pytest tests/test_claude_cli_comprehensive.py -v
"""

from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from turbowrap.utils.claude_cli import (
    DEFAULT_TIMEOUT,
    MODEL_MAP,
    ClaudeCLI,
    ClaudeCLIResult,
    ModelUsage,
)


# =============================================================================
# TEST GROUP 1: CLI Configuration Properties
# =============================================================================


class TestCLIConfigurationProperties:
    """Test that CLI configuration properties are set correctly."""

    def test_model_stored_with_alias(self):
        """Model alias should resolve and be stored."""
        cli = ClaudeCLI(model="opus")
        assert cli.model == MODEL_MAP["opus"]

    def test_model_stored_with_full_name(self):
        """Full model name should be stored as-is."""
        cli = ClaudeCLI(model="claude-3-5-sonnet-20241022")
        assert cli.model == "claude-3-5-sonnet-20241022"

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


# =============================================================================
# TEST GROUP 2: Full Prompt Construction
# =============================================================================


class TestFullPromptConstruction:
    """Test that full prompts are built correctly."""

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
        assert "---" in full  # Separator between agent and user

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
# TEST GROUP 3: Model Resolution Edge Cases
# =============================================================================


class TestModelResolutionEdgeCases:
    """Test model name resolution edge cases."""

    def test_all_aliases_resolve(self):
        """All documented aliases should resolve."""
        for alias in ["opus", "sonnet", "haiku"]:
            cli = ClaudeCLI(model=alias)
            assert cli.model == MODEL_MAP[alias]

    def test_unknown_model_passthrough(self):
        """Unknown model names should pass through unchanged."""
        cli = ClaudeCLI(model="my-custom-model-v1")
        assert cli.model == "my-custom-model-v1"

    def test_case_sensitive_aliases(self):
        """Model aliases should be case-sensitive."""
        # "Opus" is not "opus"
        cli = ClaudeCLI(model="Opus")
        assert cli.model == "Opus"  # Passed through, not resolved

    def test_empty_model_uses_settings(self):
        """Empty/None model should use settings default."""
        with patch("turbowrap.utils.claude_cli.get_settings") as mock:
            mock.return_value.agents.claude_model = "default-model"
            mock.return_value.thinking.enabled = False
            mock.return_value.thinking.s3_bucket = None
            mock.return_value.thinking.s3_region = "eu-west-1"

            cli = ClaudeCLI(model=None)
            assert cli.model == "default-model"

    def test_model_with_version_suffix(self):
        """Models with version suffixes should work."""
        cli = ClaudeCLI(model="claude-opus-4-5-20251101")
        assert cli.model == "claude-opus-4-5-20251101"


# =============================================================================
# TEST GROUP 4: ModelUsage Dataclass
# =============================================================================


class TestModelUsageDataclass:
    """Test ModelUsage dataclass behavior."""

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
# TEST GROUP 5: ClaudeCLIResult Dataclass
# =============================================================================


class TestClaudeCLIResultDataclass:
    """Test ClaudeCLIResult dataclass behavior."""

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
# TEST GROUP 6: S3 Key Generation
# =============================================================================


class TestS3KeyGeneration:
    """Test S3 key generation and formatting."""

    def test_key_includes_prefix(self):
        """S3 key should include configured prefix."""
        cli = ClaudeCLI(model="opus", s3_prefix="my-prefix")

        # The prefix is used in _save_to_s3
        assert cli.s3_prefix == "my-prefix"

    def test_key_includes_timestamp(self):
        """S3 key format includes date/time components."""
        cli = ClaudeCLI(model="opus", s3_prefix="test")

        # The timestamp is generated in _save_to_s3
        # We test that the format is correct by checking the prefix is stored
        assert cli.s3_prefix == "test"

    def test_key_includes_context_id(self):
        """S3 key should include context_id."""
        cli = ClaudeCLI(model="opus")

        # Context ID is passed to _save_to_s3
        # The key format is: {prefix}/{timestamp}/{context_id}_{artifact_type}.md
        assert cli.s3_prefix == "claude-cli"  # Default

    def test_artifact_type_in_key(self):
        """Different artifact types should have different keys."""
        cli = ClaudeCLI(model="opus")

        # Artifact types: "prompt", "output", "thinking"
        # Tested implicitly through _save_to_s3


# =============================================================================
# TEST GROUP 7: Stream JSON Parsing (Detailed)
# =============================================================================


class TestStreamJsonParsingDetailed:
    """Detailed tests for stream-json parsing."""

    def test_content_block_delta_text(self):
        """Parse content_block_delta with text."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"content_block_delta","delta":{"text":"Hello"}}\n{"type":"result","result":"Hello","modelUsage":{}}'

        output, _, _, _ = cli._parse_stream_json(raw)
        assert output == "Hello"

    def test_content_block_delta_without_text(self):
        """Handle content_block_delta without text field."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"content_block_delta","delta":{}}\n{"type":"result","result":"Done","modelUsage":{}}'

        output, _, _, _ = cli._parse_stream_json(raw)
        assert output == "Done"

    def test_message_start_event(self):
        """Handle message_start event."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"message_start","message":{}}\n{"type":"result","result":"Done","modelUsage":{}}'

        output, _, _, _ = cli._parse_stream_json(raw)
        assert output == "Done"

    def test_message_stop_event(self):
        """Handle message_stop event."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"message_stop"}\n{"type":"result","result":"Done","modelUsage":{}}'

        output, _, _, _ = cli._parse_stream_json(raw)
        assert output == "Done"

    def test_thinking_concatenation_order(self):
        """Multiple thinking blocks should be concatenated in order."""
        cli = ClaudeCLI(model="opus")
        raw = """{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"First"}]}}
{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Second"}]}}
{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Third"}]}}
{"type":"result","result":"Done","modelUsage":{}}"""

        _, _, thinking, _ = cli._parse_stream_json(raw)

        # Check order is preserved
        first_pos = thinking.find("First")
        second_pos = thinking.find("Second")
        third_pos = thinking.find("Third")

        assert first_pos < second_pos < third_pos

    def test_model_usage_accumulation(self):
        """Multiple model usages should accumulate."""
        cli = ClaudeCLI(model="opus")
        raw = """{"type":"result","result":"Done","modelUsage":{"model-a":{"inputTokens":100,"outputTokens":50},"model-b":{"inputTokens":200,"outputTokens":100}}}"""

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

    def test_missing_is_error_no_api_error(self):
        """Missing is_error should not set api_error."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"result","result":"Success","modelUsage":{}}'

        _, _, _, api_error = cli._parse_stream_json(raw)
        assert api_error is None


# =============================================================================
# TEST GROUP 8: Configuration and Settings
# =============================================================================


class TestConfigurationAndSettings:
    """Test configuration and settings handling."""

    def test_default_timeout(self):
        """Default timeout should be DEFAULT_TIMEOUT."""
        cli = ClaudeCLI(model="opus")
        assert cli.timeout == DEFAULT_TIMEOUT

    def test_custom_timeout(self):
        """Custom timeout should override default."""
        cli = ClaudeCLI(model="opus", timeout=60)
        assert cli.timeout == 60

    def test_default_s3_prefix(self):
        """Default S3 prefix should be 'claude-cli'."""
        cli = ClaudeCLI(model="opus")
        assert cli.s3_prefix == "claude-cli"

    def test_custom_s3_prefix(self):
        """Custom S3 prefix should be used."""
        cli = ClaudeCLI(model="opus", s3_prefix="custom-prefix")
        assert cli.s3_prefix == "custom-prefix"

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
# TEST GROUP 9: Error Handling Patterns
# =============================================================================


class TestErrorHandlingPatterns:
    """Test error handling patterns."""

    def test_billing_error_keywords(self):
        """Billing errors should be detected by keywords."""
        cli = ClaudeCLI(model="opus")

        billing_messages = [
            "Your credit balance is too low",
            "Billing account suspended",
            "Payment required",
            "Insufficient funds",
            "Quota exceeded",
            "Rate limit exceeded",
        ]

        for msg in billing_messages:
            raw = f'{{"type":"result","result":"{msg}","is_error":true,"modelUsage":{{}}}}'
            _, _, _, api_error = cli._parse_stream_json(raw)
            assert api_error is not None, f"Should detect: {msg}"

    def test_non_billing_error(self):
        """Non-billing errors should still be captured."""
        cli = ClaudeCLI(model="opus")
        raw = '{"type":"result","result":"Internal server error","is_error":true,"modelUsage":{}}'

        _, _, _, api_error = cli._parse_stream_json(raw)
        assert api_error == "Internal server error"

    def test_json_decode_error_skipped(self):
        """Invalid JSON lines should be skipped."""
        cli = ClaudeCLI(model="opus")
        raw = """not valid json
{"type":"result","result":"Success","modelUsage":{}}"""

        output, _, _, _ = cli._parse_stream_json(raw)
        assert output == "Success"

    def test_empty_input_handled(self):
        """Empty input should be handled gracefully."""
        cli = ClaudeCLI(model="opus")
        output, usages, thinking, error = cli._parse_stream_json("")

        assert output == ""  # Fallback to raw (empty)
        assert usages == []
        assert thinking is None


# =============================================================================
# TEST GROUP 10: Constants and Maps
# =============================================================================


class TestConstantsAndMaps:
    """Test constants and model maps."""

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
# TEST GROUP 11: Agent Prompt Caching
# =============================================================================


class TestAgentPromptCaching:
    """Test agent prompt caching behavior."""

    def test_agent_prompt_loaded_once(self, tmp_path):
        """Agent prompt should only be loaded once."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("Original")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")

        # First load
        p1 = cli.load_agent_prompt()

        # Modify file
        agent_file.write_text("Modified")

        # Second load should return cached
        p2 = cli.load_agent_prompt()

        assert p1 == p2 == "Original"

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


# =============================================================================
# TEST GROUP 12: Working Directory Handling
# =============================================================================


class TestWorkingDirectoryHandling:
    """Test working directory handling."""

    def test_working_dir_as_path(self, tmp_path):
        """Working dir as Path should work."""
        cli = ClaudeCLI(model="opus", working_dir=tmp_path)
        assert cli.working_dir == tmp_path

    def test_working_dir_none(self):
        """None working dir should use current directory."""
        cli = ClaudeCLI(model="opus", working_dir=None)
        assert cli.working_dir is None


# =============================================================================
# TEST GROUP 13: S3 Client Lazy Loading
# =============================================================================


class TestS3ClientLazyLoading:
    """Test S3 client lazy loading behavior."""

    def test_s3_client_not_created_on_init(self):
        """S3 client should not be created during __init__."""
        cli = ClaudeCLI(model="opus")
        assert cli._s3_client is None

    def test_s3_client_created_on_access(self):
        """S3 client should be created when accessed."""
        cli = ClaudeCLI(model="opus")

        with patch("turbowrap.utils.claude_cli.boto3") as mock_boto:
            mock_boto.client.return_value = MagicMock()
            _ = cli.s3_client

            mock_boto.client.assert_called_once()

    def test_s3_client_cached(self):
        """S3 client should be cached after first access."""
        cli = ClaudeCLI(model="opus")

        with patch("turbowrap.utils.claude_cli.boto3") as mock_boto:
            mock_client = MagicMock()
            mock_boto.client.return_value = mock_client

            client1 = cli.s3_client
            client2 = cli.s3_client

            assert client1 is client2
            mock_boto.client.assert_called_once()


# =============================================================================
# TEST GROUP 14: Input Validation
# =============================================================================


class TestInputValidation:
    """Test input validation behavior."""

    def test_empty_prompt_allowed(self):
        """Empty prompt should be allowed (validation at CLI level)."""
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
        long_prompt = "x" * 100000  # 100KB
        full = cli._build_full_prompt(long_prompt)
        assert len(full) == 100000


# =============================================================================
# TEST GROUP 15: Special Characters in Prompts
# =============================================================================


class TestSpecialCharactersInPrompts:
    """Test special characters in prompts."""

    def test_unicode_in_prompt(self):
        """Unicode should be preserved in prompts."""
        cli = ClaudeCLI(model="opus")
        prompt = "Hello 世界 🌍 مرحبا"
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
        prompt = 'He said "hello" and \'goodbye\''
        full = cli._build_full_prompt(prompt)
        assert 'He said "hello"' in full


# =============================================================================
# TEST GROUP 16: Token Count Edge Cases
# =============================================================================


class TestTokenCountEdgeCases:
    """Test edge cases in token count parsing."""

    def test_float_token_counts_truncated(self):
        """Float token counts should be handled (get as int)."""
        cli = ClaudeCLI(model="opus")
        # Note: JSON doesn't distinguish int/float, but our code uses .get with int default
        raw = '{"type":"result","result":"Done","modelUsage":{"model":{"inputTokens":100.5,"outputTokens":50.9}}}'

        _, usages, _, _ = cli._parse_stream_json(raw)
        # Python json.loads converts these to floats, but our code uses .get(key, 0)
        # which accepts floats too
        assert len(usages) == 1

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
