"""Orchestrator for the auto-update workflow."""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from .config import get_autoupdate_settings
from .models import AutoUpdateRun, Step1Checkpoint, Step2Checkpoint, Step3Checkpoint, Step4Checkpoint
from .steps.step1_analyze import AnalyzeFunctionalitiesStep
from .steps.step2_research import WebResearchStep
from .steps.step3_evaluate import EvaluateFeaturesStep
from .steps.step4_create_issues import CreateLinearIssuesStep
from .storage.markdown_writer import MarkdownWriter
from .storage.s3_checkpoint import S3CheckpointManager

logger = logging.getLogger(__name__)

# Type for progress callback: (step_name, step_number, message)
ProgressCallback = Callable[[str, int, str], Awaitable[None]]


class AutoUpdateOrchestrator:
    """Orchestrator for the 4-step auto-update workflow.

    Coordinates:
    1. Analyze codebase functionalities
    2. Research competitors and best practices
    3. Evaluate and propose new features
    4. Create Linear issues with HITL questions

    Each step saves a checkpoint to S3 for recovery.
    """

    def __init__(
        self,
        repo_path: Path,
        run_id: str | None = None,
    ):
        """Initialize orchestrator.

        Args:
            repo_path: Path to the repository to analyze.
            run_id: Optional run ID (generated if not provided).
        """
        self.repo_path = Path(repo_path).resolve()
        self.run_id = run_id or f"autoupdate_{uuid.uuid4().hex[:12]}"
        self.settings = get_autoupdate_settings()
        self.checkpoint_manager = S3CheckpointManager()
        self.markdown_writer = MarkdownWriter(self.repo_path)

        # Initialize steps
        self.step1 = AnalyzeFunctionalitiesStep(
            checkpoint_manager=self.checkpoint_manager,
            repo_path=self.repo_path,
        )
        self.step2 = WebResearchStep(
            checkpoint_manager=self.checkpoint_manager,
            repo_path=self.repo_path,
        )
        self.step3 = EvaluateFeaturesStep(
            checkpoint_manager=self.checkpoint_manager,
            repo_path=self.repo_path,
        )
        self.step4 = CreateLinearIssuesStep(
            checkpoint_manager=self.checkpoint_manager,
            repo_path=self.repo_path,
        )

    async def run_all(
        self,
        progress_callback: ProgressCallback | None = None,
        resume_from: int | None = None,
    ) -> AutoUpdateRun:
        """Execute all 4 steps in sequence.

        Args:
            progress_callback: Optional async callback for progress updates.
            resume_from: Optional step number to resume from (1-4).

        Returns:
            AutoUpdateRun with all step results.
        """
        run = AutoUpdateRun(
            run_id=self.run_id,
            started_at=datetime.utcnow(),
            repo_path=str(self.repo_path),
        )

        try:
            # Step 1: Analyze
            if resume_from is None or resume_from <= 1:
                await self._emit(progress_callback, "step1", 1, "Analyzing codebase functionalities...")
                run.step1 = await self.step1.execute_with_retry()
                await self.step1.save_checkpoint(self.run_id, run.step1)
                run.current_step = 2

                # Write FUNZIONALITA.md
                if run.step1.functionalities:
                    await self._emit(progress_callback, "step1", 1, "Writing FUNZIONALITA.md...")
                    self.markdown_writer.write_functionalities(run.step1.functionalities)
            else:
                # Load existing checkpoint
                run.step1 = await self.step1.load_checkpoint(self.run_id)

            # Step 2: Research
            if resume_from is None or resume_from <= 2:
                await self._emit(progress_callback, "step2", 2, "Researching competitors and best practices...")
                run.step2 = await self.step2.execute_with_retry(step1_checkpoint=run.step1)
                await self.step2.save_checkpoint(self.run_id, run.step2)
                run.current_step = 3
            else:
                run.step2 = await self.step2.load_checkpoint(self.run_id)

            # Step 3: Evaluate
            if resume_from is None or resume_from <= 3:
                await self._emit(progress_callback, "step3", 3, "Evaluating potential new features...")
                run.step3 = await self.step3.execute_with_retry(
                    step1_checkpoint=run.step1,
                    step2_checkpoint=run.step2,
                )
                await self.step3.save_checkpoint(self.run_id, run.step3)
                run.current_step = 4
            else:
                run.step3 = await self.step3.load_checkpoint(self.run_id)

            # Step 4: Create Issues
            if resume_from is None or resume_from <= 4:
                await self._emit(progress_callback, "step4", 4, "Creating Linear issues...")
                run.step4 = await self.step4.execute_with_retry(step3_checkpoint=run.step3)
                await self.step4.save_checkpoint(self.run_id, run.step4)
            else:
                run.step4 = await self.step4.load_checkpoint(self.run_id)

            run.completed_at = datetime.utcnow()
            await self._emit(progress_callback, "complete", 4, "Auto-update workflow complete!")

            return run

        except Exception as e:
            await self._emit(progress_callback, "error", run.current_step, str(e))
            logger.error(f"Auto-update workflow failed at step {run.current_step}: {e}")
            raise

    async def run_step(self, step_number: int) -> AutoUpdateRun:
        """Execute a single step with checkpoint loading.

        Args:
            step_number: Step to execute (1-4).

        Returns:
            AutoUpdateRun with results up to that step.

        Raises:
            ValueError: If step number is invalid.
        """
        if step_number < 1 or step_number > 4:
            raise ValueError(f"Step number must be 1-4, got {step_number}")

        run = AutoUpdateRun(
            run_id=self.run_id,
            started_at=datetime.utcnow(),
            repo_path=str(self.repo_path),
        )

        # Load previous checkpoints
        if step_number >= 2:
            run.step1 = await self.step1.load_checkpoint(self.run_id)
            if not run.step1:
                raise ValueError("Step 1 checkpoint not found. Run step 1 first.")

        if step_number >= 3:
            run.step2 = await self.step2.load_checkpoint(self.run_id)
            if not run.step2:
                raise ValueError("Step 2 checkpoint not found. Run step 2 first.")

        if step_number >= 4:
            run.step3 = await self.step3.load_checkpoint(self.run_id)
            if not run.step3:
                raise ValueError("Step 3 checkpoint not found. Run step 3 first.")

        # Execute requested step
        if step_number == 1:
            run.step1 = await self.step1.execute_with_retry()
            await self.step1.save_checkpoint(self.run_id, run.step1)
            if run.step1.functionalities:
                self.markdown_writer.write_functionalities(run.step1.functionalities)

        elif step_number == 2:
            run.step2 = await self.step2.execute_with_retry(step1_checkpoint=run.step1)
            await self.step2.save_checkpoint(self.run_id, run.step2)

        elif step_number == 3:
            run.step3 = await self.step3.execute_with_retry(
                step1_checkpoint=run.step1,
                step2_checkpoint=run.step2,
            )
            await self.step3.save_checkpoint(self.run_id, run.step3)

        elif step_number == 4:
            run.step4 = await self.step4.execute_with_retry(step3_checkpoint=run.step3)
            await self.step4.save_checkpoint(self.run_id, run.step4)

        run.current_step = step_number
        return run

    async def resume(self) -> AutoUpdateRun:
        """Resume from the last saved checkpoint.

        Returns:
            AutoUpdateRun continuing from where it left off.
        """
        # Determine which step to resume from
        status = await self.checkpoint_manager.get_run_status(self.run_id)

        if not status:
            logger.info("No previous checkpoints found, starting from step 1")
            return await self.run_all()

        resume_from = status.get("current_step", 1)
        logger.info(f"Resuming from step {resume_from}")

        return await self.run_all(resume_from=resume_from)

    async def get_status(self) -> dict | None:
        """Get status of current run.

        Returns:
            Status dict or None if no run found.
        """
        return await self.checkpoint_manager.get_run_status(self.run_id)

    async def _emit(
        self,
        callback: ProgressCallback | None,
        step: str,
        number: int,
        message: str,
    ) -> None:
        """Emit progress update.

        Args:
            callback: Optional callback function.
            step: Step name.
            number: Step number.
            message: Progress message.
        """
        logger.info(f"[Step {number}] {message}")
        if callback:
            await callback(step, number, message)
