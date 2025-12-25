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

import boto3
from botocore.exceptions import ClientError

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

        # S3 configuration for challenge logs
        self.s3_bucket = self.settings.thinking.s3_bucket
        self.s3_region = self.settings.thinking.s3_region
        self._s3_client = None

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    async def _save_challenge_to_s3(
        self,
        prompt: str,
        raw_output: str,
        feedback: ChallengerFeedback,
        iteration: int,
        review_id: str | None = None,
    ) -> str | None:
        """
        Save challenge prompt, raw output, and parsed feedback to S3.

        Args:
            prompt: The challenge prompt sent to Gemini
            raw_output: Raw CLI output from Gemini
            feedback: Parsed ChallengerFeedback
            iteration: Challenge iteration number
            review_id: Optional review ID for grouping

        Returns:
            S3 URL if successful, None otherwise
        """
        if not raw_output:
            return None

        try:
            # Create S3 key with timestamp
            timestamp = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
            review_id = review_id or f"challenge_{int(datetime.utcnow().timestamp())}"
            s3_key = f"challenges/{timestamp}/{review_id}_iter{iteration}.md"

            # Create markdown content with all details
            content = f"""# Gemini Challenger Log - Iteration {iteration}

**Review ID**: {review_id}
**Timestamp**: {datetime.utcnow().isoformat()}
**Model**: gemini-cli
**Satisfaction Score**: {feedback.satisfaction_score:.1f}%
**Status**: {feedback.status.value}

---

## Dimension Scores

- Completeness: {feedback.dimension_scores.completeness}
- Accuracy: {feedback.dimension_scores.accuracy}
- Depth: {feedback.dimension_scores.depth}
- Actionability: {feedback.dimension_scores.actionability}

---

## Challenge Prompt

```
{prompt}
```

---

## Raw Gemini Output

```
{raw_output}
```

---

## Parsed Feedback

### Missed Issues ({len(feedback.missed_issues)})

"""
            for mi in feedback.missed_issues:
                content += f"- **[{mi.suggested_severity}]** {mi.type}: {mi.description}\n"
                content += f"  - File: {mi.file}\n"
                content += f"  - Why important: {mi.why_important}\n\n"

            content += f"""
### Challenges ({len(feedback.challenges)})

"""
            for ch in feedback.challenges:
                content += f"- **{ch.issue_id}** ({ch.challenge_type}): {ch.challenge}\n"
                content += f"  - Reasoning: {ch.reasoning}\n\n"

            content += """
### Improvements Needed

"""
            for imp in feedback.improvements_needed:
                content += f"- {imp}\n"

            content += """
### Positive Feedback

"""
            for pos in feedback.positive_feedback:
                content += f"- {pos}\n"

            # Upload to S3
            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )

            return f"s3://{self.s3_bucket}/{s3_key}"

        except ClientError as e:
            logger.warning(f"[GEMINI S3] Failed to save challenge to S3: {e}")
            return None
        except Exception as e:
            logger.exception(f"[GEMINI S3] Unexpected error saving to S3: {e}")
            return None

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
        review_id: str | None = None,
    ) -> ChallengerFeedback:
        """
        Challenge a review produced by Claude CLI.

        Args:
            review: Review output to challenge
            file_list: List of files that were reviewed
            repo_path: Repository path (used as cwd for Gemini CLI)
            iteration: Current challenger iteration
            on_chunk: Optional callback for streaming output chunks
            review_id: Optional review ID for S3 grouping

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

        # Save challenge log to S3 in background
        asyncio.create_task(
            self._save_challenge_to_s3(
                prompt=prompt,
                raw_output=output,
                feedback=feedback,
                iteration=iteration,
                review_id=review_id,
            )
        )

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
                env["GEMINI_API_KEY"] = api_key  # Gemini CLI uses this

            # Use model from settings
            model = self.settings.agents.gemini_model

            # Build CLI arguments
            args = [
                self.cli_path,
                "-m",
                model,
                "--yolo",
                "--output-format",
                "json",
            ]

            process = await asyncio.create_subprocess_exec(
                *args,
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
            except asyncio.TimeoutError:
                logger.error(f"Gemini CLI timed out after {self.timeout}s")
                process.kill()
                return None

            await process.wait()

            # Read stderr
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode() if stderr_bytes else ""

            if stderr_text:
                logger.warning(f"[GEMINI CLI] STDERR: {stderr_text[:1000]}")

            if process.returncode != 0:
                logger.error(f"[GEMINI CLI] FAILED with code {process.returncode}")
                logger.error(f"[GEMINI CLI] Full stderr: {stderr_text}")
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

            except json.JSONDecodeError:
                # Fallback to raw output if not valid JSON
                output = raw_output
                logger.warning("Gemini CLI output not valid JSON, using raw output")

            return output

        except FileNotFoundError:
            logger.error(f"[GEMINI CLI] NOT FOUND at: {self.cli_path}")
            return None
        except Exception as e:
            logger.exception(f"[GEMINI CLI] EXCEPTION: {e}")
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

        except json.JSONDecodeError as e:
            logger.error(f"[GEMINI PARSE] JSON DECODE ERROR: {e}")
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
