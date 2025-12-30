"""Git operations routes for repository activity tracking."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import Repository
from ...utils.git_utils import (
    CommitInfo,
    GitOperationResult,
    GitStatus,
    get_repo_status,
    resolve_conflicts_with_gemini,
    run_git_command,
)
from ...utils.git_utils import get_current_branch as get_current_branch_util
from ...utils.git_utils import list_branches as list_branches_util
from ..deps import get_db, get_or_404
from ..services.operation_tracker import OperationType, get_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/git", tags=["git"])

# SSE clients for real-time git event updates
_git_sse_clients: list[asyncio.Queue[str]] = []


async def _broadcast_git_event(event_type: str, data: dict[str, str | None]) -> None:
    """Broadcast git event to all connected SSE clients."""
    message = json.dumps({"type": event_type, **data})
    dead_clients = []
    for queue in _git_sse_clients:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            dead_clients.append(queue)
    # Remove dead clients
    for queue in dead_clients:
        _git_sse_clients.remove(queue)


# Alias for API backward compatibility
GitWorkingStatus = GitStatus


class BranchInfo(BaseModel):
    """Current branch information."""

    branch: str


class BranchListInfo(BaseModel):
    """List of all branches."""

    current: str
    branches: list[str]


class CommitFileInfo(BaseModel):
    """File changed in a commit."""

    filename: str
    status: str  # A=added, M=modified, D=deleted, R=renamed
    additions: int
    deletions: int


class CommitDiff(BaseModel):
    """Commit diff content."""

    diff: str


class CheckoutRequest(BaseModel):
    """Branch checkout request."""

    branch: str


class MergeRequest(BaseModel):
    """Merge request."""

    branch: str  # Branch to merge into current
    use_ai: bool = True  # Use Gemini CLI Flash to resolve conflicts


class StashRequest(BaseModel):
    """Stash request."""

    message: str | None = None


class CommitRequest(BaseModel):
    """Commit/push request with optional message."""

    message: str | None = None


class StashPopRequest(BaseModel):
    """Stash pop/drop request."""

    index: int = 0


class MoveCommitsToBranchRequest(BaseModel):
    """Move commits to a new branch request."""

    new_branch_name: str


class MergeToMainRequest(BaseModel):
    """Merge current branch to main/master request."""

    push_after_merge: bool = False


class StashEntry(BaseModel):
    """Stash entry info."""

    index: int
    message: str
    date: str


@router.get("/repositories")
def list_repositories(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """List all repositories with basic info (including those in error state)."""
    repos = db.query(Repository).filter(Repository.deleted_at.is_(None)).all()

    result: list[dict[str, Any]] = []
    for repo in repos:
        path = repo.local_path
        path_exists = Path(path).exists() if path else False
        status = "unknown"
        if path_exists:
            try:
                # Use quick status check (just branch name or basic check)
                # Full status might be too slow for list, but for now it's ok
                pass
            except Exception:
                pass
            status = repo.status if repo.status else "unknown"

        result.append(
            {
                "id": str(repo.id),
                "name": str(repo.name) if repo.name else None,
                "path": str(path) if path else None,
                "path_exists": path_exists,
                "status": status,
            }
        )

    return result


@router.get("/repositories/{repo_id}/branch", response_model=BranchInfo)
def get_current_branch(repo_id: str, db: Session = Depends(get_db)) -> BranchInfo:
    """Get the current branch for a repository."""
    _, repo_path = _get_repo_and_path(repo_id, db)
    try:
        branch = get_current_branch_util(repo_path)
        return BranchInfo(branch=branch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories/{repo_id}/commits", response_model=list[CommitInfo])
def get_commits(
    repo_id: str, limit: int = Query(default=5, ge=1, le=50), db: Session = Depends(get_db)
) -> list[CommitInfo]:
    """Get recent commits for a repository."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        # Get local-only commit SHAs (commits not pushed to remote)
        local_only_shas: set[str] = set()
        try:
            current_branch = get_current_branch_util(repo_path)
            if current_branch and current_branch != "unknown":
                remote_branches = run_git_command(
                    repo_path, ["branch", "-r", "--list", f"origin/{current_branch}"]
                )
                if remote_branches.strip():
                    local_commits = run_git_command(
                        repo_path,
                        ["log", f"origin/{current_branch}..HEAD", "--pretty=format:%H"],
                    )
                    local_only_shas = {
                        sha.strip() for sha in local_commits.split("\n") if sha.strip()
                    }
        except Exception:
            pass

        # Get commits
        git_log_format = "--pretty=format:%H|%s|%an|%aI"
        output = run_git_command(repo_path, ["log", git_log_format, f"-n{limit}"])

        commits = []
        for line in output.split("\n"):
            if not line:
                continue

            parts = line.split("|", 3)
            if len(parts) == 4:
                sha = parts[0]
                commits.append(
                    CommitInfo(
                        sha=sha,
                        message=parts[1],
                        author=parts[2],
                        date=parts[3],
                        pushed=sha not in local_only_shas,
                    )
                )

        return commits
    except Exception as e:
        logger.error(f"[git/commits] failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories/{repo_id}/branches", response_model=BranchListInfo)
