"""GitHub integration routes - Pull Requests and Issues."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from github import Auth, Github, GithubException
from pydantic import BaseModel

from ...config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


def _get_github_client() -> Github:
    """Get authenticated GitHub client."""
    settings = get_settings()
    if not settings.agents.github_token:
        raise HTTPException(status_code=503, detail="GitHub token not configured")
    auth = Auth.Token(settings.agents.github_token)
    return Github(auth=auth)


def _time_ago(dt: datetime | None) -> str:
    """Convert datetime to 'time ago' string."""
    if not dt:
        return "N/A"
    try:
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt

        seconds = delta.total_seconds()
        if seconds < 60:
            return f"{int(seconds)}s ago"
        minutes = seconds / 60
        if minutes < 60:
            return f"{int(minutes)}m ago"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h ago"
        days = hours / 24
        if days < 7:
            return f"{int(days)}d ago"
        weeks = days / 7
        return f"{int(weeks)}w ago"
    except Exception:
        return "N/A"


# --- Models ---


class PullRequestInfo(BaseModel):
    """Pull request information."""

    number: int
    title: str
    state: str  # open, closed
    draft: bool
    user: str
    user_avatar: str | None
    created_at: str
    updated_at: str
    time_ago: str
    merged: bool
    mergeable: bool | None
    head_branch: str
    base_branch: str
    additions: int
    deletions: int
    changed_files: int
    html_url: str
    labels: list[str]


class PullRequestDetail(PullRequestInfo):
    """Detailed pull request information."""

    body: str | None
    commits: int
    comments: int
    review_comments: int
    mergeable_state: str | None


class CreatePRRequest(BaseModel):
    """Request to create a pull request."""

    title: str
    body: str | None = None
    head: str  # branch name
    base: str = "main"
    draft: bool = False


class IssueInfo(BaseModel):
    """Issue information."""

    number: int
    title: str
    state: str  # open, closed
    user: str
    user_avatar: str | None
    created_at: str
    updated_at: str
    time_ago: str
    html_url: str
    labels: list[str]
    comments: int


class IssueDetail(IssueInfo):
    """Detailed issue information."""

    body: str | None


class CreateIssueRequest(BaseModel):
    """Request to create an issue."""

    title: str
    body: str | None = None
    labels: list[str] | None = None


class WorkflowRun(BaseModel):
    """GitHub Actions workflow run."""

    id: int
    name: str
    status: str
    conclusion: str | None
    created_at: str
    updated_at: str
    time_ago: str
    html_url: str
    head_branch: str
    head_sha: str


# --- Pull Requests ---


@router.get("/repos/{owner}/{repo}/pulls")
def list_pull_requests(
    owner: str,
    repo: str,
    state: str = Query(default="open", regex="^(open|closed|all)$"),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[PullRequestInfo]:
    """List pull requests for a repository."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")
        pulls = repository.get_pulls(state=state, sort="updated", direction="desc")

        result = []
        for pr in pulls[:limit]:
            result.append(
                PullRequestInfo(
                    number=pr.number,
                    title=pr.title,
                    state=pr.state,
                    draft=pr.draft,
                    user=pr.user.login if pr.user else "unknown",
                    user_avatar=pr.user.avatar_url if pr.user else None,
                    created_at=pr.created_at.isoformat() if pr.created_at else "",
                    updated_at=pr.updated_at.isoformat() if pr.updated_at else "",
                    time_ago=_time_ago(pr.updated_at),
                    merged=pr.merged,
                    mergeable=pr.mergeable,
                    head_branch=pr.head.ref if pr.head else "",
                    base_branch=pr.base.ref if pr.base else "",
                    additions=pr.additions,
                    deletions=pr.deletions,
                    changed_files=pr.changed_files,
                    html_url=pr.html_url,
                    labels=[label.name for label in pr.labels],
                )
            )
        return result

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Repository not found")
        if e.status == 401:
            raise HTTPException(status_code=401, detail="Invalid GitHub token")
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()


@router.get("/repos/{owner}/{repo}/pulls/{number}")
def get_pull_request(owner: str, repo: str, number: int) -> PullRequestDetail:
    """Get detailed information about a pull request."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(number)

        return PullRequestDetail(
            number=pr.number,
            title=pr.title,
            state=pr.state,
            draft=pr.draft,
            user=pr.user.login if pr.user else "unknown",
            user_avatar=pr.user.avatar_url if pr.user else None,
            created_at=pr.created_at.isoformat() if pr.created_at else "",
            updated_at=pr.updated_at.isoformat() if pr.updated_at else "",
            time_ago=_time_ago(pr.updated_at),
            merged=pr.merged,
            mergeable=pr.mergeable,
            head_branch=pr.head.ref if pr.head else "",
            base_branch=pr.base.ref if pr.base else "",
            additions=pr.additions,
            deletions=pr.deletions,
            changed_files=pr.changed_files,
            html_url=pr.html_url,
            labels=[label.name for label in pr.labels],
            body=pr.body,
            commits=pr.commits,
            comments=pr.comments,
            review_comments=pr.review_comments,
            mergeable_state=pr.mergeable_state,
        )

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Pull request not found")
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()


@router.post("/repos/{owner}/{repo}/pulls")
def create_pull_request(owner: str, repo: str, request: CreatePRRequest) -> PullRequestInfo:
    """Create a new pull request."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")

        pr = repository.create_pull(
            title=request.title,
            body=request.body or "",
            head=request.head,
            base=request.base,
            draft=request.draft,
        )

        return PullRequestInfo(
            number=pr.number,
            title=pr.title,
            state=pr.state,
            draft=pr.draft,
            user=pr.user.login if pr.user else "unknown",
            user_avatar=pr.user.avatar_url if pr.user else None,
            created_at=pr.created_at.isoformat() if pr.created_at else "",
            updated_at=pr.updated_at.isoformat() if pr.updated_at else "",
            time_ago=_time_ago(pr.updated_at),
            merged=pr.merged,
            mergeable=pr.mergeable,
            head_branch=pr.head.ref if pr.head else "",
            base_branch=pr.base.ref if pr.base else "",
            additions=pr.additions,
            deletions=pr.deletions,
            changed_files=pr.changed_files,
            html_url=pr.html_url,
            labels=[label.name for label in pr.labels],
        )

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        if e.status == 422:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot create PR: {e.data.get('errors', [{}])[0].get('message', str(e))}",
            )
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()


