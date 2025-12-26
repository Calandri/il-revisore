"""Develop task implementation."""

import time
from datetime import datetime
from typing import Any

from ..db.models import AgentRun, Task
from ..llm import ClaudeClient, GeminiClient, load_prompt
from .base import BaseTask, TaskContext, TaskResult


class DevelopTask(BaseTask):
    """Development task using AI agents to write/modify code."""

    @property
    def name(self) -> str:
        return "develop"

    @property
    def description(self) -> str:
        return "AI-assisted code development"

    def execute(self, context: TaskContext) -> TaskResult:
        """Execute develop task.

        Args:
            context: Task context with db session and repo path.

        Returns:
            TaskResult with development results.
        """
        started_at = datetime.utcnow()
        start_time = time.time()

        try:
            # Get configuration
            instruction = context.config.get("instruction", "")
            target_files = context.config.get("files", [])

            if not instruction:
                raise ValueError("Develop task requires 'instruction' in config")

            # Get or create task record
            task = self._get_or_create_task(context)

            # Update task status
            task.status = "running"  # type: ignore[assignment]
            task.started_at = started_at  # type: ignore[assignment]
            context.db.commit()

            # First, analyze with Gemini Flash
            analysis = self._analyze_context(context, instruction, target_files)

            # Then, develop with Claude Opus
            development = self._develop_code(context, task, instruction, target_files, analysis)

            # Update task with results
            completed_at = datetime.utcnow()
            duration = time.time() - start_time

            result_data: dict[str, Any] = {
                "analysis": analysis,
                "development": development,
                "duration_seconds": duration,
            }
            task.status = "completed"  # type: ignore[assignment]
            task.completed_at = completed_at  # type: ignore[assignment]
            task.result = result_data  # type: ignore[assignment]
            context.db.commit()

            return TaskResult(
                status="completed",
                data=result_data,
                duration_seconds=duration,
                started_at=started_at,
                completed_at=completed_at,
            )

        except Exception as e:
            duration = time.time() - start_time
            completed_at = datetime.utcnow()

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

    def _analyze_context(
        self,
        context: TaskContext,
        instruction: str,
        target_files: list[str],
    ) -> str:
        """Analyze context with Gemini Flash.

        Args:
            context: Task context.
            instruction: Development instruction.
            target_files: Target file paths.

        Returns:
            Analysis text.
        """
        gemini = GeminiClient()

        # Read target files
        file_contents = []
        for file_path in target_files:
            full_path = context.repo_path / file_path
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8", errors="ignore")[:4000]
                file_contents.append(f"## {file_path}\n```\n{content}\n```")

        prompt = f"""Analyze this development task and provide context:

## Task
{instruction}

## Target Files
{chr(10).join(file_contents) if file_contents else "No specific files provided"}

Provide:
1. Understanding of what needs to be done
2. Key files/modules that might be affected
3. Potential challenges or considerations
4. Suggested approach

Be concise and actionable.
"""

        return gemini.generate(prompt)

    def _develop_code(
        self,
        context: TaskContext,
        task: Task,
        instruction: str,
        target_files: list[str],
        analysis: str,
    ) -> str:
        """Develop code with Claude Opus.

        Args:
            context: Task context.
            task: Task record.
            instruction: Development instruction.
            target_files: Target file paths.
            analysis: Analysis from Gemini.

        Returns:
            Development result text.
        """
        claude = ClaudeClient()

        # Read target files
        file_contents = []
        for file_path in target_files:
            full_path = context.repo_path / file_path
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8", errors="ignore")[:6000]
                file_contents.append(f"## {file_path}\n```\n{content}\n```")

        # Try to load dev prompt
        try:
            # Detect file type for appropriate prompt
            if any(f.endswith(".py") for f in target_files):
                system_prompt = load_prompt("dev_be")
            else:
                system_prompt = load_prompt("dev_fe")
        except FileNotFoundError:
            system_prompt = "You are a senior software developer. Write clean, maintainable code."

        prompt = f"""Complete this development task:

## Task
{instruction}

## Analysis
{analysis}

## Current Files
{chr(10).join(file_contents) if file_contents else "New files to create"}

Provide:
1. Code changes or new code (with full file paths)
2. Explanation of changes
3. Any additional files needed
4. Testing suggestions

Format code blocks with the file path, e.g.:
```python:path/to/file.py
# code here
```
"""

        response = claude.generate_with_metadata(prompt, system_prompt)

        # Log agent run
        agent_run = AgentRun(
            task_id=task.id,
            agent_type="claude_opus",
            agent_name="developer",
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            output={"files": target_files},
        )
        context.db.add(agent_run)
        context.db.commit()

        return response.content
