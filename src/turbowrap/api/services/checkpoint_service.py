"""Checkpoint service for review resume functionality."""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from turbowrap.db.models import ReviewCheckpoint

logger = logging.getLogger(__name__)


class CheckpointService:
    """Service for managing review checkpoints."""

    def __init__(self, db: Session):
        self.db = db

    def get_completed_reviewers(self, task_id: str) -> dict[str, ReviewCheckpoint]:
        """Get all completed checkpoints for a task.

        Returns:
            Dict mapping reviewer_name -> checkpoint
        """
        checkpoints = (
            self.db.query(ReviewCheckpoint)
            .filter(
                ReviewCheckpoint.task_id == task_id,
                ReviewCheckpoint.status == "completed",
            )
            .all()
        )
        return {str(cp.reviewer_name): cp for cp in checkpoints}

    def get_all_checkpoints(self, task_id: str) -> list[ReviewCheckpoint]:
        """Get all checkpoints for a task (any status).

        Returns:
            List of checkpoints
        """
        return self.db.query(ReviewCheckpoint).filter(ReviewCheckpoint.task_id == task_id).all()

    def save_checkpoint(
        self,
        task_id: str,
        reviewer_name: str,
        issues: list[Any],
        final_satisfaction: float,
        iterations: int,
        model_usage: list[dict[str, Any]],
        started_at: datetime,
        status: str = "completed",
    ) -> ReviewCheckpoint:
        """Save or update a reviewer checkpoint.

        Uses upsert logic: if checkpoint exists, update it.

        Args:
            task_id: The task ID
            reviewer_name: Name of the reviewer
            issues: List of Issue objects or dicts
            final_satisfaction: Challenger satisfaction score (0-100)
            iterations: Number of challenger iterations
            model_usage: Token/cost info
            started_at: When the reviewer started
            status: 'completed' or 'failed'

        Returns:
            The saved checkpoint
        """
        # Serialize issues to JSON-compatible format
        issues_data: list[dict[str, Any]] = []
        for issue in issues:
            if hasattr(issue, "model_dump"):
                issues_data.append(issue.model_dump(mode="json"))
            elif hasattr(issue, "dict"):
                issues_data.append(issue.dict())
            elif isinstance(issue, dict):
                issues_data.append(issue)
            else:
                logger.warning(f"Unknown issue type: {type(issue)}")

        # Check if checkpoint already exists
        existing = (
            self.db.query(ReviewCheckpoint)
            .filter(
                ReviewCheckpoint.task_id == task_id,
                ReviewCheckpoint.reviewer_name == reviewer_name,
            )
            .first()
        )

        if existing:
            # Update existing
            existing.status = status  # type: ignore[assignment]
            existing.issues_data = issues_data  # type: ignore[assignment]
            existing.final_satisfaction = final_satisfaction  # type: ignore[assignment]
            existing.iterations = iterations  # type: ignore[assignment]
            existing.model_usage = model_usage  # type: ignore[assignment]
            existing.started_at = started_at  # type: ignore[assignment]
            existing.completed_at = datetime.utcnow()  # type: ignore[assignment]
            checkpoint = existing
        else:
            # Create new
            checkpoint = ReviewCheckpoint(
                task_id=task_id,
                reviewer_name=reviewer_name,
                status=status,
                issues_data=issues_data,
                final_satisfaction=final_satisfaction,
                iterations=iterations,
                model_usage=model_usage,
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )
            self.db.add(checkpoint)

        self.db.commit()
        self.db.refresh(checkpoint)

        logger.info(
            f"Saved checkpoint for {reviewer_name}: status={status}, "
            f"issues={len(issues_data)}, satisfaction={final_satisfaction}"
        )
        return checkpoint

    def delete_checkpoints(self, task_id: str) -> int:
        """Delete all checkpoints for a task (used when starting fresh).

        Returns:
            Number of deleted checkpoints
        """
        count = self.db.query(ReviewCheckpoint).filter(ReviewCheckpoint.task_id == task_id).delete()
        self.db.commit()
        logger.info(f"Deleted {count} checkpoints for task {task_id}")
        return count

    def restore_issues_from_checkpoint(
        self,
        checkpoint: ReviewCheckpoint,
    ) -> tuple[list[Any], float, int]:
        """Restore issues and metadata from a checkpoint.

        Returns:
            (issues_data, final_satisfaction, iterations)
            Note: issues_data is a list of dicts, caller should convert to Issue objects
        """
        issues_data: list[Any] = list(checkpoint.issues_data) if checkpoint.issues_data else []
        satisfaction: float = (
            float(checkpoint.final_satisfaction) if checkpoint.final_satisfaction else 0.0
        )
        iters: int = int(checkpoint.iterations) if checkpoint.iterations else 1
        return (issues_data, satisfaction, iters)


def get_checkpoint_service(db: Session) -> CheckpointService:
    """Factory function for CheckpointService."""
    return CheckpointService(db)
