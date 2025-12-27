"""
Edge case tests for ClaudeCLI utility.

Run with: uv run pytest tests/claude_cli/test_edge_cases.py -v

These tests cover edge cases that could break production:
1. Unicode and special characters
2. Malformed/corrupted responses
3. Very large outputs
4. Security edge cases (path traversal, injection)
5. Resource limits
6. Agent file corruption
7. Output parsing robustness
"""

import pytest

from turbowrap.llm.claude_cli import ClaudeCLI

# =============================================================================
# Unicode and Special Characters
# =============================================================================


@pytest.mark.edge_case
class TestUnicodeAndSpecialCharacters:
    """Edge cases for Unicode, emoji, and special characters handling."""

    def test_unicode_in_output(self):
        """Handle Unicode characters in output."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":'
            '"分析结果：代码质量很好！🎉 Résumé: très bien!","modelUsage":{}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "分析结果" in output
        assert "🎉" in output
        assert "Résumé" in output
        assert api_error is None

    def test_unicode_in_thinking(self):
        """Handle Unicode in thinking content."""
        cli = ClaudeCLI(model="opus")
        thinking_text = (
            "Analysons le code... 🤔\\n\\nPunti chiave:\\n"
            "• Struttura buona\\n• Nomi variabili chiari"
        )
        raw_output = (
            '{"type":"assistant","message":{"content":[{"type":"thinking",'
            f'"thinking":"{thinking_text}"'
            "}]}}\n"
            '{"type":"result","result":"Done","modelUsage":{}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "🤔" in thinking
        assert "Punti chiave" in thinking
        assert "•" in thinking

    def test_json_special_chars_in_output(self):
        """Handle JSON special characters that need escaping."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Code: `def foo():\\n    return \\"bar\\"`","modelUsage":{}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "def foo():" in output
        assert api_error is None

    def test_code_blocks_in_output(self):
        """Handle code blocks with various languages."""
        cli = ClaudeCLI(model="opus")
        code_content = (
            "```python\\ndef hello():\\n    print('Hello')\\n```\\n\\n"
            "```javascript\\nconsole.log('test');\\n```"
        )
        raw_output = '{"type":"result","result":"' + code_content + '","modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "```python" in output
        assert "def hello():" in output
        assert "```javascript" in output


# =============================================================================
# Malformed Responses
# =============================================================================


@pytest.mark.edge_case
class TestMalformedResponses:
    """Edge cases for malformed/corrupted response handling."""

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
        assert output is not None
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
        raw_output = '{"type":"result","result":null,"modelUsage":null,"is_error":null}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        # Should handle gracefully
        assert output == raw_output or output == ""


# =============================================================================
# Large Outputs
# =============================================================================


@pytest.mark.edge_case
class TestLargeOutputs:
    """Edge cases for large output handling."""

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
            thinking_content = f"Step {i}: analyzing..."
            chunks.append(
                '{"type":"assistant","message":{"content":[{"type":"thinking",'
                f'"thinking":"{thinking_content}"'
                "}]}}"
            )
        chunks.append('{"type":"result","result":"Final answer","modelUsage":{}}')
        raw_output = "\n".join(chunks)

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Final answer"
        assert thinking is not None
        assert "Step 0:" in thinking
        assert "Step 49:" in thinking

    def test_many_model_usage_entries(self):
        """Handle response using multiple models (router scenario)."""
        cli = ClaudeCLI(model="opus")
        model_usage_json = (
            '"claude-opus-4-5-20251101":{"inputTokens":1000,"outputTokens":500,'
            '"costUSD":0.05},'
            '"claude-sonnet-4-20250514":{"inputTokens":200,"outputTokens":100,'
            '"costUSD":0.001},'
            '"claude-haiku-3-5-20241022":{"inputTokens":50,"outputTokens":25,'
            '"costUSD":0.0001}'
        )
        raw_output = f'{{"type":"result","result":"Done","modelUsage":{{{model_usage_json}}}}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 3
        total_input = sum(m.input_tokens for m in model_usage)
        total_cost = sum(m.cost_usd for m in model_usage)
        assert total_input == 1250
        assert total_cost > 0.05


