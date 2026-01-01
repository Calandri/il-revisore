"""
Review stream service - handles business logic for streaming reviews.

Extracted from the fat controller in tasks.py to follow Single Responsibility Principle.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy.orm import Session

from ...db.models import Issue, Repository, Task
from ...db.session import get_session_local
from ...review.models.progress import ProgressEvent, ProgressEventType
from ...review.models.report import FinalReport
from ...review.models.review import Issue as ReviewIssue
from ...review.models.review import (
    IssueSeverity,
    ReviewMode,
    ReviewOptions,
    ReviewRequest,
    ReviewRequestSource,
)
from ...review.orchestrator import Orchestrator
from ..review_manager import ReviewManager, ReviewSession, get_review_manager
from .checkpoint_service import CheckpointService

# NOTE: Operation tracking is now handled atomically at the ClaudeCLI/GeminiCLI level

logger = logging.getLogger(__name__)


@dataclass
class ReviewSessionInfo:
    """Information about a review session."""

    task_id: str
    repository_id: str
    session: ReviewSession
    is_reconnect: bool


class ReviewStreamService:
    """
    Service for managing streaming reviews.

    Handles:
    - Starting new reviews or reconnecting to existing ones
    - Saving review results to the database
    - SSE event generation
    """

    def __init__(self, db: Session, review_manager: ReviewManager) -> None:
        self.db = db
        self.manager = review_manager

    def find_existing_session(self, repository_id: str) -> ReviewSession | None:
        """Find an existing running review session for the repository."""
        for session in self.manager.get_active_sessions():
            if session.repository_id == repository_id:
                return session
        return None

    def create_task_record(
        self,
        repository_id: str,
        mode: str,
    ) -> Task:
        """Create a new task record in the database."""
        task = Task(
            repository_id=repository_id,
            type="review",
            status="running",
            config={
                "mode": mode,
            },
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    async def start_or_reconnect(
        self,
        repository_id: str,
        repo: Repository,
        mode: str,
        include_functional: bool,
        resume: bool = False,
        regenerate_structure: bool = False,
    ) -> ReviewSessionInfo:
        """
        Start a new review or reconnect to an existing one.

        Args:
            repository_id: The repository ID
            repo: The repository object
            mode: Review mode ('initial' or 'diff')
            include_functional: Whether to include functional analyst
            resume: If True, resume from checkpoints of the most recent failed review

        Returns:
            ReviewSessionInfo with session details and reconnect status
        """
        # Check for existing running review
        existing_session = self.find_existing_session(repository_id)

        if existing_session:
            return ReviewSessionInfo(
                task_id=existing_session.task_id,
                repository_id=repository_id,
                session=existing_session,
                is_reconnect=True,
            )

        # Check for resumable failed task
        resume_task_id: str | None = None
        completed_checkpoints: dict[str, dict[str, Any]] = {}

        if resume:
            failed_task = (
                self.db.query(Task)
                .filter(
                    Task.repository_id == repository_id,
                    Task.type == "review",
                    Task.status == "failed",
                )
                .order_by(Task.created_at.desc())
                .first()
            )

            if failed_task:
                checkpoint_service = CheckpointService(self.db)
                checkpoints = checkpoint_service.get_completed_reviewers(cast(str, failed_task.id))

                if checkpoints:
                    # We can resume! Update the task status
                    failed_task.status = "running"  # type: ignore[assignment]
                    failed_task.error = None  # type: ignore[assignment]
                    failed_task.started_at = datetime.utcnow()  # type: ignore[assignment]
                    self.db.commit()

                    resume_task_id = cast(str, failed_task.id)
                    # Convert checkpoints to dict format for orchestrator
                    for name, cp in checkpoints.items():
                        completed_checkpoints[name] = {
                            "issues_data": cp.issues_data,
                            "final_satisfaction": cp.final_satisfaction,
                            "iterations": cp.iterations,
                            "model_usage": cp.model_usage,
                        }

                    logger.info(
                        f"Resuming task {resume_task_id} with "
                        f"{len(completed_checkpoints)} completed reviewers"
                    )

        # Create new task if not resuming
        if not resume_task_id:
            task = self.create_task_record(repository_id, mode)
            task_id = cast(str, task.id)

            # Soft delete all "open" (TO DO) issues for this repository - fresh start
            # Using soft_delete() instead of hard delete to preserve data history
            from ...db.models import IssueStatus

            issues_to_archive = (
                self.db.query(Issue)
                .filter(
                    Issue.repository_id == repository_id,
                    Issue.status == IssueStatus.OPEN.value,
                    Issue.deleted_at.is_(None),  # Only non-deleted issues
                )
                .all()
            )
            if issues_to_archive:
                for issue in issues_to_archive:
                    issue.soft_delete()
                self.db.commit()
                logger.info(
                    f"[REVIEW INIT] Soft-deleted {len(issues_to_archive)} open issues for "
                    f"repository {repository_id} (fresh start, data preserved)"
                )
        else:
            task_id = resume_task_id

        # Capture values for the closure
        local_path = cast(str, repo.local_path)
        review_mode = mode
        repo_workspace_path = cast(str | None, repo.workspace_path)  # Monorepo workspace scope
        checkpoints_for_closure = completed_checkpoints  # Capture for closure
        regenerate_structure_flag = regenerate_structure  # Capture for closure

        # Extract repo name for display
        repo_url = cast(str, repo.url) if repo.url else ""
        repo_name = repo_url.rstrip("/").split("/")[-1] if repo_url else "unknown"
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        # NOTE: Operation tracking is now handled atomically at the ClaudeCLI/GeminiCLI level
        # Each CLI call (reviewers) creates its own Operation with parent_session_id linking

        # Create the review coroutine
        async def run_review(session: ReviewSession) -> None:
            """Run the review in background."""
            SessionLocal = get_session_local()
            review_db = SessionLocal()

            try:
                orchestrator = Orchestrator()
                checkpoint_service = CheckpointService(review_db)

                async def progress_callback(event: ProgressEvent) -> None:
                    """Callback to add events to session."""
                    session.add_event(event)

                async def checkpoint_callback(
                    reviewer_name: str,
                    status: str,
                    issues: list[ReviewIssue],
                    satisfaction: float,
                    iterations: int,
                    model_usage: list[dict[str, Any]],
                    started_at: datetime,
                ) -> None:
                    """Callback to save checkpoint after each reviewer."""
                    checkpoint_service.save_checkpoint(
                        task_id=task_id,
                        reviewer_name=reviewer_name,
                        issues=issues,
                        final_satisfaction=satisfaction,
                        iterations=iterations,
                        model_usage=model_usage,
                        started_at=started_at,
                        status=status,
                    )

                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(
                        pr_url=None,
                        commit_sha=None,
                        directory=local_path,
                        workspace_path=repo_workspace_path,
                    ),
                    options=ReviewOptions(
                        mode=ReviewMode.INITIAL if review_mode == "initial" else ReviewMode.DIFF,
                        include_functional=include_functional,
                        severity_threshold=IssueSeverity.LOW,
                        output_format="both",
                        regenerate_structure=regenerate_structure_flag,
                    ),
                )

                report = await orchestrator.review(
                    request,
                    progress_callback,
                    completed_checkpoints=checkpoints_for_closure,
                    checkpoint_callback=checkpoint_callback,
                    parent_session_id=task_id,
                )

                # Save results
                await self._save_review_results(review_db, task_id, repository_id, report)

                # NOTE: Operation tracking is handled atomically by ClaudeCLI/GeminiCLI

            except asyncio.CancelledError:
                db_task = review_db.query(Task).filter(Task.id == task_id).first()
                if db_task:
                    db_task.status = "cancelled"  # type: ignore[assignment]
                    db_task.completed_at = datetime.utcnow()  # type: ignore[assignment]
                    review_db.commit()
                raise

            except Exception as e:
                session.add_event(
                    ProgressEvent(
                        type=ProgressEventType.REVIEW_ERROR,
                        error=str(e),
                        message=f"Review failed: {str(e)[:100]}",
                    )
                )

                db_task = review_db.query(Task).filter(Task.id == task_id).first()
                if db_task:
                    db_task.status = "failed"  # type: ignore[assignment]
                    db_task.error = str(e)  # type: ignore[assignment]
                    db_task.completed_at = datetime.utcnow()  # type: ignore[assignment]
                    review_db.commit()

            finally:
                review_db.close()

        # Start background review
        session = await self.manager.start_review(
            task_id=task_id,
            repository_id=repository_id,
            review_coro=run_review,
        )

        return ReviewSessionInfo(
            task_id=task_id,
            repository_id=repository_id,
            session=session,
            is_reconnect=False,
        )

    async def _save_review_results(
        self,
        db: Session,
        task_id: str,
        repository_id: str,
        report: FinalReport,
    ) -> None:
        """Save review results and issues to the database."""
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if not db_task:
            return

        db_task.status = "completed"  # type: ignore[assignment]
        db_task.result = report.model_dump(mode="json")  # type: ignore[assignment]
        db_task.completed_at = datetime.utcnow()  # type: ignore[assignment]

        # Save issues to database for tracking
        for issue in report.issues:
            db_issue = Issue(
                task_id=task_id,
                repository_id=repository_id,
                issue_code=issue.id,
                severity=(
                    issue.severity.value
                    if hasattr(issue.severity, "value")
                    else str(issue.severity)
                ),
                category=(
                    issue.category.value
                    if hasattr(issue.category, "value")
                    else str(issue.category)
                ),
                rule=issue.rule,
                file=issue.file,
                line=issue.line,
                title=issue.title,
                description=issue.description,
                current_code=issue.current_code,
                suggested_fix=issue.suggested_fix,
                references=issue.references if issue.references else None,
                flagged_by=issue.flagged_by if issue.flagged_by else None,
                estimated_effort=issue.estimated_effort,
                estimated_files_count=issue.estimated_files_count,
            )
            db.add(db_issue)

        db.commit()

    async def generate_events(
        self,
        session_info: ReviewSessionInfo,
    ) -> AsyncIterator[dict[str, str]]:
        """
        Generate SSE events from review progress.

        Yields task_started, replays history for reconnections,
        then streams live events until completion.
        """
        session = session_info.session
        task_id = session_info.task_id
        is_reconnect = session_info.is_reconnect

        # Subscribe to session events
        queue = session.subscribe()

        try:
            # Emit task_started with task_id
            yield {
                "event": "task_started",
                "data": f'{{"task_id": "{task_id}", "reconnected": {str(is_reconnect).lower()}}}',
            }

            # Replay event history for reconnecting clients
            for history_event in session.get_history():
                yield history_event.to_sse()

            # If already completed, signal done
            if session.status != "running":
                return

            # Stream live events until done
            while True:
                try:
                    live_event: ProgressEvent | None = await asyncio.wait_for(
                        queue.get(), timeout=30.0
                    )

                    if live_event is None:
                        break

                    yield live_event.to_sse()

                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield {"event": "ping", "data": "{}"}

        except asyncio.CancelledError:
            # Client disconnected - DON'T cancel the review!
            pass

        finally:
            # Unsubscribe (review continues running)
            session.unsubscribe(queue)


def get_review_stream_service(db: Session) -> ReviewStreamService:
    """Factory function to create ReviewStreamService with dependencies."""
    return ReviewStreamService(db=db, review_manager=get_review_manager())
