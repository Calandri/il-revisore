"""
Gemini 3 CLI challenger implementation.
"""

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
        self.threshold = 99.0  # Default threshold

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
        prompt = f"""# Code Review Challenge - Iteration {iteration}

You are an expert code review challenger. Your mission is to ensure the review is thorough, secure, accurate, and production-ready.

## Review to Evaluate

```json
{review.model_dump_json(indent=2)}
```

## Original Code Context

{context.get_code_context(max_chars=50000)}

"""
        if context.diff:
            prompt += f"""## Code Changes (Diff)

```diff
{context.diff[:20000]}
```

"""

        # Add linked repos context if available
        if hasattr(context, 'linked_repos') and context.linked_repos:
            prompt += """## Linked Repositories Context

This repository has linked repositories. Consider cross-repo implications:

"""
            for linked in context.linked_repos:
                prompt += f"""- **{linked.get('name', 'Unknown')}** ({linked.get('link_type', 'related')}, {linked.get('direction', 'linked')})
  - Repo type: {linked.get('repo_type', 'unknown')}
"""
            prompt += """
When evaluating, check for:
- API contract consistency between frontend and backend
- Shared type definitions and interfaces
- Breaking changes that affect linked repos
- Authentication/authorization flow consistency
- Data format compatibility (request/response schemas)

"""

        prompt += """## Evaluation Dimensions

Evaluate the review on these dimensions (0-100 score each):

### 1. **Completeness** (weight: 25%)
- Are ALL files in scope reviewed (not just changed files)?
- Are all categories covered: security, performance, architecture, maintainability?
- Are edge cases and error paths considered?
- Are integration points and external API calls analyzed?
- Are database queries and data access patterns reviewed?

### 2. **Security** (weight: 30%) ⚠️ CRITICAL
Apply OWASP Top 10 checklist rigorously:
- **Injection**: SQL, NoSQL, OS command, LDAP injection vulnerabilities
- **Broken Auth**: Weak passwords, session management, credential exposure
- **Sensitive Data**: PII/secrets in logs, unencrypted data, insecure storage
- **XXE/XSS**: XML external entities, cross-site scripting vectors
- **Access Control**: Missing authorization, IDOR, privilege escalation
- **Security Misconfig**: Debug mode, default credentials, verbose errors
- **Insecure Deserialization**: Untrusted data deserialization
- **Vulnerable Components**: Outdated dependencies with known CVEs
- **Logging Failures**: Missing audit logs, sensitive data in logs
- **SSRF**: Server-side request forgery vulnerabilities

Also check:
- Input validation on ALL user inputs
- Rate limiting and DoS protection
- CORS configuration
- JWT/token handling
- File upload security
- Path traversal prevention

### 3. **Code Quality** (weight: 20%)
Evaluate technical debt and maintainability:
- **Complexity**: Functions with high cyclomatic complexity (>10)
- **Code Smells**: Long methods, god classes, feature envy, data clumps
- **DRY Violations**: Duplicated code blocks (>5 lines)
- **SOLID Violations**: Single responsibility, dependency inversion issues
- **Error Handling**: Swallowed exceptions, generic catches, missing error types
- **Type Safety**: Missing types, any abuse, unsafe casts
- **Test Coverage**: Missing tests for critical paths, edge cases untested
- **Documentation**: Missing JSDoc/docstrings for public APIs

### 4. **Depth** (weight: 15%)
- Are ROOT CAUSES identified, not just symptoms?
- Is business logic impact analyzed?
- Are cross-file and cross-module dependencies traced?
- Are database schema implications considered?
- Is performance impact quantified where possible?

### 5. **Actionability** (weight: 10%)
- Are fix suggestions COPY-PASTE ready?
- Are code examples syntactically correct and tested?
- Is priority/effort guidance realistic?
- Are migration steps clear for breaking changes?

## Required Output Format

Output ONLY valid JSON matching this schema:

```json
{
  "satisfaction_score": <weighted average 0-100>,
  "status": "APPROVED|NEEDS_REFINEMENT|MAJOR_ISSUES",
  "dimension_scores": {
    "completeness": <0-100>,
    "security": <0-100>,
    "code_quality": <0-100>,
    "depth": <0-100>,
    "actionability": <0-100>
  },
  "security_checklist": {
    "injection_checked": <true|false>,
    "auth_checked": <true|false>,
    "data_exposure_checked": <true|false>,
    "access_control_checked": <true|false>,
    "input_validation_checked": <true|false>,
    "critical_findings": ["<finding 1>", "<finding 2>"]
  },
  "code_quality_metrics": {
    "high_complexity_functions": ["<func1>", "<func2>"],
    "duplicated_code_blocks": <count>,
    "missing_error_handling": ["<location1>", "<location2>"],
    "type_safety_issues": <count>
  },
  "cross_repo_issues": [
    {
      "type": "api_mismatch|breaking_change|type_inconsistency|auth_flow",
      "description": "<what's inconsistent>",
      "affected_repos": ["<repo1>", "<repo2>"],
      "suggested_fix": "<how to resolve>"
    }
  ],
  "missed_issues": [
    {
      "type": "security|performance|architecture|logic|quality",
      "description": "<what was missed>",
      "file": "<file path>",
      "lines": "<line range or null>",
      "why_important": "<impact explanation>",
      "suggested_severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "owasp_category": "<if security: A01-A10 or null>"
    }
  ],
  "challenges": [
    {
      "issue_id": "<id of challenged issue>",
      "challenge_type": "severity|fix_incomplete|false_positive|needs_context|security_underrated",
      "challenge": "<the challenge>",
      "reasoning": "<detailed reasoning>",
      "suggested_change": "<what to change>"
    }
  ],
  "improvements_needed": [
    "<specific improvement 1>",
    "<specific improvement 2>"
  ],
  "positive_feedback": [
    "<what was done well 1>"
  ]
}
```

## Scoring Guidelines

- **99-100**: Production ready, all security checks pass, comprehensive coverage
- **90-98**: Minor improvements needed, no security issues
- **70-89**: Significant gaps, requires refinement
- **50-69**: Major issues missed, especially security
- **<50**: Review is inadequate, restart recommended

## Critical Rules

1. **SECURITY IS NON-NEGOTIABLE**: Any missed CRITICAL/HIGH security issue = automatic score cap at 70
2. **Be rigorous but fair**: Flag real problems, not style preferences
3. **Cross-repo consistency matters**: API contracts must match
4. **Quantify when possible**: "3 SQL injection points" not "some injection risks"
5. **Every missed CRITICAL issue must be documented in missed_issues**

Output ONLY the JSON, no markdown blocks or explanations.
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
            response = client.models.generate_content(
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
