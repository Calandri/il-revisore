"""Deployment status routes - GitHub Actions integration."""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, cast

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import get_settings
from ..services.operation_tracker import OperationType, get_tracker

logger = logging.getLogger(__name__)

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


async def _run_local_command(
    command: list[str],
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Run a command locally and wait for result.

    Args:
        command: Command as list of strings (no shell interpretation)
        timeout_seconds: Maximum execution time

    Returns:
        dict with status, stdout, stderr
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "status": "Timeout",
                "stdout": "",
                "stderr": f"Command timed out after {timeout_seconds}s",
            }

        return {
            "status": "Success" if process.returncode == 0 else "Failed",
            "returncode": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }

    except Exception as e:
        return {
            "status": "Error",
            "stdout": "",
            "stderr": str(e),
        }


async def _get_deployment_secrets() -> dict[str, str]:
    """Get secrets for Docker container deployment.

    Returns environment variables dict for docker run.
    """
    from ...utils.aws_secrets import get_secrets

    loop = asyncio.get_event_loop()
    secrets = await loop.run_in_executor(None, get_secrets)

    return {
        "ANTHROPIC_API_KEY": secrets.get("ANTHROPIC_API_KEY", ""),
        "TURBOWRAP_DB_URL": secrets.get("TURBOWRAP_DB_URL", ""),
        "GOOGLE_API_KEY": secrets.get("GOOGLE_API_KEY", ""),
        "GEMINI_API_KEY": secrets.get("GEMINI_API_KEY", ""),
        "GITHUB_TOKEN": secrets.get("GITHUB_TOKEN", ""),
    }


class StagingStatus(BaseModel):
    """Staging container status."""

    running: bool
    container_id: str | None = None
    image: str | None = None
    started_at: str | None = None


@router.get("/staging/status", response_model=StagingStatus)
async def get_staging_status() -> StagingStatus:
    """Check if staging container is running by hitting its health endpoint on port 8001."""
    try:
        # Try to reach staging container via HTTP (same host, port 8001)
        # Use the EC2 metadata service to get the instance's private IP,
        # or fall back to localhost (works if container network is host mode)
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try localhost first (works in most Docker setups via host network)
            response = await client.get("http://172.17.0.1:8001/api/status")
            if response.status_code == 200:
                return StagingStatus(running=True)
    except httpx.ConnectError:
        # Staging not running or not reachable
        return StagingStatus(running=False)
    except Exception as e:
        logger.debug(f"Staging check failed: {e}")
        return StagingStatus(running=False)

    return StagingStatus(running=False)


@router.post("/promote")
async def promote_to_production() -> dict[str, str]:
    """Switch staging to production.

    This stops the current production container and starts a new one
    from the latest ECR image (same as staging). Runs locally since
    TurboWrap API is on the same EC2 instance.
    """
    # First verify staging is running
    staging_status = await get_staging_status()
    if not staging_status.running:
        raise HTTPException(
            status_code=400,
            detail="No staging container running. Deploy first via GitHub Actions.",
        )

    logger.info("Promoting staging to production...")

    # Register with unified OperationTracker
    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.PROMOTE,
        operation_id=op_id,
        repo_name="il-revisore",  # The deployed app
        details={"action": "staging_to_production"},
    )

    try:
        # Step 1: Get secrets from AWS Secrets Manager
        logger.info("[PROMOTE] Fetching secrets...")
        secrets = await _get_deployment_secrets()

        if not secrets.get("TURBOWRAP_DB_URL"):
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve database URL from secrets",
            )

        # Step 2: Stop old production container
        logger.info("[PROMOTE] Stopping old production container...")
        result = await _run_local_command(
            ["docker", "stop", "turbowrap"],
            timeout_seconds=30,
        )
        logger.debug(f"docker stop turbowrap: {result['status']}")

        # Step 3: Remove old production container
        result = await _run_local_command(
            ["docker", "rm", "turbowrap"],
            timeout_seconds=10,
        )
        logger.debug(f"docker rm turbowrap: {result['status']}")

        # Step 4: Start new production container
        logger.info("[PROMOTE] Starting new production container...")
        docker_run_cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            "turbowrap",
            "-p",
            "8000:8000",
            "-v",
            "/data:/data",
            "-v",
            "/mnt/repos:/data/repos",
            "-e",
            f"TURBOWRAP_DB_URL={secrets['TURBOWRAP_DB_URL']}",
            "-e",
            f"ANTHROPIC_API_KEY={secrets['ANTHROPIC_API_KEY']}",
            "-e",
            f"GOOGLE_API_KEY={secrets['GOOGLE_API_KEY']}",
            "-e",
            f"GEMINI_API_KEY={secrets['GEMINI_API_KEY']}",
            "-e",
            f"GITHUB_TOKEN={secrets['GITHUB_TOKEN']}",
            "-e",
            "TURBOWRAP_AUTH_COGNITO_REGION=eu-west-3",
            "-e",
            "TURBOWRAP_AUTH_COGNITO_USER_POOL_ID=eu-west-3_01f2hPgzp",
            "-e",
            "TURBOWRAP_AUTH_COGNITO_APP_CLIENT_ID=6k2fu95una3arj8ql4371bkr75",
            "--restart",
            "unless-stopped",
            "198584570682.dkr.ecr.eu-west-3.amazonaws.com/turbowrap:latest",
        ]

        result = await _run_local_command(docker_run_cmd, timeout_seconds=60)

        if result["status"] != "Success":
            logger.error(f"[PROMOTE] Failed to start container: {result}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start production container: {result['stderr']}",
            )

        # Step 5: Cleanup staging container
        logger.info("[PROMOTE] Cleaning up staging container...")
        await _run_local_command(["docker", "stop", "turbowrap-staging"], timeout_seconds=30)
        await _run_local_command(["docker", "rm", "turbowrap-staging"], timeout_seconds=10)

        # Step 6: Verify production is running
        logger.info("[PROMOTE] Verifying production container...")
        await asyncio.sleep(3)  # Give container time to start

        result = await _run_local_command(
            ["docker", "ps", "--filter", "name=turbowrap", "--format", "{{.Names}}"],
            timeout_seconds=10,
        )

        if "turbowrap" not in result["stdout"]:
            raise HTTPException(
                status_code=500,
                detail="Production container failed to start",
            )

        logger.info("[PROMOTE] Promotion successful")

        # Clear deployment cache to force refresh
        _cache["data"] = None
        _cache["timestamp"] = 0

        # Mark operation as completed
        tracker.complete(op_id)

        return {
            "status": "ok",
            "message": "Production updated successfully",
            "output": "Container turbowrap started successfully",
        }

    except HTTPException as e:
        tracker.fail(op_id, error=str(e.detail))
        raise
    except Exception as e:
        logger.error(f"Error promoting to production: {e}")
        tracker.fail(op_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Promotion error: {str(e)}")