@router.post("/repos/{owner}/{repo}/pulls/{number}/merge")
def merge_pull_request(
    owner: str,
    repo: str,
    number: int,
    merge_method: str = Query(default="merge", regex="^(merge|squash|rebase)$"),
) -> dict[str, Any]:
    """Merge a pull request."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(number)

        if pr.merged:
            raise HTTPException(status_code=400, detail="PR is already merged")

        if not pr.mergeable:
            raise HTTPException(status_code=400, detail="PR is not mergeable")

        result = pr.merge(merge_method=merge_method)

        return {
            "merged": result.merged,
            "sha": result.sha,
            "message": result.message,
        }

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        if e.status == 405:
            raise HTTPException(status_code=405, detail="Merge not allowed")
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()


# --- Issues ---


@router.get("/repos/{owner}/{repo}/issues")
def list_issues(
    owner: str,
    repo: str,
    state: str = Query(default="open", regex="^(open|closed|all)$"),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[IssueInfo]:
    """List issues for a repository (excludes PRs)."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")
        issues = repository.get_issues(state=state, sort="updated", direction="desc")

        result = []
        for issue in issues[:limit]:
            # Skip PRs (GitHub API returns PRs as issues too)
            if issue.pull_request is not None:
                continue

            result.append(
                IssueInfo(
                    number=issue.number,
                    title=issue.title,
                    state=issue.state,
                    user=issue.user.login if issue.user else "unknown",
                    user_avatar=issue.user.avatar_url if issue.user else None,
                    created_at=issue.created_at.isoformat() if issue.created_at else "",
                    updated_at=issue.updated_at.isoformat() if issue.updated_at else "",
                    time_ago=_time_ago(issue.updated_at),
                    html_url=issue.html_url,
                    labels=[label.name for label in issue.labels],
                    comments=issue.comments,
                )
            )
        return result

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Repository not found")
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()


@router.get("/repos/{owner}/{repo}/issues/{number}")
def get_issue(owner: str, repo: str, number: int) -> IssueDetail:
    """Get detailed information about an issue."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")
        issue = repository.get_issue(number)

        if issue.pull_request is not None:
            raise HTTPException(status_code=404, detail="This is a pull request, not an issue")

        return IssueDetail(
            number=issue.number,
            title=issue.title,
            state=issue.state,
            user=issue.user.login if issue.user else "unknown",
            user_avatar=issue.user.avatar_url if issue.user else None,
            created_at=issue.created_at.isoformat() if issue.created_at else "",
            updated_at=issue.updated_at.isoformat() if issue.updated_at else "",
            time_ago=_time_ago(issue.updated_at),
            html_url=issue.html_url,
            labels=[label.name for label in issue.labels],
            comments=issue.comments,
            body=issue.body,
        )

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Issue not found")
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()


@router.post("/repos/{owner}/{repo}/issues")
def create_issue(owner: str, repo: str, request: CreateIssueRequest) -> IssueInfo:
    """Create a new issue."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")

        issue = repository.create_issue(
            title=request.title,
            body=request.body or "",
            labels=request.labels or [],
        )

        return IssueInfo(
            number=issue.number,
            title=issue.title,
            state=issue.state,
            user=issue.user.login if issue.user else "unknown",
            user_avatar=issue.user.avatar_url if issue.user else None,
            created_at=issue.created_at.isoformat() if issue.created_at else "",
            updated_at=issue.updated_at.isoformat() if issue.updated_at else "",
            time_ago=_time_ago(issue.updated_at),
            html_url=issue.html_url,
            labels=[label.name for label in issue.labels],
            comments=issue.comments,
        )

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()


# --- Workflow Runs ---


@router.get("/repos/{owner}/{repo}/actions/runs")
def list_workflow_runs(
    owner: str,
    repo: str,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[WorkflowRun]:
    """List recent workflow runs."""
    try:
        g = _get_github_client()
        repository = g.get_repo(f"{owner}/{repo}")
        runs = repository.get_workflow_runs()

        result = []
        for run in runs[:limit]:
            result.append(
                WorkflowRun(
                    id=run.id,
                    name=run.name or "Unknown",
                    status=run.status,
                    conclusion=run.conclusion,
                    created_at=run.created_at.isoformat() if run.created_at else "",
                    updated_at=run.updated_at.isoformat() if run.updated_at else "",
                    time_ago=_time_ago(run.updated_at),
                    html_url=run.html_url,
                    head_branch=run.head_branch or "",
                    head_sha=run.head_sha[:7] if run.head_sha else "",
                )
            )
        return result

    except GithubException as e:
        logger.error(f"GitHub API error: {e}")
        if e.status == 404:
            raise HTTPException(status_code=404, detail="Repository not found")
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        g.close()
