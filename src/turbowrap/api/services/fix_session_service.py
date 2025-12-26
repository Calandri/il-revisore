"""
Fix session service - handles business logic for fixing issues.

Extracted from the fat controller in fix.py to follow Single Responsibility Principle.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    pass


class IdempotencyStoreProtocol(Protocol):
    """Protocol for idempotency store to avoid circular imports."""

    def generate_key(
        self,
        repository_id: str,
        task_id: str,
        issue_ids: list[str],
        client_key: str | None = None,
    ) -> str: ...

    def check_and_register(
        self,
        key: str,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]: ...

    def update_status(
        self,
        key: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> None: ...

    def update_branch_name(self, key: str, branch_name: str) -> None: ...

    def remove(self, key: str) -> None: ...


from ...db.models import Issue, IssueStatus, LinearIssue, Repository, Setting, Task  # noqa: E402
from ...db.session import get_session_local  # noqa: E402
from ...fix import (  # noqa: E402
    FixEventType,
    FixOrchestrator,
    FixProgressEvent,
    FixRequest,
    IssueFixResult,
    ScopeValidationError,
)
from ...linear import LinearStateManager  # noqa: E402
from ...review.integrations.linear import LinearClient  # noqa: E402
from .operation_tracker import OperationType, get_tracker  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class FixSessionInfo:
    """Information about a fix session."""

    session_id: str
    repository: Repository
    task: Task
    issues: list[Issue]
    fix_request: FixRequest
    idempotency_key: str


@dataclass
class FixResult:
    """Result of a fix operation."""

    completed_count: int
    failed_count: int
    total: int


class FixSessionService:
    """
    Service for managing fix sessions.

    Handles:
    - Validating and preparing fix requests
    - Executing fixes with SSE streaming
    - Updating issue statuses in the database
    - Auto-transitioning linked Linear issues
    """

    def __init__(self, db: Session, idempotency_store: IdempotencyStoreProtocol) -> None:
        self.db = db
        self.idempotency = idempotency_store

    def validate_and_prepare(
        self,
        repository_id: str,
        task_id: str,
        issue_ids: list[str],
        use_existing_branch: bool = False,
        existing_branch_name: str | None = None,
        client_idempotency_key: str | None = None,
        force: bool = False,
        user_name: str | None = None,
        user_notes: str | None = None,
    ) -> tuple[FixSessionInfo | None, dict[str, Any] | None]:
        """
        Validate request and prepare fix session.

        Args:
            repository_id: Repository ID
            task_id: Task ID that found the issues
            issue_ids: List of issue IDs to fix
            use_existing_branch: If True, use existing branch instead of creating new one
            existing_branch_name: Name of existing branch to use
            client_idempotency_key: Optional client-provided idempotency key
            force: Force restart even if a session is already in progress
            user_name: Name of user starting the fix (for active sessions display)

        Returns:
            Tuple of (FixSessionInfo, None) for new sessions, or
            (None, duplicate_response) for duplicate requests

        Raises:
            ValueError: If repository, task, or issues not found
            DuplicateSessionError: If a session is already in progress
        """
        session_id = str(uuid.uuid4())

        # Verify repository FIRST (need data for metadata)
        repo = self.db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo:
            raise ValueError("Repository not found")

        # Verify task
        task = self.db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise ValueError("Task not found")

        # Load issues
        issues = (
            self.db.query(Issue)
            .filter(Issue.id.in_(issue_ids))
            .filter(Issue.repository_id == repository_id)
            .all()
        )

        if not issues:
            raise ValueError("No valid issues found")

        # Generate idempotency key
        idempotency_key = self.idempotency.generate_key(
            repository_id=repository_id,
            task_id=task_id,
            issue_ids=issue_ids,
            client_key=client_idempotency_key,
        )

        # Build metadata for active sessions display
        # Extract repo name from url (e.g., "https://github.com/org/repo" -> "repo")
        repo_url: str = cast(str, repo.url) if repo.url else ""
        repo_name = repo_url.rstrip("/").split("/")[-1] if repo_url else "unknown"
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        session_metadata: dict[str, Any] = {
            "repository_id": repository_id,
            "repository_name": repo_name,
            "task_id": task_id,
            "issue_count": len(issues),
            "issue_codes": [cast(str, i.issue_code) for i in issues],
            "user_name": user_name,
        }

        # Check for duplicate request (with metadata for new sessions)
        is_duplicate, existing = self.idempotency.check_and_register(
            key=idempotency_key,
            session_id=session_id,
            metadata=session_metadata,
        )

        if is_duplicate and existing:
            if existing.status == "in_progress":
                if force:
                    # Force restart: remove old entry and continue
                    logger.warning(
                        f"Force restart requested, removing stuck session: {existing.session_id}"
                    )
                    self.idempotency.remove(idempotency_key)
                    # Re-register with new session and metadata
                    self.idempotency.check_and_register(
                        key=idempotency_key,
                        session_id=session_id,
                        metadata=session_metadata,
                    )
                else:
                    raise DuplicateSessionError(
                        session_id=existing.session_id,
                        status=existing.status,
                        created_at=existing.created_at,
                    )
            else:
                # Return previous result
                return None, {
                    "status": "duplicate",
                    "message": "Request already processed",
                    "previous_session_id": existing.session_id,
                    "previous_status": existing.status,
                    "completed_at": (
                        existing.completed_at.isoformat() if existing.completed_at else None
                    ),
                }

        # Order issues by the requested order
        issue_order: dict[str, int] = {id: i for i, id in enumerate(issue_ids)}
        issues = sorted(issues, key=lambda x: issue_order.get(cast(str, x.id), 999))

        # Set issues to in_progress immediately
        for issue in issues:
            issue.status = IssueStatus.IN_PROGRESS.value  # type: ignore[assignment]
        self.db.commit()

        # Create fix request
        fix_request = FixRequest(
            repository_id=repository_id,
            task_id=task_id,
            issue_ids=[cast(str, i.id) for i in issues],
            use_existing_branch=use_existing_branch,
            existing_branch_name=existing_branch_name,
            workspace_path=cast(str | None, repo.workspace_path),  # Monorepo: restrict fixes
            user_notes=user_notes,  # User-provided context/instructions
        )

        # Register with unified OperationTracker
        tracker = get_tracker()
        tracker.register(
            op_type=OperationType.FIX,
            operation_id=session_id,
            repo_id=repository_id,
            repo_name=repo_name,
            branch=existing_branch_name,  # Will be updated when fix starts
            user=user_name,
            details={
                "task_id": task_id,
                "issue_count": len(issues),
                "issue_codes": [cast(str, i.issue_code) for i in issues],
            },
        )

        return (
            FixSessionInfo(
                session_id=session_id,
                repository=repo,
                task=task,
                issues=issues,
                fix_request=fix_request,
                idempotency_key=idempotency_key,
            ),
            None,
        )

    async def update_issue_statuses(
        self,
        db: Session,
        results: list[IssueFixResult],
        branch_name: str,
        session_id: str,
    ) -> tuple[int, int]:
        """
        Update database with fix results.

        Args:
            db: Database session
            results: List of IssueResult objects
            branch_name: Name of the fix branch
            session_id: Session ID for S3 log retrieval

        Returns:
            Tuple of (completed_count, failed_count)
        """
        completed_count = 0
        failed_count = 0

        for issue_result in results:
            db_issue = db.query(Issue).filter(Issue.id == issue_result.issue_id).first()
            if db_issue:
                if issue_result.status.value == "completed":
                    db_issue.status = IssueStatus.RESOLVED.value  # type: ignore[assignment]
                    db_issue.resolved_at = datetime.utcnow()  # type: ignore[assignment]
                    resolution_note_val = (
                        f"Fixed in commit {issue_result.commit_sha}"
                        if issue_result.commit_sha
                        else "Fixed"
                    )
                    db_issue.resolution_note = resolution_note_val  # type: ignore[assignment]
                    # Save fix result fields
                    db_issue.fix_code = issue_result.fix_code  # type: ignore[assignment]
                    db_issue.fix_explanation = issue_result.fix_explanation  # type: ignore[assignment]
                    db_issue.fix_files_modified = issue_result.fix_files_modified  # type: ignore[assignment]
                    db_issue.fix_commit_sha = issue_result.commit_sha  # type: ignore[assignment]
                    db_issue.fix_branch = branch_name  # type: ignore[assignment]
                    db_issue.fix_session_id = session_id  # type: ignore[assignment]
                    db_issue.fixed_at = datetime.utcnow()  # type: ignore[assignment]
                    db_issue.fixed_by = "fixer_claude"  # type: ignore[assignment]
                    completed_count += 1
                elif issue_result.status.value == "failed":
                    db_issue.status = IssueStatus.OPEN.value  # type: ignore[assignment]
                    db_issue.resolution_note = f"Fix failed: {issue_result.error}"  # type: ignore[assignment]
                    failed_count += 1

        db.commit()
        return completed_count, failed_count

    async def transition_linear_issues(
        self,
        db: Session,
        task_id: str,
        commit_sha: str,
        branch_name: str,
    ) -> None:
        """
        Auto-transition any linked Linear issues to in_review after successful commit.

        Args:
            db: Database session
            task_id: Task ID to check for linked Linear issues
            commit_sha: Commit SHA to include in transition
            branch_name: Branch name to include in transition
        """
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return

            # Check if task has linked Linear issues
            linear_issues = (
                db.query(LinearIssue)
                .filter(
                    LinearIssue.task_id == task.id,
                    LinearIssue.is_active,
                )
                .all()
            )

            if not linear_issues:
                return

            # Get Linear client
            linear_api_key = db.query(Setting).filter(Setting.key == "linear_api_key").first()

            if not linear_api_key or not linear_api_key.value:
                return

            linear_client = LinearClient(api_key=cast(str, linear_api_key.value))
            state_manager = LinearStateManager(linear_client)

            for linear_issue in linear_issues:
                try:
                    success = await state_manager.auto_transition_after_commit(
                        linear_issue, commit_sha, branch_name
                    )
                    if success:
                        logger.info(
                            f"Auto-transitioned Linear issue "
                            f"{linear_issue.linear_identifier} to in_review"
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to auto-transition Linear issue "
                        f"{linear_issue.linear_identifier}: {e}"
                    )

            # Commit Linear issue updates
            db.commit()

        except Exception as e:
            logger.error(f"Error during Linear auto-transition: {e}")
            # Don't fail the entire fix if Linear transition fails

    async def reset_issues_on_error(
        self,
        db: Session,
        issues: list[Issue],
        error_message: str | None = None,
    ) -> None:
        """
        Reset issues to open status on error.

        Args:
            db: Database session
            issues: List of issues to reset
            error_message: Optional message to add to resolution_note
        """
        for issue in issues:
            db_issue = db.query(Issue).filter(Issue.id == issue.id).first()
            if db_issue and db_issue.status == IssueStatus.IN_PROGRESS.value:
                db_issue.status = IssueStatus.OPEN.value  # type: ignore[assignment]
                if error_message:
                    db_issue.resolution_note = error_message  # type: ignore[assignment]
        db.commit()

    async def execute_fixes(
        self,
        session_info: FixSessionInfo,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute fixes and yield SSE progress events.

        Args:
            session_info: Information about the fix session

        Yields:
            SSE-formatted event dictionaries
        """
        event_queue: asyncio.Queue[FixProgressEvent | None] = asyncio.Queue()
        session_id = session_info.session_id
        repo_path = Path(cast(str, session_info.repository.local_path))
        idempotency_key = session_info.idempotency_key

        # Get tracker reference for callbacks
        tracker = get_tracker()

        async def progress_callback(event: FixProgressEvent) -> None:
            """Enqueue progress events."""
            nonlocal session_id
            if event.session_id:
                session_id = event.session_id
            # Update branch_name in session metadata when fix starts
            if event.type == FixEventType.FIX_SESSION_STARTED and event.branch_name:
                self.idempotency.update_branch_name(idempotency_key, event.branch_name)
                # Also update unified tracker
                tracker.update(session_info.session_id, branch=event.branch_name)
            await event_queue.put(event)

        async def run_fix() -> None:
            """Run fix in background."""
            SessionLocal = get_session_local()
            fix_db = SessionLocal()

            try:
                orchestrator = FixOrchestrator(repo_path=repo_path)
                result = await orchestrator.fix_issues(
                    request=session_info.fix_request,
                    issues=session_info.issues,
                    emit=progress_callback,
                )

                # Update issue statuses in database
                completed_count, failed_count = await self.update_issue_statuses(
                    fix_db,
                    result.results,
                    result.branch_name,
                    result.session_id,
                )

                # Get commit SHA from first successful result
                commit_sha = next((r.commit_sha for r in result.results if r.commit_sha), None)

                # Auto-transition Linear issues to in_review after successful commit
                if commit_sha and result.branch_name:
                    await self.transition_linear_issues(
                        fix_db,
                        session_info.fix_request.task_id,
                        commit_sha,
                        result.branch_name,
                    )

                # Mark idempotency entry as completed
                self.idempotency.update_status(
                    idempotency_key,
                    "completed",
                    {
                        "completed": completed_count,
                        "failed": failed_count,
                        "total": len(result.results),
                    },
                )

                # Mark unified tracker as completed
                tracker.complete(
                    session_info.session_id,
                    result={
                        "completed": completed_count,
                        "failed": failed_count,
                        "total": len(result.results),
                        "branch": result.branch_name,
                        "commit_sha": commit_sha,
                    },
                )

            except ScopeValidationError as e:
                # Workspace scope violation - files modified outside allowed workspace
                logger.error(f"Workspace scope violation: {e}")
                await self.reset_issues_on_error(
                    fix_db,
                    session_info.issues,
                    f"Blocked: files outside workspace '{e.workspace_path}'",
                )
                # Mark idempotency entry as failed
                self.idempotency.update_status(idempotency_key, "failed")
                # Mark unified tracker as failed
                tracker.fail(
                    session_info.session_id,
                    error=f"Scope violation: {e.workspace_path}",
                )
                await event_queue.put(
                    FixProgressEvent(
                        type=FixEventType.FIX_SESSION_ERROR,
                        error="WORKSPACE SCOPE VIOLATION",
                        message=f"Modified files outside '{e.workspace_path}': "
                        f"{', '.join(e.files_outside_scope[:3])}",
                    )
                )

            except Exception as e:
                logger.exception("Fix session error")
                await self.reset_issues_on_error(fix_db, session_info.issues)
                # Mark idempotency entry as failed
                self.idempotency.update_status(idempotency_key, "failed")
                # Mark unified tracker as failed
                tracker.fail(session_info.session_id, error=str(e))
                await event_queue.put(
                    FixProgressEvent(
                        type=FixEventType.FIX_SESSION_ERROR,
                        error=str(e),
                        message=f"Fix failed: {str(e)[:100]}",
                    )
                )

            finally:
                await event_queue.put(None)
                fix_db.close()

        # Start fix task
        fix_task = asyncio.create_task(run_fix())

        try:
            # Stream events
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event.to_sse()

        except asyncio.CancelledError:
            fix_task.cancel()
            raise


class DuplicateSessionError(Exception):
    """Raised when a duplicate fix session is detected."""

    def __init__(self, session_id: str, status: str, created_at: datetime) -> None:
        self.session_id = session_id
        self.status = status
        self.created_at = created_at
        super().__init__(f"Fix session already in progress: {session_id}")


def get_fix_session_service(db: Session) -> FixSessionService:
    """Factory function to create FixSessionService with dependencies."""
    # Import here to avoid circular import - fix.py imports from this module
    from ..routes.fix import _idempotency_store

    return FixSessionService(db=db, idempotency_store=_idempotency_store)
