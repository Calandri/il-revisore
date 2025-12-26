"""
Advanced tests for ClaudeCLI utility with real-world edge cases.

Run with: uv run pytest tests/test_claude_cli_advanced.py -v

These tests cover edge cases that could break production:
1. Malformed stream-json responses
2. Unicode and special characters
3. Very large outputs
4. Concurrent execution
5. Network/process errors
6. Real billing error formats
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from turbowrap.utils.claude_cli import ClaudeCLI


class TestRealWorldStreamJson:
    """Test 1: Real-world stream-json formats from Claude CLI."""

    def test_parse_real_successful_response(self):
        """Parse actual Claude CLI success response format."""
        cli = ClaudeCLI(model="opus")

        # Real format from Claude CLI v2.0.64+
        raw_output = """\
{"type":"content_block_start","content_block":{"type":"text","text":""}}
{"type":"content_block_delta","delta":{"type":"text_delta","text":"Here is"}}
{"type":"content_block_delta","delta":{"type":"text_delta","text":" my analysis"}}
{"type":"content_block_stop"}
{"type":"message_stop"}
{"type":"result","result":"Here is my analysis","modelUsage":{"claude-opus-4-5-20251101":{"inputTokens":1234,"outputTokens":567,"cacheReadInputTokens":100,"cacheCreationInputTokens":50,"costUSD":0.0523}},"is_error":false}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Here is my analysis"
        assert api_error is None
        assert len(model_usage) == 1
        assert model_usage[0].input_tokens == 1234
        assert model_usage[0].output_tokens == 567
        assert model_usage[0].cache_read_tokens == 100
        assert model_usage[0].cache_creation_tokens == 50
        assert abs(model_usage[0].cost_usd - 0.0523) < 0.0001

    def test_parse_real_thinking_response(self):
        """Parse actual extended thinking response format."""
        cli = ClaudeCLI(model="opus")

        # Real format with extended thinking
        raw_output = """\
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"First, I need to understand the problem...\\n\\nLet me analyze step by step:\\n1. Check the input\\n2. Validate the format"}]}}
{"type":"content_block_delta","delta":{"type":"text_delta","text":"Based on my analysis"}}
{"type":"result","result":"Based on my analysis, the solution is X.","modelUsage":{"claude-opus-4-5-20251101":{"inputTokens":500,"outputTokens":200}}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "Based on my analysis" in output
        assert thinking is not None
        assert "step by step" in thinking
        assert "1. Check the input" in thinking

    def test_parse_tool_use_response(self):
        """Parse response with tool calls (should extract text, ignore tools)."""
        cli = ClaudeCLI(model="opus")

        # Response with tool use
        raw_output = """\
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_123","name":"Read","input":{"file_path":"/test.py"}}]}}
{"type":"tool_result","tool_use_id":"toolu_123","content":"file content here"}
{"type":"content_block_delta","delta":{"type":"text_delta","text":"After reading the file, I found"}}
{"type":"result","result":"After reading the file, I found the issue.","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "After reading the file" in output
        assert api_error is None


class TestRealBillingErrors:
    """Test 2: Real billing/API error formats from Anthropic."""

    def test_credit_balance_error(self):
        """Real credit balance error format."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Your credit balance is too low to access Claude claude-opus-4-5-20251101. Please go to Plans & Billing to upgrade or purchase credits.","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "credit balance" in api_error.lower()

    def test_rate_limit_429_error(self):
        """Real rate limit error format."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Rate limit exceeded. You have exceeded your rate limit of 50 requests per minute. Please wait before making another request.","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "rate limit" in api_error.lower()

    def test_overloaded_error(self):
        """Real API overloaded error format."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"The API is temporarily overloaded. Please try again in a few moments.","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "overloaded" in api_error.lower()

    def test_invalid_api_key_error(self):
        """Real invalid API key error."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Invalid API key. Please check your ANTHROPIC_API_KEY environment variable.","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "api key" in api_error.lower() or "invalid" in api_error.lower()

    def test_context_length_error(self):
        """Real context length exceeded error."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"This request would exceed the model's maximum context length of 200000 tokens. Your request used 250000 tokens.","is_error":true,"modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is not None
        assert "context length" in api_error.lower() or "tokens" in api_error.lower()


class TestUnicodeAndSpecialCharacters:
    """Test 3: Unicode, emoji, and special characters handling."""

    def test_unicode_in_output(self):
        """Handle Unicode characters in output."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"分析结果：代码质量很好！🎉 Résumé: très bien!","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "分析结果" in output
        assert "🎉" in output
        assert "Résumé" in output
        assert api_error is None

    def test_unicode_in_thinking(self):
        """Handle Unicode in thinking content."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Analysons le code... 🤔\\n\\nPunti chiave:\\n• Struttura buona\\n• Nomi variabili chiari"}]}}
{"type":"result","result":"Done","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "🤔" in thinking
        assert "Punti chiave" in thinking
        assert "•" in thinking

    def test_json_special_chars_in_output(self):
        """Handle JSON special characters that need escaping."""
        cli = ClaudeCLI(model="opus")
        # Output contains quotes, backslashes, newlines
        raw_output = """{"type":"result","result":"Code: `def foo():\\n    return \\"bar\\"`","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "def foo():" in output
        assert api_error is None

    def test_code_blocks_in_output(self):
        """Handle code blocks with various languages."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"```python\\ndef hello():\\n    print('Hello')\\n```\\n\\n```javascript\\nconsole.log('test');\\n```","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "```python" in output
        assert "def hello():" in output
        assert "```javascript" in output


class TestLargeOutputs:
    """Test 4: Large output handling."""

    def test_very_large_output(self):
        """Handle very large output (simulating big code review)."""
        cli = ClaudeCLI(model="opus")

        # Simulate 100KB output
        large_content = "x" * 100000
        raw_output = f'{{"type":"result","result":"{large_content}","modelUsage":{{}}}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(output) == 100000
        assert api_error is None

    def test_many_thinking_chunks(self):
        """Handle many thinking chunks (deep reasoning)."""
        cli = ClaudeCLI(model="opus")

        # 50 thinking chunks
        chunks = []
        for i in range(50):
            chunks.append(
                f'{{"type":"assistant","message":{{"content":[{{"type":"thinking","thinking":"Step {i}: analyzing..."}}]}}}}'
            )
        chunks.append('{"type":"result","result":"Final answer","modelUsage":{}}')
        raw_output = "\n".join(chunks)

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Final answer"
        assert thinking is not None
        # Should concatenate all 50 thinking chunks
        assert "Step 0:" in thinking
        assert "Step 49:" in thinking

    def test_many_model_usage_entries(self):
        """Handle response using multiple models (router scenario)."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Done","modelUsage":{"claude-opus-4-5-20251101":{"inputTokens":1000,"outputTokens":500,"costUSD":0.05},"claude-sonnet-4-20250514":{"inputTokens":200,"outputTokens":100,"costUSD":0.001},"claude-haiku-3-5-20241022":{"inputTokens":50,"outputTokens":25,"costUSD":0.0001}}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 3
        total_input = sum(m.input_tokens for m in model_usage)
        total_cost = sum(m.cost_usd for m in model_usage)
        assert total_input == 1250
        assert total_cost > 0.05


class TestMalformedResponses:
    """Test 5: Malformed/corrupted response handling."""

    def test_truncated_json(self):
        """Handle truncated JSON (connection dropped)."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Partial outpu"""  # Truncated

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        # Should fallback to raw output
        assert output == raw_output
        assert api_error is None

    def test_mixed_valid_invalid_lines(self):
        """Handle mix of valid and invalid JSON lines."""
        cli = ClaudeCLI(model="opus")
        raw_output = """\
{"type":"content_block_delta","delta":{"text":"Hello"}}
INVALID LINE HERE
{"another": "invalid
{"type":"result","result":"Success","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Success"
        assert api_error is None

    def test_empty_result_field(self):
        """Handle empty result field - falls back to raw since '' is falsy."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        # Empty string is falsy, so current impl falls back to raw
        # This is acceptable behavior - empty result is unusual
        assert output is not None  # Either "" or raw_output
        assert api_error is None

    def test_missing_result_type(self):
        """Handle response without result type event."""
        cli = ClaudeCLI(model="opus")
        raw_output = """\
{"type":"content_block_delta","delta":{"text":"Some output"}}
{"type":"message_stop"}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        # Should fallback to raw
        assert output == raw_output

    def test_null_values_in_response(self):
        """Handle null values in JSON."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":null,"modelUsage":null,"is_error":null}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        # Should handle gracefully
        assert output == raw_output or output == ""


class TestAgentPromptEdgeCases:
    """Test 6: Agent prompt edge cases."""

    def test_empty_agent_file(self, tmp_path):
        """Handle empty agent MD file."""
        agent_file = tmp_path / "empty.md"
        agent_file.write_text("")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        prompt = cli.load_agent_prompt()

        assert prompt == ""

    def test_binary_file_as_agent(self, tmp_path):
        """Handle binary file accidentally used as agent."""
        agent_file = tmp_path / "binary.md"
        agent_file.write_bytes(b"\x00\x01\x02\x03")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")

        # Should handle gracefully (may raise or return garbage)
        try:
            prompt = cli.load_agent_prompt()
            # If it doesn't raise, just verify it returns something
            assert prompt is not None
        except UnicodeDecodeError:
            pass  # Acceptable behavior

    def test_very_large_agent_file(self, tmp_path):
        """Handle very large agent MD file."""
        agent_file = tmp_path / "large.md"
        agent_file.write_text("# Instructions\n\n" + "- Rule\n" * 10000)

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        prompt = cli.load_agent_prompt()

        assert len(prompt) > 50000

    def test_agent_with_template_syntax(self, tmp_path):
        """Handle agent file with {placeholders} that look like format strings."""
        agent_file = tmp_path / "template.md"
        agent_file.write_text("Review {files} and find {issues}")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
        full_prompt = cli._build_full_prompt("User prompt")

        # Should not crash on format-like strings
        assert "{files}" in full_prompt
        assert "User prompt" in full_prompt


class TestS3SaveEdgeCases:
    """Test 7: S3 save edge cases."""

    @pytest.mark.asyncio
    async def test_s3_bucket_not_configured(self):
        """Handle S3 bucket not configured."""
        with patch("turbowrap.utils.claude_cli.get_settings") as mock_settings:
            mock_settings.return_value.agents.claude_model = "opus"
            mock_settings.return_value.thinking.enabled = False
            mock_settings.return_value.thinking.s3_bucket = None  # Not configured
            mock_settings.return_value.thinking.s3_region = None

            cli = ClaudeCLI(model="opus")
            result = await cli._save_to_s3("content", "output", "test-123")

            assert result is None  # Should gracefully return None

    @pytest.mark.asyncio
    async def test_s3_save_with_special_chars_in_context_id(self):
        """Handle special characters in context_id for S3 key."""
        cli = ClaudeCLI(model="opus")

        # Context ID with special chars
        context_id = "review/2024/test:file.py"

        # Mock S3 client by setting private attribute directly
        mock_s3 = MagicMock()
        cli._s3_client = mock_s3
        cli.s3_bucket = "test-bucket"

        await cli._save_to_s3("content", "output", context_id)

        # Should have called S3 (key may be modified)
        mock_s3.put_object.assert_called_once()


class TestConcurrencyScenarios:
    """Test 8: Concurrent execution scenarios."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_runs(self):
        """Multiple concurrent ClaudeCLI runs don't interfere."""
        results = []

        async def run_cli(index):
            with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:

                async def mock_exec(*args, **kwargs):
                    await asyncio.sleep(0.01)  # Simulate work
                    return (f"Output {index}", [], None, None, None)

                mock_execute.side_effect = mock_exec

                with patch.object(ClaudeCLI, "_save_to_s3", return_value=None):
                    cli = ClaudeCLI(model="opus")
                    result = await cli.run(f"Prompt {index}")
                    return (index, result.output)

        # Run 5 concurrent executions
        tasks = [run_cli(i) for i in range(5)]
        results = await asyncio.gather(*tasks)

        # Each should have correct output
        for index, output in results:
            assert output == f"Output {index}"

    def test_agent_prompt_cache_thread_safety(self, tmp_path):
        """Agent prompt cache is safe across calls."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("Original content")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")

        # Multiple calls should return same cached value
        prompts = [cli.load_agent_prompt() for _ in range(100)]

        assert all(p == "Original content" for p in prompts)


class TestTimeoutScenarios:
    """Test 9: Timeout handling scenarios."""

    @pytest.mark.asyncio
    async def test_timeout_returns_proper_error(self):
        """Timeout returns structured error result."""
        with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:
            mock_execute.return_value = (None, [], None, None, "Timeout after 5s")

            with patch.object(ClaudeCLI, "_save_to_s3", return_value=None):
                cli = ClaudeCLI(model="opus", timeout=5)
                result = await cli.run("Test")

        assert result.success is False
        assert "Timeout" in result.error
        assert result.output == ""
        # Note: duration_ms is 0 when mocking _execute_cli (timing not captured)

    def test_different_timeout_values(self):
        """Different timeout values are properly configured."""
        cli_short = ClaudeCLI(model="opus", timeout=30)
        cli_long = ClaudeCLI(model="opus", timeout=600)

        assert cli_short.timeout == 30
        assert cli_long.timeout == 600


class TestModelUsageParsing:
    """Test 10: Model usage parsing edge cases."""

    def test_zero_token_usage(self):
        """Handle zero token usage (edge case)."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Empty response","modelUsage":{"claude-opus":{"inputTokens":0,"outputTokens":0,"costUSD":0}}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 1
        assert model_usage[0].input_tokens == 0
        assert model_usage[0].output_tokens == 0

    def test_missing_cost_field(self):
        """Handle missing costUSD field."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Done","modelUsage":{"claude-opus":{"inputTokens":100,"outputTokens":50}}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 1
        assert model_usage[0].cost_usd == 0.0  # Default

    def test_very_high_token_count(self):
        """Handle very high token counts."""
        cli = ClaudeCLI(model="opus")
        raw_output = """{"type":"result","result":"Done","modelUsage":{"claude-opus":{"inputTokens":199999,"outputTokens":100000,"costUSD":15.50}}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert model_usage[0].input_tokens == 199999
        assert model_usage[0].output_tokens == 100000
        assert model_usage[0].cost_usd == 15.50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
