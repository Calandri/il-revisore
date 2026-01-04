"""Widget installation task using Claude Haiku."""

import hashlib
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..db.models import Repository, Task, WidgetApiKey
from ..db.models.base import generate_uuid
from ..llm.claude_cli import ClaudeCLI
from .base import BaseTask, TaskContext, TaskResult

logger = logging.getLogger(__name__)


class WidgetInstallTask(BaseTask):
    """Task to install TurboWrap widget using Claude Haiku."""

    @property
    def name(self) -> str:
        return "widget_install"

    @property
    def description(self) -> str:
        return "Install TurboWrap Issue Widget in repository"

    def execute(self, context: TaskContext) -> TaskResult:
        """Execute widget installation task.

        Args:
            context: Task context with db session and repo path.

        Returns:
            TaskResult with installation results.
        """
        started_at = datetime.utcnow()
        start_time = time.time()

        try:
            # Get or create task record
            task = self._get_or_create_task(context)
            task.status = "running"
            task.started_at = started_at
            context.db.commit()

            # Get repository info
            repo_id = context.config.get("repository_id")
            repo = context.db.query(Repository).filter(Repository.id == repo_id).first()
            if not repo:
                raise ValueError(f"Repository not found: {repo_id}")

            # Get or create widget API key
            raw_key = self._ensure_widget_key(context, repo)

            # Get team_id from config or repo
            team_id = context.config.get("team_id", "")

            # Build prompt for Claude Haiku
            prompt = f"""Install the TurboWrap Issue Widget in this repository.

## Configuration Values
- **Repository path**: {context.repo_path}
- **Repository ID**: {repo_id}
- **API Key**: {raw_key}
- **Team ID**: {team_id or "Not specified"}

Follow the instructions in the agent prompt to:
1. Detect the framework (Next.js, React, or HTML)
2. Find the correct file to modify
3. Install the widget with the configuration above

Use the exact API Key and Repository ID provided above.
"""

            # Run Claude Haiku with widget_installer.md agent
            agent_md_path = (
                Path(__file__).parent.parent.parent.parent / "agents" / "widget_installer.md"
            )

            logger.info(f"[WIDGET_INSTALL] Starting Claude Haiku with agent: {agent_md_path}")
            logger.info(f"[WIDGET_INSTALL] Working dir: {context.repo_path}")

            cli = ClaudeCLI(
                model="haiku",
                agent_md_path=agent_md_path,
                working_dir=context.repo_path,
                timeout=300,  # 5 minutes
                s3_prefix="widget-install",
            )

            result = cli.run_sync(
                prompt,
                operation_type="widget_install",
                repo_name=repo.name or "unknown",
            )

            # Update task with results
            completed_at = datetime.utcnow()
            duration = time.time() - start_time

            result_data: dict[str, Any] = {
                "output": result.output,
                "success": result.success,
                "duration_seconds": duration,
                "api_key_prefix": raw_key[:8],
            }

            if result.error:
                result_data["error"] = result.error

            task.status = "completed" if result.success else "failed"
            task.completed_at = completed_at
            task.result = result_data
            context.db.commit()

            return TaskResult(
                status="completed" if result.success else "failed",
                data=result_data,
                error=result.error,
                duration_seconds=duration,
                started_at=started_at,
                completed_at=completed_at,
            )

        except Exception as e:
            logger.exception(f"[WIDGET_INSTALL] Failed: {e}")
            duration = time.time() - start_time
            completed_at = datetime.utcnow()

            # Update task as failed
            task = context.db.query(Task).filter(Task.id == context.config.get("task_id")).first()
            if task:
                task.status = "failed"
                task.completed_at = completed_at
                task.error = str(e)
                context.db.commit()

            return TaskResult(
                status="failed",
                error=str(e),
                duration_seconds=duration,
                started_at=started_at,
                completed_at=completed_at,
            )

    def _get_or_create_task(self, context: TaskContext) -> Task:
        """Get existing task or create new one."""
        task_id = context.config.get("task_id")

        if task_id:
            task = context.db.query(Task).filter(Task.id == task_id).first()
            if task:
                return task

        # Create new task
        task = Task(
            repository_id=context.config.get("repository_id"),
            type=self.name,
            status="pending",
            config=context.config,
        )
        context.db.add(task)
        context.db.commit()
        context.db.refresh(task)

        return task

    def _ensure_widget_key(self, context: TaskContext, repo: Repository) -> str:
        """Get existing or create new widget API key.

        If a key exists, regenerates it to get the raw key.
        If no key exists, creates a new one.

        Args:
            context: Task context with db session.
            repo: Repository model instance.

        Returns:
            Raw API key (twk_xxx...).
        """
        repo_id = str(repo.id)

        # Check for existing active key
        existing = (
            context.db.query(WidgetApiKey)
            .filter(
                WidgetApiKey.repository_id == repo_id,
                WidgetApiKey.is_active.is_(True),
            )
            .first()
        )

        if existing:
            # Deactivate existing key - we need to regenerate to get raw key
            logger.info(f"[WIDGET_INSTALL] Deactivating existing key: {existing.key_prefix}")
            existing.is_active = False
            context.db.commit()

        # Generate new key
        random_part = secrets.token_hex(16)  # 32 hex chars
        raw_key = f"twk_{random_part}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]  # "twk_xxxx"

        # Create widget key record
        widget_key = WidgetApiKey(
            id=generate_uuid(),
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=f"Widget Key - {repo.name} (Auto Install)",
            repository_id=repo_id,
            is_active=True,
        )

        context.db.add(widget_key)
        context.db.commit()

        logger.info(f"[WIDGET_INSTALL] Created new widget key: {key_prefix}...")

        return raw_key
