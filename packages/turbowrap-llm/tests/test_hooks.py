"""Tests for hooks module (ArtifactSaver, OperationTracker)."""

import pytest

from turbowrap_llm.hooks import (
    NoOpArtifactSaver,
    NoOpOperationTracker,
)


class TestNoOpArtifactSaver:
    """Tests for NoOpArtifactSaver."""

    @pytest.mark.asyncio
    async def test_save_markdown_returns_none(self) -> None:
        """Test save_markdown returns None."""
        saver = NoOpArtifactSaver()

        result = await saver.save_markdown(
            content="test content",
            artifact_type="output",
            context_id="ctx-123",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_save_markdown_with_metadata(self) -> None:
        """Test save_markdown accepts metadata."""
        saver = NoOpArtifactSaver()

        result = await saver.save_markdown(
            content="test content",
            artifact_type="prompt",
            context_id="ctx-123",
            metadata={"model": "opus", "duration_ms": 1000},
        )

        assert result is None


class TestNoOpOperationTracker:
    """Tests for NoOpOperationTracker."""

    @pytest.mark.asyncio
    async def test_progress_no_op(self) -> None:
        """Test progress does nothing."""
        tracker = NoOpOperationTracker()

        # Should not raise
        await tracker.progress(
            operation_id="op-123",
            status="running",
            session_id="sess-456",
        )

    @pytest.mark.asyncio
    async def test_progress_with_all_params(self) -> None:
        """Test progress accepts all parameters."""
        tracker = NoOpOperationTracker()

        # Should not raise
        await tracker.progress(
            operation_id="op-123",
            status="completed",
            session_id="sess-456",
            error="test error",
            details={"duration_ms": 1000},
            publish_delay_ms=100,
        )


class TestCustomImplementations:
    """Tests for custom implementations of protocols."""

    @pytest.mark.asyncio
    async def test_custom_artifact_saver(self) -> None:
        """Test custom ArtifactSaver implementation."""
        saved_artifacts: list[dict] = []

        class MemoryArtifactSaver:
            async def save_markdown(
                self,
                content: str,
                artifact_type: str,
                context_id: str,
                metadata: dict | None = None,
            ) -> str | None:
                saved_artifacts.append(
                    {
                        "content": content,
                        "type": artifact_type,
                        "context_id": context_id,
                        "metadata": metadata,
                    }
                )
                return f"memory://{context_id}/{artifact_type}"

        saver = MemoryArtifactSaver()

        url = await saver.save_markdown(
            content="Hello World",
            artifact_type="output",
            context_id="test-123",
            metadata={"model": "opus"},
        )

        assert url == "memory://test-123/output"
        assert len(saved_artifacts) == 1
        assert saved_artifacts[0]["content"] == "Hello World"
        assert saved_artifacts[0]["metadata"] == {"model": "opus"}

    @pytest.mark.asyncio
    async def test_custom_operation_tracker(self) -> None:
        """Test custom OperationTracker implementation."""
        tracked_operations: dict[str, dict] = {}

        class MemoryOperationTracker:
            async def progress(
                self,
                operation_id: str,
                status: str,
                session_id: str | None = None,
                error: str | None = None,
                details: dict | None = None,
                publish_delay_ms: int = 0,
            ) -> None:
                tracked_operations[operation_id] = {
                    "status": status,
                    "session_id": session_id,
                    "error": error,
                    "details": details,
                }

        tracker = MemoryOperationTracker()

        await tracker.progress(
            operation_id="op-123",
            status="running",
            session_id="sess-456",
        )

        assert "op-123" in tracked_operations
        assert tracked_operations["op-123"]["status"] == "running"
        assert tracked_operations["op-123"]["session_id"] == "sess-456"

        # Update same operation (idempotent)
        await tracker.progress(
            operation_id="op-123",
            status="completed",
            session_id="sess-456",
            details={"duration_ms": 1000},
        )

        assert tracked_operations["op-123"]["status"] == "completed"
        assert tracked_operations["op-123"]["details"] == {"duration_ms": 1000}
