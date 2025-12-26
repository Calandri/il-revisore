"""Step 4: Create Linear issues for proposed features."""

import logging
from datetime import datetime
from pathlib import Path

from turbowrap.review.integrations.linear import LinearClient

from ..models import CreatedIssue, ProposedFeature, Step3Checkpoint, Step4Checkpoint, StepStatus
from ..storage.s3_checkpoint import S3CheckpointManager
from .base import BaseStep

logger = logging.getLogger(__name__)


class CreateLinearIssuesStep(BaseStep[Step4Checkpoint]):
    """Step 4: Create Linear issues for proposed features.

    Creates issues on Linear with:
    - Detailed feature description
    - Effort/impact estimates
    - Human-in-the-loop questions as checklist
    """

    step_name = "step4_create_issues"
    step_number = 4
    checkpoint_class = Step4Checkpoint

    def __init__(
        self,
        checkpoint_manager: S3CheckpointManager,
        repo_path: Path,
        linear_client: LinearClient | None = None,
    ):
        """Initialize step.

        Args:
            checkpoint_manager: S3 checkpoint manager.
            repo_path: Path to repository.
            linear_client: Optional Linear client.
        """
        super().__init__(checkpoint_manager, repo_path)
        self._linear_client = linear_client

    def _get_linear_client(self) -> LinearClient:
        """Get or create Linear client."""
        if self._linear_client is None:
            self._linear_client = LinearClient()
        return self._linear_client

    def _priority_score_to_linear(self, score: float) -> int:
        """Convert priority score (0-100) to Linear priority (1-4).

        Args:
            score: Priority score 0-100.

        Returns:
            Linear priority: 1=Urgent, 2=High, 3=Normal, 4=Low.
        """
        if score >= 80:
            return 1  # Urgent
        if score >= 60:
            return 2  # High
        if score >= 40:
            return 3  # Normal
        return 4  # Low

    def _format_issue_description(self, feature: ProposedFeature) -> str:
        """Format issue description with HITL questions.

        Args:
            feature: Proposed feature.

        Returns:
            Markdown-formatted issue description.
        """
        # Format questions as checklist
        questions = "\n".join([f"- [ ] {q}" for q in feature.human_questions])

        # Format related functionalities
        related = ", ".join(feature.related_existing) if feature.related_existing else "None"

        return f"""## Descrizione

{feature.description}

## Razionale

{feature.rationale}

## Stime

| Metrica | Valore |
|---------|--------|
| **Effort** | {feature.effort_estimate} |
| **Impact** | {feature.impact_estimate} |
| **Priority Score** | {feature.priority_score:.1f}/100 |

## Origine

Fonte: `{feature.source}`

## Funzionalita Correlate

{related}

---

## Domande per Raffinamento (Human-in-the-Loop)

Le seguenti domande aiuteranno a definire meglio i requisiti.
**Rispondi a queste domande nei commenti** per procedere con l'implementazione:

{questions}

---

*Issue generata automaticamente da TurboWrap Auto-Update*
"""

    async def execute(
        self,
        previous_checkpoint: Step4Checkpoint | None = None,
        step3_checkpoint: Step3Checkpoint | None = None,
    ) -> Step4Checkpoint:
        """Execute Step 4: Create Linear issues.

        Args:
            previous_checkpoint: Previous checkpoint if resuming.
            step3_checkpoint: Step 3 checkpoint with proposed features.

        Returns:
            Step4Checkpoint with created issues.
        """
        # Skip if already completed
        if self.should_skip(previous_checkpoint):
            logger.info(f"{self.step_name} already completed, skipping")
            return previous_checkpoint  # type: ignore

        checkpoint = Step4Checkpoint(
            step=self.step_name,
            status=StepStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
        )

        try:
            if not step3_checkpoint:
                raise ValueError("Step 3 checkpoint is required")

            features = step3_checkpoint.proposed_features
            if not features:
                logger.warning("No features to create issues for")
                checkpoint.status = StepStatus.COMPLETED
                checkpoint.completed_at = datetime.utcnow()
                return checkpoint

            # Filter by minimum priority score
            min_score = self.settings.min_priority_score
            features_to_create = [f for f in features if f.priority_score >= min_score]

            logger.info(
                f"Creating issues for {len(features_to_create)} features "
                f"(filtered from {len(features)} with min score {min_score})"
            )

            # Validate team ID
            team_id = self.settings.linear_team_id
            if not team_id:
                raise ValueError(
                    "Linear team ID not configured. "
                    "Set TURBOWRAP_AUTOUPDATE_LINEAR_TEAM_ID environment variable."
                )

            linear = self._get_linear_client()

            for feature in features_to_create:
                try:
                    issue = await self._create_issue(linear, team_id, feature)
                    checkpoint.created_issues.append(issue)
                    logger.info(f"Created issue {issue.linear_identifier}: {issue.title}")
                except Exception as e:
                    error_msg = f"{feature.id}: {str(e)}"
                    checkpoint.skipped_features.append(error_msg)
                    logger.warning(f"Failed to create issue for {feature.id}: {e}")

            checkpoint.status = StepStatus.COMPLETED
            checkpoint.completed_at = datetime.utcnow()

            logger.info(
                f"Step 4 complete: {len(checkpoint.created_issues)} issues created, "
                f"{len(checkpoint.skipped_features)} skipped"
            )

        except Exception as e:
            logger.error(f"Step 4 failed: {e}")
            checkpoint.status = StepStatus.FAILED
            checkpoint.error = str(e)
            raise

        return checkpoint

    async def _create_issue(
        self,
        linear: LinearClient,
        team_id: str,
        feature: ProposedFeature,
    ) -> CreatedIssue:
        """Create a single Linear issue.

        Args:
            linear: Linear client.
            team_id: Linear team UUID.
            feature: Feature to create issue for.

        Returns:
            CreatedIssue with Linear details.
        """
        title = f"[Auto-Update] {feature.title}"
        description = self._format_issue_description(feature)
        priority = self._priority_score_to_linear(feature.priority_score)

        # Get optional label IDs
        label_ids = self.settings.linear_label_ids if self.settings.linear_label_ids else None

        issue_data = await linear.create_issue(
            team_id=team_id,
            title=title,
            description=description,
            priority=priority,
            label_ids=label_ids,
        )

        return CreatedIssue(
            linear_id=issue_data["id"],
            linear_identifier=issue_data["identifier"],
            linear_url=issue_data["url"],
            feature_id=feature.id,
            title=feature.title,
            created_at=datetime.utcnow(),
        )
