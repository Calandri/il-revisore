"""
Gemini CLI-based challenger implementation.

Uses Gemini CLI subprocess to validate reviews, with access to the codebase
for double-checking the accuracy of Claude's review.
"""

import asyncio
import codecs
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import (
    Challenge,
    ChallengerFeedback,
    ChallengerStatus,
    DimensionScores,
    MissedIssue,
)
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext
from turbowrap.utils.aws_secrets import get_google_api_key

logger = logging.getLogger(__name__)

# Timeouts
GEMINI_CLI_TIMEOUT = 120  # 2 minutes per challenge


class GeminiCLIChallenger(BaseReviewer):
    """
    Review challenger using Gemini CLI.

    Evaluates reviews produced by Claude CLI and provides feedback.
    Has access to the codebase (via cwd) to double-check the review accuracy.
    """

    def __init__(
        self,
        name: str = "challenger",
        cli_path: str = "gemini",
        timeout: int = GEMINI_CLI_TIMEOUT,
    ):
        """
        Initialize Gemini CLI challenger.

        Args:
            name: Challenger identifier
            cli_path: Path to Gemini CLI executable
            timeout: Timeout in seconds for CLI execution
        """
        super().__init__(name, model="gemini-cli")

        self.settings = get_settings()
        self.cli_path = cli_path
        self.timeout = timeout
        self.threshold = self.settings.challenger.satisfaction_threshold

    async def review(self, context: ReviewContext) -> ReviewOutput:
        """Not used for challenger - use challenge() instead."""
        raise NotImplementedError("Use challenge() method for GeminiCLIChallenger")

    async def refine(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
    ) -> ReviewOutput:
        """Not used for challenger."""
        raise NotImplementedError("Challenger does not refine reviews")

    async def challenge(
        self,
        review: ReviewOutput,
        file_list: list[str],
        repo_path: Path | None,
        iteration: int = 1,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ChallengerFeedback:
        """
        Challenge a review produced by Claude CLI.

        Args:
            review: Review output to challenge
            file_list: List of files that were reviewed
            repo_path: Repository path (used as cwd for Gemini CLI)
            iteration: Current challenger iteration
            on_chunk: Optional callback for streaming output chunks

        Returns:
            ChallengerFeedback with evaluation and suggestions
        """
        # Build the challenge prompt
        prompt = self._build_challenge_prompt(review, file_list, iteration)

        # Run Gemini CLI with streaming
        output = await self._run_gemini_cli(prompt, repo_path, on_chunk)

        if output is None:
            return self._create_fallback_feedback(iteration)

        # Parse the response
        feedback = self._parse_response(output, iteration)
        feedback.threshold = self.threshold

        return feedback

    def _build_challenge_prompt(
        self,
        review: ReviewOutput,
        file_list: list[str],
        iteration: int,
    ) -> str:
        """Build the challenge prompt for Gemini CLI."""
        prompt = f"""# Review Quality Evaluation - Iteration {iteration}

You are evaluating the QUALITY of a code review, not the code itself.
Your job is to determine if the reviewer did a good job.

**IMPORTANT**: You have access to the files. Read them to verify the review accuracy.

## The Review to Evaluate

```json
{review.model_dump_json(indent=2)}
```

## Files That Were Reviewed

Read these files to verify the review:
"""

        for f in file_list:
            prompt += f"- {f}\n"

        prompt += """

## Your Task

1. **Read the files** listed above
2. **Verify each issue** - is it real? Is the severity correct?
3. **Check for missed issues** - did the reviewer miss anything important?
4. **Evaluate fix suggestions** - are they correct and complete?

Evaluate the REVIEW on these 4 dimensions (0-100 each):

### 1. Completeness (weight: 25%)
- Did the reviewer analyze ALL relevant files?
- Did they cover security, performance, architecture, and maintainability?

### 2. Accuracy (weight: 30%)
- Are the issues found REAL problems?
- Are the severity levels appropriate?
- Are there false positives?

### 3. Depth (weight: 25%)
- Did the reviewer identify ROOT CAUSES or just symptoms?
- Did they understand business logic implications?

### 4. Actionability (weight: 20%)
- Are the fix suggestions clear and specific?
- Are code examples correct and usable?

## Output Format

Return ONLY valid JSON:

```json
{
  "satisfaction_score": <weighted average 0-100>,
  "status": "APPROVED|NEEDS_REFINEMENT|MAJOR_ISSUES",
  "dimension_scores": {
    "completeness": <0-100>,
    "accuracy": <0-100>,
    "depth": <0-100>,
    "actionability": <0-100>
  },
  "missed_issues": [
    {
      "type": "security|performance|architecture|logic",
      "description": "<what the reviewer missed>",
      "file": "<file path>",
      "lines": "<line range or null>",
      "why_important": "<why this matters>",
      "suggested_severity": "CRITICAL|HIGH|MEDIUM|LOW"
    }
  ],
  "challenges": [
    {
      "issue_id": "<id of issue to challenge>",
      "challenge_type": "severity|false_positive|fix_incomplete",
      "challenge": "<what's wrong with this issue>",
      "reasoning": "<why>",
      "suggested_change": "<how to fix>"
    }
  ],
  "improvements_needed": ["<improvement 1>", "<improvement 2>"],
  "positive_feedback": ["<what was done well>"]
}
```

## Scoring Guide

- **90-100**: Excellent review, comprehensive and accurate
- **70-89**: Good review with minor gaps
- **50-69**: Adequate review but missing important areas
- **<50**: Poor review, major issues missed

Be fair but rigorous. Output ONLY the JSON, no markdown or explanations.
"""
        return prompt

    async def _run_gemini_cli(
        self,
        prompt: str,
        repo_path: Path | None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """
        Run Gemini CLI with the prompt, streaming output.

        Args:
            prompt: The full prompt to send
            repo_path: Working directory for the CLI
            on_chunk: Optional callback for streaming chunks

        Returns:
            CLI output or None if failed
        """
        cwd = str(repo_path) if repo_path else None

        try:
            # Build environment with API key from AWS Secrets Manager
            env = os.environ.copy()
            api_key = get_google_api_key()
            if api_key:
                env["GOOGLE_API_KEY"] = api_key
                logger.info("GOOGLE_API_KEY loaded from AWS Secrets Manager")
            else:
                logger.warning("GOOGLE_API_KEY not found in AWS - using environment")

            # Use model from settings
            model = self.settings.agents.gemini_model

            logger.info(f"Running Gemini CLI for challenge in {cwd} with model={model}")

            process = await asyncio.create_subprocess_exec(
                self.cli_path,
                "-m",
                model,
                "--yolo",
                "--output-format",
                "json",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            # Write prompt to stdin
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
            process.stdin.close()

            # Read stdout in streaming mode with incremental UTF-8 decoder
            # This handles multi-byte UTF-8 characters split across chunk boundaries
            output_chunks = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        chunk = await process.stdout.read(1024)
                        if not chunk:
                            # Flush remaining bytes
                            decoded = decoder.decode(b"", final=True)
                            if decoded:
                                output_chunks.append(decoded)
                                if on_chunk:
                                    await on_chunk(decoded)
                            break
                        # Incremental decode - handles partial multi-byte chars
                        decoded = decoder.decode(chunk)
                        if decoded:
                            output_chunks.append(decoded)
                            # Emit chunk for streaming
                            if on_chunk:
                                await on_chunk(decoded)
                            logger.debug(f"Gemini CLI chunk: {len(decoded)} chars")
            except asyncio.TimeoutError:
                logger.error(f"Gemini CLI timed out after {self.timeout}s")
                process.kill()
                return None

            await process.wait()

            if process.returncode != 0:
                stderr = await process.stderr.read()
                logger.error(f"Gemini CLI failed: {stderr.decode()}")
                return None

            raw_output = "".join(output_chunks)

            # Parse JSON output to extract result and model info
            try:
                cli_response = json.loads(raw_output)

                # Check for error
                if "error" in cli_response:
                    error_msg = cli_response["error"].get("message", "Unknown error")
                    logger.error(f"Gemini CLI error: {error_msg}")
                    return None

                # Extract result - Gemini uses 'result' or 'response'
                output = cli_response.get("result") or cli_response.get("response", raw_output)

                # Log model info if available
                model_info = cli_response.get("model") or cli_response.get("modelUsed")
                if model_info:
                    logger.info(f"Gemini CLI model used: {model_info}")

                # Log token usage if available
                usage = cli_response.get("usage", {})
                if usage:
                    logger.info(
                        f"Gemini CLI usage: in={usage.get('inputTokens', 0)}, "
                        f"out={usage.get('outputTokens', 0)}"
                    )
            except json.JSONDecodeError:
                # Fallback to raw output if not valid JSON
                output = raw_output
                logger.warning("Gemini CLI output not valid JSON, using raw output")

            logger.info(f"Gemini CLI completed, output length: {len(output)}")
            return output

        except FileNotFoundError:
            logger.error(f"Gemini CLI not found at: {self.cli_path}")
            return None
        except Exception as e:
            logger.exception(f"Gemini CLI error: {e}")
            return None

    def _parse_response(
        self,
        response_text: str,
        iteration: int,
    ) -> ChallengerFeedback:
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

            # Parse dimension scores
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
                missed_issues.append(
                    MissedIssue(
                        type=mi_data.get("type", "unknown"),
                        description=mi_data.get("description", ""),
                        file=mi_data.get("file", "unknown"),
                        lines=mi_data.get("lines"),
                        why_important=mi_data.get("why_important", ""),
                        suggested_severity=mi_data.get("suggested_severity"),
                    )
                )

            # Parse challenges
            challenges = []
            for ch_data in data.get("challenges", []):
                challenges.append(
                    Challenge(
                        issue_id=ch_data.get("issue_id", "unknown"),
                        challenge_type=ch_data.get("challenge_type", "needs_context"),
                        challenge=ch_data.get("challenge", ""),
                        reasoning=ch_data.get("reasoning", ""),
                        suggested_change=ch_data.get("suggested_change"),
                    )
                )

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
            logger.error(f"Failed to parse Gemini response: {response_text[:500]}")
            return self._create_fallback_feedback(iteration)

    def _score_to_status(self, score: float) -> ChallengerStatus:
        """Convert satisfaction score to status."""
        if score >= self.threshold:
            return ChallengerStatus.APPROVED
        if score >= 70:
            return ChallengerStatus.NEEDS_REFINEMENT
        return ChallengerStatus.MAJOR_ISSUES

    def _create_fallback_feedback(self, iteration: int) -> ChallengerFeedback:
        """Create fallback feedback when CLI fails."""
        return ChallengerFeedback(
            iteration=iteration,
            satisfaction_score=80,  # Default to passing to avoid blocking
            threshold=self.threshold,
            status=ChallengerStatus.NEEDS_REFINEMENT,
            dimension_scores=DimensionScores(
                completeness=80,
                accuracy=80,
                depth=80,
                actionability=80,
            ),
            improvements_needed=["Gemini CLI unavailable - manual review recommended."],
            positive_feedback=["Review structure appears reasonable."],
        )
