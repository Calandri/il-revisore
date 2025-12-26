"""
Fixtures specific to ClaudeCLI tests.

These fixtures extend the global conftest.py with ClaudeCLI-specific test data.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_stream_json_success():
    """Sample successful stream-json output."""
    return (
        '{"type":"content_block_delta","delta":{"text":"Hello"}}\n'
        '{"type":"content_block_delta","delta":{"text":" World"}}\n'
        '{"type":"result","result":"Hello World","modelUsage":{'
        '"claude-opus-4-5-20251101":{"inputTokens":100,"outputTokens":50,'
        '"cacheReadInputTokens":0,"cacheCreationInputTokens":0,"costUSD":0.005}}}'
    )


@pytest.fixture
def sample_stream_json_error():
    """Sample error stream-json output."""
    return (
        '{"type":"result","result":"Your credit balance is too low",'
        '"is_error":true,"modelUsage":{}}'
    )


@pytest.fixture
def sample_stream_json_with_thinking():
    """Sample stream-json with extended thinking."""
    thinking_block = (
        '{"type":"assistant","message":{"content":[{"type":"thinking",'
        '"thinking":"Let me analyze this problem step by step..."}]}}\n'
    )
    content_block = '{"type":"content_block_delta",' '"delta":{"text":"Based on my analysis"}}\n'
    result_block = (
        '{"type":"result","result":"Based on my analysis, the answer is 42.",'
        '"modelUsage":{"claude-opus-4-5-20251101":{'
        '"inputTokens":200,"outputTokens":100}}}'
    )
    return thinking_block + content_block + result_block


@pytest.fixture
def sample_real_world_response():
    """Real format from Claude CLI v2.0.64+"""
    return """\
{"type":"content_block_start","content_block":{"type":"text","text":""}}
{"type":"content_block_delta","delta":{"type":"text_delta","text":"Here is"}}
{"type":"content_block_delta","delta":{"type":"text_delta","text":" my analysis"}}
{"type":"content_block_stop"}
{"type":"message_stop"}
{"type":"result","result":"Here is my analysis","modelUsage":{
"claude-opus-4-5-20251101":{"inputTokens":1234,"outputTokens":567,
"cacheReadInputTokens":100,"cacheCreationInputTokens":50,"costUSD":0.0523}},
"is_error":false}"""


@pytest.fixture
def mock_claude_cli_execution():
    """Pre-configured mock for ClaudeCLI._execute_cli."""
    from turbowrap.utils.claude_cli import ClaudeCLI, ModelUsage

    with (
        patch.object(ClaudeCLI, "_execute_cli") as mock_execute,
        patch.object(ClaudeCLI, "_save_to_s3", return_value="s3://bucket/key"),
    ):
        mock_execute.return_value = (
            "Output text",
            [ModelUsage(model="opus", input_tokens=100, output_tokens=50, cost_usd=0.01)],
            "Thinking content",
            '{"type":"result"}',
            None,  # No error
        )
        yield mock_execute


@pytest.fixture
def mock_settings_for_claude_cli():
    """Mock settings specifically for ClaudeCLI tests."""
    with patch("turbowrap.utils.claude_cli.get_settings") as mock:
        settings = MagicMock()
        settings.agents.claude_model = "claude-opus-4-5-20251101"
        settings.thinking.enabled = True
        settings.thinking.budget_tokens = 10000
        settings.thinking.s3_bucket = "test-bucket"
        settings.thinking.s3_region = "eu-west-1"
        mock.return_value = settings
        yield settings


@pytest.fixture
def temp_agent_file(tmp_path):
    """Create a temporary agent file for testing."""
    agent_file = tmp_path / "test_agent.md"
    agent_file.write_text("# Test Agent\n\nYou are a test agent.")
    return agent_file


@pytest.fixture
def billing_error_messages():
    """Common billing error messages from Anthropic API."""
    return [
        (
            "Your credit balance is too low to access Claude "
            "claude-opus-4-5-20251101. Please go to Plans & Billing "
            "to upgrade or purchase credits."
        ),
        (
            "Rate limit exceeded. You have exceeded your rate limit of "
            "50 requests per minute. Please wait before making another request."
        ),
        "The API is temporarily overloaded. Please try again in a few moments.",
        ("Invalid API key. Please check your ANTHROPIC_API_KEY " "environment variable."),
        (
            "This request would exceed the model's maximum context length of "
            "200000 tokens. Your request used 250000 tokens."
        ),
    ]
