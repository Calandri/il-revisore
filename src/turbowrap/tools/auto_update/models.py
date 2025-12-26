"""Pydantic models for auto-update checkpoints and data structures."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """Status of a workflow step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Functionality(BaseModel):
    """A functionality extracted from the codebase."""

    id: str = Field(..., description="Unique ID in kebab-case")
    name: str = Field(..., description="Descriptive name")
    description: str = Field(..., description="2-3 sentence description")
    category: str = Field(..., description="One of: review, fix, linear, cli, api, core, tools")
    files: list[str] = Field(default_factory=list, description="Main files involved")
    dependencies: list[str] = Field(default_factory=list, description="Dependencies on other functionalities")
    maturity: str = Field(default="stable", description="One of: stable, beta, experimental")


class Step1Checkpoint(BaseModel):
    """Checkpoint for Step 1: Analyze Functionalities."""

    step: str = "step1_analyze"
    status: StepStatus = StepStatus.PENDING
    started_at: datetime
    completed_at: datetime | None = None
    repo_path: str
    commit_sha: str | None = None
    functionalities: list[Functionality] = Field(default_factory=list)
    error: str | None = None


class ResearchResult(BaseModel):
    """A web research result."""

    query: str = Field(..., description="Search query used")
    source: str = Field(..., description="Source URL or domain")
    title: str = Field(..., description="Result title")
    summary: str = Field(..., description="Summary of findings")
    relevance_score: float = Field(default=0.5, ge=0, le=1, description="Relevance 0-1")
    extracted_features: list[str] = Field(default_factory=list, description="Features mentioned")


class Step2Checkpoint(BaseModel):
    """Checkpoint for Step 2: Web Research."""

    step: str = "step2_research"
    status: StepStatus = StepStatus.PENDING
    started_at: datetime
    completed_at: datetime | None = None
    research_results: list[ResearchResult] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list, description="Competitor tools identified")
    emerging_technologies: list[str] = Field(default_factory=list)
    best_practices: list[str] = Field(default_factory=list)
    error: str | None = None


class ProposedFeature(BaseModel):
    """A proposed new feature."""

    id: str = Field(..., description="Unique ID in kebab-case")
    title: str = Field(..., description="Feature title")
    description: str = Field(..., description="Detailed description")
    rationale: str = Field(..., description="Why this adds value")
    source: str = Field(..., description="One of: competitor, best_practice, emerging_tech")
    effort_estimate: str = Field(..., description="One of: small, medium, large, xlarge")
    impact_estimate: str = Field(..., description="One of: low, medium, high, critical")
    priority_score: float = Field(default=0, ge=0, le=100, description="Calculated priority 0-100")
    related_existing: list[str] = Field(default_factory=list, description="Related existing functionality IDs")
    human_questions: list[str] = Field(default_factory=list, description="3-5 HITL questions")


class RejectedFeature(BaseModel):
    """A feature that was considered but rejected."""

    id: str
    title: str
    reason: str = Field(..., description="Why it was rejected")


class Step3Checkpoint(BaseModel):
    """Checkpoint for Step 3: Feature Evaluation."""

    step: str = "step3_evaluate"
    status: StepStatus = StepStatus.PENDING
    started_at: datetime
    completed_at: datetime | None = None
    proposed_features: list[ProposedFeature] = Field(default_factory=list)
    rejected_features: list[RejectedFeature] = Field(default_factory=list)
    error: str | None = None


class CreatedIssue(BaseModel):
    """A Linear issue that was created."""

    linear_id: str = Field(..., description="Linear issue UUID")
    linear_identifier: str = Field(..., description="Linear identifier e.g. TW-123")
    linear_url: str = Field(..., description="Linear issue URL")
    feature_id: str = Field(..., description="Related ProposedFeature ID")
    title: str
    created_at: datetime


class Step4Checkpoint(BaseModel):
    """Checkpoint for Step 4: Create Linear Issues."""

    step: str = "step4_create_issues"
    status: StepStatus = StepStatus.PENDING
    started_at: datetime
    completed_at: datetime | None = None
    created_issues: list[CreatedIssue] = Field(default_factory=list)
    skipped_features: list[str] = Field(default_factory=list, description="Feature IDs that failed")
    error: str | None = None


class AutoUpdateRun(BaseModel):
    """Complete state of an auto-update run."""

    run_id: str = Field(..., description="Unique run identifier")
    started_at: datetime
    completed_at: datetime | None = None
    repo_path: str
    current_step: int = Field(default=1, ge=1, le=4)
    step1: Step1Checkpoint | None = None
    step2: Step2Checkpoint | None = None
    step3: Step3Checkpoint | None = None
    step4: Step4Checkpoint | None = None
