"""Test execution task."""

import asyncio
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from ..db.models import Repository, TestCase, TestRun, TestSuite
from .base import BaseTask, TaskConfig, TaskContext, TaskResult
from .test_parsers import PytestParser
from .test_parsers.base import BaseTestParser

logger = logging.getLogger(__name__)


class TestTaskConfig(TaskConfig):
    """Configuration for test execution task."""

    run_id: str = Field(..., description="TestRun UUID to execute")
    timeout_seconds: int = Field(default=300, ge=30, le=3600, description="Max execution time")


class TestTask(BaseTask):
    """Execute tests for a test suite.

    Runs tests using the configured framework and command,
    parses output, and saves results to database.
    """

    # Framework -> Parser mapping
    PARSERS: dict[str, type[BaseTestParser]] = {
        "pytest": PytestParser,
        # Future: "playwright", "vitest", "jest", "cypress"
    }

    @property
    def name(self) -> str:
        return "test"

    @property
    def description(self) -> str:
        return "Execute test suite and collect results"

    @property
    def config_class(self) -> type[TestTaskConfig]:
        return TestTaskConfig

    def execute(self, context: TaskContext) -> TaskResult:
        """Execute test task synchronously."""
        return asyncio.run(self.execute_async(context))

    async def execute_async(self, context: TaskContext) -> TaskResult:
        """Execute test task.

        Args:
            context: Task context with db session and repo path.

        Returns:
            TaskResult with test results.
        """
        started_at = datetime.utcnow()
        start_time = time.time()
        config: TestTaskConfig = self.validate_config(context.config)  # type: ignore[assignment]

        try:
            # Load TestRun
            run = context.db.query(TestRun).filter(TestRun.id == config.run_id).first()
            if not run:
                raise ValueError(f"TestRun not found: {config.run_id}")

            # Load TestSuite
            suite = context.db.query(TestSuite).filter(TestSuite.id == run.suite_id).first()
            if not suite:
                raise ValueError(f"TestSuite not found: {run.suite_id}")

            # Load Repository
            repo = context.db.query(Repository).filter(Repository.id == suite.repository_id).first()
            if not repo:
                raise ValueError(f"Repository not found: {suite.repository_id}")

            repo_path = Path(repo.local_path)
            if not repo_path.exists():
                raise ValueError(f"Repository path not found: {repo_path}")

            # Update run status
            run.status = "running"
            run.started_at = started_at

            # Get git info
            branch, commit_sha = self._get_git_info(repo_path)
            run.branch = branch
            run.commit_sha = commit_sha

            context.db.commit()

            # Get parser for framework
            parser = self._get_parser(suite.framework)

            # Build command
            command = self._build_command(suite, parser, repo_path)

            logger.info(f"Running tests: {' '.join(command)}")

            # Execute tests
            result = await self._run_tests(
                command=command,
                cwd=repo_path,
                timeout=config.timeout_seconds,
                env_vars=parser.get_env_vars(),
            )

            # Parse results
            parsed = parser.parse(result["output"], result["exit_code"])

            # Save test cases
            self._save_test_cases(context.db, run, parsed.test_cases)

            # Update run with results
            duration = time.time() - start_time
            completed_at = datetime.utcnow()

            run.status = "passed" if parsed.failed == 0 and parsed.errors == 0 else "failed"
            run.completed_at = completed_at
            run.duration_seconds = parsed.duration_seconds or duration
            run.total_tests = parsed.total
            run.passed = parsed.passed
            run.failed = parsed.failed
            run.skipped = parsed.skipped
            run.errors = parsed.errors

            context.db.commit()

            return TaskResult(
                status="completed",
                data={
                    "run_id": str(run.id),
                    "status": run.status,
                    "total": parsed.total,
                    "passed": parsed.passed,
                    "failed": parsed.failed,
                    "skipped": parsed.skipped,
                    "duration_seconds": run.duration_seconds,
                },
                duration_seconds=duration,
                started_at=started_at,
                completed_at=completed_at,
            )

        except asyncio.TimeoutError:
            return self._handle_error(
                context, config.run_id, "Test execution timed out", started_at, start_time
            )
        except subprocess.CalledProcessError as e:
            return self._handle_error(
                context, config.run_id, f"Test command failed: {e}", started_at, start_time
            )
        except Exception as e:
            logger.exception(f"Test execution failed: {e}")
            return self._handle_error(context, config.run_id, str(e), started_at, start_time)

    def _get_parser(self, framework: str) -> BaseTestParser:
        """Get parser for framework."""
        parser_class = self.PARSERS.get(framework)
        if not parser_class:
            # Default to pytest parser with warning
            logger.warning(f"No parser for framework '{framework}', using pytest parser")
            parser_class = PytestParser
        return parser_class()

    def _build_command(
        self, suite: TestSuite, parser: BaseTestParser, repo_path: Path
    ) -> list[str]:
        """Build test command."""
        if suite.command:
            # Use custom command, replace {path} placeholder
            cmd = suite.command.replace("{path}", suite.path)
            return cmd.split()

        # Use parser's default command
        test_path = str(repo_path / suite.path)
        return parser.get_default_command(test_path)

    async def _run_tests(
        self,
        command: list[str],
        cwd: Path,
        timeout: int,
        env_vars: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run test command as subprocess.

        Args:
            command: Command to execute.
            cwd: Working directory.
            timeout: Timeout in seconds.
            env_vars: Additional environment variables.

        Returns:
            Dict with output and exit_code.
        """
        import os

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
        )

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")
            return {"output": output, "exit_code": process.returncode or 0}
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise

    def _get_git_info(self, repo_path: Path) -> tuple[str | None, str | None]:
        """Get current git branch and commit SHA."""
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                stderr=subprocess.DEVNULL,
            )
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                stderr=subprocess.DEVNULL,
            )
            return branch.decode().strip(), commit.decode().strip()[:40]
        except subprocess.CalledProcessError:
            return None, None

    def _save_test_cases(self, db: Any, run: TestRun, test_cases: list[Any]) -> None:
        """Save test case results to database."""
        for tc in test_cases:
            test_case = TestCase(
                run_id=str(run.id),
                name=tc.name,
                class_name=tc.class_name,
                file=tc.file,
                line=tc.line,
                status=tc.status,
                duration_ms=tc.duration_ms,
                error_message=tc.error_message,
                stack_trace=tc.stack_trace,
                metadata_=tc.metadata,
            )
            db.add(test_case)

    def _handle_error(
        self,
        context: TaskContext,
        run_id: str,
        error_message: str,
        started_at: datetime,
        start_time: float,
    ) -> TaskResult:
        """Handle execution error and update run status."""
        duration = time.time() - start_time
        completed_at = datetime.utcnow()

        try:
            run = context.db.query(TestRun).filter(TestRun.id == run_id).first()
            if run:
                run.status = "error"
                run.error_message = error_message
                run.completed_at = completed_at
                run.duration_seconds = duration
                context.db.commit()
        except Exception as e:
            logger.error(f"Failed to update run status: {e}")

        return TaskResult(
            status="failed",
            error=error_message,
            duration_seconds=duration,
            started_at=started_at,
            completed_at=completed_at,
        )


async def run_test_task(run_id: str, db_session: Any, repo_path: Path) -> TaskResult:
    """Convenience function to run a test task.

    Args:
        run_id: TestRun UUID.
        db_session: Database session.
        repo_path: Repository local path.

    Returns:
        TaskResult with execution results.
    """
    task = TestTask()
    context = TaskContext(
        db=db_session,
        repo_path=repo_path,
        config={"run_id": run_id, "repository_id": ""},
    )
    return await task.execute_async(context)
