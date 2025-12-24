"""
Models for challenger feedback and evaluation.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ChallengerStatus(str, Enum):
    """Status of challenger evaluation."""

    APPROVED = "APPROVED"
    NEEDS_REFINEMENT = "NEEDS_REFINEMENT"
    MAJOR_ISSUES = "MAJOR_ISSUES"


class DimensionScores(BaseModel):
    """Scores for each evaluation dimension of the REVIEW quality."""

    completeness: float = Field(
        50, ge=0, le=100, description="Did the review cover all files/areas?"
    )
    accuracy: float = Field(
        50, ge=0, le=100, description="Are the issues found real? Severity correct?"
    )
    depth: float = Field(
        50, ge=0, le=100, description="Did the review find root causes or just symptoms?"
    )
    actionability: float = Field(
        50, ge=0, le=100, description="Are the fix suggestions clear and correct?"
    )

    @property
    def weighted_score(self) -> float:
        """Calculate weighted satisfaction score."""
        weights = {
            "completeness": 0.25,
            "accuracy": 0.30,
            "depth": 0.25,
            "actionability": 0.20,
        }
        return (
            self.completeness * weights["completeness"]
            + self.accuracy * weights["accuracy"]
            + self.depth * weights["depth"]
            + self.actionability * weights["actionability"]
        )


class MissedIssue(BaseModel):
    """An issue the reviewer missed."""

    type: str = Field(..., description="Issue type (security, performance, etc.)")
    description: str = Field(..., description="Description of the missed issue")
    file: str = Field(..., description="File where issue exists")
    lines: Optional[str] = Field(None, description="Line range (e.g., '45-62')")
    why_important: str = Field(..., description="Why this issue matters")
    suggested_severity: Optional[str] = Field(
        None, description="Suggested severity level"
    )


class Challenge(BaseModel):
    """A challenge to an existing issue assessment."""

    issue_id: str = Field(..., description="ID of the challenged issue")
    challenge_type: str = Field(
        ...,
        description="Type: severity, fix_incomplete, false_positive, needs_context",
    )
    challenge: str = Field(..., description="The challenge statement")
    reasoning: str = Field(..., description="Detailed reasoning for the challenge")
    suggested_change: Optional[str] = Field(
        None, description="What the reviewer should change"
    )


class ChallengerFeedback(BaseModel):
    """Complete feedback from the challenger."""

    iteration: int = Field(..., description="Current iteration number")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    satisfaction_score: float = Field(
        ..., ge=0, le=100, description="Overall satisfaction percentage"
    )
    threshold: float = Field(..., description="Required threshold to pass")
    status: ChallengerStatus

    dimension_scores: DimensionScores

    missed_issues: list[MissedIssue] = Field(
        default_factory=list, description="Issues the reviewer missed"
    )
    challenges: list[Challenge] = Field(
        default_factory=list, description="Challenges to existing issues"
    )
    improvements_needed: list[str] = Field(
        default_factory=list, description="General improvements needed"
    )
    positive_feedback: list[str] = Field(
        default_factory=list, description="What the reviewer did well"
    )

    @property
    def passed(self) -> bool:
        """Check if the review passes the threshold."""
        return self.satisfaction_score >= self.threshold

    def to_refinement_prompt(self) -> str:
        """Generate a prompt for the reviewer to refine their review."""
        sections = []

        if self.missed_issues:
            sections.append("## Missed Issues to Address\n")
            for i, missed in enumerate(self.missed_issues, 1):
                sections.append(
                    f"{i}. **{missed.type.upper()}** in `{missed.file}`"
                    f"{f' (lines {missed.lines})' if missed.lines else ''}\n"
                    f"   - {missed.description}\n"
                    f"   - Why important: {missed.why_important}\n"
                )

        if self.challenges:
            sections.append("\n## Challenges to Address\n")
            for challenge in self.challenges:
                sections.append(
                    f"- **{challenge.issue_id}**: {challenge.challenge}\n"
                    f"  - Reasoning: {challenge.reasoning}\n"
                )
                if challenge.suggested_change:
                    sections.append(f"  - Suggested: {challenge.suggested_change}\n")

        if self.improvements_needed:
            sections.append("\n## General Improvements\n")
            for improvement in self.improvements_needed:
                sections.append(f"- {improvement}\n")

        return "".join(sections)
