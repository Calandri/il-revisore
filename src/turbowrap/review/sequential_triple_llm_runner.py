"""
Sequential Triple-LLM Review Runner.

Optimized runner that launches 3 CLI processes (one per LLM),
each executing all specialists sequentially within a single session.

This reduces 15 separate CLI processes (5 specialists × 3 LLMs) down to just 3,
sharing cache within each LLM session and significantly reducing costs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from turbowrap.config import get_settings
from turbowrap.llm.claude_cli import ClaudeCLI
from turbowrap.llm.gemini import GeminiCLI
from turbowrap.llm.grok import GrokCLI
from turbowrap.orchestration.report_utils import deduplicate_issues
from turbowrap.review.models.review import (
    Issue,
    IssueCategory,
    IssueSeverity,
    ReviewOutput,
    ReviewSummary,
)
from turbowrap.review.reviewers.utils import parse_review_output

if TYPE_CHECKING:
    from turbowrap.review.reviewers.base import ReviewContext

logger = logging.getLogger(__name__)

# Timeout for sequential review (longer since it runs all specialists)
SEQUENTIAL_TIMEOUT = 900  # 15 minutes


@dataclass
class SequentialTripleLLMResult:
    """Result of sequential triple-LLM review."""

    # Merged review output (all specialists, all LLMs)
    final_review: ReviewOutput

    # Per-LLM aggregated stats
    claude_issues_count: int = 0
    gemini_issues_count: int = 0
    grok_issues_count: int = 0
    merged_issues_count: int = 0
    overlap_count: int = 0  # Issues found by 2+ LLMs
    triple_overlap_count: int = 0  # Issues found by all 3 LLMs

    # Status (ok or error message)
    claude_status: str = "ok"
    gemini_status: str = "ok"
    grok_status: str = "ok"

    # Duration
    claude_duration_seconds: float = 0.0
    gemini_duration_seconds: float = 0.0
    grok_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0

    # Per-specialist results (specialist_name -> ReviewOutput)
    claude_reviews: dict[str, ReviewOutput] = field(default_factory=dict)
    gemini_reviews: dict[str, ReviewOutput] = field(default_factory=dict)
    grok_reviews: dict[str, ReviewOutput] = field(default_factory=dict)


class SequentialTripleLLMRunner:
    """
    Run triple-LLM review with sequential specialists.

    Instead of 15 CLI processes (5 reviewers × 3 LLMs),
    runs only 3 CLI processes (1 per LLM), each executing
    all specialists sequentially within a single session.

    Benefits:
    - Cache is shared across all specialists within each LLM
    - ~80% reduction in cache creation costs
    - Same total output quality (15 review perspectives)
    """

    def __init__(
        self,
        specialists: list[str],
        timeout: int = SEQUENTIAL_TIMEOUT,
    ):
        """
        Initialize sequential triple-LLM runner.

        Args:
            specialists: List of specialist names (e.g., ["reviewer_be_architecture", ...])
            timeout: Timeout in seconds for each CLI execution
        """
        self.specialists = specialists
        self.timeout = timeout
        self.settings = get_settings()

    async def run(
        self,
        context: ReviewContext,
        file_list: list[str] | None = None,
        on_claude_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_gemini_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_grok_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> SequentialTripleLLMResult:
        """
        Run all 3 LLMs in parallel, each with sequential specialists.

        Args:
            context: Review context with repo path and metadata
            file_list: List of files to review (uses context.files if not provided)
            on_claude_chunk: Optional callback for Claude streaming output
            on_gemini_chunk: Optional callback for Gemini streaming output
            on_grok_chunk: Optional callback for Grok streaming output

        Returns:
            SequentialTripleLLMResult with merged issues and per-LLM stats
        """
        start_time = time.time()
        files = file_list or context.files

        # Load all agent prompts once
        agent_prompts = self._load_agent_prompts()

        # Build the sequential prompt (same for all LLMs)
        prompt = self._build_sequential_prompt(context, files, agent_prompts)

        logger.info(
            f"[SEQ-TRIPLE-LLM] Starting review with {len(self.specialists)} specialists "
            f"across 3 LLMs ({len(files)} files)"
        )

        # Launch 3 CLI in parallel
        claude_task = asyncio.create_task(self._run_claude(context, prompt, on_claude_chunk))
        gemini_task = asyncio.create_task(self._run_gemini(context, prompt, on_gemini_chunk))
        grok_task = asyncio.create_task(self._run_grok(context, prompt, on_grok_chunk))

        # Wait for all with exception handling
        results = await asyncio.gather(claude_task, gemini_task, grok_task, return_exceptions=True)

        claude_result, gemini_result, grok_result = results

        # Process results
        claude_ok = not isinstance(claude_result, Exception)
        gemini_ok = not isinstance(gemini_result, Exception)
        grok_ok = not isinstance(grok_result, Exception)

        claude_reviews: dict[str, ReviewOutput] = {}
        gemini_reviews: dict[str, ReviewOutput] = {}
        grok_reviews: dict[str, ReviewOutput] = {}

        if claude_ok and isinstance(claude_result, tuple):
            claude_reviews, claude_duration = claude_result
        else:
            claude_duration = 0.0
            if isinstance(claude_result, Exception):
                logger.error(f"[SEQ-TRIPLE-LLM] Claude failed: {claude_result}")

        if gemini_ok and isinstance(gemini_result, tuple):
            gemini_reviews, gemini_duration = gemini_result
        else:
            gemini_duration = 0.0
            if isinstance(gemini_result, Exception):
                logger.error(f"[SEQ-TRIPLE-LLM] Gemini failed: {gemini_result}")

        if grok_ok and isinstance(grok_result, tuple):
            grok_reviews, grok_duration = grok_result
        else:
            grok_duration = 0.0
            if isinstance(grok_result, Exception):
                logger.error(f"[SEQ-TRIPLE-LLM] Grok failed: {grok_result}")

        # Collect all issues with source tagging
        all_issues: list[Issue] = []

        for spec_name, review in claude_reviews.items():
            for issue in review.issues:
                if "claude" not in issue.flagged_by:
                    issue.flagged_by.append("claude")
                if spec_name not in issue.flagged_by:
                    issue.flagged_by.append(spec_name)
            all_issues.extend(review.issues)

        for spec_name, review in gemini_reviews.items():
            for issue in review.issues:
                if "gemini" not in issue.flagged_by:
                    issue.flagged_by.append("gemini")
                if spec_name not in issue.flagged_by:
                    issue.flagged_by.append(spec_name)
            all_issues.extend(review.issues)

        for spec_name, review in grok_reviews.items():
            for issue in review.issues:
                if "grok" not in issue.flagged_by:
                    issue.flagged_by.append("grok")
                if spec_name not in issue.flagged_by:
                    issue.flagged_by.append(spec_name)
            all_issues.extend(review.issues)

        # Merge and deduplicate issues
        merged_issues = deduplicate_issues(all_issues)

        # Count overlaps
        overlap_count = sum(
            1
            for issue in merged_issues
            if any(llm in issue.flagged_by for llm in ["claude", "gemini", "grok"])
            and sum(llm in issue.flagged_by for llm in ["claude", "gemini", "grok"]) > 1
        )
        triple_overlap_count = sum(
            1
            for issue in merged_issues
            if "claude" in issue.flagged_by
            and "gemini" in issue.flagged_by
            and "grok" in issue.flagged_by
        )

        # Calculate merged summary
        merged_summary = self._merge_summaries(
            claude_reviews, gemini_reviews, grok_reviews, merged_issues, len(files)
        )

        # Create merged review output
        final_review = ReviewOutput(
            reviewer="sequential_triple_llm",
            summary=merged_summary,
            issues=merged_issues,
            duration_seconds=time.time() - start_time,
        )

        # Issue counts per LLM
        claude_issues_count = sum(len(r.issues) for r in claude_reviews.values())
        gemini_issues_count = sum(len(r.issues) for r in gemini_reviews.values())
        grok_issues_count = sum(len(r.issues) for r in grok_reviews.values())

        # Determine statuses
        def _get_status(ok: bool, reviews: dict[str, ReviewOutput], result: Any) -> str:
            if ok and reviews:
                return "ok"
            if not ok:
                return str(result)[:50]
            return "no_output"

        claude_status = _get_status(claude_ok, claude_reviews, claude_result)
        gemini_status = _get_status(gemini_ok, gemini_reviews, gemini_result)
        grok_status = _get_status(grok_ok, grok_reviews, grok_result)

        # Log results
        logger.info(
            f"[SEQ-TRIPLE-LLM] Complete: "
            f"Claude={claude_issues_count} ({claude_status}, {len(claude_reviews)} specs), "
            f"Gemini={gemini_issues_count} ({gemini_status}, {len(gemini_reviews)} specs), "
            f"Grok={grok_issues_count} ({grok_status}, {len(grok_reviews)} specs), "
            f"Merged={len(merged_issues)} (overlap={overlap_count}, triple={triple_overlap_count})"
        )

        return SequentialTripleLLMResult(
            final_review=final_review,
            claude_issues_count=claude_issues_count,
            gemini_issues_count=gemini_issues_count,
            grok_issues_count=grok_issues_count,
            merged_issues_count=len(merged_issues),
            overlap_count=overlap_count,
            triple_overlap_count=triple_overlap_count,
            claude_status=claude_status,
            gemini_status=gemini_status,
            grok_status=grok_status,
            claude_duration_seconds=claude_duration,
            gemini_duration_seconds=gemini_duration,
            grok_duration_seconds=grok_duration,
            total_duration_seconds=time.time() - start_time,
            claude_reviews=claude_reviews,
            gemini_reviews=gemini_reviews,
            grok_reviews=grok_reviews,
        )

    def _load_agent_prompts(self) -> dict[str, str]:
        """Load agent prompts from MD files for all specialists."""
        prompts = {}
        agents_dir = self.settings.agents_dir

        for spec_name in self.specialists:
            md_path = agents_dir / f"{spec_name}.md"
            if md_path.exists():
                try:
                    content = md_path.read_text(encoding="utf-8")
                    # Remove YAML frontmatter if present
                    if content.startswith("---"):
                        end_marker = content.find("---", 3)
                        if end_marker != -1:
                            content = content[end_marker + 3 :].strip()
                    prompts[spec_name] = content
                    logger.debug(f"Loaded agent prompt: {spec_name} ({len(content)} chars)")
                except Exception as e:
                    logger.warning(f"Failed to load agent prompt {md_path}: {e}")
            else:
                logger.warning(f"Agent prompt not found: {md_path}")

        return prompts

    def _build_sequential_prompt(
        self,
        context: ReviewContext,
        file_list: list[str],
        agent_prompts: dict[str, str],
    ) -> str:
        """
        Build the combined prompt for sequential specialist execution.

        The prompt instructs the LLM to:
        1. Analyze files once (cached)
        2. Apply each specialist perspective sequentially
        3. Output separate JSON blocks for each specialist
        """
        sections = []

        # Header
        sections.append(
            """# Sequential Multi-Specialist Code Review

