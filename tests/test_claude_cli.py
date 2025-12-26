"""
Tests for ClaudeCLI utility.

Run with: uv run pytest tests/test_claude_cli.py -v

These tests verify the ClaudeCLI refactoring is correct before deployment.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from turbowrap.utils.claude_cli import (
    ClaudeCLI,
    ClaudeCLIResult,
    ModelUsage,
    MODEL_MAP,
)


class TestModelMapping:
    """Test 1: Model alias resolution works correctly."""

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

    def test_full_model_name_passthrough(self):
        """Full model names should pass through unchanged."""
        full_name = "claude-opus-4-5-20251101"
        cli = ClaudeCLI(model=full_name)
        assert cli.model == full_name

    def test_default_model_from_settings(self):
        """When no model specified, use settings default."""
        with patch("turbowrap.utils.claude_cli.get_settings") as mock_settings:
            mock_settings.return_value.agents.claude_model = "test-model"
            mock_settings.return_value.thinking.enabled = False
            mock_settings.return_value.thinking.s3_bucket = None
            mock_settings.return_value.thinking.s3_region = "eu-west-1"
            cli = ClaudeCLI(model=None)
            assert cli.model == "test-model"


class TestStreamJsonParsing:
    """Test 2: NDJSON stream-json parsing handles edge cases."""

    def test_parse_valid_result_event(self):
        """Parse a valid result event with model usage."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Hello world","modelUsage":{"claude-opus-4-5-20251101":{"inputTokens":100,"outputTokens":50,"costUSD":0.005}}}"""

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
        raw_output = """{"type":"result","result":"Your credit balance is too low","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error == "Your credit balance is too low"
        assert output == "Your credit balance is too low"  # Output still contains error message

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
        raw_output = """{"type":"other","data":"some data"}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == raw_output  # Fallback to raw
        assert api_error is None

    def test_parse_invalid_json_lines_skipped(self):
        """Invalid JSON lines should be skipped without error."""
        cli = ClaudeCLI(model="opus")
        raw_output = """invalid json here
{"type":"result","result":"Success","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Success"
        assert api_error is None


class TestAgentPromptLoading:
    """Test 3: Agent MD file loading works correctly."""

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

        # First load
        prompt1 = cli.load_agent_prompt()
        assert prompt1 == "Original content"

        # Modify file
        agent_file.write_text("Modified content")

        # Second load should return cached value
        prompt2 = cli.load_agent_prompt()
        assert prompt2 == "Original content"

    def test_build_full_prompt_with_agent(self, tmp_path):
        """Full prompt includes agent instructions."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("# Agent Instructions")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        full_prompt = cli._build_full_prompt("User prompt here")

        assert "# Agent Instructions" in full_prompt
        assert "User prompt here" in full_prompt
        assert "---" in full_prompt  # Separator between agent and user prompt


class TestBillingErrorDetection:
    """Test 4: Billing/API errors are properly detected and returned."""

    def test_billing_error_in_result(self):
        """Billing error should be returned in api_error."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Your credit balance is too low to process this request","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "credit balance" in api_error.lower()

    def test_rate_limit_error_detection(self):
        """Rate limit error should be detected."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Rate limit exceeded. Please try again later.","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "rate limit" in api_error.lower()

    def test_successful_result_no_error(self):
        """Successful result should have no api_error."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Task completed successfully","modelUsage":{"opus":{"inputTokens":100,"outputTokens":50}}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is None
        assert output == "Task completed successfully"


class TestResultStructure:
    """Test 5: ClaudeCLIResult structure is correct for all scenarios."""

    @pytest.mark.asyncio
    async def test_successful_result_structure(self):
        """Successful run returns proper ClaudeCLIResult."""
        with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:
            mock_execute.return_value = (
                "Output text",
                [ModelUsage(model="opus", input_tokens=100, output_tokens=50, cost_usd=0.01)],
                "Thinking content",
                '{"type":"result"}',
                None,  # No error
            )
            with patch.object(ClaudeCLI, "_save_to_s3", return_value="s3://bucket/key"):
                cli = ClaudeCLI(model="opus")
                result = await cli.run("Test prompt")

        assert result.success is True
        assert result.output == "Output text"
        assert result.thinking == "Thinking content"
        assert result.error is None
        assert len(result.model_usage) == 1
        assert result.model_usage[0].input_tokens == 100

    @pytest.mark.asyncio
    async def test_error_result_structure(self):
        """Error run returns ClaudeCLIResult with success=False."""
        with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:
            mock_execute.return_value = (
                "Error message",
                [],
                None,
                None,
                "API Error: Billing issue",
            )
            with patch.object(ClaudeCLI, "_save_to_s3", return_value=None):
                cli = ClaudeCLI(model="opus")
                result = await cli.run("Test prompt")

        assert result.success is False
        assert result.error == "API Error: Billing issue"
        assert result.output == "Error message"  # Output still available

    @pytest.mark.asyncio
    async def test_timeout_result_structure(self):
        """Timeout returns ClaudeCLIResult with timeout error."""
        with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:
            mock_execute.return_value = (
                None,
                [],
                None,
                None,
                "Timeout after 180s",
            )
            with patch.object(ClaudeCLI, "_save_to_s3", return_value=None):
                cli = ClaudeCLI(model="opus", timeout=180)
                result = await cli.run("Test prompt")

        assert result.success is False
        assert "Timeout" in result.error
        assert result.output == ""


class TestSyncWrapper:
    """Test 6: Sync wrapper works correctly in different contexts."""

    def test_run_sync_from_non_async_context(self):
        """run_sync should work from non-async code."""
        with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:
            # Create a proper async mock
            async def mock_execute_cli(*args, **kwargs):
                return ("Sync output", [], None, None, None)

            mock_execute.side_effect = mock_execute_cli
            with patch.object(ClaudeCLI, "_save_to_s3") as mock_s3:
                async def mock_save(*args, **kwargs):
                    return "s3://bucket/key"

                mock_s3.side_effect = mock_save

                cli = ClaudeCLI(model="opus")
                result = cli.run_sync("Test prompt")

        assert result.success is True
        assert result.output == "Sync output"

    def test_run_sync_parameters_passed_correctly(self):
        """run_sync should have correct signature matching run()."""
        cli = ClaudeCLI(model="opus")

        # Verify the method exists and has correct signature
        assert hasattr(cli, "run_sync")
        import inspect

        sig = inspect.signature(cli.run_sync)
        params = list(sig.parameters.keys())

        # run_sync should have same params as run() except callbacks
        assert "prompt" in params
        assert "context_id" in params
        assert "thinking_budget" in params
        assert "save_prompt" in params
        assert "save_output" in params
        assert "save_thinking" in params

        # Streaming callbacks not supported in sync mode
        assert "on_chunk" not in params
        assert "on_stderr" not in params


class TestEdgeCases:
    """Additional edge case tests."""

    def test_empty_raw_output(self):
        """Empty output should be handled gracefully."""
        cli = ClaudeCLI(model="opus")
        output, model_usage, thinking, api_error = cli._parse_stream_json("")

        assert output == ""  # Fallback to raw (empty)
        assert model_usage == []
        assert thinking is None

    def test_multiple_thinking_blocks(self):
        """Multiple thinking blocks should be concatenated."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"First thought..."}]}}
{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Second thought..."}]}}
{"type":"result","result":"Done","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "First thought" in thinking
        assert "Second thought" in thinking

    def test_model_usage_multiple_models(self):
        """Handle responses with multiple model usage entries."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Done","modelUsage":{"model-a":{"inputTokens":100,"outputTokens":50},"model-b":{"inputTokens":200,"outputTokens":100}}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 2
        total_input = sum(m.input_tokens for m in model_usage)
        assert total_input == 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
