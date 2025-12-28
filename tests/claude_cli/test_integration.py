"""
Integration tests for ClaudeCLI utility.

Run with: uv run pytest tests/claude_cli/test_integration.py -v

These tests verify component interactions:
1. Full execution pipeline (run method)
2. S3 save operations
3. Sync wrapper functionality
4. Concurrent execution
5. Timeout handling
6. S3 client lazy loading
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from turbowrap.llm.claude_cli import ClaudeCLI, ModelUsage
from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

# =============================================================================
# Full Execution Pipeline
# =============================================================================


@pytest.mark.integration
class TestResultStructure:
    """Integration tests for ClaudeCLIResult structure in different scenarios."""

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
                "test-session-id",
                set(),  # tools_used
            )
            with patch.object(S3ArtifactSaver, "save_markdown", new_callable=AsyncMock) as mock_s3:
                mock_s3.return_value = "s3://bucket/key"
                cli = ClaudeCLI(model="opus")
                result = await cli.run("Test prompt", operation_type="test", repo_name="test-repo")

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
                None,  # session_id
                set(),  # tools_used
            )
            with patch.object(S3ArtifactSaver, "save_markdown", new_callable=AsyncMock) as mock_s3:
                mock_s3.return_value = None
                cli = ClaudeCLI(model="opus")
                result = await cli.run("Test prompt", operation_type="test", repo_name="test-repo")

        assert result.success is False
        assert result.error == "API Error: Billing issue"
        assert result.output == "Error message"

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
                None,  # session_id
                set(),  # tools_used
            )
            with patch.object(S3ArtifactSaver, "save_markdown", new_callable=AsyncMock) as mock_s3:
                mock_s3.return_value = None
                cli = ClaudeCLI(model="opus", timeout=180)
                result = await cli.run("Test prompt", operation_type="test", repo_name="test-repo")

        assert result.success is False
        assert "Timeout" in result.error
        assert result.output == ""


# =============================================================================
# Sync Wrapper
# =============================================================================


@pytest.mark.integration
class TestSyncWrapper:
    """Integration tests for sync wrapper functionality."""

    def test_run_sync_from_non_async_context(self):
        """run_sync should work from non-async code."""
        with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:

            async def mock_execute_cli(*args, **kwargs):
                return ("Sync output", [], None, None, None, "test-session", set())

            mock_execute.side_effect = mock_execute_cli
            with patch.object(S3ArtifactSaver, "save_markdown", new_callable=AsyncMock) as mock_s3:
                mock_s3.return_value = "s3://bucket/key"

                cli = ClaudeCLI(model="opus")
                result = cli.run_sync("Test prompt", operation_type="test", repo_name="test-repo")

        assert result.success is True
        assert result.output == "Sync output"

    def test_run_sync_parameters_passed_correctly(self):
        """run_sync should have correct signature matching run()."""
        cli = ClaudeCLI(model="opus")

        assert hasattr(cli, "run_sync")
        import inspect

        sig = inspect.signature(cli.run_sync)
        params = list(sig.parameters.keys())

        assert "prompt" in params
        assert "operation_type" in params
        assert "repo_name" in params
        assert "context_id" in params
        assert "thinking_budget" in params
        assert "save_prompt" in params
        assert "save_output" in params
        assert "save_thinking" in params

        # Streaming callbacks not supported in sync mode
        assert "on_chunk" not in params
        assert "on_stderr" not in params


# =============================================================================
# S3 Operations
# =============================================================================


@pytest.mark.integration
class TestS3SaveEdgeCases:
    """Integration tests for S3 save edge cases."""

    @pytest.mark.asyncio
    async def test_s3_bucket_not_configured(self):
        """Handle S3 bucket not configured - saver returns None."""
        with patch("turbowrap.llm.claude_cli.get_settings") as mock_settings:
            mock_settings.return_value.agents.claude_model = "opus"
            mock_settings.return_value.thinking.enabled = False
            mock_settings.return_value.thinking.s3_bucket = None
            mock_settings.return_value.thinking.s3_region = "us-east-1"

            cli = ClaudeCLI(model="opus")
            # With no bucket configured, save_markdown returns None
            result = await cli._s3_saver.save_markdown("content", "output", "test-123")

            assert result is None

    @pytest.mark.asyncio
    async def test_s3_save_with_special_chars_in_context_id(self):
        """Handle special characters in context_id for S3 key."""
        cli = ClaudeCLI(model="opus")

        context_id = "review/2024/test:file.py"

        # Mock the saver's client
        mock_s3 = MagicMock()
        cli._s3_saver._client = mock_s3
        cli._s3_saver.bucket = "test-bucket"

        await cli._s3_saver.save_markdown("content", "output", context_id)

        mock_s3.put_object.assert_called_once()


@pytest.mark.integration
class TestS3ClientLazyLoading:
    """Integration tests for S3 client lazy loading behavior via S3ArtifactSaver."""

    def test_s3_client_not_created_on_init(self):
        """S3 client should not be created during __init__."""
        cli = ClaudeCLI(model="opus")
        # _s3_saver is created, but its internal _client should be None
        assert cli._s3_saver._client is None

    def test_s3_client_created_on_access(self):
        """S3 client should be created when accessed."""
        cli = ClaudeCLI(model="opus")

        with patch("turbowrap.utils.s3_artifact_saver.boto3") as mock_boto:
            mock_boto.client.return_value = MagicMock()
            _ = cli._s3_saver.client

            mock_boto.client.assert_called_once()

    def test_s3_client_cached(self):
        """S3 client should be cached after first access."""
        cli = ClaudeCLI(model="opus")

        with patch("turbowrap.utils.s3_artifact_saver.boto3") as mock_boto:
            mock_client = MagicMock()
            mock_boto.client.return_value = mock_client

            client1 = cli._s3_saver.client
            client2 = cli._s3_saver.client

            assert client1 is client2
            mock_boto.client.assert_called_once()


# =============================================================================
# Concurrency Scenarios
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
class TestConcurrencyScenarios:
    """Integration tests for concurrent execution scenarios."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_runs(self):
        """Multiple concurrent ClaudeCLI runs don't interfere."""
        results = []

        async def run_cli(index):
            with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:

                async def mock_exec(*args, **kwargs):
                    await asyncio.sleep(0.01)  # Simulate work
                    return (f"Output {index}", [], None, None, None, "test-session", set())

                mock_execute.side_effect = mock_exec

                with patch.object(
                    S3ArtifactSaver, "save_markdown", new_callable=AsyncMock
                ) as mock_s3:
                    mock_s3.return_value = None
                    cli = ClaudeCLI(model="opus")
                    result = await cli.run(
                        f"Prompt {index}", operation_type="test", repo_name="test-repo"
                    )
                    return (index, result.output)

        # Run 5 concurrent executions
        tasks = [run_cli(i) for i in range(5)]
        results = await asyncio.gather(*tasks)

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


# =============================================================================
# Timeout Scenarios
# =============================================================================


@pytest.mark.integration
class TestTimeoutScenarios:
    """Integration tests for timeout handling scenarios."""

    @pytest.mark.asyncio
    async def test_timeout_returns_proper_error(self):
        """Timeout returns structured error result."""
        with patch.object(ClaudeCLI, "_execute_cli") as mock_execute:
            mock_execute.return_value = (None, [], None, None, "Timeout after 5s", None, set())

            with patch.object(S3ArtifactSaver, "save_markdown", new_callable=AsyncMock) as mock_s3:
                mock_s3.return_value = None
                cli = ClaudeCLI(model="opus", timeout=5)
                result = await cli.run("Test", operation_type="test", repo_name="test-repo")

        assert result.success is False
        assert "Timeout" in result.error
        assert result.output == ""

    def test_different_timeout_values(self):
        """Different timeout values are properly configured."""
        cli_short = ClaudeCLI(model="opus", timeout=30)
        cli_long = ClaudeCLI(model="opus", timeout=600)

        assert cli_short.timeout == 30
        assert cli_long.timeout == 600


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
