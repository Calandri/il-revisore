"""Deployment status routes - GitHub Actions integration."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Literal, cast

import boto3
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import get_settings

logger = logging.getLogger(__name__)

# AWS SSM config
AWS_REGION = "eu-west-3"
EC2_INSTANCE_ID = "i-02cac4811086c1f92"

router = APIRouter(prefix="/deployments", tags=["deployments"])

# Cache for GitHub API responses (avoid rate limits)
_cache: dict[str, Any] = {"data": None, "timestamp": 0}
CACHE_TTL_SECONDS = 30

# GitHub repo info
GITHUB_OWNER = "Calandri"
GITHUB_REPO = "il-revisore"
WORKFLOW_NAME = "Deploy to AWS"


class DeploymentRun(BaseModel):
    """Single deployment run."""

    id: int
    commit_sha: str
    commit_short: str
    commit_message: str | None  # First line of commit message
    commit_url: str  # Link to GitHub commit page
    status: Literal["queued", "in_progress", "completed"]
    conclusion: Literal["success", "failure", "cancelled", "skipped", "timed_out"] | None
    started_at: str | None
    completed_at: str | None
    duration_seconds: int | None
    time_ago: str
    html_url: str  # Link to GitHub Actions run


class DeploymentStatus(BaseModel):
    """Complete deployment status."""

    current: DeploymentRun | None  # Most recent successful deploy
    in_progress: DeploymentRun | None  # Currently running deploy
    recent: list[DeploymentRun]  # Last 5 deploys
    last_updated: str


def _time_ago(dt_str: str | None) -> str:
    """Convert ISO datetime to 'time ago' string."""
    if not dt_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt

        seconds = delta.total_seconds()
        if seconds < 60:
            return f"{int(seconds)}s fa"
        minutes = seconds / 60
        if minutes < 60:
            return f"{int(minutes)}m fa"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h fa"
        days = hours / 24
        if days < 7:
            return f"{int(days)}d fa"
        weeks = days / 7
        return f"{int(weeks)}w fa"
    except Exception:
        return "N/A"


def _parse_run(run: dict[str, Any]) -> DeploymentRun:
    """Parse GitHub Actions run to DeploymentRun."""
    started_at = run.get("run_started_at") or run.get("created_at")
    completed_at = run.get("updated_at") if run.get("status") == "completed" else None

    duration = None
    if started_at and completed_at:
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            duration = int((end - start).total_seconds())
        except Exception:
            pass

    commit_sha = run.get("head_sha", "unknown")

    # Extract commit message (first line only)
    head_commit = run.get("head_commit", {})
    commit_message = head_commit.get("message", "")
    if commit_message:
        commit_message = commit_message.split("\n")[0][:80]  # First line, max 80 chars

    # Build commit URL
    commit_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/commit/{commit_sha}"

    return DeploymentRun(
        id=run["id"],
        commit_sha=commit_sha,
        commit_short=commit_sha[:7],
        commit_message=commit_message or None,
        commit_url=commit_url,
        status=run["status"],
        conclusion=run.get("conclusion"),
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration,
        time_ago=_time_ago(started_at),
        html_url=run.get("html_url", ""),
    )


async def _fetch_deployments() -> DeploymentStatus:
    """Fetch deployment status from GitHub Actions API."""
    settings = get_settings()

    if not settings.agents.github_token:
        raise HTTPException(status_code=503, detail="GitHub token not configured")

    # Check cache
    now = time.time()
    cached_data = _cache["data"]
    if cached_data is not None and (now - _cache["timestamp"]) < CACHE_TTL_SECONDS:
        return cast(DeploymentStatus, cached_data)

    headers = {
        "Authorization": f"Bearer {settings.agents.github_token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/runs"
    params: dict[str, str | int] = {
        "per_page": 10,
        "event": "push",  # Only push-triggered deploys
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers, params=params)

        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid GitHub token")
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Repository not found")
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code, detail=f"GitHub API error: {response.text}"
            )

        data = response.json()

    # Filter for deploy workflow only
    deploy_runs = [run for run in data.get("workflow_runs", []) if run.get("name") == WORKFLOW_NAME]

    # Parse runs
    parsed_runs = [_parse_run(run) for run in deploy_runs[:10]]

    # Find current (most recent successful) and in-progress
    current = None
    in_progress = None
    recent = []

    for run in parsed_runs:
        if run.status == "in_progress" and not in_progress:
            in_progress = run
        elif run.status == "completed" and run.conclusion == "success" and not current:
            current = run
        recent.append(run)

    result = DeploymentStatus(
        current=current,
        in_progress=in_progress,
        recent=recent[:5],
        last_updated=datetime.now(timezone.utc).isoformat(),
    )

    # Update cache
    _cache["data"] = result
    _cache["timestamp"] = now

    return result


@router.get("/status", response_model=DeploymentStatus)
async def get_deployment_status() -> DeploymentStatus:
    """Get current deployment status and recent history."""
    return await _fetch_deployments()


@router.get("/current")
async def get_current_deployment() -> dict[str, Any]:
    """Get just the current production deployment info."""
    status = await _fetch_deployments()
    return {
        "current": status.current,
        "in_progress": status.in_progress is not None,
    }


@router.post("/trigger")
async def trigger_deployment() -> dict[str, str]:
    """Trigger a new deployment via workflow_dispatch."""
    settings = get_settings()

    if not settings.agents.github_token:
        raise HTTPException(status_code=503, detail="GitHub token not configured")

    headers = {
        "Authorization": f"Bearer {settings.agents.github_token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Trigger workflow_dispatch on main branch
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/deploy.yml/dispatches"
    payload = {"ref": "main"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code == 204:
            # Clear cache to force refresh
            _cache["data"] = None
            _cache["timestamp"] = 0
            return {"status": "ok", "message": "Deploy triggered successfully"}
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Workflow not found")
        raise HTTPException(
            status_code=response.status_code, detail=f"Failed to trigger deploy: {response.text}"
        )


@router.post("/rollback/{commit_sha}")
async def rollback_to_commit(commit_sha: str) -> dict[str, str]:
    """Rollback to a specific commit by triggering a deploy with that SHA.

    Note: This requires the workflow to support workflow_dispatch with inputs,
    or we can use the GitHub API to create a deployment.
    For now, this is a placeholder that shows how it would work.
    """
    settings = get_settings()

    if not settings.agents.github_token:
        raise HTTPException(status_code=503, detail="GitHub token not configured")

    # Validate commit SHA format
    if len(commit_sha) < 7 or len(commit_sha) > 40:
        raise HTTPException(status_code=400, detail="Invalid commit SHA")

    headers = {
        "Authorization": f"Bearer {settings.agents.github_token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # For rollback, we trigger workflow_dispatch with the specific ref
    # This requires modifying the workflow to accept workflow_dispatch
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/deploy.yml/dispatches"
    payload = {"ref": commit_sha}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code == 204:
            # Clear cache to force refresh
            _cache["data"] = None
            _cache["timestamp"] = 0
            return {
                "status": "ok",
                "message": f"Rollback to {commit_sha[:7]} triggered successfully",
            }
        if response.status_code == 422:
            raise HTTPException(
                status_code=422,
                detail="Cannot rollback - commit not found or workflow doesn't support this ref",
            )
        raise HTTPException(
            status_code=response.status_code, detail=f"Failed to trigger rollback: {response.text}"
        )


async def _run_ssm_command(commands: list[str], timeout_seconds: int = 30) -> dict[str, Any]:
    """Run commands on EC2 via SSM and wait for result."""
    loop = asyncio.get_event_loop()

    def _execute():
        ssm = boto3.client("ssm", region_name=AWS_REGION)

        # Send command
        response = ssm.send_command(
            InstanceIds=[EC2_INSTANCE_ID],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
        )
        command_id = response["Command"]["CommandId"]

        # Wait for completion
        for _ in range(timeout_seconds):
            time.sleep(1)
            try:
                result = ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=EC2_INSTANCE_ID,
                )
                status = result["Status"]
                if status in ("Success", "Failed", "Cancelled", "TimedOut"):
                    return {
                        "status": status,
                        "stdout": result.get("StandardOutputContent", ""),
                        "stderr": result.get("StandardErrorContent", ""),
                    }
            except ssm.exceptions.InvocationDoesNotExist:
                continue

        return {"status": "Timeout", "stdout": "", "stderr": "Command timed out"}

    return await loop.run_in_executor(None, _execute)


class StagingStatus(BaseModel):
    """Staging container status."""

    running: bool
    container_id: str | None = None
    image: str | None = None
    started_at: str | None = None


@router.get("/staging/status", response_model=StagingStatus)
async def get_staging_status() -> StagingStatus:
    """Check if staging container (turbowrap-staging) is running on port 8001."""
    try:
        result = await _run_ssm_command(
            [
                'docker ps --filter "name=turbowrap-staging" --format "{{.ID}}|{{.Image}}|{{.CreatedAt}}" | head -1'
            ],
            timeout_seconds=15,
        )

        if result["status"] != "Success":
            logger.warning(f"SSM command failed: {result}")
            return StagingStatus(running=False)

        output = result["stdout"].strip()
        if not output:
            return StagingStatus(running=False)

        parts = output.split("|")
        if len(parts) >= 3:
            return StagingStatus(
                running=True,
                container_id=parts[0],
                image=parts[1],
                started_at=parts[2],
            )

        return StagingStatus(running=True, container_id=parts[0] if parts else None)

    except Exception as e:
        logger.error(f"Error checking staging status: {e}")
        return StagingStatus(running=False)


@router.post("/promote")
async def promote_to_production() -> dict[str, str]:
    """Switch staging to production via SSM.

    This stops the current production container and starts a new one
    from the latest ECR image (same as staging).
    """
    # First verify staging is running
    staging_status = await get_staging_status()
    if not staging_status.running:
        raise HTTPException(
            status_code=400,
            detail="No staging container running. Deploy first via GitHub Actions.",
        )

    logger.info("Promoting staging to production...")

    # Commands to switch - get secrets and start new production container
    commands = [
        "set -e",
        "echo === PROMOTING STAGING TO PRODUCTION ===",
        # Get secrets
        "SECRETS=$(aws secretsmanager get-secret-value --secret-id agent-zero/global/api-keys --region eu-west-3 --query SecretString --output text)",
        'ANTHROPIC_KEY=$(echo $SECRETS | jq -r .ANTHROPIC_API_KEY)',
        'DB_URL=$(echo $SECRETS | jq -r .TURBOWRAP_DB_URL)',
        'GOOGLE_KEY=$(echo $SECRETS | jq -r .GOOGLE_API_KEY)',
        'GEMINI_KEY=$(echo $SECRETS | jq -r .GEMINI_API_KEY)',
        'GITHUB_TOKEN=$(echo $SECRETS | jq -r .GITHUB_TOKEN)',
        # Stop old production
        "echo Stopping old production...",
        "docker stop turbowrap 2>/dev/null || true",
        "docker rm turbowrap 2>/dev/null || true",
        # Start new production from latest image
        "echo Starting new production...",
        'docker run -d --name turbowrap -p 8000:8000 -v /data:/data -v /mnt/repos:/data/repos -e TURBOWRAP_DB_URL="$DB_URL" -e ANTHROPIC_API_KEY="$ANTHROPIC_KEY" -e GOOGLE_API_KEY="$GOOGLE_KEY" -e GEMINI_API_KEY="$GEMINI_KEY" -e GITHUB_TOKEN="$GITHUB_TOKEN" -e TURBOWRAP_AUTH_COGNITO_REGION=eu-west-3 -e TURBOWRAP_AUTH_COGNITO_USER_POOL_ID=eu-west-3_01f2hPgzp -e TURBOWRAP_AUTH_COGNITO_APP_CLIENT_ID=6k2fu95una3arj8ql4371bkr75 --restart unless-stopped 198584570682.dkr.ecr.eu-west-3.amazonaws.com/turbowrap:latest',
        # Cleanup staging
        "echo Cleaning up staging...",
        "docker stop turbowrap-staging 2>/dev/null || true",
        "docker rm turbowrap-staging 2>/dev/null || true",
        # Verify
        "echo Verifying...",
        "sleep 3",
        "docker ps | grep turbowrap",
        "echo === PROMOTION COMPLETE ===",
    ]

    try:
        result = await _run_ssm_command(commands, timeout_seconds=60)

        if result["status"] == "Success":
            logger.info("Promotion successful")
            # Clear deployment cache to force refresh
            _cache["data"] = None
            _cache["timestamp"] = 0
            return {
                "status": "ok",
                "message": "Production updated successfully",
                "output": result["stdout"],
            }
        else:
            logger.error(f"Promotion failed: {result}")
            raise HTTPException(
                status_code=500,
                detail=f"Promotion failed: {result['stderr'] or result['stdout']}",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error promoting to production: {e}")
        raise HTTPException(status_code=500, detail=f"Promotion error: {str(e)}")
