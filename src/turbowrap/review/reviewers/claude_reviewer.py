"""
Claude Opus 4.5 reviewer implementation.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import anthropic

from turbowrap.config import get_settings
from turbowrap.review.models.challenger import ChallengerFeedback
from turbowrap.review.models.review import ReviewOutput
from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext, S3LoggingMixin
from turbowrap.review.reviewers.utils import parse_review_output

logger = logging.getLogger(__name__)

# Type for thinking stream callback
ThinkingCallback = Callable[[str], Awaitable[None]]


class ClaudeReviewer(BaseReviewer, S3LoggingMixin):
    """
    Code reviewer using Claude Opus 4.5.

    Implements the reviewer role in the dual-reviewer system.
    Uses S3LoggingMixin for centralized S3 logging.
    """

    def __init__(
        self,
        name: str = "reviewer_be",
        model: str = "claude-opus-4-5-20251101",
        api_key: str | None = None,
    ):
        """
        Initialize Claude reviewer.

        Args:
            name: Reviewer identifier (reviewer_be, reviewer_fe, analyst_func)
            model: Claude model to use
            api_key: Anthropic API key (uses env var if not provided)
        """
        super().__init__(name, model)

        self.settings = get_settings()
        self.api_key = api_key or self.settings.agents.anthropic_api_key

        # Thinking settings from config
        self.thinking_enabled = self.settings.thinking.enabled
        self.thinking_budget = self.settings.thinking.budget_tokens

        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable."
            )

        self.client = anthropic.Anthropic(api_key=self.api_key)

    async def review(
        self,
        context: ReviewContext,
        thinking_callback: ThinkingCallback | None = None,
        review_id: str | None = None,
    ) -> ReviewOutput:
        """
        Perform code review using Claude with extended thinking.

        Args:
            context: Review context with files and metadata
            thinking_callback: Optional callback for streaming thinking chunks
            review_id: Optional review ID for S3 storage

        Returns:
            ReviewOutput with findings
        """
        start_time = time.time()
        review_id = review_id or f"{self.name}_{int(time.time())}"

        # Build the review prompt
        system_prompt = self._build_system_prompt(context)
        user_prompt = self._build_user_prompt(context)

        # Stream with extended thinking
        thinking_content, response_text = await asyncio.to_thread(
            self._stream_with_thinking_sync,
            system_prompt,
            user_prompt,
            thinking_callback,
        )

        # Save thinking to S3 in background (using mixin)
        if thinking_content:
            asyncio.create_task(
                self.log_thinking_to_s3(thinking_content, review_id, self.model, len(context.files))
            )

        # Parse the response using centralized parser
        review_output = self._parse_response(response_text, context)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()

        # Save complete review to S3 in background (using mixin)
        asyncio.create_task(
            self.log_review_to_s3(
                system_prompt, user_prompt, response_text, review_output, review_id, self.model
            )
        )

        return review_output

    def _stream_with_thinking_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        thinking_callback: ThinkingCallback | None = None,
    ) -> tuple[str, str]:
        """
        Synchronous version of streaming with extended thinking.
        Runs in thread pool to not block event loop.
        """
        thinking_content = ""
        response_text = ""

        # Build messages
        messages: list[anthropic.types.MessageParam] = [{"role": "user", "content": user_prompt}]

        # Build thinking config if enabled
        thinking_config: anthropic.types.ThinkingConfigParam | None = None
        if self.thinking_enabled:
            thinking_config = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }

        # Use streaming with explicit parameters
        stream_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system_prompt,
            "messages": messages,
        }
        if thinking_config is not None:
            stream_kwargs["thinking"] = thinking_config

        with self.client.messages.stream(**stream_kwargs) as stream:
            for event in stream:
                if hasattr(event, "type") and event.type == "content_block_delta":
                    if hasattr(event, "delta") and hasattr(event.delta, "type"):
                        if event.delta.type == "thinking_delta":
                            chunk = event.delta.thinking
                            thinking_content += chunk
                            # Note: callback handled separately
                        elif event.delta.type == "text_delta":
                            response_text += event.delta.text

        return thinking_content, response_text

    async def refine(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
        thinking_callback: ThinkingCallback | None = None,
        review_id: str | None = None,
    ) -> ReviewOutput:
        """
        Refine review based on challenger feedback with extended thinking.

        Args:
            context: Original review context
            previous_review: Previous review output
            feedback: Challenger feedback to address
            thinking_callback: Optional callback for streaming thinking
            review_id: Optional review ID for S3 storage

        Returns:
            Refined ReviewOutput
        """
        start_time = time.time()
        review_id = review_id or f"{self.name}_refine_{int(time.time())}"

        # Build refinement prompt
        system_prompt = self._build_system_prompt(context)
        user_prompt = self._build_refinement_prompt(context, previous_review, feedback)

        # Stream with extended thinking
        thinking_content, response_text = await asyncio.to_thread(
            self._stream_with_thinking_sync,
            system_prompt,
            user_prompt,
            thinking_callback,
        )

        # Save thinking to S3 in background (using mixin)
        if thinking_content:
            asyncio.create_task(
                self.log_thinking_to_s3(thinking_content, review_id, self.model, len(context.files))
            )

        # Parse the response using centralized parser
        review_output = self._parse_response(response_text, context)
        review_output.duration_seconds = time.time() - start_time
        review_output.reviewer = self.name
        review_output.timestamp = datetime.utcnow()
        review_output.iteration = previous_review.iteration + 1

        # Add refinement notes
        review_output.refinement_notes = previous_review.refinement_notes.copy()
        review_output.refinement_notes.append(
            {
                "iteration": review_output.iteration,
                "addressed_challenges": len(feedback.challenges),
                "added_issues": len(feedback.missed_issues),
                "satisfaction_before": feedback.satisfaction_score,
            }
        )

        # Save complete refinement to S3 in background (using mixin)
        asyncio.create_task(
            self.log_review_to_s3(
                system_prompt, user_prompt, response_text, review_output, review_id, self.model
            )
        )

        return review_output

    def _build_system_prompt(self, context: ReviewContext) -> str:
        """Build the system prompt for Claude."""
        base_prompt = context.agent_prompt or self._get_default_prompt()

        output_format = """

