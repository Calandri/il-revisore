"""Step 2: Web research for competitors and best practices."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from turbowrap.llm import GeminiProClient

from ..models import ResearchResult, Step1Checkpoint, Step2Checkpoint, StepStatus
from ..storage.s3_checkpoint import S3CheckpointManager
from .base import BaseStep

logger = logging.getLogger(__name__)


class WebResearchStep(BaseStep[Step2Checkpoint]):
    """Step 2: Research competitors, best practices, and emerging technologies.

    Uses Gemini Pro with grounding to search the web for:
    - Competitor tools and their features
    - Industry best practices
    - Emerging technologies and APIs
    """

    step_name = "step2_research"
    step_number = 2
    checkpoint_class = Step2Checkpoint

    def __init__(
        self,
        checkpoint_manager: S3CheckpointManager,
        repo_path: Path,
        gemini_client: GeminiProClient | None = None,
    ):
        """Initialize step.

        Args:
            checkpoint_manager: S3 checkpoint manager.
            repo_path: Path to repository.
            gemini_client: Optional Gemini Pro client.
        """
        super().__init__(checkpoint_manager, repo_path)
        self.gemini_client = gemini_client

    def _get_gemini_client(self) -> GeminiProClient:
        """Get or create Gemini Pro client."""
        if self.gemini_client is None:
            self.gemini_client = GeminiProClient(model=self.settings.research_model)
        return self.gemini_client

    async def execute(
        self,
        previous_checkpoint: Step2Checkpoint | None = None,
        step1_checkpoint: Step1Checkpoint | None = None,
        **kwargs: Any,
    ) -> Step2Checkpoint:
        """Execute Step 2: Web research.

        Args:
            previous_checkpoint: Previous checkpoint if resuming.
            step1_checkpoint: Step 1 checkpoint for context.
            **kwargs: Additional keyword arguments (unused).

        Returns:
            Step2Checkpoint with research results.
        """
        # Skip if already completed
        if self.should_skip(previous_checkpoint):
            logger.info(f"{self.step_name} already completed, skipping")
            return previous_checkpoint  # type: ignore[return-value]

        checkpoint = Step2Checkpoint(
            step=self.step_name,
            status=StepStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
        )

        try:
            logger.info("Starting web research")

            # Build context from Step 1 if available
            existing_context = ""
            if step1_checkpoint and step1_checkpoint.functionalities:
                funcs = [
                    f"{f.name}: {f.description[:100]}"
                    for f in step1_checkpoint.functionalities[:10]
                ]
                existing_context = "\n".join(funcs)

            # Execute research for each query
            all_results = []
            for query in self.settings.competitor_queries:
                logger.info(f"Researching: {query}")
                results = await self._search_with_grounding(query, existing_context)
                all_results.extend(results)

            checkpoint.research_results = all_results

            # Synthesize findings
            synthesis = await self._synthesize_findings(all_results)
            checkpoint.competitors = synthesis.get("competitors", [])
            checkpoint.emerging_technologies = synthesis.get("emerging_technologies", [])
            checkpoint.best_practices = synthesis.get("best_practices", [])

            checkpoint.status = StepStatus.COMPLETED
            checkpoint.completed_at = datetime.utcnow()

            logger.info(
                f"Research complete: {len(checkpoint.competitors)} competitors, "
                f"{len(checkpoint.emerging_technologies)} technologies, "
                f"{len(checkpoint.best_practices)} best practices"
            )

        except Exception as e:
            logger.error(f"Step 2 failed: {e}")
            checkpoint.status = StepStatus.FAILED
            checkpoint.error = str(e)
            raise

        return checkpoint

    async def _search_with_grounding(
        self,
        query: str,
        existing_context: str = "",
    ) -> list[ResearchResult]:
        """Execute web search with Gemini grounding.

        Args:
            query: Search query.
            existing_context: Context about existing functionalities.

        Returns:
            List of research results.
        """
        gemini = self._get_gemini_client()

        prompt = f"""You are a technical analyst researching developer tools and \
AI-powered software.

Search query: {query}

{f"Context - Our existing capabilities:{chr(10)}{existing_context}" if existing_context else ""}

Based on your knowledge and the search query, provide a comprehensive analysis of:

1. **Tools and Products**: List specific tools/products that match this search
2. **Key Features**: Notable features each tool offers
3. **Pricing Models**: How they monetize (if known)
4. **Integrations**: What they integrate with
5. **Unique Selling Points**: What makes each stand out

For each finding, rate its relevance to a code review/AI development tool on a scale of 0-1.

Respond in JSON format:
{{
  "results": [
    {{
      "source": "example.com or tool name",
      "title": "Tool/Finding Name",
      "summary": "2-3 sentence summary of the finding",
      "relevance_score": 0.85,
      "extracted_features": ["feature1", "feature2", "feature3"]
    }}
  ]
}}

Be specific and factual. Include at least 3-5 relevant results.
"""

        result = gemini.generate(prompt)

        # Parse JSON response
        try:
            json_str = result
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                json_str = result.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())
            research_results = []

            for item in data.get("results", []):
                try:
                    res = ResearchResult(
                        query=query,
                        source=item.get("source", "unknown"),
                        title=item.get("title", "Unknown"),
                        summary=item.get("summary", ""),
                        relevance_score=float(item.get("relevance_score", 0.5)),
                        extracted_features=item.get("extracted_features", []),
                    )
                    research_results.append(res)
                except Exception as e:
                    logger.warning(f"Failed to parse research result: {e}")

            return research_results

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse research response: {e}")
            return []

    async def _synthesize_findings(
        self,
        results: list[ResearchResult],
    ) -> dict[str, list[str]]:
        """Synthesize research findings into categories.

        Args:
            results: All research results.

        Returns:
            Dict with competitors, technologies, and best practices.
        """
        if not results:
            return {
                "competitors": [],
                "emerging_technologies": [],
                "best_practices": [],
            }

        gemini = self._get_gemini_client()

        # Build summary of findings
        findings_text = "\n".join(
            [
                f"- {r.title} ({r.source}): {r.summary}"
                for r in results[:20]  # Limit for context window
            ]
        )

        prompt = f"""Analyze these research findings about AI developer tools:

{findings_text}

Synthesize into three categories:

1. **Competitors**: Specific product/tool names that compete in the code review / AI dev tools space
2. **Emerging Technologies**: New technologies, APIs, or approaches mentioned
3. **Best Practices**: Industry best practices and patterns for AI developer tools

Respond in JSON:
{{
  "competitors": ["Tool A", "Tool B", "Tool C"],
  "emerging_technologies": ["Technology 1", "Technology 2"],
  "best_practices": ["Practice 1", "Practice 2"]
}}

Be concise - list only the top 5-10 items per category.
"""

        result = gemini.generate(prompt)

        try:
            json_str = result
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                json_str = result.split("```")[1].split("```")[0]

            parsed: dict[str, list[str]] = json.loads(json_str.strip())
            return parsed

        except json.JSONDecodeError:
            logger.error("Failed to parse synthesis response")
            return {
                "competitors": [],
                "emerging_technologies": [],
                "best_practices": [],
            }