You will perform a comprehensive code review from multiple specialist perspectives.
Execute each specialist review IN SEQUENCE, outputting separate JSON blocks.

IMPORTANT: This is a single session - read files ONCE and reuse your understanding
for all specialist perspectives. This is more efficient than separate reviews.
"""
        )

        # Repository context
        if context.structure_docs:
            sections.append("## Repository Structure Documentation\n")
            for path, content in context.structure_docs.items():
                # Limit structure doc size to avoid prompt overflow
                if len(content) > 30000:
                    content = content[:30000] + "\n... (truncated)"
                sections.append(f"### {path}\n{content}\n")

        if context.business_context:
            sections.append(f"## Business Context\n{context.business_context}\n")

        # File list
        sections.append("## Files to Analyze\n")
        sections.append("Read and analyze the following files:\n")
        for f in file_list:
            sections.append(f"- {f}\n")

        # Workspace constraint for monorepos
        if context.workspace_path:
            sections.append(
                f"""
## IMPORTANT: Monorepo Workspace Scope
This is a **monorepo** review. Only analyze files within: `{context.workspace_path}/`
DO NOT navigate outside this workspace.
"""
            )

        # Specialist sections
        sections.append("\n---\n# SPECIALIST REVIEWS\n")
        sections.append(f"Execute the following {len(agent_prompts)} specialist reviews:\n")

        for i, (spec_name, prompt_content) in enumerate(agent_prompts.items(), 1):
            # Truncate very long prompts
            if len(prompt_content) > 15000:
                prompt_content = prompt_content[:15000] + "\n... (truncated)"

            # Build JSON schema example (split for readability)
            summary_schema = (
                '"summary": {"files_reviewed": N, "critical_issues": N, '
                '"high_issues": N, "medium_issues": N, "low_issues": N, "score": 1-10}'
            )
            issue_schema = (
                '{"code": "ISSUE-001", "severity": "critical|high|medium|low", '
                '"category": "...", "file": "...", "line": N, "title": "...", '
                '"description": "...", "suggested_fix": "...", "effort": 1-5}'
            )

            sections.append(
                f"""
