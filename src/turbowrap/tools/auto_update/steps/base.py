"""Base class for workflow steps."""

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from ..config import get_autoupdate_settings
from ..models import StepStatus
from ..storage.s3_checkpoint import S3CheckpointManager

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseStep(ABC, Generic[T]):
    """Abstract base class for workflow steps.

    Each step:
    - Has a unique name and number
    - Can execute and produce a checkpoint
    - Can load/save checkpoints from S3
    - Supports retry logic with exponential backoff
    """

    def __init__(
        self,
        checkpoint_manager: S3CheckpointManager,
        repo_path: Path,
    ):
        """Initialize step.

        Args:
            checkpoint_manager: S3 checkpoint manager instance.
            repo_path: Path to the repository being analyzed.
        """
        self.checkpoint_manager = checkpoint_manager
        self.repo_path = Path(repo_path).resolve()
        self.settings = get_autoupdate_settings()

    @property
    @abstractmethod
    def step_name(self) -> str:
        """Unique step name (e.g., 'step1_analyze')."""
        ...

    @property
    @abstractmethod
    def step_number(self) -> int:
        """Step number (1-4)."""
        ...

    @property
    @abstractmethod
    def checkpoint_class(self) -> type[T]:
        """Pydantic model class for this step's checkpoint."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> T:
        """Execute the step and return a checkpoint.

        Subclasses must implement this method.

        Returns:
            Checkpoint with step results.
        """
        ...

    async def load_checkpoint(self, run_id: str) -> T | None:
        """Load previous checkpoint from S3.

        Args:
            run_id: Run identifier.

        Returns:
            Checkpoint or None if not found.
        """
        return await self.checkpoint_manager.load(
            run_id=run_id,
            step_name=self.step_name,
            model_class=self.checkpoint_class,
        )

    async def save_checkpoint(self, run_id: str, checkpoint: T) -> str:
        """Save checkpoint to S3.

        Args:
            run_id: Run identifier.
            checkpoint: Checkpoint to save.

        Returns:
            S3 URI of saved checkpoint.
        """
        return await self.checkpoint_manager.save(
            run_id=run_id,
            step_name=self.step_name,
            checkpoint=checkpoint,
        )

    def can_resume(self, checkpoint: T | None) -> bool:
        """Check if step can be resumed from checkpoint.

        Args:
            checkpoint: Previous checkpoint or None.

        Returns:
            True if step can be resumed.
        """
        if checkpoint is None:
            return False
        return checkpoint.status == StepStatus.COMPLETED

    def should_skip(self, checkpoint: T | None) -> bool:
        """Check if step should be skipped (already completed).

        Args:
            checkpoint: Previous checkpoint or None.

        Returns:
            True if step is already completed.
        """
        if checkpoint is None:
            return False
        return checkpoint.status == StepStatus.COMPLETED

    async def execute_with_retry(self, **kwargs) -> T:
        """Execute step with automatic retry on failure.

        Uses exponential backoff for retries.

        Returns:
            Checkpoint from successful execution.

        Raises:
            Last exception if all retries fail.
        """
        last_error = None
        max_retries = self.settings.max_retries
        delay = self.settings.retry_delay_seconds

        for attempt in range(max_retries):
            try:
                logger.info(f"Executing {self.step_name} (attempt {attempt + 1}/{max_retries})")
                return await self.execute(**kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"{self.step_name} failed (attempt {attempt + 1}): {e}")

                if attempt < max_retries - 1:
                    wait_time = delay * (2**attempt)  # Exponential backoff
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)

        logger.error(f"{self.step_name} failed after {max_retries} attempts")
        raise last_error  # type: ignore
