"""S3 checkpoint manager for saving and loading step checkpoints."""

import asyncio
import logging
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from ..config import get_autoupdate_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class S3CheckpointManager:
    """Manages upload/download of checkpoints to S3."""

    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        prefix: str | None = None,
    ):
        """Initialize S3 checkpoint manager.

        Args:
            bucket: S3 bucket name. Defaults to config value.
            region: AWS region. Defaults to config value.
            prefix: S3 key prefix. Defaults to config value.
        """
        settings = get_autoupdate_settings()
        self.bucket = bucket or settings.s3_bucket
        self.region = region or settings.s3_region
        self.prefix = prefix or settings.s3_prefix
        self._client = None

    @property
    def client(self):
        """Lazy-load S3 client."""
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def _get_key(self, run_id: str, step_name: str) -> str:
        """Generate S3 key for a checkpoint.

        Args:
            run_id: Unique run identifier.
            step_name: Step name (e.g., 'step1_analyze').

        Returns:
            S3 key path.
        """
        now = datetime.utcnow()
        return f"{self.prefix}{now.strftime('%Y/%m/%d')}/{run_id}/{step_name}.json"

    async def save(
        self,
        run_id: str,
        step_name: str,
        checkpoint: BaseModel,
    ) -> str:
        """Save checkpoint to S3.

        Args:
            run_id: Unique run identifier.
            step_name: Step name.
            checkpoint: Pydantic model to save.

        Returns:
            S3 URI of saved checkpoint.
        """
        key = self._get_key(run_id, step_name)
        body = checkpoint.model_dump_json(indent=2)

        logger.info(f"Saving checkpoint to s3://{self.bucket}/{key}")

        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )

        return f"s3://{self.bucket}/{key}"

    async def load(
        self,
        run_id: str,
        step_name: str,
        model_class: type[T],
    ) -> T | None:
        """Load checkpoint from S3.

        Args:
            run_id: Unique run identifier.
            step_name: Step name.
            model_class: Pydantic model class to deserialize into.

        Returns:
            Deserialized checkpoint or None if not found.
        """
        from botocore.exceptions import ClientError

        # Search for the most recent checkpoint for this run/step
        prefix = f"{self.prefix}"

        try:
            paginator = self.client.get_paginator("list_objects_v2")
            latest_key = None
            latest_time = None

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if run_id in key and step_name in key:
                        if latest_time is None or obj["LastModified"] > latest_time:
                            latest_key = key
                            latest_time = obj["LastModified"]

            if not latest_key:
                logger.debug(f"No checkpoint found for run_id={run_id}, step={step_name}")
                return None

            logger.info(f"Loading checkpoint from s3://{self.bucket}/{latest_key}")

            response = await asyncio.to_thread(
                self.client.get_object,
                Bucket=self.bucket,
                Key=latest_key,
            )

            content = response["Body"].read().decode("utf-8")
            return model_class.model_validate_json(content)

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.error(f"S3 error loading checkpoint: {e}")
            raise

    async def list_runs(self, limit: int = 10) -> list[dict]:
        """List recent auto-update runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run info dicts with run_id, started_at, status.
        """
        runs: dict[str, dict] = {}

        try:
            paginator = self.client.get_paginator("list_objects_v2")

            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    parts = key.replace(self.prefix, "").split("/")
                    if len(parts) >= 4:
                        # Format: YYYY/MM/DD/run_id/step.json
                        run_id = parts[3]
                        if run_id not in runs:
                            runs[run_id] = {
                                "run_id": run_id,
                                "started_at": obj["LastModified"].isoformat(),
                                "steps_completed": [],
                            }
                        step_name = parts[4].replace(".json", "") if len(parts) > 4 else ""
                        if step_name and step_name not in runs[run_id]["steps_completed"]:
                            runs[run_id]["steps_completed"].append(step_name)

            # Sort by started_at descending
            sorted_runs = sorted(
                runs.values(),
                key=lambda x: x["started_at"],
                reverse=True,
            )

            return sorted_runs[:limit]

        except Exception as e:
            logger.error(f"Error listing runs: {e}")
            return []

    async def get_run_status(self, run_id: str) -> dict | None:
        """Get status of a specific run.

        Args:
            run_id: Run identifier.

        Returns:
            Run status dict or None if not found.
        """
        from ..models import (
            Step1Checkpoint,
            Step2Checkpoint,
            Step3Checkpoint,
            Step4Checkpoint,
        )

        step_models = {
            "step1_analyze": Step1Checkpoint,
            "step2_research": Step2Checkpoint,
            "step3_evaluate": Step3Checkpoint,
            "step4_create_issues": Step4Checkpoint,
        }

        status = {
            "run_id": run_id,
            "steps": {},
            "current_step": None,
            "completed": False,
        }

        for step_name, model_class in step_models.items():
            checkpoint = await self.load(run_id, step_name, model_class)
            if checkpoint:
                status["steps"][step_name] = {
                    "status": checkpoint.status.value,
                    "started_at": checkpoint.started_at.isoformat(),
                    "completed_at": (
                        checkpoint.completed_at.isoformat() if checkpoint.completed_at else None
                    ),
                    "error": checkpoint.error,
                }

        # Determine current step
        step_order = ["step1_analyze", "step2_research", "step3_evaluate", "step4_create_issues"]
        for i, step_name in enumerate(step_order):
            step_info = status["steps"].get(step_name)
            if step_info is None:
                status["current_step"] = i + 1
                break
            if step_info["status"] in ["pending", "in_progress", "failed"]:
                status["current_step"] = i + 1
                break
        else:
            status["completed"] = True
            status["current_step"] = 4

        return status if status["steps"] else None