## Required Output Format

You MUST output your review as valid JSON matching this exact schema:

```json
{
  "summary": {
    "files_reviewed": <int>,
    "critical_issues": <int>,
    "high_issues": <int>,
    "medium_issues": <int>,
    "low_issues": <int>,
    "score": <float 0-10>
  },
  "issues": [
    {
      "id": "<REVIEWER-SEVERITY-NNN>",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "security|performance|architecture|style|logic|ux|testing|documentation",
      "rule": "<optional linting rule code>",
      "file": "<file path>",
      "line": <line number or null>,
      "title": "<brief title>",
      "description": "<detailed description>",
      "current_code": "<problematic code snippet>",
      "suggested_fix": "<corrected code>",
      "references": ["<url1>", "<url2>"]
    }
  ],
  "checklists": {
    "security": { "passed": <int>, "failed": <int>, "skipped": <int> },
    "performance": { "passed": <int>, "failed": <int>, "skipped": <int> },
    "architecture": { "passed": <int>, "failed": <int>, "skipped": <int> }
  },
  "metrics": {
    "complexity_avg": <float or null>,
    "test_coverage": <float or null>,
    "type_coverage": <float or null>
  }
}
```

IMPORTANT: Output ONLY the JSON. No markdown code blocks, no explanations before or after.
"""
        return base_prompt + output_format

    def _build_user_prompt(self, context: ReviewContext) -> str:
        """Build the user prompt for initial review."""
        sections = ["# Code Review Request\n"]

        # Add requirements if present
        if context.request.requirements:
            req = context.request.requirements
            sections.append("## Requirements\n")
            if req.description:
                sections.append(f"**Description**: {req.description}\n")
            if req.acceptance_criteria:
                sections.append("**Acceptance Criteria**:\n")
                for criterion in req.acceptance_criteria:
                    sections.append(f"- {criterion}\n")
            if req.ticket_url:
                sections.append(f"**Ticket**: {req.ticket_url}\n")

        # Add diff if available
        if context.diff:
            sections.append("\n## Changes (Diff)\n")
            sections.append(f"```diff\n{context.diff}\n```\n")

        # Add file contents
        sections.append("\n## Files to Review\n")
        sections.append(context.get_code_context())

        # Add specific instructions
        sections.append("\n## Review Instructions\n")
        sections.append(
            "1. Analyze all code thoroughly\n"
            "2. Identify security vulnerabilities, performance issues, and bugs\n"
            "3. Check for adherence to best practices and architectural patterns\n"
            "4. Provide specific, actionable feedback with code examples\n"
            "5. Prioritize issues by severity\n"
            "6. Output ONLY valid JSON as specified\n"
        )

        return "".join(sections)

    def _build_refinement_prompt(
        self,
        context: ReviewContext,
        previous_review: ReviewOutput,
        feedback: ChallengerFeedback,
    ) -> str:
        """Build the prompt for review refinement."""
        sections = ["# Review Refinement Request\n"]

        # Include previous review (complete with all issues)
        sections.append("## Previous Review\n")
        sections.append(f"```json\n{previous_review.model_dump_json(indent=2)}\n```\n")

        sections.append("\n## Challenger Feedback\n")
        sections.append(feedback.to_refinement_prompt())

        sections.append("\n## Original Code Context\n")
        sections.append(context.get_code_context())

        sections.append("\n## Refinement Instructions\n")
        sections.append(
            "1. Address ALL missed issues identified by the challenger\n"
            "2. Re-evaluate challenged issues and adjust if warranted\n"
            "3. Incorporate general improvements suggested\n"
            "4. Maintain all valid issues from the previous review\n"
            "5. Output the complete refined review as JSON\n"
        )

        return "".join(sections)

    def _parse_response(self, response_text: str, context: ReviewContext) -> ReviewOutput:
        """Parse Claude's response into ReviewOutput using centralized parser."""
        return parse_review_output(response_text, self.name, len(context.files))

    def _get_default_prompt(self) -> str:
        """Get default system prompt if agent file not found."""
        return """You are an expert code reviewer. Analyze the provided code thoroughly and identify:

1. Security vulnerabilities (SQL injection, XSS, authentication issues, etc.)
2. Performance problems (N+1 queries, memory leaks, inefficient algorithms)
3. Architectural issues (SOLID violations, tight coupling, missing abstractions)
4. Code style problems (naming, formatting, documentation)
5. Logic errors and edge cases
6. Testing gaps

Provide specific, actionable feedback with code examples where applicable.
Prioritize issues by severity: CRITICAL > HIGH > MEDIUM > LOW.
"""
