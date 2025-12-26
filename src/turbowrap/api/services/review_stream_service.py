"""
Review stream service - handles business logic for streaming reviews.

Extracted from the fat controller in tasks.py to follow Single Responsibility Principle.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ...db.models import Issue, Repository, Task
from ...db.session import get_session_local
from ...review.models.progress import ProgressEvent, ProgressEventType
from ...review.models.review import (
    ReviewMode,
    ReviewOptions,
    ReviewRequest,
    ReviewRequestSource,
)
from ...review.orchestrator import Orchestrator
from ..review_manager import ReviewManager, ReviewSession, get_review_manager

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

    def __init__(self, db: Session, review_manager: ReviewManager):
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
        challenger_enabled: bool,
    ) -> Task:
        """Create a new task record in the database."""
        task = Task(
            repository_id=repository_id,
            type="review",
            status="running",
            config={
                "mode": mode,
                "challenger_enabled": challenger_enabled,
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
        challenger_enabled: bool,
        include_functional: bool,
    ) -> ReviewSessionInfo:
        """
        Start a new review or reconnect to an existing one.

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

        # Create new task record
        task = self.create_task_record(repository_id, mode, challenger_enabled)
        task_id = task.id

        # Capture values for the closure
        local_path = repo.local_path
        review_mode = mode
        repo_workspace_path = repo.workspace_path  # Monorepo workspace scope

        # Create the review coroutine
        async def run_review(session: ReviewSession):
            """Run the review in background."""
            SessionLocal = get_session_local()
            review_db = SessionLocal()

            try:
                orchestrator = Orchestrator()

                async def progress_callback(event: ProgressEvent):
                    """Callback to add events to session."""
                    session.add_event(event)

                request = ReviewRequest(
                    type="directory",
                    source=ReviewRequestSource(
                        directory=local_path,
                        workspace_path=repo_workspace_path,
                    ),
                    options=ReviewOptions(
                        mode=ReviewMode.INITIAL if review_mode == "initial" else ReviewMode.DIFF,
                        challenger_enabled=challenger_enabled,
                        include_functional=include_functional,
                    ),
                )

                report = await orchestrator.review(request, progress_callback)

                # Save results
                await self._save_review_results(
                    review_db, task_id, repository_id, report
                )

            except asyncio.CancelledError:
                db_task = review_db.query(Task).filter(Task.id == task_id).first()
                if db_task:
                    db_task.status = "cancelled"
                    db_task.completed_at = datetime.utcnow()
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
                    db_task.status = "failed"
                    db_task.error = str(e)
                    db_task.completed_at = datetime.utcnow()
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
        report,
    ) -> None:
        """Save review results and issues to the database."""
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if not db_task:
            return

        db_task.status = "completed"
        db_task.result = report.model_dump(mode="json")
        db_task.completed_at = datetime.utcnow()

        # Save issues to database for tracking
        for issue in report.issues:
            db_issue = Issue(
                task_id=task_id,
                repository_id=repository_id,
                issue_code=issue.id,
                severity=issue.severity.value if hasattr(issue.severity, "value") else str(issue.severity),
                category=issue.category.value if hasattr(issue.category, "value") else str(issue.category),
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
    ) -> AsyncIterator[dict]:
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
            for event in session.get_history():
                yield event.to_sse()

            # If already completed, signal done
            if session.status != "running":
                return

            # Stream live events until done
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    if event is None:
                        break

                    yield event.to_sse()

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
