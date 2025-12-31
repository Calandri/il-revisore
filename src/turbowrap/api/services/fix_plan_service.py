"""
Fix plan service - handles execution plan generation for fixing issues.

Extracted from the fat controller in fix.py to follow Single Responsibility Principle.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from turbowrap.db.models import Issue
from turbowrap.fix.models import (
    ExecutionStep,
    IssueContextInfo,
    IssueEntry,
    IssuePlan,
    IssueTodo,
    MasterTodo,
    MasterTodoSummary,
)
from turbowrap.fix.todo_manager import TodoManager
from turbowrap.llm.claude_cli import ClaudeCLI
from turbowrap.review.reviewers.utils.json_extraction import parse_llm_json

if TYPE_CHECKING:
    from turbowrap.db.models import Repository

logger = logging.getLogger(__name__)

# Agent file path
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
FIX_PLANNER_AGENT = AGENTS_DIR / "fix_planner.md"


@dataclass
class PlanStepInfo:
    """Info about a single execution step."""

    step: int
    issue_codes: list[str]
    reason: str | None


@dataclass
class PlanResult:
    """Result of the planning phase."""

    session_id: str
    master_todo_path: str
    issue_count: int
    step_count: int
    execution_steps: list[PlanStepInfo]
    ready_to_execute: bool


class FixPlanService:
    """Service for generating execution plans for fixing issues.

    Analyzes issues, generates execution steps (parallel vs serial),
    and creates TODO files for the fixer agents.
    """

    def __init__(
        self,
        repo: Repository,
        db: Session,
    ) -> None:
        """Initialize the service.

        Args:
            repo: Repository to work with.
            db: Database session.
        """
        self.repo = repo
        self.db = db
        self.cli: ClaudeCLI | None = None

    async def create_plan(
        self,
        issues: list[Issue],
        clarify_session_id: str,
        enable_subtasks: bool | None = None,
    ) -> PlanResult:
        """Create execution plan for fixing issues.

        Args:
            issues: Issues to plan fixes for.
            clarify_session_id: Claude session ID from clarification phase.
            enable_subtasks: Override for subtask splitting. If None, uses config default.

        Returns:
            PlanResult with execution steps and TODO paths.
        """
        # Store subtasks setting (request override or config default)
        self._enable_subtasks = enable_subtasks

        # Build prompt
        prompt = self._build_planning_prompt(issues)

        # Run CLI
        result = await self._run_planner(prompt, issues, clarify_session_id)

        # Parse response
        data = self._parse_planner_response(result.output, result.session_id, issues)

        # Build TODO models
        master_todo, issue_todos = self._build_todos(data, issues, result.session_id)

        # Save TODO files
        paths = await self._save_todos(result.session_id, master_todo, issue_todos)

        # Save plans to DB
        self._save_plans_to_db(issue_todos, issues)

        # Build result
        return self._build_result(result.session_id, master_todo, paths)

    def _format_issues(self, issues: list[Issue]) -> str:
        """Format issues for the planning prompt, including clarifications."""
        lines = []
        for i, issue in enumerate(issues, 1):
            lines.append(f"## Issue {i}: {issue.issue_code}")
            lines.append(f"**Title:** {issue.title}")
            lines.append(f"**File:** {issue.file}:{issue.line or '?'}")
            lines.append(f"**Severity:** {issue.severity}")
            lines.append(f"**Description:** {issue.description}")
            if issue.suggested_fix:
                lines.append(f"**Suggested Fix:** {issue.suggested_fix}")

            # Include clarifications if present (redundancy for robustness)
            clarifications = list(issue.clarifications or [])
            if clarifications:
                lines.append("\n**Clarifications (from user):**")
                for c in clarifications:
                    q = c.get("question", "")
                    a = c.get("answer", "")
                    lines.append(f"- Q: {q}")
                    lines.append(f"  A: {a}")

            lines.append("")
        return "\n".join(lines)

    def _build_planning_prompt(self, issues: list[Issue]) -> str:
        """Build the planning prompt for Claude."""
        from turbowrap.config import get_settings

        settings = get_settings()
        issues_text = self._format_issues(issues)

        # Use request override if set, otherwise config default
        enable_subtasks = (
            self._enable_subtasks
            if self._enable_subtasks is not None
            else settings.fix_planner.enable_subtasks
        )

        # Build subtasks configuration note
        if enable_subtasks:
            subtasks_note = f"""
