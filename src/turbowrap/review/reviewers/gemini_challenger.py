"""
Unified Gemini Challenger with SDK and CLI modes.

Consolidates gemini_challenger and gemini_cli_challenger into a single class
with a mode parameter.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import os
from collections.abc import Awaitable, Callable
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback, ChallengerStatus, DimensionScores
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext, S3LoggingMixin
from turbowrap.review.reviewers.utils import (
    build_challenge_prompt_cli,
    build_challenge_prompt_sdk,
    parse_challenger_feedback,
)

logger = logging.getLogger(__name__)


class GeminiMode(str, Enum):
    """Execution mode for Gemini challenger."""

    SDK = "sdk"  # Code embedded in prompt, uses google-genai SDK
    CLI = "cli"  # File list only, uses gemini CLI subprocess


class GeminiChallenger(BaseReviewer, S3LoggingMixin):
    """
    Unified Gemini challenger supporting both SDK and CLI modes.

    SDK mode: Embeds code in prompt (limited by token limits)
    CLI mode: Passes file list, model reads files autonomously (no limit)

    Usage:
        # SDK mode (default, for smaller codebases)
        challenger = GeminiChallenger(mode="sdk")
        feedback = await challenger.challenge(context, review)

        # CLI mode (for large codebases)
        challenger = GeminiChallenger(mode="cli")
        feedback = await challenger.challenge_cli(review, file_list, repo_path)
    """

    def __init__(
        self,
        name: str = "challenger",
        mode: GeminiMode | Literal["sdk", "cli"] = GeminiMode.SDK,
        timeout: int = 120,
        cli_path: str = "gemini",
    ):
        """
        Initialize Gemini challenger.

        Args:
            name: Challenger identifier
            mode: Execution mode (sdk or cli)
            timeout: Timeout in seconds for execution
            cli_path: Path to Gemini CLI executable (only for cli mode)
        """
        model = (
            "gemini-cli" if mode == GeminiMode.CLI or mode == "cli" else "gemini-3-flash-preview"
        )
        super().__init__(name, model)

        self.mode = GeminiMode(mode)
        self.settings = get_settings()
        self.timeout = timeout
        self.cli_path = cli_path
        self.threshold = self.settings.challenger.satisfaction_threshold

        # API key for SDK mode
        self.api_key = self.settings.agents.effective_google_key

    async def review(self, context: ReviewContext) -> ReviewOutput:
        """Not used for challenger - use challenge() instead."""
        raise NotImplementedError("Use challenge() method for GeminiChallenger")

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
        context: ReviewContext,
        review: ReviewOutput,
        iteration: int = 1,
        review_id: str | None = None,
    ) -> ChallengerFeedback:
        """
        Challenge a review (SDK mode - code in prompt).

        For CLI mode, use challenge_cli() instead.

        Args:
            context: Review context with code contents
            review: Review output to challenge
            iteration: Current iteration number
            review_id: Optional review ID for S3 logging

        Returns:
            ChallengerFeedback with evaluation and suggestions
        """
        if self.mode == GeminiMode.CLI:
            raise ValueError("Use challenge_cli() for CLI mode, or create with mode='sdk'")

        prompt = build_challenge_prompt_sdk(review, context, iteration)
        response = await self._call_sdk(prompt)

        feedback = parse_challenger_feedback(response, iteration, self.threshold)

        # Log to S3 in background (using mixin)
        if review_id:
            asyncio.create_task(
                self.log_challenge_to_s3(prompt, response, feedback, review_id, self.model)
            )

        return feedback

    async def challenge_cli(
        self,
        review: ReviewOutput,
        file_list: list[str],
        repo_path: Path | None,
        iteration: int = 1,
        review_id: str | None = None,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> ChallengerFeedback:
        """
        Challenge a review (CLI mode - file list only).

        The model reads files autonomously during execution.

        Args:
            review: Review output to challenge
            file_list: List of files that were reviewed
            repo_path: Repository path (used as cwd for CLI)
            iteration: Current iteration number
            review_id: Optional review ID for S3 logging
            on_chunk: Optional callback for streaming output chunks

        Returns:
            ChallengerFeedback with evaluation and suggestions
        """
        prompt = build_challenge_prompt_cli(review, file_list, iteration)
        response = await self._call_cli(prompt, repo_path, on_chunk)

        if response is None:
            return self._create_fallback_feedback(iteration)

        feedback = parse_challenger_feedback(response, iteration, self.threshold)

        # Log to S3 in background (using mixin)
        if review_id:
            asyncio.create_task(
                self.log_challenge_to_s3(prompt, response, feedback, review_id, "gemini-cli")
            )

        return feedback

    async def _call_sdk(self, prompt: str) -> str:
        """Call Gemini via SDK."""
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.settings.agents.gemini_model,
                contents=prompt,
            )
            text_result: str | None = response.text
            if text_result is None:
                return self._get_fallback_response()
            return text_result
        except ImportError:
            logger.warning("[GEMINI SDK] google-genai not installed, using fallback")
            return self._get_fallback_response()
        except Exception as e:
            logger.error(f"[GEMINI SDK] API error: {e}")
            return self._get_fallback_response(score=50, message=f"Challenger API error: {e}")

    async def _call_cli(
        self,
        prompt: str,
        repo_path: Path | None,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> str | None:
        """Call Gemini via CLI subprocess."""
        from turbowrap.utils.aws_secrets import get_google_api_key

        cwd = str(repo_path) if repo_path else None

        try:
            # Build environment with API key
            env = os.environ.copy()
            api_key = get_google_api_key()
            if api_key:
                env["GOOGLE_API_KEY"] = api_key
                env["GEMINI_API_KEY"] = api_key

            # Build CLI arguments
            args = [
                self.cli_path,
                "-m",
                self.settings.agents.gemini_model,
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

            # Write prompt to stdin - guard against None
            if process.stdin is None:
                logger.error("[GEMINI CLI] stdin is not available")
                return None
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
            process.stdin.close()

            # Guard against None stdout
            if process.stdout is None:
                logger.error("[GEMINI CLI] stdout is not available")
                return None

            # Read stdout in streaming mode with incremental UTF-8 decoder
            output_chunks: list[str] = []
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

            try:
                async with asyncio.timeout(self.timeout):  # type: ignore[attr-defined]
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
                            if on_chunk:
                                await on_chunk(decoded)
            except asyncio.TimeoutError:
                logger.error(f"[GEMINI CLI] Timeout after {self.timeout}s")
                process.kill()
                return None

            await process.wait()

            if process.returncode != 0:
                if process.stderr is not None:
                    stderr = await process.stderr.read()
                    logger.error(f"[GEMINI CLI] Failed: {stderr.decode()[:500]}")
                else:
                    logger.error("[GEMINI CLI] Failed with no stderr")
                return None

            raw_output = "".join(output_chunks)

            # Parse CLI JSON wrapper
            try:
                cli_response: dict[str, Any] = json.loads(raw_output)
                if "error" in cli_response:
                    logger.error(f"[GEMINI CLI] Error: {cli_response['error']}")
                    return None
                result_value = cli_response.get("result") or cli_response.get(
                    "response", raw_output
                )
                if isinstance(result_value, str):
                    return result_value
                return raw_output
            except json.JSONDecodeError:
                return raw_output

        except FileNotFoundError:
            logger.error(f"[GEMINI CLI] Not found at: {self.cli_path}")
            return None
        except Exception as e:
            logger.exception(f"[GEMINI CLI] Exception: {e}")
            return None

    def _create_fallback_feedback(
        self,
        iteration: int = 1,
        score: int = 80,
        message: str = "Gemini unavailable - manual review recommended.",
    ) -> ChallengerFeedback:
        """
        Create fallback feedback when execution fails.

        Args:
            iteration: Current iteration number
            score: Satisfaction score (0-100)
            message: Error/warning message for improvements_needed

        Returns:
            ChallengerFeedback with consistent fallback values
        """
        return ChallengerFeedback(
            iteration=iteration,
            satisfaction_score=score,
            threshold=self.threshold,
            status=ChallengerStatus.NEEDS_REFINEMENT,
            dimension_scores=DimensionScores(
                completeness=score, accuracy=score, depth=score, actionability=score
            ),
            improvements_needed=[message] if message else [],
            positive_feedback=["Review structure appears reasonable."] if score >= 70 else [],
        )

    def _get_fallback_response(self, score: int = 80, message: str = "SDK unavailable") -> str:
        """
        Get fallback JSON response.

        Uses _create_fallback_feedback internally for consistency.
        """
        feedback = self._create_fallback_feedback(iteration=1, score=score, message=message)
        return feedback.model_dump_json()
