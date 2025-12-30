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

    # Default expiration for pre-signed URLs (7 days in seconds - S3 maximum)
    DEFAULT_URL_EXPIRATION = 7 * 24 * 60 * 60

    def __init__(
        self,
        bucket: str | None,
        region: str,
        prefix: str,
        url_expiration: int | None = None,
    ):
        """Initialize S3 artifact saver.

        Args:
            bucket: S3 bucket name (None to disable saving)
            region: AWS region
            prefix: S3 key prefix for artifacts
            url_expiration: Pre-signed URL expiration in seconds (default: 7 days)
        """
        self.bucket = bucket
        self.region = region
        self.prefix = prefix
        self.url_expiration = url_expiration or self.DEFAULT_URL_EXPIRATION
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

    def _generate_presigned_url(self, s3_key: str) -> str:
        """Generate a pre-signed URL for accessing a private S3 object.

        Args:
            s3_key: The S3 object key

        Returns:
            Pre-signed HTTPS URL that provides temporary authenticated access
        """
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=self.url_expiration,
        )

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
            # Generate pre-signed URL for authenticated browser access
            presigned_url = self._generate_presigned_url(s3_key)
            logger.info(f"[S3] Saved {artifact_type} to {s3_key}")
            return presigned_url
        except ClientError as e:
            logger.warning(f"[S3] Upload failed: {e}")
            return None

    async def save_raw(
        self,
        content: str,
        artifact_type: str,
        context_id: str,
    ) -> str | None:
        """Save raw content to S3 without any processing.

        Args:
            content: Raw content to save (no wrapping/formatting)
            artifact_type: Type of artifact (prompt, output, error)
            context_id: Identifier for grouping artifacts

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.bucket:
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
        s3_key = f"{self.prefix}/{timestamp}/{context_id}_{artifact_type}.jsonl"

        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            # Generate pre-signed URL for authenticated browser access
            presigned_url = self._generate_presigned_url(s3_key)
            logger.info(f"[S3] Saved raw {artifact_type} to {s3_key}")
            return presigned_url
        except ClientError as e:
            logger.warning(f"[S3] Raw upload failed: {e}")
            return None

    async def save_json(
        self,
        content: dict[str, Any],
        artifact_type: str,
        context_id: str,
    ) -> str | None:
        """Save JSON artifact to S3.

        Args:
            content: Dictionary to serialize as JSON
            artifact_type: Type of artifact (todo, config, etc.)
            context_id: Identifier for grouping artifacts

        Returns:
            S3 URL if successful, None otherwise
        """
        import json

        if not self.bucket:
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
        s3_key = f"{self.prefix}/{timestamp}/{context_id}_{artifact_type}.json"

        try:
            json_content = json.dumps(content, indent=2, ensure_ascii=False)
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=s3_key,
                Body=json_content.encode("utf-8"),
                ContentType="application/json",
            )
            # Generate pre-signed URL for authenticated browser access
            presigned_url = self._generate_presigned_url(s3_key)
            logger.info(f"[S3] Saved JSON {artifact_type} to {s3_key}")
            return presigned_url
        except ClientError as e:
            logger.warning(f"[S3] JSON upload failed: {e}")
            return None
