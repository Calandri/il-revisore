"""Protocol interfaces for extensibility.

This module defines Protocol classes that allow injecting custom implementations
for artifact saving and operation tracking without coupling to specific backends.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ArtifactSaver(Protocol):
    """Protocol for saving artifacts (prompts, outputs) to storage.

    Implementations can save to S3, local filesystem, or any other backend.
    """

    async def save_markdown(
        self,
        content: str,
        artifact_type: str,
        context_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Save markdown content.

        Args:
            content: Markdown content to save.
            artifact_type: Type of artifact (e.g., "prompt", "output").
            context_id: Unique identifier for the context/session.
            metadata: Optional metadata to include.

        Returns:
            URL or path to saved artifact, or None if save failed.
        """
        ...

    async def save_json(
        self,
        data: dict[str, Any],
        artifact_type: str,
        context_id: str,
    ) -> str | None:
        """Save JSON data.

        Args:
            data: Dictionary to save as JSON.
            artifact_type: Type of artifact.
            context_id: Unique identifier for the context/session.

        Returns:
            URL or path to saved artifact, or None if save failed.
        """
        ...


@runtime_checkable
class OperationTracker(Protocol):
    """Protocol for tracking CLI operations.

    Single idempotent function for all operation lifecycle events.
    Implementations can save to database, publish SSE events, etc.
    """

    async def progress(
        self,
        operation_id: str,
        status: str,
        *,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
        error: str | None = None,
        publish_delay_ms: int = 0,
    ) -> None:
        """Track operation progress (idempotent).

        This single function handles all lifecycle events:
        - status="running": Operation started
        - status="streaming": Receiving output
        - status="completed": Operation finished successfully
        - status="failed": Operation failed (include error)

        Args:
            operation_id: Unique operation identifier.
            status: Current status (running, streaming, completed, failed).
            session_id: CLI session ID (for resume capability).
            details: Additional details (tokens, cost, duration, etc.).
            error: Error message if status is "failed".
            publish_delay_ms: SSE publish delay (-1=never, 0=immediate, >0=debounce).
        """
        ...


class NoOpArtifactSaver:
    """No-op implementation of ArtifactSaver."""

    async def save_markdown(
        self,
        content: str,
        artifact_type: str,
        context_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        return None

    async def save_json(
        self,
        data: dict[str, Any],
        artifact_type: str,
        context_id: str,
    ) -> str | None:
        return None


class NoOpOperationTracker:
    """No-op implementation of OperationTracker."""

    async def progress(
        self,
        operation_id: str,
        status: str,
        *,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
        error: str | None = None,
        publish_delay_ms: int = 0,
    ) -> None:
        pass


# Optional S3 implementation (only available if boto3 is installed)
try:
    import boto3
    from botocore.exceptions import ClientError

    class S3ArtifactSaver:
        """S3 implementation of ArtifactSaver."""

        def __init__(
            self,
            bucket: str,
            region: str | None = None,
            prefix: str = "llm-artifacts",
        ):
            """Initialize S3 artifact saver.

            Args:
                bucket: S3 bucket name.
                region: AWS region (uses default if not specified).
                prefix: Key prefix for all artifacts.
            """
            self.bucket = bucket
            self.prefix = prefix
            kwargs = {"region_name": region} if region else {}
            self._client = boto3.client("s3", **kwargs)

        async def save_markdown(
            self,
            content: str,
            artifact_type: str,
            context_id: str,
            metadata: dict[str, Any] | None = None,
        ) -> str | None:
            """Save markdown to S3."""
            import asyncio

            key = f"{self.prefix}/{context_id}/{artifact_type}.md"
            try:
                await asyncio.to_thread(
                    self._client.put_object,
                    Bucket=self.bucket,
                    Key=key,
                    Body=content.encode("utf-8"),
                    ContentType="text/markdown",
                    Metadata={k: str(v) for k, v in (metadata or {}).items()},
                )
                # Generate presigned URL (1 hour expiry)
                url = self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=3600,
                )
                return url
            except ClientError:
                return None

        async def save_json(
            self,
            data: dict[str, Any],
            artifact_type: str,
            context_id: str,
        ) -> str | None:
            """Save JSON to S3."""
            import asyncio
            import json

            key = f"{self.prefix}/{context_id}/{artifact_type}.json"
            try:
                await asyncio.to_thread(
                    self._client.put_object,
                    Bucket=self.bucket,
                    Key=key,
                    Body=json.dumps(data, indent=2).encode("utf-8"),
                    ContentType="application/json",
                )
                url = self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=3600,
                )
                return url
            except ClientError:
                return None

except ImportError:
    # boto3 not installed, S3ArtifactSaver not available
    pass
