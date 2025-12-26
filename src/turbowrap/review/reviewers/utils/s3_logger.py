"""
Centralized S3 logging for reviewer artifacts.

Handles:
- Prompts (input to LLM)
- Outputs (LLM response)
- Thinking (extended thinking)
- Reviews (full review with metadata)
- Challenges (challenger feedback)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)


@dataclass
class S3ArtifactMetadata:
    """Metadata for S3 artifact."""

    review_id: str
    component: str  # e.g., "reviewer_be", "challenger"
    model: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    extra: dict[str, Any] = field(default_factory=dict)


class S3Logger:
    """
    Centralized S3 logger for reviewer artifacts.

    Usage:
        s3_logger = S3Logger()

        # Save a review
        url = await s3_logger.save_review(
            system_prompt="...",
            user_prompt="...",
            response="...",
            review_json="...",
            metadata=S3ArtifactMetadata(...)
        )

        # Save thinking
        url = await s3_logger.save_thinking(content, metadata)

        # Save challenge
        url = await s3_logger.save_challenge(prompt, response, feedback_json, metadata)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.thinking.s3_bucket
        self.region = settings.thinking.s3_region
        self._client: S3Client | None = None

    @property
    def client(self) -> S3Client:
        """Lazy-load S3 client."""
        if self._client is None:
            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    @property
    def enabled(self) -> bool:
        """Check if S3 logging is enabled."""
        return bool(self.bucket)

    async def save_thinking(
        self,
        content: str,
        metadata: S3ArtifactMetadata,
        files_reviewed: int = 0,
    ) -> str | None:
        """Save extended thinking to S3."""
        if not self.enabled or not content:
            return None

        md_content = self._build_thinking_markdown(content, metadata, files_reviewed)
        return await self._upload(md_content, "thinking", metadata)

    async def save_review(
        self,
        system_prompt: str,
        user_prompt: str,
        response: str,
        review_json: str,
        metadata: S3ArtifactMetadata,
        duration_seconds: float = 0.0,
        files_reviewed: int = 0,
    ) -> str | None:
        """Save complete review artifact to S3."""
        if not self.enabled:
            return None

        md_content = self._build_review_markdown(
            system_prompt,
            user_prompt,
            response,
            review_json,
            metadata,
            duration_seconds,
            files_reviewed,
        )
        return await self._upload(md_content, "reviews", metadata)

    async def save_challenge(
        self,
        prompt: str,
        response: str,
        feedback_json: str,
        metadata: S3ArtifactMetadata,
        iteration: int = 1,
        satisfaction_score: float = 0.0,
        status: str = "UNKNOWN",
    ) -> str | None:
        """Save challenge artifact to S3."""
        if not self.enabled:
            return None

        md_content = self._build_challenge_markdown(
            prompt,
            response,
            feedback_json,
            metadata,
            iteration,
            satisfaction_score,
            status,
        )
        return await self._upload(md_content, "challenges", metadata, f"_iter{iteration}")

    async def _upload(
        self,
        content: str,
        prefix: str,
        metadata: S3ArtifactMetadata,
        suffix: str = "",
    ) -> str | None:
        """Upload content to S3."""
        try:
            timestamp = metadata.timestamp.strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"{prefix}/{timestamp}/{metadata.review_id}_{metadata.component}{suffix}.md"

            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )

            s3_url = f"s3://{self.bucket}/{s3_key}"
            logger.info(f"[S3_LOGGER] Saved to {s3_url}")
            return s3_url

        except ClientError as e:
            logger.warning(f"[S3_LOGGER] Upload failed: {e}")
            return None

    def _build_thinking_markdown(
        self,
        content: str,
        metadata: S3ArtifactMetadata,
        files_reviewed: int,
    ) -> str:
        return f"""# Extended Thinking - {metadata.component}

**Review ID**: {metadata.review_id}
**Timestamp**: {metadata.timestamp.isoformat()}
**Model**: {metadata.model}
**Files Reviewed**: {files_reviewed}

---

## Thinking Process

{content}
"""

    def _build_review_markdown(
        self,
        system_prompt: str,
        user_prompt: str,
        response: str,
        review_json: str,
        metadata: S3ArtifactMetadata,
        duration_seconds: float,
        files_reviewed: int,
    ) -> str:
        return f"""# Code Review - {metadata.component}

**Review ID**: {metadata.review_id}
**Timestamp**: {metadata.timestamp.isoformat()}
**Model**: {metadata.model}
**Files Reviewed**: {files_reviewed}
**Duration**: {duration_seconds:.2f}s

---

## System Prompt

```
{system_prompt}
```

---

## User Prompt

```
{user_prompt}
```

---

## Raw Response

```
{response}
```

---

## Parsed Review Output

```json
{review_json}
```
"""

    def _build_challenge_markdown(
        self,
        prompt: str,
        response: str,
        feedback_json: str,
        metadata: S3ArtifactMetadata,
        iteration: int,
        satisfaction_score: float,
        status: str,
    ) -> str:
        return f"""# Challenger Feedback - Iteration {iteration}

**Review ID**: {metadata.review_id}
**Timestamp**: {metadata.timestamp.isoformat()}
**Model**: {metadata.model}
**Satisfaction Score**: {satisfaction_score:.1f}%
**Status**: {status}

---

## Prompt

```
{prompt}
```

---

## Raw Response

```
{response}
```

---

## Parsed Feedback

```json
{feedback_json}
```
"""
