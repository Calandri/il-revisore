"""
Generic checkpoint manager for orchestrator state persistence.

Supports:
- S3 storage (production)
- Local file storage (development)
- Automatic serialization of Pydantic models
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from turbowrap.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class CheckpointManager(Generic[T]):
    """
    Generic checkpoint manager for orchestrator state persistence.

    Supports:
    - S3 storage (default for production)
    - Local file storage (for development/testing)
    - Automatic serialization of Pydantic models
    """

    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        prefix: str = "checkpoints/",
        use_local: bool = False,
        local_dir: Path | None = None,
    ):
        """
        Initialize checkpoint manager.

        Args:
            bucket: S3 bucket name (from settings if not provided)
            region: AWS region (from settings if not provided)
            prefix: S3 key prefix / local subdirectory
            use_local: Use local file storage instead of S3
            local_dir: Local directory for checkpoints (defaults to .checkpoints/)
        """
        settings = get_settings()
        self.bucket = bucket or settings.thinking.s3_bucket
        self.region = region or settings.thinking.s3_region
        self.prefix = prefix
        self.use_local = use_local
        self.local_dir = local_dir or Path(".checkpoints")
        self._client = None

    @property
    def s3_client(self) -> Any:
        """Lazy-load S3 client."""
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def _get_key(self, run_id: str, checkpoint_name: str) -> str:
        """Generate storage key for a checkpoint."""
        date_str = datetime.utcnow().strftime("%Y/%m/%d")
        return f"{self.prefix}{date_str}/{run_id}/{checkpoint_name}.json"

    async def save(
        self,
        run_id: str,
        checkpoint_name: str,
        data: T | dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Save checkpoint data.

        Args:
            run_id: Unique run identifier
            checkpoint_name: Name for this checkpoint (e.g., "reviewer_be_architecture")
            data: Pydantic model or dict to save
            metadata: Optional metadata to include

        Returns:
            Storage URI (s3:// or file://)
        """
        key = self._get_key(run_id, checkpoint_name)

        # Serialize data
        if isinstance(data, BaseModel):
            body = data.model_dump_json(indent=2)
        else:
            body = json.dumps(data, indent=2, default=str)

        # Add metadata wrapper if provided
        if metadata:
            wrapped = {
                "checkpoint": json.loads(body) if isinstance(body, str) else body,
                "metadata": {
                    "saved_at": datetime.utcnow().isoformat(),
                    "run_id": run_id,
                    "checkpoint_name": checkpoint_name,
                    **metadata,
                },
            }
            body = json.dumps(wrapped, indent=2, default=str)

        if self.use_local:
            return await self._save_local(key, body)
        return await self._save_s3(key, body)

    async def load(
        self,
        run_id: str,
        checkpoint_name: str,
        model_class: type[T] | None = None,
    ) -> T | dict[str, Any] | None:
        """
        Load checkpoint data.

        Args:
            run_id: Run identifier
            checkpoint_name: Checkpoint name
            model_class: Optional Pydantic model to deserialize into

        Returns:
            Deserialized checkpoint or None if not found
        """
        if self.use_local:
            content = await self._load_local(run_id, checkpoint_name)
        else:
            content = await self._load_s3(run_id, checkpoint_name)

        if content is None:
            return None

        # Handle wrapped format
        parsed: dict[str, Any] = json.loads(content)
        if "checkpoint" in parsed and "metadata" in parsed:
            parsed = parsed["checkpoint"]

        if model_class:
            return model_class.model_validate(parsed)
        return parsed

    async def _save_s3(self, key: str, body: str) -> str:
        """Save to S3."""
        logger.info(f"Saving checkpoint to s3://{self.bucket}/{key}")

        await asyncio.to_thread(
            self.s3_client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        return f"s3://{self.bucket}/{key}"

    async def _save_local(self, key: str, body: str) -> str:
        """Save to local file."""
        file_path = self.local_dir / key
        file_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving checkpoint to {file_path}")
        await asyncio.to_thread(file_path.write_text, body)
        return f"file://{file_path.absolute()}"

    async def _load_s3(self, run_id: str, checkpoint_name: str) -> str | None:
        """Load from S3 (searches for most recent)."""
        from botocore.exceptions import ClientError

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            latest_key = None
            latest_time = None

            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if run_id in key and checkpoint_name in key:
                        if latest_time is None or obj["LastModified"] > latest_time:
                            latest_key = key
                            latest_time = obj["LastModified"]

            if not latest_key:
                logger.debug(
                    f"No checkpoint found for run_id={run_id}, checkpoint={checkpoint_name}"
                )
                return None

            logger.info(f"Loading checkpoint from s3://{self.bucket}/{latest_key}")

            response = await asyncio.to_thread(
                self.s3_client.get_object,
                Bucket=self.bucket,
                Key=latest_key,
            )
            body: str = response["Body"].read().decode("utf-8")
            return body

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.error(f"S3 error loading checkpoint: {e}")
            raise

    async def _load_local(self, run_id: str, checkpoint_name: str) -> str | None:
        """Load from local file."""
        # Search for most recent checkpoint
        pattern = f"**/{run_id}/{checkpoint_name}.json"
        matches = list(self.local_dir.glob(pattern))

        if not matches:
            logger.debug(f"No checkpoint found for run_id={run_id}, checkpoint={checkpoint_name}")
            return None

        # Return most recent
        latest = max(matches, key=lambda p: p.stat().st_mtime)
        logger.info(f"Loading checkpoint from {latest}")
        return await asyncio.to_thread(latest.read_text)

    async def list_checkpoints(self, run_id: str) -> list[str]:
        """List all checkpoints for a run."""
        checkpoints = []

        if self.use_local:
            pattern = f"**/{run_id}/*.json"
            for path in self.local_dir.glob(pattern):
                checkpoints.append(path.stem)
        else:
            try:
                paginator = self.s3_client.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                    for obj in page.get("Contents", []):
                        if run_id in obj["Key"]:
                            name = obj["Key"].split("/")[-1].replace(".json", "")
                            if name not in checkpoints:
                                checkpoints.append(name)
            except Exception as e:
                logger.error(f"Error listing checkpoints: {e}")

        return checkpoints

    async def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        List recent runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run info dicts with run_id, started_at, checkpoints.
        """
        runs: dict[str, dict[str, Any]] = {}

        if self.use_local:
            # Scan local directory
            for path in self.local_dir.glob("**/*.json"):
                parts = path.relative_to(self.local_dir).parts
                if len(parts) >= 4:
                    run_id = parts[3]
                    if run_id not in runs:
                        runs[run_id] = {
                            "run_id": run_id,
                            "started_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                            "checkpoints": [],
                        }
                    checkpoint_name = path.stem
                    if checkpoint_name not in runs[run_id]["checkpoints"]:
                        runs[run_id]["checkpoints"].append(checkpoint_name)
        else:
            try:
                paginator = self.s3_client.get_paginator("list_objects_v2")

                for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                    for obj in page.get("Contents", []):
                        key = obj["Key"]
                        parts = key.replace(self.prefix, "").split("/")
                        if len(parts) >= 4:
                            # Format: YYYY/MM/DD/run_id/checkpoint.json
                            run_id = parts[3]
                            if run_id not in runs:
                                runs[run_id] = {
                                    "run_id": run_id,
                                    "started_at": obj["LastModified"].isoformat(),
                                    "checkpoints": [],
                                }
                            checkpoint_name = (
                                parts[4].replace(".json", "") if len(parts) > 4 else ""
                            )
                            if (
                                checkpoint_name
                                and checkpoint_name not in runs[run_id]["checkpoints"]
                            ):
                                runs[run_id]["checkpoints"].append(checkpoint_name)

            except Exception as e:
                logger.error(f"Error listing runs: {e}")
                return []

        # Sort by started_at descending
        sorted_runs = sorted(
            runs.values(),
            key=lambda x: x["started_at"],
            reverse=True,
        )

        return sorted_runs[:limit]
