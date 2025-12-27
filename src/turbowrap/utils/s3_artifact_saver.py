"""Unified S3 artifact saving for CLI runners.

Provides a centralized async S3 saver with lazy client loading,
eliminating code duplication across ClaudeCLI and GeminiCLI.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3ArtifactSaver:
    """Async S3 artifact saver with lazy client loading.

    Usage:
        saver = S3ArtifactSaver(bucket="my-bucket", region="us-east-1", prefix="cli-logs")
        url = await saver.save_markdown(content, "output", "context_123", {"model": "opus"})
    """

    def __init__(self, bucket: str | None, region: str, prefix: str):
        """Initialize S3 artifact saver.

        Args:
            bucket: S3 bucket name (None to disable saving)
            region: AWS region
            prefix: S3 key prefix for artifacts
        """
        self.bucket = bucket
        self.region = region
        self.prefix = prefix
        self._client: Any = None
        self._bucket_region: str | None = None

    @property
    def client(self) -> Any:
        """Lazy-load S3 client."""
        if self._client is None:
            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def _get_bucket_region(self) -> str:
        """Get the actual bucket region from S3 (may differ from configured region)."""
        if self._bucket_region is None:
            try:
                response = self.client.get_bucket_location(Bucket=self.bucket)
                # get_bucket_location returns None for us-east-1
                self._bucket_region = response.get("LocationConstraint") or "us-east-1"
            except ClientError:
                self._bucket_region = self.region
        return self._bucket_region

    async def save_markdown(
        self,
        content: str,
        artifact_type: str,
        context_id: str,
        metadata: dict[str, Any] | None = None,
        source_name: str = "CLI",
    ) -> str | None:
        """Save markdown artifact to S3.

        Args:
            content: Content to save
            artifact_type: Type of artifact (prompt, output, error)
            context_id: Identifier for grouping artifacts
            metadata: Optional metadata (model, duration_ms, etc.)
            source_name: Source identifier for markdown header

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.bucket:
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
        s3_key = f"{self.prefix}/{timestamp}/{context_id}_{artifact_type}.md"

        model = metadata.get("model", "unknown") if metadata else "unknown"
        md_content = f"""# {source_name} {artifact_type.title()}

**Context ID**: {context_id}
**Timestamp**: {datetime.now(timezone.utc).isoformat()}
**Artifact Type**: {artifact_type}
**Model**: {model}

---

## Content

```
{content}
```
"""

        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=s3_key,
                Body=md_content.encode("utf-8"),
                ContentType="text/markdown",
            )
            # Use HTTPS URL for browser access (get actual bucket region from S3)
            bucket_region = self._get_bucket_region()
            s3_url = f"https://{self.bucket}.s3.{bucket_region}.amazonaws.com/{s3_key}"
            logger.info(f"[S3] Saved {artifact_type} to {s3_key}")
            return s3_url
        except ClientError as e:
            logger.warning(f"[S3] Upload failed: {e}")
            return None