def list_branches(repo_id: str, db: Session = Depends(get_db)) -> BranchListInfo:
    """List all branches for a repository."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    current = get_current_branch_util(repo_path)
    try:
        branches = list_branches_util(repo_path, include_remote=True)
        return BranchListInfo(current=current, branches=branches)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories/{repo_id}/commits/{sha}/files", response_model=list[CommitFileInfo])
def get_commit_files(repo_id: str, sha: str, db: Session = Depends(get_db)) -> list[CommitFileInfo]:
    """Get list of files changed in a commit with stats."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        # Get file status (A/M/D/R)
        status_output = run_git_command(
            repo_path, ["diff-tree", "--no-commit-id", "--name-status", "-r", sha]
        )
        # Get numstat for additions/deletions
        numstat_output = run_git_command(repo_path, ["show", "--numstat", "--format=", sha])

        status_map: dict[str, str] = {}
        for line in status_output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0][0]
                filename = parts[-1]
                status_map[filename] = status

        files: list[CommitFileInfo] = []
        for line in numstat_output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                additions = int(parts[0]) if parts[0] != "-" else 0
                deletions = int(parts[1]) if parts[1] != "-" else 0
                filename = parts[2]
                status = status_map.get(filename, "M")
                files.append(
                    CommitFileInfo(
                        filename=filename, status=status, additions=additions, deletions=deletions
                    )
                )

        return files
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories/{repo_id}/commits/{sha}/diff", response_model=CommitDiff)
def get_commit_diff(repo_id: str, sha: str, db: Session = Depends(get_db)) -> CommitDiff:
    """Get the diff for a specific commit."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        full_diff = run_git_command(repo_path, ["show", sha])
        return CommitDiff(diff=full_diff)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories/{repo_id}/commits/{sha}/files/diff", response_model=CommitDiff)
def get_commit_file_diff(
    repo_id: str,
    sha: str,
    path: str = Query(..., description="File path within the repository"),
    db: Session = Depends(get_db),
) -> CommitDiff:
    """Get the diff for a specific file in a specific commit."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        file_diff = run_git_command(repo_path, ["show", "--format=", sha, "--", path])
        return CommitDiff(diff=file_diff)
    except Exception as e:
        # If the file doesn't exist in the commit, return empty diff
        if "does not exist" in str(e).lower() or "pathspec" in str(e).lower():
            return CommitDiff(diff="")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Git Operations (write operations)
# ============================================================================


def _get_repo_and_path(repo_id: str, db: Session) -> tuple[Repository, Path]:
    """Get repository and its path or raise 404."""
    repo = get_or_404(db, Repository, repo_id, "Repository not found")

    repo_path = Path(repo.local_path) if repo.local_path else None
    if not repo_path or not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository path not found")

    return repo, repo_path


def _get_repo_path(repo_id: str, db: Session) -> Path:
    _, path = _get_repo_and_path(repo_id, db)
    return path


