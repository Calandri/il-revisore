"""
Gemini 3 CLI challenger implementation.
"""

import asyncio
import json
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from turbowrap.config import get_settings
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.models.challenger import (
    ChallengerFeedback,
    ChallengerStatus,
    DimensionScores,
    MissedIssue,
    Challenge,
)
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext


class GeminiChallenger(BaseReviewer):
    """
    Review challenger using Gemini 3 CLI.

    Implements the challenger role in the dual-reviewer system.
    Evaluates reviews produced by Claude and provides feedback.
    """

    def __init__(
        self,
        name: str = "challenger",
        model: str = "gemini-3-flash-preview",
        api_key: Optional[str] = None,
        cli_path: str = "gemini",
    ):
        """
        Initialize Gemini challenger.

        Args:
            name: Challenger identifier
            model: Model identifier
            api_key: Google API key (uses env var if not provided)
            cli_path: Path to Gemini CLI executable
        """
        super().__init__(name, model)

        settings = get_settings()
        self.api_key = api_key or settings.agents.effective_google_key
        self.cli_path = cli_path
        self.threshold = settings.challenger.satisfaction_threshold  # From config

    async def review(self, context: ReviewContext) -> ReviewOutput:
        """
        Not used for challenger - use challenge() instead.
        """
        raise NotImplementedError("Use challenge() method for GeminiChallenger")

    async def refine(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
    ) -> ReviewOutput:
        """
        Not used for challenger.
        """
        raise NotImplementedError("Challenger does not refine reviews")

    async def challenge(
        self,
        context: ReviewContext,
        review: ReviewOutput,
        iteration: int = 1,
    ) -> ChallengerFeedback:
        """
        Challenge a review produced by the reviewer.

        Args:
            context: Original review context
            review: Review output to challenge
            iteration: Current challenger iteration

        Returns:
            ChallengerFeedback with evaluation and suggestions
        """
        start_time = time.time()

        # Build the challenger prompt
        prompt = self._build_challenge_prompt(context, review, iteration)

        # Call Gemini CLI
        response = await self._call_gemini_cli(prompt, context)

        # Parse the response
        feedback = self._parse_response(response, iteration)
        feedback.threshold = self.threshold

        return feedback

    def _build_challenge_prompt(
        self,
        context: ReviewContext,
        review: ReviewOutput,
        iteration: int,
    ) -> str:
        """Build the challenge prompt for Gemini."""
        prompt = f"""# Review Quality Evaluation - Iteration {iteration}

You are evaluating the QUALITY of a code review, not the code itself.
Your job is to determine if the reviewer did a good job.

## The Review to Evaluate

```json
{review.model_dump_json(indent=2)}
```

## The Code/Context Being Reviewed

{context.get_code_context(max_chars=30000)}

## Your Task

Evaluate the REVIEW on these 4 dimensions (0-100 each):

### 1. Completeness (weight: 25%)
- Did the reviewer analyze ALL relevant files?
- Did they cover security, performance, architecture, and maintainability?
- Did they miss any obvious areas that should have been reviewed?

### 2. Accuracy (weight: 30%)
- Are the issues found by the reviewer REAL problems?
- Are the severity levels (CRITICAL, HIGH, MEDIUM, LOW) appropriate?
- Are there any false positives (issues that aren't really issues)?

### 3. Depth (weight: 25%)
- Did the reviewer identify ROOT CAUSES or just symptoms?
- Did they understand the business logic implications?
- Did they trace dependencies across files?

### 4. Actionability (weight: 20%)
- Are the fix suggestions clear and specific?
- Could a developer implement the fixes without guessing?
- Are code examples correct and usable?

## Output Format

Return ONLY valid JSON:

```json
{{
  "satisfaction_score": <weighted average 0-100>,
  "status": "APPROVED|NEEDS_REFINEMENT|MAJOR_ISSUES",
  "dimension_scores": {{
    "completeness": <0-100>,
    "accuracy": <0-100>,
    "depth": <0-100>,
    "actionability": <0-100>
  }},
  "missed_issues": [
    {{
      "type": "security|performance|architecture|logic",
      "description": "<what the reviewer missed>",
      "file": "<file path>",
      "lines": "<line range or null>",
      "why_important": "<why this matters>",
      "suggested_severity": "CRITICAL|HIGH|MEDIUM|LOW"
    }}
  ],
  "challenges": [
    {{
      "issue_id": "<id of issue to challenge>",
      "challenge_type": "severity|false_positive|fix_incomplete",
      "challenge": "<what's wrong with this issue>",
      "reasoning": "<why>",
      "suggested_change": "<how to fix>"
    }}
  ],
  "improvements_needed": ["<improvement 1>", "<improvement 2>"],
  "positive_feedback": ["<what was done well>"]
}}
```

## Scoring Guide

- **90-100**: Excellent review, comprehensive and accurate
- **70-89**: Good review with minor gaps
- **50-69**: Adequate review but missing important areas
- **<50**: Poor review, major issues missed

Be fair but rigorous. Only flag REAL problems with the review.
Output ONLY the JSON, no markdown or explanations.
"""
        return prompt

    async def _call_gemini_cli(self, prompt: str, context: ReviewContext) -> str:
        """
        Call Gemini CLI with the prompt.

        Uses subprocess to invoke the Gemini CLI tool.
        """
        # Write prompt to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
        ) as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            # Build CLI command
            cmd = [
                self.cli_path,
                "prompt",
                "--file", prompt_file,
                "--format", "json",
            ]

            # Add API key if set
            if self.api_key:
                cmd.extend(["--api-key", self.api_key])

            # Run CLI
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=context.repo_path,
            )

            if result.returncode != 0:
                # Try alternative invocation
                return await self._call_gemini_api_fallback(prompt)

            return result.stdout

        except subprocess.TimeoutExpired:
            return await self._call_gemini_api_fallback(prompt)
        except FileNotFoundError:
            # CLI not found, use API fallback
            return await self._call_gemini_api_fallback(prompt)
        finally:
            Path(prompt_file).unlink(missing_ok=True)

    async def _call_gemini_api_fallback(self, prompt: str) -> str:
        """
        Fallback to direct Gemini API call if CLI fails.

        Uses the new google-genai SDK (not deprecated google.generativeai).
        """
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)

            # Run sync call in thread to avoid blocking event loop
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3-flash-preview",
                contents=prompt,
            )

            return response.text

        except ImportError:
            # Return a default response if SDK not available
            return self._get_fallback_response()
        except Exception as e:
            return json.dumps({
                "satisfaction_score": 50,
                "status": "NEEDS_REFINEMENT",
                "dimension_scores": {
                    "completeness": 50,
                    "accuracy": 50,
                    "depth": 50,
                    "actionability": 50,
                },
                "missed_issues": [],
                "challenges": [],
                "improvements_needed": [f"Challenger API error: {str(e)}"],
                "positive_feedback": [],
            })

    def _parse_response(self, response_text: str, iteration: int) -> ChallengerFeedback:
        """Parse Gemini's response into ChallengerFeedback."""
        try:
            # Try to extract JSON from response
            json_text = response_text.strip()

            # Handle markdown code blocks
            if json_text.startswith("```"):
                lines = json_text.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```"):
                        in_block = not in_block
                        continue
                    if in_block:
                        json_lines.append(line)
                json_text = "\n".join(json_lines)

            data = json.loads(json_text)

            # Parse dimension scores (matching the prompt's requested fields)
            dim_data = data.get("dimension_scores", {})
            dimension_scores = DimensionScores(
                completeness=dim_data.get("completeness", 50),
                accuracy=dim_data.get("accuracy", 50),
                depth=dim_data.get("depth", 50),
                actionability=dim_data.get("actionability", 50),
            )

            # Parse missed issues
            missed_issues = []
            for mi_data in data.get("missed_issues", []):
                missed_issues.append(MissedIssue(
                    type=mi_data.get("type", "unknown"),
                    description=mi_data.get("description", ""),
                    file=mi_data.get("file", "unknown"),
                    lines=mi_data.get("lines"),
                    why_important=mi_data.get("why_important", ""),
                    suggested_severity=mi_data.get("suggested_severity"),
                ))

            # Parse challenges
            challenges = []
            for ch_data in data.get("challenges", []):
                challenges.append(Challenge(
                    issue_id=ch_data.get("issue_id", "unknown"),
                    challenge_type=ch_data.get("challenge_type", "needs_context"),
                    challenge=ch_data.get("challenge", ""),
                    reasoning=ch_data.get("reasoning", ""),
                    suggested_change=ch_data.get("suggested_change"),
                ))

            # Determine status
            score = data.get("satisfaction_score", dimension_scores.weighted_score)
            status_str = data.get("status", "")

            if status_str:
                try:
                    status = ChallengerStatus(status_str)
                except ValueError:
                    status = self._score_to_status(score)
            else:
                status = self._score_to_status(score)

            return ChallengerFeedback(
                iteration=iteration,
                timestamp=datetime.utcnow(),
                satisfaction_score=score,
                threshold=self.threshold,
                status=status,
                dimension_scores=dimension_scores,
                missed_issues=missed_issues,
                challenges=challenges,
                improvements_needed=data.get("improvements_needed", []),
                positive_feedback=data.get("positive_feedback", []),
            )

        except json.JSONDecodeError:
            # Return minimal feedback on parse error
            return ChallengerFeedback(
                iteration=iteration,
                satisfaction_score=50,
                threshold=self.threshold,
                status=ChallengerStatus.NEEDS_REFINEMENT,
                dimension_scores=DimensionScores(
                    completeness=50,
                    accuracy=50,
                    depth=50,
                    actionability=50,
                ),
                improvements_needed=[
                    f"Failed to parse challenger response: {response_text[:500]}"
                ],
            )

    def _score_to_status(self, score: float) -> ChallengerStatus:
        """Convert satisfaction score to status."""
        if score >= self.threshold:
            return ChallengerStatus.APPROVED
        elif score >= 70:
            return ChallengerStatus.NEEDS_REFINEMENT
        else:
            return ChallengerStatus.MAJOR_ISSUES

    def _get_fallback_response(self) -> str:
        """Get fallback response when API is unavailable."""
        return json.dumps({
            "satisfaction_score": 80,
            "status": "NEEDS_REFINEMENT",
            "dimension_scores": {
                "completeness": 80,
                "accuracy": 80,
                "depth": 80,
                "actionability": 80,
            },
            "missed_issues": [],
            "challenges": [],
            "improvements_needed": [
                "Gemini API unavailable - using fallback. Manual review recommended."
            ],
            "positive_feedback": ["Review structure appears reasonable."],
        })