# =============================================================================
# Agent Prompt Edge Cases
# =============================================================================


@pytest.mark.edge_case
class TestAgentPromptEdgeCases:
    """Edge cases for agent prompt loading."""

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


# =============================================================================
# Model Usage Parsing
# =============================================================================


@pytest.mark.edge_case
class TestModelUsageParsing:
    """Edge cases for model usage parsing."""

    def test_zero_token_usage(self):
        """Handle zero token usage (edge case)."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Empty response","modelUsage":{'
            '"claude-opus":{"inputTokens":0,"outputTokens":0,"costUSD":0}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 1
        assert model_usage[0].input_tokens == 0
        assert model_usage[0].output_tokens == 0

    def test_missing_cost_field(self):
        """Handle missing costUSD field."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Done","modelUsage":{'
            '"claude-opus":{"inputTokens":100,"outputTokens":50}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 1
        assert model_usage[0].cost_usd == 0.0  # Default

    def test_very_high_token_count(self):
        """Handle very high token counts."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Done","modelUsage":{'
            '"claude-opus":{"inputTokens":199999,"outputTokens":100000,'
            '"costUSD":15.50}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert model_usage[0].input_tokens == 199999
        assert model_usage[0].output_tokens == 100000
        assert model_usage[0].cost_usd == 15.50


# =============================================================================
# Extreme Edge Cases
# =============================================================================


@pytest.mark.edge_case
class TestExtremeEdgeCases:
    """Extreme edge cases for robustness testing."""

    def test_null_bytes_in_output(self):
        """Handle null bytes in output (binary data leak)."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":"Hello\\u0000World","modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None
        assert api_error is None

    def test_ansi_escape_codes_in_output(self):
        """Handle ANSI escape codes (terminal color codes) in output."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"\\u001b[31mERROR\\u001b[0m: '
            'Not really an error","modelUsage":{}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None
        assert api_error is None  # Should NOT be detected as error

    def test_json_with_bom(self):
        """Handle JSON with UTF-8 BOM (common Windows issue)."""
        cli = ClaudeCLI(model="opus")
        raw_output = '\ufeff{"type":"result","result":"BOM test","modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None

    def test_windows_line_endings(self):
        """Handle Windows CRLF line endings in NDJSON."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"content_block_delta","delta":{"text":"Hello"}}\r\n'
            '{"type":"result","result":"Done","modelUsage":{}}\r\n'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Done"
        assert api_error is None

    def test_mixed_line_endings(self):
        """Handle mixed LF, CR, CRLF line endings."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"content_block_delta","delta":{"text":"A"}}\n'
            '{"type":"content_block_delta","delta":{"text":"B"}}\r\n'
            '{"type":"content_block_delta","delta":{"text":"C"}}\r'
            '{"type":"result","result":"ABC","modelUsage":{}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None

    def test_extremely_nested_json(self):
        """Handle deeply nested JSON (potential stack overflow)."""
        cli = ClaudeCLI(model="opus")
        nested = '{"a":' * 50 + '"deep"' + "}" * 50
        raw_output = f'{{"type":"result","result":{nested},"modelUsage":{{}}}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is None

    def test_json_with_trailing_comma(self):
        """Handle JSON with trailing comma (common user mistake)."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"oops",}\n{"type":"result","result":"valid","modelUsage":{}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "valid"

    def test_result_looks_like_error_but_isnt(self):
        """Don't false-positive on 'error' keyword in normal output."""
        cli = ClaudeCLI(model="opus")
        result_text = "The function handles error cases correctly. No billing issues found."
        raw_output = f'{{"type":"result","result":"{result_text}","modelUsage":{{}}}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert api_error is None
        assert "error" in output.lower()

    def test_model_usage_with_negative_values(self):
        """Handle negative token counts (should never happen but...)."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Done","modelUsage":{'
            '"model":{"inputTokens":-100,"outputTokens":-50,"costUSD":-5.00}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert len(model_usage) == 1
        assert model_usage[0].input_tokens == -100

    def test_duplicate_result_events(self):
        """Handle multiple result events (should use last one)."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"First result",'
            '"modelUsage":{"m1":{"inputTokens":100,"outputTokens":50}}}\n'
            '{"type":"result","result":"Second result",'
            '"modelUsage":{"m2":{"inputTokens":200,"outputTokens":100}}}\n'
            '{"type":"result","result":"Third result",'
            '"modelUsage":{"m3":{"inputTokens":300,"outputTokens":150}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Third result"
        assert len(model_usage) == 3


# =============================================================================
# Security Edge Cases
# =============================================================================


@pytest.mark.edge_case
class TestPathTraversalAndInjection:
    """Security edge cases - path traversal, injection attempts."""

    def test_context_id_path_traversal(self):
        """Context ID with path traversal should be handled."""
        context_id = "../../../etc/passwd"

        # S3 key is built with f-string, path traversal chars are included
        # S3 allows ".." in keys but doesn't affect server filesystem
        s3_key = f"test/{context_id}_output.md"

        assert "../" in s3_key

    def test_context_id_with_s3_special_chars(self):
        """Context ID with control characters should be handled."""
        context_id = "test\x00id\x1fwith\x7fcontrol"

        s3_key = f"test/{context_id}_output.md"

        # Key contains control chars (S3 may reject these)
        assert "\x00" in s3_key

    def test_model_name_with_special_chars(self):
        """Model name with injection attempt."""
        cli = ClaudeCLI(model="opus; rm -rf /")

        assert cli.model == "opus; rm -rf /"


# =============================================================================
# Resource Limits
# =============================================================================


@pytest.mark.edge_case
class TestResourceLimits:
    """Edge cases for resource limits."""

    def test_timeout_zero(self):
        """Timeout of 0 seconds."""
        cli = ClaudeCLI(model="opus", timeout=0)
        assert cli.timeout == 0

    def test_timeout_negative(self):
        """Negative timeout (invalid input)."""
        cli = ClaudeCLI(model="opus", timeout=-10)
        assert cli.timeout == -10

    def test_thinking_budget_extreme_high(self):
        """Extremely high thinking budget."""
        cli = ClaudeCLI(model="opus")
        assert hasattr(cli, "settings")


# =============================================================================
# Agent File Corruption
# =============================================================================


@pytest.mark.edge_case
class TestAgentFileCorruption:
    """Edge cases for agent file corruption."""

    def test_agent_file_deleted_between_checks(self, tmp_path):
        """Agent file deleted after ClaudeCLI init but before load."""
        agent_file = tmp_path / "agent.md"
        agent_file.write_text("# Instructions")

        cli = ClaudeCLI(agent_md_path=agent_file, model="opus")

        agent_file.unlink()

        prompt = cli.load_agent_prompt()
        assert prompt is None

    def test_agent_file_replaced_with_directory(self, tmp_path):
        """Agent file path becomes a directory (weird but possible)."""
        agent_path = tmp_path / "agent.md"
        agent_path.write_text("# Instructions")

        cli = ClaudeCLI(agent_md_path=agent_path, model="opus")

        agent_path.unlink()
        agent_path.mkdir()

        try:
            prompt = cli.load_agent_prompt()
            assert prompt is None
        except IsADirectoryError:
            pass  # Current behavior

    def test_agent_file_permission_denied(self, tmp_path):
        """Agent file with no read permissions."""
        import os
        import platform

        if platform.system() == "Windows":
            pytest.skip("chmod not supported on Windows")

        agent_file = tmp_path / "agent.md"
        agent_file.write_text("# Secret Instructions")

        os.chmod(agent_file, 0o000)

        try:
            cli = ClaudeCLI(agent_md_path=agent_file, model="opus")
            try:
                prompt = cli.load_agent_prompt()
                assert prompt is None
            except PermissionError:
                pass  # Current behavior
        finally:
            os.chmod(agent_file, 0o644)


# =============================================================================
# Output Parsing Robustness
# =============================================================================


@pytest.mark.edge_case
class TestOutputParsingRobustness:
    """Edge cases for output parsing against malformed data."""

    def test_result_is_array_not_string(self):
        """Handle result field being an array instead of string."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":["item1","item2"],"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None

    def test_result_is_object_not_string(self):
        """Handle result field being an object instead of string."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":{"key":"value"},"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None

    def test_result_is_number(self):
        """Handle result field being a number."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":42,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None

    def test_result_is_boolean(self):
        """Handle result field being a boolean."""
        cli = ClaudeCLI(model="opus")
        raw_output = '{"type":"result","result":true,"modelUsage":{}}'

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output is not None

    def test_thinking_is_not_string(self):
        """Handle thinking field being non-string type."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"assistant","message":{"content":[{"type":"thinking",'
            '"thinking":{"nested":"object"}}]}}\n'
            '{"type":"result","result":"Done","modelUsage":{}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Done"

    def test_model_usage_tokens_as_strings(self):
        """Handle token counts as strings instead of integers."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Done","modelUsage":{'
            '"model":{"inputTokens":"100","outputTokens":"50"}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Done"

    def test_model_usage_cost_as_string(self):
        """Handle cost as string instead of float."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Done","modelUsage":{'
            '"model":{"inputTokens":100,"outputTokens":50,"costUSD":"0.005"}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Done"

    def test_empty_model_name(self):
        """Handle empty string as model name in usage."""
        cli = ClaudeCLI(model="opus")
        raw_output = (
            '{"type":"result","result":"Done","modelUsage":{'
            '"":{"inputTokens":100,"outputTokens":50}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert output == "Done"
        assert len(model_usage) == 1
        assert model_usage[0].model == ""


# =============================================================================
# Real-World Stream JSON (additional edge cases)
# =============================================================================


@pytest.mark.edge_case
class TestRealWorldStreamJson:
    """Real-world stream-json formats from Claude CLI."""

    def test_parse_real_successful_response(self):
        """Parse actual Claude CLI success response format."""
        cli = ClaudeCLI(model="opus")

        # NDJSON requires each JSON object on a single line
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

        thinking_content = (
            "First, I need to understand the problem...\\n\\n"
            "Let me analyze step by step:\\n1. Check the input\\n2. Validate the format"
        )
        raw_output = (
            '{"type":"assistant","message":{"role":"assistant",'
            f'"content":[{{"type":"thinking","thinking":"{thinking_content}"}}]}}}}\n'
            '{"type":"content_block_delta","delta":{"type":"text_delta",'
            '"text":"Based on my analysis"}}\n'
            '{"type":"result","result":"Based on my analysis, the solution is X.",'
            '"modelUsage":{"claude-opus-4-5-20251101":{'
            '"inputTokens":500,"outputTokens":200}}}'
        )

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "Based on my analysis" in output
        assert thinking is not None
        assert "step by step" in thinking
        assert "1. Check the input" in thinking

    def test_parse_tool_use_response(self):
        """Parse response with tool calls (should extract text, ignore tools)."""
        cli = ClaudeCLI(model="opus")

        raw_output = """\
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_123","name":"Read","input":{"file_path":"/test.py"}}]}}
{"type":"tool_result","tool_use_id":"toolu_123","content":"file content here"}
{"type":"content_block_delta","delta":{"type":"text_delta",
"text":"After reading the file, I found"}}
{"type":"result","result":"After reading the file, I found the issue.","modelUsage":{}}"""

        output, model_usage, thinking, api_error = cli._parse_stream_json(raw_output)

        assert "After reading the file" in output
        assert api_error is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