## Sub-Task Splitting: ENABLED

You MAY split issues into parallel sub-tasks if:
- Issue affects {settings.fix_planner.min_files_for_split}+ independent files
- Each file can be modified independently
- Max {settings.fix_planner.max_subtasks_per_issue} sub-tasks per issue

See "Sub-Task Splitting" section in your instructions for format.
"""
        else:
            subtasks_note = """
## Sub-Task Splitting: DISABLED

Do NOT split issues into sub-tasks. Each issue = 1 agent.
Use standard output format (no parent_issue or target_files fields).
"""

        return f"""Proceed to the PLANNING phase.
{subtasks_note}

Issues to plan:

{issues_text}

Generate the execution plan. For each issue:
1. Read the target file to understand context
2. Search for similar patterns in the codebase
3. Identify dependencies between issues
4. Generate a step-by-step plan
5. **IMPORTANT**: If clarifications are provided, incorporate user preferences into your plan

Respond ONLY with valid JSON in the PHASE 2 (Planning) format:
{{
  "phase": "planning",
  "master_todo": {{ ... }},
  "issue_todos": [ ... ]
}}"""

    async def _run_planner(
        self,
        prompt: str,
        issues: list[Issue],
        clarify_session_id: str,
    ) -> Any:
        """Run Claude CLI for planning.

        Args:
            prompt: The prompt to send.
            issues: Issues being planned.
            clarify_session_id: Session ID to resume.

        Returns:
            ClaudeCLI result.

        Raises:
            Exception: If CLI fails.
        """
        from turbowrap.api.services.operation_tracker import get_tracker

        working_dir = Path(self.repo.local_path) if self.repo.local_path else None
        agent_path = FIX_PLANNER_AGENT if FIX_PLANNER_AGENT.exists() else None
        logger.info(f"[PLAN] Creating CLI with working_dir={working_dir}, agent={agent_path}")

        cli = ClaudeCLI(
            working_dir=working_dir,
            model="opus",
            agent_md_path=agent_path,
        )
        self.cli = cli

        # Resume the clarify session to preserve context
        logger.info(f"[PLAN] Running CLI (resuming session={clarify_session_id})")

        # Update clarify operation to show we're now in planning phase
        tracker = get_tracker()
        tracker.update(
            clarify_session_id,
            details={"phase": "planning"},
        )

        result = await cli.run(
            prompt=prompt,
            operation_type="fix_planning",
            repo_name=str(self.repo.name) if self.repo.name else "unknown",
            resume_session_id=clarify_session_id,
            operation_details={
                "parent_session_id": clarify_session_id,
                "issue_codes": [i.issue_code for i in issues if i.issue_code],
                "issue_ids": [str(i.id) for i in issues],
                "issue_count": len(issues),
            },
        )
        logger.info(f"[PLAN] CLI run complete, output length: {len(result.output or '')}")

        if not result.output:
            raise Exception("No response from planner")
        if not result.session_id:
            raise Exception("Claude CLI did not return a session ID")

        return result

    def _parse_planner_response(
        self,
        output: str,
        session_id: str,
        issues: list[Issue],
    ) -> dict[str, Any]:
        """Parse Claude's planning response."""
        # MANDATORY: Log CLI output for debugging
        logger.info("[PLAN] === CLI OUTPUT ===")
        logger.info(f"[PLAN] Output length: {len(output)}")
        logger.info(f"[PLAN] Output (first 1000 chars): {output[:1000]}")

        try:
            data = parse_llm_json(output)
            logger.info(f"[PLAN] Parsed data type: {type(data)}")
            logger.info(f"[PLAN] Parsed data keys: {list(data.keys()) if data else 'None'}")
            if data:
                logger.info(f"[PLAN] phase: {data.get('phase')}")
                logger.info(f"[PLAN] master_todo keys: {list(data.get('master_todo', {}).keys())}")
                logger.info(f"[PLAN] issue_todos count: {len(data.get('issue_todos', []))}")
        except Exception as e:
            logger.exception(f"[PLAN] JSON parsing failed: {e}")
            logger.error(f"[PLAN] Raw output: {output[:2000]}")
            raise

        if not data or data.get("phase") != "planning":
            logger.warning(
                f"[PLAN] FALLBACK TRIGGERED: data={data is not None}, "
                f"phase={data.get('phase') if data else 'N/A'}"
            )
            logger.warning(f"[PLAN] Raw output first 2000 chars: {output[:2000]}")
            data = self._create_fallback_plan(issues, session_id)

        return data

    def _create_fallback_plan(
        self,
        issues: list[Issue],
        session_id: str,
    ) -> dict[str, Any]:
        """Create a fallback plan when LLM response is invalid."""
        return {
            "phase": "planning",
            "master_todo": {
                "session_id": session_id,
                "execution_steps": [
                    {
                        "step": 1,
                        "issues": [
                            {
                                "code": issue.issue_code or f"issue-{i}",
                                "todo_file": f"fix_todo_{issue.issue_code or f'issue-{i}'}.json",
                                "agent_type": "fixer-single",
                            }
                            for i, issue in enumerate(issues)
                        ],
                        "reason": "Fallback: all issues in single step",
                    }
                ],
                "summary": {"total_issues": len(issues), "total_steps": 1},
            },
            "issue_todos": [
                {
                    "issue_code": issue.issue_code or f"issue-{i}",
                    "issue_id": issue.id,
                    "file": issue.file or "",
                    "line": issue.line,
                    "title": issue.title or "",
                    "clarifications": [],
                    "context": {},
                    "plan": {
                        "approach": "patch",
                        "steps": [f"1. Fix: {issue.title}"],
                        "estimated_lines_changed": 5,
                    },
                }
                for i, issue in enumerate(issues)
            ],
        }

    def _build_todos(
        self,
        data: dict[str, Any],
        issues: list[Issue],
        session_id: str,
    ) -> tuple[MasterTodo, list[IssueTodo]]:
        """Build MasterTodo and IssueTodos from parsed data."""
        # Build execution steps
        execution_steps: list[ExecutionStep] = []
        for step_data in data.get("master_todo", {}).get("execution_steps", []):
            step = ExecutionStep(
                step=step_data.get("step", 1),
                issues=[
                    IssueEntry(
                        code=ie.get("code", ""),
                        todo_file=ie.get("todo_file", f"fix_todo_{ie.get('code', '')}.json"),
                        agent_type=ie.get("agent_type", "fixer-single"),
                        # Sub-task fields (optional, for multi-file splitting)
                        parent_issue=ie.get("parent_issue"),
                        target_files=ie.get("target_files", []),
                        subtask_index=ie.get("subtask_index"),
                    )
                    for ie in step_data.get("issues", [])
                ],
                reason=step_data.get("reason"),
            )
            execution_steps.append(step)

        # Create fallback if no steps
        if not execution_steps:
            execution_steps = [
                ExecutionStep(
                    step=1,
                    issues=[
                        IssueEntry(
                            code=issue.issue_code or f"issue-{i}",
                            todo_file=f"fix_todo_{issue.issue_code or f'issue-{i}'}.json",
                            agent_type="fixer-single",
                        )
                        for i, issue in enumerate(issues)
                    ],
                    reason="All issues in single step (fallback)",
                )
            ]

        master_todo = MasterTodo(
            session_id=session_id,
            execution_steps=execution_steps,
            summary=MasterTodoSummary(
                total_issues=len(issues),
                total_steps=len(execution_steps),
            ),
        )

        # Build IssueTodos
        issue_todos: list[IssueTodo] = []
        issue_code_map = {issue.issue_code: issue for issue in issues if issue.issue_code}

        for todo_data in data.get("issue_todos", []):
            issue_code = todo_data.get("issue_code", "")
            issue = issue_code_map.get(issue_code)
            if not issue:
                continue

            context_data = todo_data.get("context", {})
            context = IssueContextInfo(
                file_content_snippet=context_data.get("file_content_snippet"),
                related_files=[],
                existing_patterns=context_data.get("existing_patterns", []),
            )

            plan_data = todo_data.get("plan", {})
            # Parse estimated_lines_changed safely (LLM may return string)
            raw_lines = plan_data.get("estimated_lines_changed", 0)
            if isinstance(raw_lines, str):
                match = re.search(r"\d+", raw_lines)
                estimated_lines = int(match.group()) if match else 5
            else:
                estimated_lines = int(raw_lines) if raw_lines else 0

            plan = (
                IssuePlan(
                    approach=plan_data.get("approach", "patch"),
                    steps=plan_data.get("steps", []),
                    estimated_lines_changed=estimated_lines,
                    risks=plan_data.get("risks", []),
                    verification=plan_data.get("verification"),
                )
                if plan_data
                else None
            )

            issue_todo = IssueTodo(
                issue_code=issue_code,
                issue_id=issue.id,
                file=issue.file or "",
                line=issue.line,
                title=issue.title or "",
                clarifications=[],
                context=context,
                plan=plan,
            )
            issue_todos.append(issue_todo)

        # Create fallback IssueTodos for missing issues
        planned_codes = {t.issue_code for t in issue_todos}
        for issue in issues:
            if issue.issue_code and issue.issue_code not in planned_codes:
                issue_todos.append(
                    IssueTodo(
                        issue_code=issue.issue_code,
                        issue_id=issue.id,
                        file=issue.file or "",
                        line=issue.line,
                        title=issue.title or "",
                        clarifications=[],
                        context=IssueContextInfo(),
                        plan=IssuePlan(
                            approach="patch",
                            steps=[f"1. Fix {issue.title}"],
                            estimated_lines_changed=5,
                        ),
                    )
                )

        return master_todo, issue_todos

    async def _save_todos(
        self,
        session_id: str,
        master_todo: MasterTodo,
        issue_todos: list[IssueTodo],
    ) -> dict[str, Path]:
        """Save TODO files to disk."""
        todo_manager = TodoManager(session_id)
        return await todo_manager.save_all(master_todo, issue_todos)

    def _save_plans_to_db(
        self,
        issue_todos: list[IssueTodo],
        issues: list[Issue],
    ) -> None:
        """Save fix plans to issues in database."""
        issue_code_map: dict[str, Issue] = {
            str(issue.issue_code): issue for issue in issues if issue.issue_code
        }

        for issue_todo in issue_todos:
            issue = issue_code_map.get(str(issue_todo.issue_code))
            if issue and issue_todo.plan:
                issue.fix_plan = {  # type: ignore[assignment]
                    "approach": issue_todo.plan.approach,
                    "steps": issue_todo.plan.steps,
                    "estimated_lines_changed": issue_todo.plan.estimated_lines_changed,
                    "risks": issue_todo.plan.risks or [],
                    "verification": issue_todo.plan.verification,
                }
        self.db.commit()
        logger.info(f"[PLAN] Saved fix_plan to {len(issue_todos)} issues")

    def _build_result(
        self,
        session_id: str,
        master_todo: MasterTodo,
        paths: dict[str, Path],
    ) -> PlanResult:
        """Build the final PlanResult."""
        step_infos = [
            PlanStepInfo(
                step=step.step,
                issue_codes=[ie.code for ie in step.issues],
                reason=step.reason,
            )
            for step in master_todo.execution_steps
        ]

        # total_issues is always an int in the model
        total_issues = master_todo.summary.total_issues
        issue_count = len(total_issues) if isinstance(total_issues, list) else int(total_issues)  # type: ignore[arg-type]

        return PlanResult(
            session_id=session_id,
            master_todo_path=str(paths.get("master", "")),
            issue_count=issue_count,
            step_count=master_todo.summary.total_steps,
            execution_steps=step_infos,
            ready_to_execute=True,
        )