def _extract_repo_name(repo: Repository) -> str:
    """Extract display name from repository."""
    if repo.url:
        url_str = str(repo.url)
        name = url_str.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name
    return str(repo.name) if repo.name else "unknown"


@router.get("/repositories/{repo_id}/status", response_model=GitWorkingStatus)
def get_working_status(repo_id: str, db: Session = Depends(get_db)) -> GitWorkingStatus:
    """Get working directory status (modified, staged, untracked files)."""
    _, repo_path = _get_repo_and_path(repo_id, db)
    try:
        return get_repo_status(repo_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/repositories/{repo_id}/checkout", response_model=GitOperationResult)
def checkout_branch(
    repo_id: str, request: CheckoutRequest, db: Session = Depends(get_db)
) -> GitOperationResult:
    """Checkout a branch."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["checkout", request.branch])
        return GitOperationResult(
            success=True, message=f"Switched to branch '{request.branch}'", output=output
        )
    except Exception as e:
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/fetch", response_model=GitOperationResult)
def fetch_remote(repo_id: str, db: Session = Depends(get_db)) -> GitOperationResult:
    """Fetch from remote."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["fetch", "--all", "--prune"])
        return GitOperationResult(success=True, message="Fetched from remote", output=output)
    except Exception as e:
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/pull", response_model=GitOperationResult)
def pull_remote(repo_id: str, db: Session = Depends(get_db)) -> GitOperationResult:
    """Pull from remote."""
    repo, repo_path = _get_repo_and_path(repo_id, db)
    repo_name = _extract_repo_name(repo)
    current_branch = get_current_branch_util(repo_path)

    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.GIT_PULL,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=repo_name,
        branch=current_branch,
    )

    try:
        output = run_git_command(repo_path, ["pull"])
        tracker.complete(op_id, result={"output": output[:200] if output else None})
        return GitOperationResult(success=True, message="Pulled from remote", output=output)
    except Exception as e:
        tracker.fail(op_id, error=str(e))
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/push", response_model=GitOperationResult)
def push_remote(repo_id: str, db: Session = Depends(get_db)) -> GitOperationResult:
    """Push to remote."""
    repo, repo_path = _get_repo_and_path(repo_id, db)
    repo_name = _extract_repo_name(repo)
    current_branch = get_current_branch_util(repo_path)

    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.GIT_PUSH,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=repo_name,
        branch=current_branch,
    )

    try:
        output = run_git_command(repo_path, ["push"])
        tracker.complete(op_id, result={"output": output[:200] if output else None})
        return GitOperationResult(success=True, message="Pushed to remote", output=output)
    except Exception as e:
        tracker.fail(op_id, error=str(e))
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/push/smart", response_model=GitOperationResult)
async def smart_push_remote(
    repo_id: str,
    request: CommitRequest | None = None,
    db: Session = Depends(get_db),
) -> GitOperationResult:
    """Smart Push: Auto-Commit -> Pull (Rebase) -> AI Resolve -> Push.

    Delegates the entire workflow to Gemini Flash via 'smart_push' utility.
    """
    from ...utils.git_utils import smart_push

    repo, repo_path = _get_repo_and_path(repo_id, db)
    repo_name = _extract_repo_name(repo)
    current_branch = get_current_branch_util(repo_path)

    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.MERGE_AND_PUSH,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=repo_name,
        branch=current_branch,
    )

    msg = request.message if request and request.message else "Update via TurboWrap"

    try:
        result = await smart_push(repo_path, commit_message=msg, op_id=op_id)

        if result.success:
            out = result.output[:200] if result.output else "Success"
            tracker.complete(op_id, result={"output": out})
        else:
            tracker.fail(op_id, error=result.message)

        return result
    except Exception as e:
        tracker.fail(op_id, error=str(e))
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/move-commits-to-branch", response_model=GitOperationResult)
def move_commits_to_branch(
    repo_id: str, request: MoveCommitsToBranchRequest, db: Session = Depends(get_db)
) -> GitOperationResult:
    """Move unpushed commits to a new branch and reset current branch.

    This operation:
    1. Creates a new branch with the current commits
    2. Resets the original branch to match remote
    3. Switches to the new branch
    """
    repo, repo_path = _get_repo_and_path(repo_id, db)
    repo_name = _extract_repo_name(repo)
    current_branch = get_current_branch_util(repo_path)

    # Validate branch name
    new_branch = request.new_branch_name.strip()
    if not new_branch:
        return GitOperationResult(success=False, message="Branch name cannot be empty")

    # Check if branch already exists
    try:
        existing_branches = list_branches_util(repo_path, include_remote=False)
        if new_branch in existing_branches:
            return GitOperationResult(
                success=False, message=f"Branch '{new_branch}' already exists"
            )
    except Exception:
        pass

    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.GIT_CHECKOUT,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=repo_name,
        branch=current_branch,
        details={"action": "move_commits_to_branch", "new_branch": new_branch},
    )

    try:
        # 1. Create new branch from current HEAD
        run_git_command(repo_path, ["branch", new_branch])

        # 2. Reset current branch to remote
        try:
            run_git_command(repo_path, ["reset", "--hard", f"origin/{current_branch}"])
        except Exception as reset_err:
            # If no remote tracking, just leave it as is and switch to new branch
            logger.warning(f"[GIT] Could not reset to origin/{current_branch}: {reset_err}")

        # 3. Checkout the new branch
        run_git_command(repo_path, ["checkout", new_branch])

        tracker.complete(op_id, result={"new_branch": new_branch})
        return GitOperationResult(
            success=True,
            message=f"Commits moved to '{new_branch}'. Now on '{new_branch}'.",
            output=f"Created and switched to branch '{new_branch}'",
        )
    except Exception as e:
        tracker.fail(op_id, error=str(e))
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/merge-to-main", response_model=GitOperationResult)
async def merge_to_main(
    repo_id: str, request: MergeToMainRequest, db: Session = Depends(get_db)
) -> GitOperationResult:
    """Merge current branch into main/master and stay on main.

    This operation:
    1. Saves the current branch name
    2. Determines main branch (main or master)
    3. Checkouts main and pulls latest
    4. Merges the source branch (with AI conflict resolution if needed)
    5. Optionally pushes to remote
    6. Stays on main
    """
    repo, repo_path = _get_repo_and_path(repo_id, db)
    repo_name = _extract_repo_name(repo)
    source_branch = get_current_branch_util(repo_path)

    # Check if already on main/master
    if source_branch in ("main", "master"):
        return GitOperationResult(success=False, message="Already on main/master branch")

    # Determine the main branch name
    try:
        branches = list_branches_util(repo_path, include_remote=False)
        if "main" in branches:
            main_branch = "main"
        elif "master" in branches:
            main_branch = "master"
        else:
            return GitOperationResult(success=False, message="No main or master branch found")
    except Exception as e:
        return GitOperationResult(success=False, message=f"Failed to list branches: {e}")

    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.GIT_MERGE,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=repo_name,
        branch=main_branch,
        details={
            "action": "merge_to_main",
            "source_branch": source_branch,
            "target_branch": main_branch,
            "push_after": request.push_after_merge,
        },
    )

    try:
        # 1. Checkout main
        run_git_command(repo_path, ["checkout", main_branch])

        # 2. Pull latest
        try:
            run_git_command(repo_path, ["pull"])
        except Exception as pull_err:
            logger.warning(f"[GIT] Pull failed (continuing): {pull_err}")

        # 3. Merge source branch
        try:
            merge_output = run_git_command(repo_path, ["merge", source_branch])
        except Exception as merge_err:
            err_msg = str(merge_err)
            is_conflict = "CONFLICT" in err_msg or "conflict" in err_msg.lower()

            if is_conflict:
                logger.info("[GIT] Merge conflict detected, calling Gemini...")
                result = await resolve_conflicts_with_gemini(
                    repo_path=repo_path,
                    context_desc=f"Merge {source_branch} into {main_branch}",
                    op_id=op_id,
                )

                if result.success:
                    try:
                        commit_msg = f"Merge {source_branch}: AI-resolved conflicts"
                        run_git_command(repo_path, ["commit", "-m", commit_msg])
                        merge_output = "Merge completed with AI resolution"
                    except Exception as commit_err:
                        # Abort merge and go back to source branch
                        try:
                            run_git_command(repo_path, ["merge", "--abort"])
                        except Exception:
                            pass
                        run_git_command(repo_path, ["checkout", source_branch])
                        tracker.fail(op_id, error=f"Commit failed: {commit_err}")
                        return GitOperationResult(
                            success=False, message=f"Commit failed: {commit_err}"
                        )
                else:
                    # Abort merge and go back to source branch
                    try:
                        run_git_command(repo_path, ["merge", "--abort"])
                    except Exception:
                        pass
                    run_git_command(repo_path, ["checkout", source_branch])
                    tracker.fail(op_id, error=result.message)
                    return GitOperationResult(
                        success=False, message=f"AI resolution failed: {result.message}"
                    )
            else:
                # Non-conflict error, abort and return
                try:
                    run_git_command(repo_path, ["merge", "--abort"])
                except Exception:
                    pass
                run_git_command(repo_path, ["checkout", source_branch])
                tracker.fail(op_id, error=err_msg)
                return GitOperationResult(success=False, message=err_msg)

        # 4. Push if requested
        push_output = ""
        if request.push_after_merge:
            try:
                push_output = run_git_command(repo_path, ["push"])
            except Exception as push_err:
                logger.warning(f"[GIT] Push failed: {push_err}")
                push_output = f"Push failed: {push_err}"

        # 5. Stay on main (already there)
        final_msg = f"Merged '{source_branch}' into '{main_branch}'"
        if push_output:
            final_msg += f". {push_output}"

        tracker.complete(op_id, result={"output": final_msg[:200]})
        return GitOperationResult(
            success=True,
            message=final_msg,
            output=merge_output,
        )
    except Exception as e:
        # Try to go back to source branch on any unexpected error
        try:
            run_git_command(repo_path, ["checkout", source_branch])
        except Exception:
            pass
        tracker.fail(op_id, error=str(e))
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/merge", response_model=GitOperationResult)
async def merge_branch(
    repo_id: str, request: MergeRequest, db: Session = Depends(get_db)
) -> GitOperationResult:
    """Merge a branch into current.

    If use_ai=True (default) and conflicts occur, uses Gemini CLI Flash
    to automatically resolve them.
    """
    repo, repo_path = _get_repo_and_path(repo_id, db)
    repo_name = _extract_repo_name(repo)
    current_branch = get_current_branch_util(repo_path)

    tracker = get_tracker()
    op_id = str(uuid.uuid4())
    tracker.register(
        op_type=OperationType.GIT_MERGE,
        operation_id=op_id,
        repo_id=repo_id,
        repo_name=repo_name,
        branch=current_branch,
        details={
            "source_branch": request.branch,
            "target_branch": current_branch,
            "use_ai": request.use_ai,
        },
    )

    try:
        output = run_git_command(repo_path, ["merge", request.branch])
        tracker.complete(op_id, result={"output": output[:200] if output else None})
        return GitOperationResult(success=True, message=f"Merged '{request.branch}'", output=output)
    except Exception as e:
        # Check for conflicts
        err_msg = str(e)
        is_conflict = "CONFLICT" in err_msg or "conflict" in err_msg.lower()

        if is_conflict and request.use_ai:
            logger.info("[GIT] Merge conflict detected, calling Gemini...")

            # Use centralized utility
            result = await resolve_conflicts_with_gemini(
                repo_path=repo_path,
                context_desc=f"Merge {request.branch} into {current_branch}",
                op_id=op_id,
            )

            if result.success:
                # IMPORTANT: resolve_conflicts_with_gemini only Stages files.
                # We need to finalize the merge commit.
                try:
                    commit_msg = f"Merge {request.branch}: AI-resolved conflicts"
                    # 'git commit --no-edit' often works for concluding a merge if logic allows,
                    # but 'git commit -m' is safer if we want a custom message.
                    # Git merge conflict state usually requires 'git commit' to conclude.
                    commit_out = run_git_command(repo_path, ["commit", "-m", commit_msg])

                    final_msg = f"Merge completed with AI resolution.\n{commit_out}"
                    tracker.complete(op_id, result={"output": final_msg[:200]})

                    return GitOperationResult(
                        success=True, message=final_msg, output=result.output, ai_resolved=True
                    )
                except Exception as commit_err:
                    tracker.fail(op_id, error=f"Conflicts resolved but commit failed: {commit_err}")
                    return GitOperationResult(success=False, message=f"Commit failed: {commit_err}")

            # Failed to resolve
            try:
                run_git_command(repo_path, ["merge", "--abort"])
            except Exception:
                pass

            tracker.fail(op_id, error=result.message)
            return result

        tracker.fail(op_id, error=err_msg)
        return GitOperationResult(success=False, message=err_msg)


