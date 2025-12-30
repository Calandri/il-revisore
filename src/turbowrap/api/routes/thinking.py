"""Thinking logs routes - fetch extended thinking from S3."""

import asyncio
from typing import Any

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException

from turbowrap.config import get_settings
from turbowrap.utils.aws_clients import get_s3_client as get_cached_s3_client

router = APIRouter(prefix="/thinking", tags=["thinking"])


def get_s3_client() -> Any:
    """Get S3 client with region from config."""
    settings = get_settings()
    return get_cached_s3_client(region=settings.thinking.s3_region)


@router.get("/{task_id}/{reviewer_name}")
async def get_thinking_log(
    task_id: str,
    reviewer_name: str,
) -> dict[str, Any]:
    """
    Fetch thinking log for a specific reviewer from S3.

    Args:
        task_id: The task ID (UUID)
        reviewer_name: The reviewer name (e.g., reviewer_be, reviewer_fe)

    Returns:
        Thinking content as markdown with metadata
    """
    settings = get_settings()

    if not settings.thinking.enabled:
        raise HTTPException(status_code=404, detail="Extended thinking is not enabled")

    # Search for the thinking file in S3
    # Format: thinking/{YYYY}/{MM}/{DD}/{HHMMSS}/{review_id}_{reviewer_name}.md
    # where review_id can be task_id or {reviewer_name}_{timestamp}
    try:
        s3_client = get_s3_client()

        # List objects with prefix to find the file
        paginator = s3_client.get_paginator("list_objects_v2")

        # Track exact match (with task_id) and fallback (any file for this reviewer)
        exact_match_key = None
        exact_match_time = None
        fallback_key = None
        fallback_time = None

        for page in paginator.paginate(
            Bucket=settings.thinking.s3_bucket,
            Prefix="thinking/",
        ):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                filename = key.split("/")[-1]

                # Check if this file is for the requested reviewer
                # Filename format: {something}_{reviewer_name}.md
                if not filename.endswith(f"_{reviewer_name}.md"):
                    continue

                # Check if it's an exact match for this task_id
                if task_id in key or task_id in filename:
                    if exact_match_time is None or obj["LastModified"] > exact_match_time:
                        exact_match_key = key
                        exact_match_time = obj["LastModified"]
                else:
                    # Fallback: any file for this reviewer (get most recent)
                    if fallback_time is None or obj["LastModified"] > fallback_time:
                        fallback_key = key
                        fallback_time = obj["LastModified"]

        # Prefer exact match, fall back to most recent for this reviewer
        found_key = exact_match_key or fallback_key

        if not found_key:
            raise HTTPException(
                status_code=404, detail=f"Thinking log not found for {reviewer_name}"
            )

        # Get the object content
        response = await asyncio.to_thread(
            s3_client.get_object,
            Bucket=settings.thinking.s3_bucket,
            Key=found_key,
        )

        content = response["Body"].read().decode("utf-8")

        return {
            "task_id": task_id,
            "reviewer_name": reviewer_name,
            "s3_key": found_key,
            "last_modified": response["LastModified"].isoformat(),
            "content": content,
        }

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "NoSuchBucket":
            raise HTTPException(status_code=503, detail="Thinking storage not available")
        raise HTTPException(status_code=500, detail=f"Failed to fetch thinking log: {str(e)}")


@router.get("/list/{review_id}")
async def list_thinking_logs(
    review_id: str,
) -> dict[str, Any]:
    """
    List all thinking logs for a review.

    Args:
        review_id: The review/task ID

    Returns:
        List of available thinking logs with metadata
    """
    settings = get_settings()

    if not settings.thinking.enabled:
        return {"logs": [], "enabled": False}

    try:
        s3_client = get_s3_client()

        logs = []
        paginator = s3_client.get_paginator("list_objects_v2")

        for page in paginator.paginate(
            Bucket=settings.thinking.s3_bucket,
            Prefix="thinking/",
        ):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Match any file containing the review_id
                if review_id in key and key.endswith(".md"):
                    # Extract reviewer name from filename
                    filename = key.split("/")[-1]
                    # Format: {review_id}_{reviewer_name}.md
                    parts = filename.replace(".md", "").split("_")
                    if len(parts) >= 2:
                        reviewer_name = "_".join(parts[1:])  # Handle reviewer_be etc
                        logs.append(
                            {
                                "reviewer_name": reviewer_name,
                                "s3_key": key,
                                "last_modified": obj["LastModified"].isoformat(),
                                "size_bytes": obj["Size"],
                            }
                        )

        return {"review_id": review_id, "logs": logs, "enabled": True}

    except ClientError as e:
        return {"review_id": review_id, "logs": [], "enabled": True, "error": str(e)}
