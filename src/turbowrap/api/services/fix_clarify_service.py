"""
Fix clarify service - handles pre-fix clarification phase.

Extracted from the fat controller in fix.py to follow Single Responsibility Principle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from turbowrap.db.models import Issue, IssueStatus
from turbowrap.llm.claude_cli import ClaudeCLI
from turbowrap.review.reviewers.utils.json_extraction import parse_llm_json

if TYPE_CHECKING:
    from turbowrap.db.models import Repository

logger = logging.getLogger(__name__)

# Agent file path
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
FIX_CLARIFIER_AGENT = AGENTS_DIR / "fix_clarifier.md"


@dataclass
class ClarifyQuestion:
    """A single clarification question."""

    id: str
    question: str
    context: str | None = None


@dataclass
class ClarifyQuestionGroup:
    """Questions grouped by issue code."""

    issue_code: str
    questions: list[ClarifyQuestion]


@dataclass
class ClarifyResult:
    """Result of the clarification phase."""

    has_questions: bool
    questions: list[ClarifyQuestion]
    questions_by_issue: list[ClarifyQuestionGroup]
    message: str
    session_id: str
    ready_to_fix: bool


class FixClarifyService:
    """Service for handling pre-fix clarification phase.

    Manages the conversation with Claude to clarify issues before fixing.
    Supports multi-turn Q&A until ready_to_fix=True.
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

    async def clarify(
        self,
        issues: list[Issue],
        session_id: str | None = None,
        answers: dict[str, str] | None = None,
        previous_questions: list[ClarifyQuestion] | None = None,
    ) -> ClarifyResult:
        """Run clarification phase.

        Args:
            issues: Issues to clarify.
            session_id: Claude session ID for resume (None on first call).
            answers: User's answers to previous questions.
            previous_questions: Previous questions for context.

        Returns:
            ClarifyResult with questions or ready_to_fix=True.
        """
        # First call: mark issues as IN_PROGRESS
        if not session_id:
            self._mark_issues_in_progress(issues)

        # Build prompt
        prompt = self._build_prompt(issues, answers, previous_questions)

        # Run CLI
        result = await self._run_clarifier(prompt, issues, session_id)

        # Parse response
        clarify_result = self._parse_response(result.output, result.session_id)

        # Save clarifications to issues if ready to fix
        if clarify_result.ready_to_fix and answers and previous_questions:
            self._save_clarifications(issues, previous_questions, answers)

        return clarify_result

    def _mark_issues_in_progress(self, issues: list[Issue]) -> None:
        """Mark issues as IN_PROGRESS on first call."""
        for issue in issues:
            if issue.status == IssueStatus.OPEN.value:
                issue.status = IssueStatus.IN_PROGRESS.value  # type: ignore[assignment]
                issue.phase_started_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        self.db.commit()
        logger.info(f"[CLARIFY] Marked {len(issues)} issues as IN_PROGRESS")

    def _format_issues(self, issues: list[Issue]) -> str:
        """Format issues for the clarification prompt."""
        lines = []
        for i, issue in enumerate(issues, 1):
            lines.append(f"## Issue {i}: {issue.issue_code}")
            lines.append(f"**Title:** {issue.title}")
            lines.append(f"**File:** {issue.file}:{issue.line or '?'}")
            lines.append(f"**Severity:** {issue.severity}")
            lines.append(f"**Description:** {issue.description}")
            if issue.suggested_fix:
                lines.append(f"**Suggested Fix:** {issue.suggested_fix}")
            lines.append("")
        return "\n".join(lines)

    def _format_answers(self, answers: dict[str, str]) -> str:
        """Format user answers for the follow-up prompt."""
        lines = []
        for qid, answer in answers.items():
            lines.append(f"- **{qid}:** {answer}")
        return "\n".join(lines)

    def _build_prompt(
        self,
        issues: list[Issue],
        answers: dict[str, str] | None,
        previous_questions: list[ClarifyQuestion] | None,
    ) -> str:
        """Build prompt based on whether this is first call or resume."""
        issues_text = self._format_issues(issues)

        if answers and previous_questions:
            # Resume with answers
            answers_text = self._format_answers(answers)
            prev_q_text = "\n".join(f"- {q.id}: {q.question}" for q in previous_questions)

            return f"""Your previous questions:
{prev_q_text}

User's answers:
{answers_text}

Do you have any other questions or are you ready to proceed with the fix?

Respond ONLY with valid JSON:
{{"has_questions": bool, "questions": [...], "message": "...", "ready_to_fix": bool}}"""

        # First call
        return f"""You need to fix these issues:

{issues_text}

What do you think? Are they all clear? Do you have enough context to proceed?
If you have questions, feel free to ask them. Otherwise, confirm that you're ready.

Respond ONLY with valid JSON:
{{"has_questions": bool, "questions": [...], "message": "...", "ready_to_fix": bool}}"""

    async def _run_clarifier(
        self,
        prompt: str,
        issues: list[Issue],
        session_id: str | None,
    ) -> Any:
        """Run Claude CLI for clarification.

        Args:
            prompt: The prompt to send.
            issues: Issues being clarified.
            session_id: Session ID for resume.

        Returns:
            ClaudeCLI result.

        Raises:
            Exception: If CLI fails.
        """
        cli = ClaudeCLI(
            working_dir=Path(self.repo.local_path) if self.repo.local_path else None,
            model="haiku",
            agent_md_path=FIX_CLARIFIER_AGENT if FIX_CLARIFIER_AGENT.exists() else None,
        )
        self.cli = cli

        result = await cli.run(
            prompt=prompt,
            operation_type="fix_clarification",
            repo_name=str(self.repo.name) if self.repo.name else "unknown",
            resume_session_id=session_id,
            operation_details={
                "issue_codes": [i.issue_code for i in issues if i.issue_code],
                "issue_ids": [str(i.id) for i in issues],
                "issue_count": len(issues),
                "parent_session_id": session_id if session_id else None,
            },
        )

        if not result.output:
            raise Exception("No response from Claude")
        if not result.session_id:
            raise Exception("Claude CLI did not return a session ID")

        return result

    def _parse_response(
        self,
        output: str,
        session_id: str,
    ) -> ClarifyResult:
        """Parse Claude's response into ClarifyResult."""
        data = parse_llm_json(output)

        if not data:
            # Fallback: assume ready to fix if parsing fails
            logger.warning(f"Failed to parse clarify response: {output[:500]}")
            return ClarifyResult(
                has_questions=False,
                questions=[],
                questions_by_issue=[],
                message="Analysis complete. Ready to proceed with the fix.",
                session_id=session_id,
                ready_to_fix=True,
            )

        # Build response - parse both flat and grouped questions
        questions: list[ClarifyQuestion] = []
        questions_by_issue: list[ClarifyQuestionGroup] = []

        # Try grouped format first (from fix_clarify_planner.md style)
        for group in data.get("questions_by_issue", []):
            if isinstance(group, dict) and "issue_code" in group:
                group_questions: list[ClarifyQuestion] = []
                for q in group.get("questions", []):
                    if isinstance(q, dict) and "question" in q:
                        group_questions.append(
                            ClarifyQuestion(
                                id=q.get("id", f"{group['issue_code']}-q{len(group_questions)+1}"),
                                question=q["question"],
                                context=q.get("context"),
                            )
                        )
                questions_by_issue.append(
                    ClarifyQuestionGroup(
                        issue_code=group["issue_code"],
                        questions=group_questions,
                    )
                )
                questions.extend(group_questions)

        # Fallback to flat list if no grouped questions
        if not questions_by_issue:
            for q in data.get("questions", []):
                if isinstance(q, dict) and "question" in q:
                    questions.append(
                        ClarifyQuestion(
                            id=q.get("id", f"q{len(questions)+1}"),
                            question=q["question"],
                            context=q.get("context"),
                        )
                    )

        return ClarifyResult(
            has_questions=data.get("has_questions", False),
            questions=questions,
            questions_by_issue=questions_by_issue,
            message=data.get("message", ""),
            session_id=session_id,
            ready_to_fix=data.get("ready_to_fix", False),
        )

    def _save_clarifications(
        self,
        issues: list[Issue],
        questions: list[ClarifyQuestion],
        answers: dict[str, str],
    ) -> None:
        """Save clarification Q&A to issues for future reference."""
        clarification_records = []
        for q in questions:
            if q.id in answers:
                clarification_records.append(
                    {
                        "question_id": q.id,
                        "question": q.question,
                        "context": q.context,
                        "answer": answers[q.id],
                        "asked_at": datetime.now(timezone.utc).isoformat(),
                        "answered_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        if clarification_records:
            for issue in issues:
                existing: list[Any] = list(issue.clarifications or [])
                issue.clarifications = existing + clarification_records  # type: ignore[assignment]
            self.db.commit()
            logger.info(
                f"[CLARIFY] Saved {len(clarification_records)} clarifications "
                f"to {len(issues)} issues"
            )
