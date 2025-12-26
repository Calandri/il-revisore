"""
Pytest configuration and shared fixtures for TurboWrap tests.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    """Mock settings for tests that don't need real config."""
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
def mock_aws_secrets():
    """Mock AWS secrets for tests."""
    with patch("turbowrap.utils.claude_cli.get_anthropic_api_key") as mock:
        mock.return_value = "test-api-key"
        yield mock


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository for testing."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Create a simple Python file
    (repo / "main.py").write_text(
        """
def hello():
    return "Hello, World!"
"""
    )

    # Create a structure file
    (repo / "STRUCTURE.md").write_text(
        """
# Project Structure

- main.py: Main entry point
"""
    )

    return repo


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
    thinking = (
        '{"type":"assistant","message":{"content":[{"type":"thinking",'
        '"thinking":"Let me analyze this problem step by step..."}]}}\n'
    )
    content = '{"type":"content_block_delta",' '"delta":{"text":"Based on my analysis"}}\n'
    result = (
        '{"type":"result","result":"Based on my analysis, the answer is 42.",'
        '"modelUsage":{"claude-opus-4-5-20251101":{'
        '"inputTokens":200,"outputTokens":100}}}'
    )
    return thinking + content + result


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
