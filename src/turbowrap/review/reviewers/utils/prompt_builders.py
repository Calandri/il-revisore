"""
Prompt builders for challenger.

Provides centralized challenge prompt templates that can be used
with either SDK (code in prompt) or CLI (file list only) modes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from turbowrap.review.models.review import ReviewOutput
    from turbowrap.review.reviewers.base import ReviewContext


# Scoring guide and output format (shared between modes)
CHALLENGE_OUTPUT_FORMAT = """
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

Be fair but rigorous. Only flag REAL problems with the review.
Output ONLY the JSON, no markdown or explanations.
"""


CHALLENGE_DIMENSIONS = """
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
"""


def build_challenge_prompt_sdk(
    review: ReviewOutput,
    context: ReviewContext,
    iteration: int,
    max_code_chars: int = 30000,
) -> str:
    """
    Build challenge prompt for SDK mode (code embedded in prompt).

    Args:
        review: Review to challenge
        context: Review context with file contents
        iteration: Current iteration
        max_code_chars: Max chars for code context

    Returns:
        Complete prompt string
    """
    return f"""# Review Quality Evaluation - Iteration {iteration}

You are evaluating the QUALITY of a code review, not the code itself.
Your job is to determine if the reviewer did a good job.

## The Review to Evaluate

```json
{review.model_dump_json(indent=2)}
```

## The Code/Context Being Reviewed

{context.get_code_context(max_chars=max_code_chars)}

## Your Task

{CHALLENGE_DIMENSIONS}

{CHALLENGE_OUTPUT_FORMAT}
"""


def build_challenge_prompt_cli(
    review: ReviewOutput,
    file_list: list[str],
    iteration: int,
) -> str:
    """
    Build challenge prompt for CLI mode (file list only, model reads files).

    Args:
        review: Review to challenge
        file_list: List of files to verify
        iteration: Current iteration

    Returns:
        Complete prompt string
    """
    files_section = "\n".join(f"- {f}" for f in file_list)

    return f"""# Review Quality Evaluation - Iteration {iteration}

You are evaluating the QUALITY of a code review, not the code itself.
Your job is to determine if the reviewer did a good job.

**IMPORTANT**: You have access to the files. Read them to verify the review accuracy.

## The Review to Evaluate

```json
{review.model_dump_json(indent=2)}
```

## Files That Were Reviewed

Read these files to verify the review:
{files_section}

## Your Task

1. **Read the files** listed above
2. **Verify each issue** - is it real? Is the severity correct?
3. **Check for missed issues** - did the reviewer miss anything important?
4. **Evaluate fix suggestions** - are they correct and complete?

{CHALLENGE_DIMENSIONS}

{CHALLENGE_OUTPUT_FORMAT}
"""