@router.get("/repositories/{repo_id}/stash", response_model=list[StashEntry])
def list_stashes(repo_id: str, db: Session = Depends(get_db)) -> list[StashEntry]:
    """List all stashes."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["stash", "list", "--format=%gd|%s|%aI"])
        stashes = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            if len(parts) >= 2:
                index_str = parts[0].replace("stash@{", "").replace("}", "")
                try:
                    index = int(index_str)
                    stashes.append(
                        StashEntry(
                            index=index,
                            message=parts[1],
                            date=parts[2] if len(parts) > 2 else "",
                        )
                    )
                except ValueError:
                    pass
        return stashes
    except Exception:
        return []


@router.post("/repositories/{repo_id}/stash", response_model=GitOperationResult)
def stash_changes(
    repo_id: str, request: StashRequest, db: Session = Depends(get_db)
) -> GitOperationResult:
    """Stash changes."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        cmd = ["stash", "push"]
        if request.message:
            cmd.extend(["-m", request.message])

        output = run_git_command(repo_path, cmd)
        return GitOperationResult(success=True, message="Stashed changes", output=output)
    except Exception as e:
        return GitOperationResult(success=False, message=str(e))


@router.post("/repositories/{repo_id}/stash/pop", response_model=GitOperationResult)
def pop_stash(
    repo_id: str, request: StashPopRequest, db: Session = Depends(get_db)
) -> GitOperationResult:
    """Pop a stash."""
    _, repo_path = _get_repo_and_path(repo_id, db)

    try:
        output = run_git_command(repo_path, ["stash", "pop", f"stash@{{{request.index}}}"])
        return GitOperationResult(success=True, message="Popped stash", output=output)
    except Exception as e:
        return GitOperationResult(success=False, message=str(e))


# =========================================================================
# SSE Real-time Git Events (for File Editor auto-refresh)
# =========================================================================


@router.get("/events")
async def git_events(request: Request) -> StreamingResponse:
    """SSE endpoint for real-time git events.

    Clients connect to receive notifications when git operations occur
    (commit, merge, checkout, etc.) triggered by git hooks.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        _git_sse_clients.append(queue)
        try:
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    # Wait for message with timeout (keeps connection alive)
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        finally:
            if queue in _git_sse_clients:
                _git_sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/notify")
async def notify_git_event(
    event_type: str,
    repo_path: str | None = None,
) -> dict[str, bool | int]:
    """Notify all clients of a git event (called by git hooks).

    Args:
        event_type: Type of git event (commit, merge, checkout, rewrite)
        repo_path: Path to the repository where the event occurred

    This endpoint is called by git hooks installed in repositories.
    It broadcasts the event to all connected SSE clients.
    """
    await _broadcast_git_event(
        event_type,
        {"repo_path": repo_path},
    )
    logger.info(f"[Git SSE] Broadcast {event_type} for repo {repo_path}")
    return {"success": True, "clients": len(_git_sse_clients)}
