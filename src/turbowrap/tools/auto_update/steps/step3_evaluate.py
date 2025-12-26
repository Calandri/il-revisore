"""Step 3: Evaluate and propose new features."""

import json
import logging
from datetime import datetime
from pathlib import Path

from turbowrap.llm import ClaudeClient

from ..models import (
    ProposedFeature,
    RejectedFeature,
    Step1Checkpoint,
    Step2Checkpoint,
    Step3Checkpoint,
    StepStatus,
)
from ..storage.s3_checkpoint import S3CheckpointManager
from .base import BaseStep

logger = logging.getLogger(__name__)

EVALUATION_SYSTEM_PROMPT = """You are a senior software architect evaluating potential new features for a developer tool.

Your task is to:
1. Compare existing capabilities with market research
2. Identify gaps and opportunities
3. Propose specific, actionable new features
4. Reject ideas that don't fit the product vision

Be critical and selective. Only propose features that:
- Add clear value to developers
- Are technically feasible
- Align with the product's core mission (AI-powered code review and development)

For each proposed feature, generate 3-5 specific questions that would help refine the requirements.
These questions will be presented to humans for input before implementation.
"""


class EvaluateFeaturesStep(BaseStep[Step3Checkpoint]):
    """Step 3: Evaluate research findings and propose new features.

    Uses Claude for deep analysis comparing existing functionalities
    with market research to identify improvement opportunities.
    """

    step_name = "step3_evaluate"
    step_number = 3
    checkpoint_class = Step3Checkpoint

    def __init__(
        self,
        checkpoint_manager: S3CheckpointManager,
        repo_path: Path,
        claude_client: ClaudeClient | None = None,
    ):
        """Initialize step.

        Args:
            checkpoint_manager: S3 checkpoint manager.
            repo_path: Path to repository.
            claude_client: Optional Claude client.
        """
        super().__init__(checkpoint_manager, repo_path)
        self.claude_client = claude_client

    def _get_claude_client(self) -> ClaudeClient:
        """Get or create Claude client."""
        if self.claude_client is None:
            self.claude_client = ClaudeClient(model=self.settings.evaluation_model)
        return self.claude_client

    def _calculate_priority(self, feature: ProposedFeature) -> float:
        """Calculate priority score based on effort and impact.

        Priority = Impact * 60 + Effort Bonus * 40

        Args:
            feature: Feature to score.

        Returns:
            Priority score 0-100.
        """
        effort_scores = {
            "small": 1.0,
            "medium": 0.7,
            "large": 0.4,
            "xlarge": 0.2,
        }
        impact_scores = {
            "low": 0.25,
            "medium": 0.5,
            "high": 0.75,
            "critical": 1.0,
        }

        effort = effort_scores.get(feature.effort_estimate.lower(), 0.5)
        impact = impact_scores.get(feature.impact_estimate.lower(), 0.5)

        return (impact * 60) + (effort * 40)

    async def execute(
        self,
        previous_checkpoint: Step3Checkpoint | None = None,
        step1_checkpoint: Step1Checkpoint | None = None,
        step2_checkpoint: Step2Checkpoint | None = None,
    ) -> Step3Checkpoint:
        """Execute Step 3: Feature evaluation.

        Args:
            previous_checkpoint: Previous checkpoint if resuming.
            step1_checkpoint: Step 1 checkpoint with existing functionalities.
            step2_checkpoint: Step 2 checkpoint with research results.

        Returns:
            Step3Checkpoint with proposed and rejected features.
        """
        # Skip if already completed
        if self.should_skip(previous_checkpoint):
            logger.info(f"{self.step_name} already completed, skipping")
            return previous_checkpoint  # type: ignore

        checkpoint = Step3Checkpoint(
            step=self.step_name,
            status=StepStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
        )

        try:
            logger.info("Evaluating potential new features")

            if not step1_checkpoint or not step2_checkpoint:
                raise ValueError("Step 1 and Step 2 checkpoints are required")

            # Build evaluation prompt
            prompt = self._build_evaluation_prompt(step1_checkpoint, step2_checkpoint)

            # Get Claude's evaluation
            claude = self._get_claude_client()
            response = claude.generate(prompt, system_prompt=EVALUATION_SYSTEM_PROMPT)

            # Parse response
            proposed, rejected = self._parse_evaluation(response)

            # Calculate priority scores
            for feature in proposed:
                feature.priority_score = self._calculate_priority(feature)

            # Sort by priority
            proposed.sort(key=lambda f: f.priority_score, reverse=True)

            # Limit to max features
            max_features = self.settings.max_features_to_propose
            checkpoint.proposed_features = proposed[:max_features]
            checkpoint.rejected_features = rejected

            checkpoint.status = StepStatus.COMPLETED
            checkpoint.completed_at = datetime.utcnow()

            logger.info(
                f"Evaluation complete: {len(checkpoint.proposed_features)} proposed, "
                f"{len(checkpoint.rejected_features)} rejected"
            )

        except Exception as e:
            logger.error(f"Step 3 failed: {e}")
            checkpoint.status = StepStatus.FAILED
            checkpoint.error = str(e)
            raise

        return checkpoint

    def _build_evaluation_prompt(
        self,
        step1: Step1Checkpoint,
        step2: Step2Checkpoint,
    ) -> str:
        """Build evaluation prompt from previous steps.

        Args:
            step1: Step 1 checkpoint.
            step2: Step 2 checkpoint.

        Returns:
            Evaluation prompt string.
        """
        # Format existing functionalities
        existing = "\n".join([
            f"- **{f.name}** ({f.category}): {f.description}"
            for f in step1.functionalities
        ])

        # Format research results
        research = "\n".join([
            f"- {r.title} ({r.source}): {r.summary}"
            for r in step2.research_results[:15]
        ])

        competitors = ", ".join(step2.competitors[:10]) if step2.competitors else "None identified"
        technologies = ", ".join(step2.emerging_technologies[:10]) if step2.emerging_technologies else "None identified"
        practices = "\n".join([f"- {p}" for p in step2.best_practices[:10]]) if step2.best_practices else "None identified"

        return f"""## Existing Functionalities of TurboWrap

{existing}

## Market Research Results

{research}

## Competitors Identified

{competitors}

## Emerging Technologies

{technologies}

## Best Practices

{practices}

---

## Your Task

Analyze the gap between our existing functionalities and the market.

For each potential new feature:
1. Describe the feature in detail
2. Explain why it adds value (rationale)
3. Estimate effort: small (days), medium (1-2 weeks), large (3-4 weeks), xlarge (1+ months)
4. Estimate impact: low, medium, high, critical
5. Identify related existing functionalities
6. Formulate 3-5 specific questions for human input (to refine requirements)

Also identify features that seem interesting but should be rejected, with clear reasons.

Respond in JSON format:
{{
  "proposed_features": [
    {{
      "id": "auto-fix-suggestions",
      "title": "Auto-Fix Suggestions with Code Generation",
      "description": "Automatically generate fix suggestions for identified issues...",
      "rationale": "Competitor X offers this feature with high user satisfaction...",
      "source": "competitor",
      "effort_estimate": "large",
      "impact_estimate": "high",
      "related_existing": ["code-review-challenger", "fix-module"],
      "human_questions": [
        "What confidence level is required before suggesting auto-fixes?",
        "Should auto-fixes be limited to specific issue types?",
        "How should conflicts with existing formatters be handled?"
      ]
    }}
  ],
  "rejected_features": [
    {{
      "id": "blockchain-audit",
      "title": "Blockchain Smart Contract Auditing",
      "reason": "Out of scope - TurboWrap focuses on general code review, not blockchain-specific tools"
    }}
  ]
}}

Be selective. Propose 5-10 high-impact features max. Reject ideas that don't fit.
"""

    def _parse_evaluation(
        self,
        response: str,
    ) -> tuple[list[ProposedFeature], list[RejectedFeature]]:
        """Parse Claude's evaluation response.

        Args:
            response: Raw response from Claude.

        Returns:
            Tuple of (proposed features, rejected features).
        """
        proposed = []
        rejected = []

        try:
            # Extract JSON from response
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())

            # Parse proposed features
            for item in data.get("proposed_features", []):
                try:
                    feature = ProposedFeature(
                        id=item.get("id", "unknown"),
                        title=item.get("title", "Unknown Feature"),
                        description=item.get("description", ""),
                        rationale=item.get("rationale", ""),
                        source=item.get("source", "analysis"),
                        effort_estimate=item.get("effort_estimate", "medium"),
                        impact_estimate=item.get("impact_estimate", "medium"),
                        related_existing=item.get("related_existing", []),
                        human_questions=item.get("human_questions", []),
                    )
                    proposed.append(feature)
                except Exception as e:
                    logger.warning(f"Failed to parse proposed feature: {e}")

            # Parse rejected features
            for item in data.get("rejected_features", []):
                try:
                    feature = RejectedFeature(
                        id=item.get("id", "unknown"),
                        title=item.get("title", "Unknown"),
                        reason=item.get("reason", "No reason provided"),
                    )
                    rejected.append(feature)
                except Exception as e:
                    logger.warning(f"Failed to parse rejected feature: {e}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse evaluation response: {e}")
            logger.debug(f"Response was: {response[:500]}")

        return proposed, rejected
