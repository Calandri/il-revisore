"""
Backup of unused models from fix/models.py.

These models were part of the old clarification/planning flow
but are no longer used after the orchestrator refactoring.

Keep for reference in case they're needed later.
"""

from pydantic import BaseModel, Field


class IssueClarificationQuestion(BaseModel):
    """A clarification question for a specific issue."""

    id: str = Field(..., description="Question ID (format: {issue_code}-q{n})")
    question: str = Field(..., description="The question to ask the user")
    context: str | None = Field(default=None, description="Why this question is being asked")


class IssueQuestionsGroup(BaseModel):
    """Group of questions for a single issue."""

    issue_code: str = Field(..., description="Issue code (e.g., BE-001)")
    questions: list[IssueClarificationQuestion] = Field(
        default_factory=list, description="Questions for this issue"
    )


class ClarificationPhaseOutput(BaseModel):
    """Output from the clarification phase of the planner."""

    phase: str = Field(default="clarification", description="Current phase")
    has_questions: bool = Field(..., description="Whether there are questions to ask")
    questions_by_issue: list[IssueQuestionsGroup] = Field(
        default_factory=list, description="Questions grouped by issue"
    )
    issues_without_questions: list[str] = Field(
        default_factory=list, description="Issue codes that don't need clarification"
    )
    ready_to_plan: bool = Field(..., description="Whether ready to proceed to planning")


class PlanningPhaseOutput(BaseModel):
    """Output from the planning phase of the planner.

    Note: This would need MasterTodo and IssueTodo imports if restored.
    """

    phase: str = Field(default="planning", description="Current phase")
    # master_todo: MasterTodo = Field(..., description="Master TODO for orchestrator")
    # issue_todos: list[IssueTodo] = Field(..., description="Individual issue TODOs")
