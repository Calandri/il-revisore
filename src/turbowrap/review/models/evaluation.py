"""
Models for repository evaluation scoring.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RepositoryEvaluation(BaseModel):
    """
    Final evaluation scores for a repository.

    Each metric is scored 0-100 where:
    - 0-49: Poor (red)
    - 50-74: Needs improvement (yellow)
    - 75-100: Good (green)
    """

    # Core metrics (0-100)
    functionality: int = Field(
        ..., ge=0, le=100,
        description="Completeness of features, coverage of requirements"
    )
    code_quality: int = Field(
        ..., ge=0, le=100,
        description="Code cleanliness, naming, structure, readability"
    )
    comment_quality: int = Field(
        ..., ge=0, le=100,
        description="Documentation, docstrings, useful comments"
    )
    architecture_quality: int = Field(
        ..., ge=0, le=100,
        description="Design patterns, layer separation, SOLID principles"
    )
    effectiveness: int = Field(
        ..., ge=0, le=100,
        description="Performance, efficiency, resource usage"
    )
    code_duplication: int = Field(
        ..., ge=0, le=100,
        description="DRY compliance, code reuse (100 = no duplication)"
    )

    # Calculated overall score
    overall_score: int = Field(
        ..., ge=0, le=100,
        description="Weighted average of all metrics"
    )

    # Summary and insights
    summary: str = Field(
        ..., min_length=10, max_length=500,
        description="2-3 sentence executive summary"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Top 3-5 strengths of the codebase"
    )
    weaknesses: list[str] = Field(
        default_factory=list,
        description="Top 3-5 areas needing improvement"
    )

    # Metadata
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    evaluator_model: str = Field(default="claude-opus-4-5-20251101")

    @field_validator("strengths", "weaknesses")
    @classmethod
    def limit_list_length(cls, v: list[str]) -> list[str]:
        """Limit to max 5 items."""
        return v[:5] if len(v) > 5 else v

    @classmethod
    def calculate_overall(
        cls,
        functionality: int,
        code_quality: int,
        comment_quality: int,
        architecture_quality: int,
        effectiveness: int,
        code_duplication: int,
    ) -> int:
        """
        Calculate weighted overall score.

        Weights:
        - architecture_quality: 25%
        - code_quality: 25%
        - functionality: 15%
        - effectiveness: 15%
        - comment_quality: 10%
        - code_duplication: 10%
        """
        return round(
            architecture_quality * 0.25 +
            code_quality * 0.25 +
            functionality * 0.15 +
            effectiveness * 0.15 +
            comment_quality * 0.10 +
            code_duplication * 0.10
        )

    def get_color(self, score: int) -> str:
        """Get color class for a score."""
        if score < 50:
            return "red"
        if score < 75:
            return "yellow"
        return "green"

    def to_dict_with_colors(self) -> dict:
        """Return metrics with color indicators for UI."""
        return {
            "functionality": {"score": self.functionality, "color": self.get_color(self.functionality)},
            "code_quality": {"score": self.code_quality, "color": self.get_color(self.code_quality)},
            "comment_quality": {"score": self.comment_quality, "color": self.get_color(self.comment_quality)},
            "architecture_quality": {"score": self.architecture_quality, "color": self.get_color(self.architecture_quality)},
            "effectiveness": {"score": self.effectiveness, "color": self.get_color(self.effectiveness)},
            "code_duplication": {"score": self.code_duplication, "color": self.get_color(self.code_duplication)},
            "overall_score": {"score": self.overall_score, "color": self.get_color(self.overall_score)},
            "summary": self.summary,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
        }