---
## SPECIALIST {i}: {spec_name}

{prompt_content}

**OUTPUT for {spec_name}:**
After completing this review, output a JSON block:
```json
{{"specialist": "{spec_name}", "review": {{
  {summary_schema},
  "issues": [
    {issue_schema}
  ]
}}}}
```
---
"""
            )

        # Output instructions
        output_file = ".turbowrap_review_sequential.json"
        if context.repo_path:
            if context.workspace_path:
                output_path = str(context.repo_path / context.workspace_path / output_file)
            else:
                output_path = str(context.repo_path / output_file)
        else:
            output_path = output_file

        sections.append(
            f"""
---
# FINAL OUTPUT INSTRUCTIONS

1. Read all files listed above ONCE
2. For EACH specialist (1 through {len(agent_prompts)}):
   a. Apply that specialist's perspective
   b. Output the JSON block with {{"specialist": "name", "review": {{...}}}}
3. Ensure each JSON block is valid and complete
4. Save ALL JSON blocks to: `{output_path}`
5. After writing, confirm: "Sequential review saved to {output_path}"

CRITICAL: Output {len(agent_prompts)} separate JSON blocks, one per specialist.
Each must have the exact format shown above with "specialist" and "review" keys.
"""
        )

        return "".join(sections)

    async def _run_claude(
        self,
        context: ReviewContext,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[dict[str, ReviewOutput], float]:
        """Run Claude CLI with sequential specialists."""
        start_time = time.time()
        try:
            cli = ClaudeCLI(
                working_dir=context.repo_path,
                model="opus",
                timeout=self.timeout,
                s3_prefix="reviews/claude_sequential",
            )

            meta = context.metadata or {}
            review_id = meta.get("review_id", "unknown")
            repo_name = context.repo_path.name if context.repo_path else "unknown"

            result = await cli.run(
                prompt,
                operation_type="review",
                repo_name=repo_name,
                context_id=f"{review_id}_sequential_claude",
                save_prompt=True,
                save_output=True,
                on_chunk=on_chunk,
                track_operation=True,
                user_name="system",
                operation_details={
                    "reviewer": "sequential_claude",
                    "specialists": self.specialists,
                    "workspace_path": context.workspace_path,
                },
            )

            if not result.success:
                logger.error(f"[SEQ-CLAUDE] Failed: {result.error}")
                return {}, time.time() - start_time

            reviews = self._parse_sequential_output(result.output, "claude", len(context.files))
            return reviews, time.time() - start_time

        except Exception as e:
            logger.exception(f"[SEQ-CLAUDE] Exception: {e}")
            raise

    async def _run_gemini(
        self,
        context: ReviewContext,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[dict[str, ReviewOutput], float]:
        """Run Gemini CLI with sequential specialists."""
        start_time = time.time()
        try:
            cli = GeminiCLI(
                working_dir=context.repo_path,
                model="gemini-2.5-pro-preview-05-06",
                timeout=self.timeout,
                s3_prefix="reviews/gemini_sequential",
            )

            meta = context.metadata or {}
            review_id = meta.get("review_id", "unknown")
            repo_name = context.repo_path.name if context.repo_path else "unknown"

            result = await cli.run(
                prompt,
                operation_type="review",
                repo_name=repo_name,
                context_id=f"{review_id}_sequential_gemini",
                save_prompt=True,
                save_output=True,
                on_chunk=on_chunk,
                track_operation=True,
                user_name="system",
                operation_details={
                    "reviewer": "sequential_gemini",
                    "specialists": self.specialists,
                    "workspace_path": context.workspace_path,
                },
            )

            if not result.success:
                logger.error(f"[SEQ-GEMINI] Failed: {result.error}")
                return {}, time.time() - start_time

            reviews = self._parse_sequential_output(result.output, "gemini", len(context.files))
            return reviews, time.time() - start_time

        except Exception as e:
            logger.exception(f"[SEQ-GEMINI] Exception: {e}")
            raise

    async def _run_grok(
        self,
        context: ReviewContext,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[dict[str, ReviewOutput], float]:
        """Run Grok CLI with sequential specialists."""
        start_time = time.time()
        try:
            cli = GrokCLI(
                working_dir=context.repo_path,
                model="grok-4-1-fast-reasoning",
                timeout=self.timeout,
                s3_prefix="reviews/grok_sequential",
            )

            meta = context.metadata or {}
            review_id = meta.get("review_id", "unknown")
            repo_name = context.repo_path.name if context.repo_path else "unknown"

            result = await cli.run(
                prompt,
                operation_type="review",
                repo_name=repo_name,
                context_id=f"{review_id}_sequential_grok",
                save_prompt=True,
                save_output=True,
                on_chunk=on_chunk,
                track_operation=True,
                user_name="system",
                operation_details={
                    "reviewer": "sequential_grok",
                    "specialists": self.specialists,
                    "workspace_path": context.workspace_path,
                },
            )

            if not result.success:
                logger.error(f"[SEQ-GROK] Failed: {result.error}")
                return {}, time.time() - start_time

            reviews = self._parse_sequential_output(result.output, "grok", len(context.files))
            return reviews, time.time() - start_time

        except Exception as e:
            logger.exception(f"[SEQ-GROK] Exception: {e}")
            raise

    def _parse_sequential_output(
        self,
        output: str,
        llm: str,
        files_count: int,
    ) -> dict[str, ReviewOutput]:
        """
        Parse multi-specialist JSON output from single CLI session.

        Extracts all JSON blocks with {"specialist": "name", "review": {...}}
        and converts them to ReviewOutput objects.
        """
        results: dict[str, ReviewOutput] = {}

        if not output:
            logger.warning(f"[SEQ-{llm.upper()}] Empty output")
            return results

        # Strategy 1: Try to extract JSON blocks between ``` markers first
        json_blocks = re.findall(r"```json\s*(.*?)\s*```", output, re.DOTALL)

        for block in json_blocks:
            try:
                data = json.loads(block.strip())
                if isinstance(data, dict) and "specialist" in data and "review" in data:
                    spec_name = data["specialist"]
                    review_data = data["review"]
                    review = self._convert_review_data(review_data, spec_name, llm, files_count)
                    if review:
                        results[spec_name] = review
                        n_issues = len(review.issues)
                        logger.debug(f"[SEQ-{llm.upper()}] Parsed {spec_name}: {n_issues} issues")
            except json.JSONDecodeError as e:
                logger.debug(f"[SEQ-{llm.upper()}] JSON block parse error: {e}")
                continue

        # Strategy 2: Try to find JSON objects without code blocks
        if not results:
            # Look for {"specialist": patterns
            specialist_matches = list(re.finditer(r'\{\s*"specialist"\s*:', output))
            for match in specialist_matches:
                start = match.start()
                # Find matching closing brace
                brace_count = 0
                end = start
                for i, char in enumerate(output[start:], start):
                    if char == "{":
                        brace_count += 1
                    elif char == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            end = i + 1
                            break

                if end > start:
                    try:
                        json_str = output[start:end]
                        data = json.loads(json_str)
                        if "specialist" in data and "review" in data:
                            spec_name = data["specialist"]
                            review_data = data["review"]
                            review = self._convert_review_data(
                                review_data, spec_name, llm, files_count
                            )
                            if review:
                                results[spec_name] = review
                    except json.JSONDecodeError:
                        continue

        # Strategy 3: Fallback to parsing markdown-style output
        if not results:
            logger.warning(f"[SEQ-{llm.upper()}] No JSON blocks found, trying markdown parse")
            # Try to use the existing parse_review_output for markdown format
            for spec_name in self.specialists:
                if spec_name in output:
                    # Extract section for this specialist
                    spec_pattern = rf"## SPECIALIST \d+: {spec_name}.*?(?=## SPECIALIST \d+:|$)"
                    spec_match = re.search(spec_pattern, output, re.DOTALL)
                    if spec_match:
                        spec_output = spec_match.group(0)
                        review = parse_review_output(spec_output, spec_name, files_count)
                        if review and review.issues:
                            results[spec_name] = review

        logger.info(f"[SEQ-{llm.upper()}] Parsed {len(results)} specialist reviews")
        return results

    def _convert_review_data(
        self,
        review_data: dict[str, Any],
        spec_name: str,
        llm: str,
        files_count: int,
    ) -> ReviewOutput | None:
        """Convert parsed review data dict to ReviewOutput."""
        try:
            # Extract summary
            summary_data = review_data.get("summary", {})
            summary = ReviewSummary(
                files_reviewed=summary_data.get("files_reviewed", files_count),
                critical_issues=summary_data.get("critical_issues", 0),
                high_issues=summary_data.get("high_issues", 0),
                medium_issues=summary_data.get("medium_issues", 0),
                low_issues=summary_data.get("low_issues", 0),
                score=summary_data.get("score", 5.0),
            )

            # Extract issues
            issues: list[Issue] = []
            for issue_data in review_data.get("issues", []):
                try:
                    severity_str = issue_data.get("severity", "medium").lower()
                    valid_severities = ["critical", "high", "medium", "low"]
                    if severity_str in valid_severities:
                        severity = IssueSeverity(severity_str)
                    else:
                        severity = IssueSeverity.MEDIUM

                    # Map category string to enum
                    category_str = issue_data.get("category", "logic").lower()
                    category_map = {
                        "security": IssueCategory.SECURITY,
                        "performance": IssueCategory.PERFORMANCE,
                        "architecture": IssueCategory.ARCHITECTURE,
                        "style": IssueCategory.STYLE,
                        "logic": IssueCategory.LOGIC,
                        "ux": IssueCategory.UX,
                        "testing": IssueCategory.TESTING,
                        "documentation": IssueCategory.DOCUMENTATION,
                    }
                    category = category_map.get(category_str, IssueCategory.LOGIC)

                    issue = Issue(
                        id=issue_data.get("code", f"{spec_name.upper()}-{len(issues)+1:03d}"),
                        severity=severity,
                        category=category,
                        file=issue_data.get("file", ""),
                        line=issue_data.get("line"),
                        title=issue_data.get("title", "Untitled Issue"),
                        description=issue_data.get("description", ""),
                        suggested_fix=issue_data.get("suggested_fix"),
                        estimated_effort=issue_data.get("effort"),
                        flagged_by=[llm, spec_name],
                    )
                    issues.append(issue)
                except Exception as e:
                    logger.debug(f"[SEQ-{llm.upper()}] Failed to parse issue: {e}")
                    continue

            return ReviewOutput(
                reviewer=spec_name,
                summary=summary,
                issues=issues,
            )

        except Exception as e:
            logger.warning(f"[SEQ-{llm.upper()}] Failed to convert review data: {e}")
            return None

    def _merge_summaries(
        self,
        claude_reviews: dict[str, ReviewOutput],
        gemini_reviews: dict[str, ReviewOutput],
        grok_reviews: dict[str, ReviewOutput],
        merged_issues: list[Issue],
        files_count: int,
    ) -> ReviewSummary:
        """Merge summaries from all LLMs and specialists."""
        # Count severities in merged issues
        critical = sum(1 for i in merged_issues if i.severity == IssueSeverity.CRITICAL)
        high = sum(1 for i in merged_issues if i.severity == IssueSeverity.HIGH)
        medium = sum(1 for i in merged_issues if i.severity == IssueSeverity.MEDIUM)
        low = sum(1 for i in merged_issues if i.severity == IssueSeverity.LOW)

        # Average scores from all reviews
        scores: list[float] = []
        for review in claude_reviews.values():
            scores.append(review.summary.score)
        for review in gemini_reviews.values():
            scores.append(review.summary.score)
        for review in grok_reviews.values():
            scores.append(review.summary.score)

        avg_score = sum(scores) / len(scores) if scores else 5.0

        return ReviewSummary(
            files_reviewed=files_count,
            critical_issues=critical,
            high_issues=high,
            medium_issues=medium,
            low_issues=low,
            score=avg_score,
        )
