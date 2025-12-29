"""
Parallel Triple-LLM Review Runner.

Launches 3 CLI processes IN PARALLEL (Claude, Gemini, Grok),
each executing all specialists within a single session.

Architecture:
    ┌───────────────────────────────────────────────────────────────┐
    │  ParallelTripleLLMRunner.run()                                │
    │  └── asyncio.gather() → 3 CLI IN PARALLEL                     │
    │       ├── ClaudeCLI  → reads agents/*.md → N specialist JSONs │
    │       ├── GeminiCLI  → reads agents/*.md → N specialist JSONs │
    │       └── GrokCLI    → reads agents/*.md → N specialist JSONs │
    │                                                               │
    │  Result: 3×N reviews → deduplicate → merged final report      │
    └───────────────────────────────────────────────────────────────┘

Benefits vs old approach (15 CLI processes):
- 3 CLI processes instead of 15 (5 specialists × 3 LLMs)
- Cache shared within each LLM session
- ~80% reduction in cache creation costs
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from turbowrap.config import get_settings
from turbowrap.llm.claude_cli import ClaudeCLI
from turbowrap.llm.gemini import GeminiCLI
from turbowrap.llm.grok import GrokCLI
from turbowrap.orchestration.report_utils import deduplicate_issues
from turbowrap.review.models.review import (
    Issue,
    IssueSeverity,
    ReviewOutput,
    ReviewSummary,
)
from turbowrap.review.reviewers.utils import convert_dict_to_review_output, parse_review_output

if TYPE_CHECKING:
    from turbowrap.review.reviewers.base import ReviewContext

logger = logging.getLogger(__name__)

# Timeout for parallel review (longer since each CLI runs all specialists)
PARALLEL_TIMEOUT = 900  # 15 minutes


# Agent descriptions extracted from frontmatter (avoid loading full MD content)
AGENT_DESCRIPTIONS: dict[str, str] = {
    "reviewer_be_architecture": (
        "Backend Architecture Reviewer - Python/FastAPI specialist. "
        "Focus: SOLID principles, layer separation (apis/services/repositories), "
        "dependency injection, code smells, module organization."
    ),
    "reviewer_be_quality": (
        "Backend Quality Reviewer - Python code quality specialist. "
        "Focus: Ruff linting, mypy type safety, Bandit security, "
        "OWASP vulnerabilities, async patterns, logging."
    ),
    "reviewer_fe_architecture": (
        "Frontend Architecture Reviewer - React/TypeScript specialist. "
        "Focus: component organization, state management, hook patterns, "
        "i18n, Next.js conventions, separation of concerns."
    ),
    "reviewer_fe_quality": (
        "Frontend Quality Reviewer - React/TypeScript code quality specialist. "
        "Focus: ESLint rules, TypeScript strict mode, Web Vitals, "
        "accessibility (a11y), security, testing patterns."
    ),
    "analyst_func": (
        "Functional Analyst - Business logic specialist. "
        "Focus: requirement compliance, edge case coverage, "
        "user flows, data integrity, authorization checks."
    ),
}


@dataclass
class ParallelTripleLLMResult:
    """Result of parallel triple-LLM review."""

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


class ParallelTripleLLMRunner:
    """
    Run triple-LLM review with 3 CLI processes in PARALLEL.

    Each LLM (Claude, Gemini, Grok) receives the same prompt and:
    1. Reads agent MD files from the agents/ directory
    2. Applies each specialist perspective to the code
    3. Outputs separate JSON blocks for each specialist

    The prompts are kept minimal - they point to agent files
    instead of embedding 800+ lines of MD content.
    """

    def __init__(
        self,
        specialists: list[str],
        timeout: int = PARALLEL_TIMEOUT,
    ):
        """
        Initialize parallel triple-LLM runner.

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
    ) -> ParallelTripleLLMResult:
        """
        Run all 3 LLMs in PARALLEL, each executing all specialists.

        Args:
            context: Review context with repo path and metadata
            file_list: List of files to review (uses context.files if not provided)
            on_claude_chunk: Optional callback for Claude streaming output
            on_gemini_chunk: Optional callback for Gemini streaming output
            on_grok_chunk: Optional callback for Grok streaming output

        Returns:
            ParallelTripleLLMResult with merged issues and per-LLM stats
        """
        start_time = time.time()
        files = file_list or context.files

        # Build the parallel prompt (same for all LLMs)
        prompt = self._build_parallel_prompt(context, files)

        logger.info(
            f"[PARALLEL-LLM] Starting review with {len(self.specialists)} specialists "
            f"across 3 LLMs IN PARALLEL ({len(files)} files)"
        )

        # Launch 3 CLI IN PARALLEL
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
                logger.error(f"[PARALLEL-LLM] Claude failed: {claude_result}")

        if gemini_ok and isinstance(gemini_result, tuple):
            gemini_reviews, gemini_duration = gemini_result
        else:
            gemini_duration = 0.0
            if isinstance(gemini_result, Exception):
                logger.error(f"[PARALLEL-LLM] Gemini failed: {gemini_result}")

        if grok_ok and isinstance(grok_result, tuple):
            grok_reviews, grok_duration = grok_result
        else:
            grok_duration = 0.0
            if isinstance(grok_result, Exception):
                logger.error(f"[PARALLEL-LLM] Grok failed: {grok_result}")

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
            reviewer="parallel_triple_llm",
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
            f"[PARALLEL-LLM] Complete: "
            f"Claude={claude_issues_count} ({claude_status}, {len(claude_reviews)} specs), "
            f"Gemini={gemini_issues_count} ({gemini_status}, {len(gemini_reviews)} specs), "
            f"Grok={grok_issues_count} ({grok_status}, {len(grok_reviews)} specs), "
            f"Merged={len(merged_issues)} (overlap={overlap_count}, triple={triple_overlap_count})"
        )

        return ParallelTripleLLMResult(
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

    def _build_parallel_prompt(
        self,
        context: ReviewContext,
        file_list: list[str],
    ) -> str:
        """
        Build the prompt for parallel specialist execution.

        Key design: Does NOT embed full agent MD content.
        Instead, points to agents/ directory and provides short descriptions.
        Each CLI will read the MD files as needed.
        """
        sections = []

        # Header with MANDATORY parallel execution instruction
        task_calls = "\n".join(
            f'   - Task(subagent_type="{spec}", prompt="Review code using {spec}.md guidelines")'
            for spec in self.specialists
        )

        sections.append(
            f"""# Parallel Multi-Specialist Code Review

═══════════════════════════════════════════════════════════════════════════════
██  MANDATORY: LAUNCH {len(self.specialists)} AGENTS IN PARALLEL                              ██
═══════════════════════════════════════════════════════════════════════════════

You MUST use the Task tool to launch {len(self.specialists)} specialist agents IN PARALLEL.
Each agent reads its own `.md` file and reviews the code from its perspective.

## REQUIRED ACTION - Execute NOW:

Launch these {len(self.specialists)} Task calls IN A SINGLE MESSAGE (parallel execution):

{task_calls}

Each agent will:
1. Read its specialist `.md` file from `{self.settings.agents_dir}/`
2. Analyze the files listed below
3. Output a JSON block with its review

DO NOT execute specialists sequentially. Use PARALLEL Task calls.

═══════════════════════════════════════════════════════════════════════════════
"""
        )

        # Specialist list with descriptions
        sections.append("\n## Specialists to Launch\n")
        for i, spec_name in enumerate(self.specialists, 1):
            description = AGENT_DESCRIPTIONS.get(spec_name, f"Review specialist: {spec_name}")
            sections.append(
                f"""
### {i}. {spec_name}
- **Agent file**: `{self.settings.agents_dir}/{spec_name}.md`
- **Focus**: {description}
"""
            )

        # Repository context (brief)
        if context.structure_docs:
            sections.append("\n## Repository Structure\n")
            for path, content in context.structure_docs.items():
                # Only include first 5000 chars of structure docs
                if len(content) > 5000:
                    content = content[:5000] + "\n... (see full file)"
                sections.append(f"### {path}\n{content}\n")

        if context.business_context:
            sections.append(f"\n## Business Context\n{context.business_context}\n")

        # File list
        sections.append("\n## Files to Review\n")
        for f in file_list:
            sections.append(f"- `{f}`\n")

        # Workspace constraint for monorepos
        if context.workspace_path:
            sections.append(
                f"""
## Monorepo Scope
This is a monorepo review. Only analyze files within: `{context.workspace_path}/`
"""
            )

        # Output format
        output_file = ".turbowrap_review_parallel.json"
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
## OUTPUT FORMAT

For EACH specialist, output a JSON block:

```json
{{"specialist": "<specialist_name>", "review": {{
  "summary": {{
    "files_reviewed": <int>,
    "critical_issues": <int>,
    "high_issues": <int>,
    "medium_issues": <int>,
    "low_issues": <int>,
    "score": <float 1-10>
  }},
  "issues": [
    {{
      "code": "SPEC-001",
      "severity": "critical|high|medium|low",
      "category": "security|performance|architecture|style|logic|ux|testing|documentation",
      "file": "path/to/file.py",
      "line": <int or null>,
      "title": "Brief title",
      "description": "Detailed description",
      "suggested_fix": "How to fix",
      "effort": <1-5>
    }}
  ]
}}}}
```

## Instructions

1. Read the files listed above
2. Read each specialist's `.md` file from `{self.settings.agents_dir}/`
3. Apply each specialist's perspective and output their JSON block
4. Save all JSON blocks to: `{output_path}`
5. Confirm: "Review saved to {output_path}"

Output {len(self.specialists)} JSON blocks total, one per specialist.
"""
        )

        return "".join(sections)

    async def _run_claude(
        self,
        context: ReviewContext,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[dict[str, ReviewOutput], float]:
        """Run Claude CLI with parallel specialists."""
        start_time = time.time()
        try:
            cli = ClaudeCLI(
                working_dir=context.repo_path,
                model="opus",
                timeout=self.timeout,
                s3_prefix="reviews/claude_parallel",
            )

            meta = context.metadata or {}
            review_id = meta.get("review_id", "unknown")
            repo_name = context.repo_path.name if context.repo_path else "unknown"

            result = await cli.run(
                prompt,
                operation_type="review",
                repo_name=repo_name,
                context_id=f"{review_id}_parallel_claude",
                save_prompt=True,
                save_output=True,
                on_chunk=on_chunk,
                track_operation=True,
                user_name="system",
                operation_details={
                    "reviewer": "parallel_claude",
                    "specialists": self.specialists,
                    "workspace_path": context.workspace_path,
                    "parent_session_id": review_id,
                },
            )

            if not result.success:
                logger.error(f"[PARALLEL-CLAUDE] Failed: {result.error}")
                return {}, time.time() - start_time

            reviews = self._parse_output(
                result.output,
                "claude",
                len(context.files),
                repo_path=context.repo_path,
                workspace_path=context.workspace_path,
            )
            return reviews, time.time() - start_time

        except Exception as e:
            logger.exception(f"[PARALLEL-CLAUDE] Exception: {e}")
            raise

    async def _run_gemini(
        self,
        context: ReviewContext,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[dict[str, ReviewOutput], float]:
        """Run Gemini CLI with parallel specialists."""
        start_time = time.time()
        try:
            cli = GeminiCLI(
                working_dir=context.repo_path,
                model="gemini-3-flash-preview",
                timeout=self.timeout,
                s3_prefix="reviews/gemini_parallel",
            )

            meta = context.metadata or {}
            review_id = meta.get("review_id", "unknown")
            repo_name = context.repo_path.name if context.repo_path else "unknown"

            result = await cli.run(
                prompt,
                operation_type="review",
                repo_name=repo_name,
                context_id=f"{review_id}_parallel_gemini",
                save_prompt=True,
                save_output=True,
                on_chunk=on_chunk,
                track_operation=True,
                user_name="system",
                operation_details={
                    "reviewer": "parallel_gemini",
                    "specialists": self.specialists,
                    "workspace_path": context.workspace_path,
                    "parent_session_id": review_id,
                },
            )

            if not result.success:
                logger.error(f"[PARALLEL-GEMINI] Failed: {result.error}")
                return {}, time.time() - start_time

            reviews = self._parse_output(
                result.output,
                "gemini",
                len(context.files),
                repo_path=context.repo_path,
                workspace_path=context.workspace_path,
            )
            return reviews, time.time() - start_time

        except Exception as e:
            logger.exception(f"[PARALLEL-GEMINI] Exception: {e}")
            raise

    async def _run_grok(
        self,
        context: ReviewContext,
        prompt: str,
        on_chunk: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[dict[str, ReviewOutput], float]:
        """Run Grok CLI with parallel specialists."""
        start_time = time.time()
        try:
            cli = GrokCLI(
                working_dir=context.repo_path,
                model="grok-4-1-fast-reasoning",
                timeout=self.timeout,
                s3_prefix="reviews/grok_parallel",
            )

            meta = context.metadata or {}
            review_id = meta.get("review_id", "unknown")
            repo_name = context.repo_path.name if context.repo_path else "unknown"

            result = await cli.run(
                prompt,
                operation_type="review",
                repo_name=repo_name,
                context_id=f"{review_id}_parallel_grok",
                save_prompt=True,
                save_output=True,
                on_chunk=on_chunk,
                track_operation=True,
                user_name="system",
                operation_details={
                    "reviewer": "parallel_grok",
                    "specialists": self.specialists,
                    "workspace_path": context.workspace_path,
                    "parent_session_id": review_id,
                },
            )

            if not result.success:
                logger.error(f"[PARALLEL-GROK] Failed: {result.error}")
                return {}, time.time() - start_time

            reviews = self._parse_output(
                result.output,
                "grok",
                len(context.files),
                repo_path=context.repo_path,
                workspace_path=context.workspace_path,
            )
            return reviews, time.time() - start_time

        except Exception as e:
            logger.exception(f"[PARALLEL-GROK] Exception: {e}")
            raise

    def _parse_output(
        self,
        output: str,
        llm: str,
        files_count: int,
        repo_path: Path | None = None,
        workspace_path: str | None = None,
    ) -> dict[str, ReviewOutput]:
        """
        Parse multi-specialist JSON output from single CLI session.

        Extracts all JSON blocks with {"specialist": "name", "review": {...}}
        and converts them to ReviewOutput objects.

        Strategy (in order):
        1. Parse JSON blocks from stream output
        2. Fallback: Read from saved .turbowrap_review_parallel.json file
        """
        results: dict[str, ReviewOutput] = {}

        if not output:
            logger.warning(f"[PARALLEL-{llm.upper()}] Empty output")
            return results

        # Strategy 1: Extract JSON blocks between ``` markers
        json_blocks = re.findall(r"```json\s*(.*?)\s*```", output, re.DOTALL)

        for block in json_blocks:
            try:
                data = json.loads(block.strip())
                if isinstance(data, dict) and "specialist" in data and "review" in data:
                    spec_name = data["specialist"]
                    review_data = data["review"]
                    # Use centralized converter with LLM and specialist tagging
                    review = convert_dict_to_review_output(
                        review_data, spec_name, files_count, flagged_by=[llm, spec_name]
                    )
                    if review:
                        results[spec_name] = review
                        n_issues = len(review.issues)
                        logger.debug(
                            f"[PARALLEL-{llm.upper()}] Parsed {spec_name}: {n_issues} issues"
                        )
            except json.JSONDecodeError as e:
                logger.debug(f"[PARALLEL-{llm.upper()}] JSON block parse error: {e}")
                continue

        # Strategy 2: Find JSON objects without code blocks
        if not results:
            specialist_matches = list(re.finditer(r'\{\s*"specialist"\s*:', output))
            for match in specialist_matches:
                start = match.start()
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
                            # Use centralized converter
                            review = convert_dict_to_review_output(
                                review_data, spec_name, files_count, flagged_by=[llm, spec_name]
                            )
                            if review:
                                results[spec_name] = review
                    except json.JSONDecodeError:
                        continue

        # Strategy 3: Fallback to markdown-style parsing
        if not results:
            logger.warning(f"[PARALLEL-{llm.upper()}] No JSON blocks found, trying markdown parse")
            for spec_name in self.specialists:
                if spec_name in output:
                    spec_pattern = rf"## SPECIALIST \d+: {spec_name}.*?(?=## SPECIALIST \d+:|$)"
                    spec_match = re.search(spec_pattern, output, re.DOTALL)
                    if spec_match:
                        spec_output = spec_match.group(0)
                        review = parse_review_output(spec_output, spec_name, files_count)
                        if review and review.issues:
                            results[spec_name] = review

        # Strategy 4: Read from saved file (most reliable fallback)
        if not results and repo_path:
            results = self._parse_from_saved_file(repo_path, workspace_path, llm, files_count)

        logger.info(f"[PARALLEL-{llm.upper()}] Parsed {len(results)} specialist reviews")
        return results

    def _parse_from_saved_file(
        self,
        repo_path: Path,
        workspace_path: str | None,
        llm: str,
        files_count: int,
    ) -> dict[str, ReviewOutput]:
        """
        Read reviews from saved .turbowrap_review_parallel.json file.

        This is the most reliable source since LLMs save directly to file.
        """
        results: dict[str, ReviewOutput] = {}
        output_file = ".turbowrap_review_parallel.json"

        # Determine file path (monorepo vs single repo)
        if workspace_path:
            file_path = Path(repo_path) / workspace_path / output_file
        else:
            file_path = Path(repo_path) / output_file

        if not file_path.exists():
            logger.debug(f"[PARALLEL-{llm.upper()}] Saved file not found: {file_path}")
            return results

        try:
            content = file_path.read_text()
            logger.info(f"[PARALLEL-{llm.upper()}] Reading from saved file: {file_path}")

            # Try to parse as JSON
            data = json.loads(content)

            # Handle different formats:
            # Format 1: {"specialist_name": {review_data}, ...}
            # Format 2: [{"specialist": "name", "review": {...}}, ...]
            # Format 3: {"specialists": {"name": {...}, ...}}

            if isinstance(data, dict):
                # Check for specialists wrapper
                if "specialists" in data:
                    data = data["specialists"]

                # Try each key as specialist name
                for key, value in data.items():
                    if key in self.specialists or any(s in key for s in self.specialists):
                        spec_name = key
                        # Normalize specialist name
                        for s in self.specialists:
                            if s in key:
                                spec_name = s
                                break

                        review_data = value
                        # If value has "review" wrapper, unwrap it
                        if isinstance(value, dict) and "review" in value:
                            review_data = value["review"]

                        review = convert_dict_to_review_output(
                            review_data, spec_name, files_count, flagged_by=[llm, spec_name]
                        )
                        if review:
                            results[spec_name] = review
                            logger.debug(
                                f"[PARALLEL-{llm.upper()}] From file: {spec_name} "
                                f"with {len(review.issues)} issues"
                            )

            elif isinstance(data, list):
                # List of specialist reviews
                for item in data:
                    if isinstance(item, dict) and "specialist" in item:
                        spec_name = item["specialist"]
                        review_data = item.get("review", item)
                        review = convert_dict_to_review_output(
                            review_data, spec_name, files_count, flagged_by=[llm, spec_name]
                        )
                        if review:
                            results[spec_name] = review

            logger.info(f"[PARALLEL-{llm.upper()}] Loaded {len(results)} reviews from file")

        except json.JSONDecodeError as e:
            logger.error(f"[PARALLEL-{llm.upper()}] Failed to parse saved file: {e}")
        except Exception as e:
            logger.error(f"[PARALLEL-{llm.upper()}] Error reading saved file: {e}")

        return results

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
