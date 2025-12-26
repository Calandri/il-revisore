"""Linear issue analyzer using Claude CLI for 2-phase workflow."""

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import settings
from turbowrap.db.models import LinearIssue
from turbowrap.review.integrations.linear import LinearClient

logger = logging.getLogger(__name__)


class LinearIssueAnalyzer:
    """Analyzes Linear issues with Claude in 2 phases.

    Phase 1: Generate clarifying questions
    Phase 2: Deep analysis with user answers
    """

    def __init__(self, linear_client: LinearClient):
        """Initialize analyzer.

        Args:
            linear_client: Linear API client for posting comments
        """
        self.linear_client = linear_client
        self.last_improved_description: str | None = None
        self.last_analysis_summary: str | None = None
        self.last_repository_recommendations: list[str] = []

        # S3 config
        self.s3_bucket = settings.thinking.s3_bucket
        self.s3_region = settings.thinking.s3_region
        self._s3_client = None

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    async def _save_analysis_to_s3(
        self,
        phase: str,
        issue_id: str,
        prompt: str,
        output: str,
        parsed_result: dict | list | None = None,
    ) -> str | None:
        """Save analysis prompt and output to S3.

        Args:
            phase: "phase1" or "phase2"
            issue_id: Linear issue identifier
            prompt: The prompt sent to Claude
            output: Raw output from Claude
            parsed_result: Parsed result (questions or analysis)

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.s3_bucket:
            return None

        try:
            timestamp = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"linear-analysis/{timestamp}/{issue_id}_{phase}.md"

            content = f"""# Linear Issue Analysis - {phase.upper()}

**Issue ID**: {issue_id}
**Timestamp**: {datetime.utcnow().isoformat()}
**Phase**: {phase}

---

## Prompt

```
{prompt}
```

---

## Raw Output

```
{output}
```

---

## Parsed Result

```json
{json.dumps(parsed_result, indent=2, default=str) if parsed_result else "N/A"}
```
"""

            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )

            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"[LINEAR ANALYZER] Saved {phase} to S3: {s3_url}")
            return s3_url

        except ClientError as e:
            logger.warning(f"Failed to save analysis to S3: {e}")
            return None

    async def analyze_phase1_questions(self, issue: LinearIssue) -> list[dict]:
        """Phase 1: Generate 5-10 clarifying questions.

        Args:
            issue: LinearIssue to analyze

        Returns:
            List of questions: [{"id": 1, "question": "...", "why": "..."}]
        """
        logger.info(f"Starting Phase 1 analysis for {issue.linear_identifier}")

        prompt = self._build_questions_prompt(issue)

        try:
            output = await self._run_claude_cli(prompt, timeout=120)
            questions = self._parse_questions(output)

            # Save to S3 for debugging
            await self._save_analysis_to_s3(
                "phase1", issue.linear_identifier, prompt, output, questions
            )

            logger.info(f"Generated {len(questions)} questions for {issue.linear_identifier}")
            return questions

        except Exception as e:
            logger.error(f"Phase 1 analysis failed: {e}")
            raise

    async def analyze_phase2_with_answers(
        self,
        issue: LinearIssue,
        user_answers: dict[int, str],
    ) -> AsyncIterator[str]:
        """Phase 2: Deep analysis with user answers (streaming).

        Args:
            issue: LinearIssue to analyze
            user_answers: Dict mapping question ID to user's answer

        Yields:
            Progress messages, then "COMPLETE" when done
        """
        logger.info(f"Starting Phase 2 analysis for {issue.linear_identifier}")

        yield "Starting deep analysis with your answers..."

        prompt = self._build_analysis_prompt(issue, user_answers)

        try:
            yield "Running Claude analysis..."
            output = await self._run_claude_cli(prompt, timeout=180)

            yield "Parsing analysis results..."
            improved_desc, analysis_summary, metadata = self._parse_analysis(output)

            # Save to S3 for debugging
            await self._save_analysis_to_s3(
                "phase2", issue.linear_identifier, prompt, output,
                {"improved_desc": improved_desc, "summary": analysis_summary, "metadata": metadata}
            )

            # Store for later DB update
            self.last_improved_description = improved_desc
            self.last_analysis_summary = analysis_summary
            self.last_repository_recommendations = metadata.get("repositories", [])

            # Post comment to Linear with improved description
            yield "Posting analysis to Linear..."
            comment_body = self._format_linear_comment(improved_desc, analysis_summary)
            comment_id = await self.linear_client.create_comment(
                issue.linear_id,
                comment_body,
            )

            logger.info(f"Posted analysis comment {comment_id} to Linear issue {issue.linear_identifier}")

            yield "COMPLETE"

        except Exception as e:
            logger.error(f"Phase 2 analysis failed: {e}")
            yield f"ERROR: {str(e)}"
            raise

    def _build_questions_prompt(self, issue: LinearIssue) -> str:
        """Build prompt for Phase 1: question generation.

        Args:
            issue: LinearIssue to analyze

        Returns:
            Complete prompt for Claude CLI
        """
        agent_prompt = self._load_agent_prompt()

        # Format issue context
        issue_context = f"""
# Linear Issue to Analyze

**Identifier**: {issue.linear_identifier}
**Title**: {issue.title}

**Description**:
{issue.description or "No description provided"}

**Priority**: {self._format_priority(issue.priority)}
**Labels**: {', '.join([label.get('name', '') for label in (issue.labels or [])])}
**Assignee**: {issue.assignee_name or "Unassigned"}
**State**: {issue.linear_state_name or "Unknown"}

---

**TASK**: Generate 5-10 clarifying questions for this issue following the Phase 1 workflow.
"""

        return f"{agent_prompt}\n\n{issue_context}"

    def _build_analysis_prompt(
        self,
        issue: LinearIssue,
        user_answers: dict[int, str],
    ) -> str:
        """Build prompt for Phase 2: deep analysis with answers.

        Args:
            issue: LinearIssue to analyze
            user_answers: User's answers to questions

        Returns:
            Complete prompt for Claude CLI
        """
        agent_prompt = self._load_agent_prompt()

        # Format user answers
        answers_text = "\n".join([
            f"**Q{qid}**: {answer}"
            for qid, answer in user_answers.items()
        ])

        issue_context = f"""
# Linear Issue to Analyze

**Identifier**: {issue.linear_identifier}
**Title**: {issue.title}

**Description**:
{issue.description or "No description provided"}

**Priority**: {self._format_priority(issue.priority)}
**Labels**: {', '.join([label.get('name', '') for label in (issue.labels or [])])}
**Assignee**: {issue.assignee_name or "Unassigned"}
**State**: {issue.linear_state_name or "Unknown"}

---

# User Answers to Questions

{answers_text}

---

**TASK**: Perform comprehensive Phase 2 analysis using the user's answers. Provide:
1. Improved Description (with Problem Statement, Acceptance Criteria, Technical Approach, Dependencies & Risks, Edge Cases)
2. Analysis Summary (Problem Core, Scope, Feasibility, Development Type, Files Affected, Complexity Breakdown, Cascade Effects, Repository Recommendations, Effort Estimate)

Be specific with file paths and technical details.
"""

        return f"{agent_prompt}\n\n{issue_context}"

    def _parse_questions(self, output: str) -> list[dict]:
        """Parse questions from Claude Phase 1 output.

        Args:
            output: Raw output from Claude CLI

        Returns:
            List of question dicts
        """
        # Look for JSON block with questions
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', output, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if "questions" in data:
                    return data["questions"]
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON questions: {e}")

        # Fallback: look for questions pattern in text
        questions = []
        question_pattern = r'"id":\s*(\d+),\s*"question":\s*"([^"]+)",\s*"why":\s*"([^"]+)"'
        matches = re.finditer(question_pattern, output, re.MULTILINE)

        for match in matches:
            questions.append({
                "id": int(match.group(1)),
                "question": match.group(2),
                "why": match.group(3),
            })

        if not questions:
            # Last resort: extract any question-like sentences
            logger.warning("Could not parse structured questions, extracting from text")
            lines = output.split('\n')
            qid = 1
            for line in lines:
                if '?' in line and len(line.strip()) > 20:
                    questions.append({
                        "id": qid,
                        "question": line.strip(),
                        "why": "Clarify requirements",
                    })
                    qid += 1
                    if qid > 10:
                        break

        return questions[:10]  # Max 10 questions

    def _parse_analysis(self, output: str) -> tuple[str, str, dict]:
        """Parse improved description and analysis from Phase 2 output.

        Args:
            output: Raw output from Claude CLI

        Returns:
            Tuple of (improved_description, analysis_summary, metadata)
        """
        improved_desc = ""
        analysis_summary = ""
        metadata = {"repositories": []}

        # Extract Improved Description section
        desc_match = re.search(
            r'##?\s*Improved Description\s*\n(.*?)(?=##?\s*Analysis Summary|\Z)',
            output,
            re.DOTALL | re.IGNORECASE,
        )
        if desc_match:
            improved_desc = desc_match.group(1).strip()

        # Extract Analysis Summary section
        summary_match = re.search(
            r'##?\s*Analysis Summary\s*\n(.*?)(?=##?\s*[A-Z]|\Z)',
            output,
            re.DOTALL | re.IGNORECASE,
        )
        if summary_match:
            analysis_summary = summary_match.group(1).strip()

        # Extract Repository Recommendations
        repo_match = re.search(
            r'\*\*Repository Recommendations\*\*.*?\n(.*?)(?=\n\*\*|\Z)',
            output,
            re.DOTALL,
        )
        if repo_match:
            repo_text = repo_match.group(1)
            # Extract repo names from list items
            repo_names = re.findall(r'[-*]\s*`?([a-zA-Z0-9_-]+)`?', repo_text)
            metadata["repositories"] = repo_names[:3]  # Max 3

        # If sections not found, use entire output
        if not improved_desc:
            improved_desc = output[:2000]  # First 2000 chars
        if not analysis_summary:
            analysis_summary = output[2000:4000] if len(output) > 2000 else "See improved description"

        return improved_desc, analysis_summary, metadata

    def _format_linear_comment(self, improved_desc: str, analysis_summary: str) -> str:
        """Format analysis results as Linear comment.

        Args:
            improved_desc: Improved description text
            analysis_summary: Analysis summary text

        Returns:
            Markdown-formatted comment body
        """
        return f"""## 🤖 TurboWrap Issue Analysis

{improved_desc}

---

### 📊 Analysis Summary

{analysis_summary}

---

*Generated by TurboWrap Linear Analyzer*
"""

    def _load_agent_prompt(self) -> str:
        """Load agent prompt from file.

        Returns:
            Agent prompt text
        """
        # Assuming agents/ is at project root
        project_root = Path(__file__).parent.parent.parent.parent
        prompt_path = project_root / "agents" / "linear_issue_analyzer.md"

        if not prompt_path.exists():
            logger.warning(f"Agent prompt not found at {prompt_path}, using default")
            return "You are a Linear issue analyzer. Analyze the issue and provide detailed insights."

        return prompt_path.read_text()

    def _format_priority(self, priority: int) -> str:
        """Format priority int to human-readable string.

        Args:
            priority: Priority int (0-4)

        Returns:
            Priority label
        """
        priority_map = {
            0: "None",
            1: "🔴 Urgent",
            2: "🟠 High",
            3: "🟡 Normal",
            4: "🟢 Low",
        }
        return priority_map.get(priority, "Unknown")

    async def _run_claude_cli(self, prompt: str, timeout: int = 120) -> str:
        """Execute Claude CLI with streaming output.

        Args:
            prompt: Input prompt for Claude
            timeout: Timeout in seconds

        Returns:
            Complete output from Claude
        """
        # Get API key from environment
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        # Prepare command
        # NOTE: --verbose is REQUIRED when using --print + --output-format=stream-json
        cmd = [
            "claude",
            "--print",
            "--verbose",
            "--output-format", "stream-json",
            "--model", "claude-opus-4-5-20251101",
        ]

        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = api_key
        # Workaround: Bun file watcher bug on macOS /var/folders
        env["TMPDIR"] = "/tmp"

        logger.debug(f"Running Claude CLI with timeout {timeout}s")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Send prompt to stdin
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode()),
                timeout=timeout,
            )

            if process.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"Claude CLI failed: {error_msg}")
                raise RuntimeError(f"Claude CLI error: {error_msg}")

            output = stdout.decode()
            logger.debug(f"Claude CLI output length: {len(output)} chars")

            return output

        except asyncio.TimeoutError:
            logger.error(f"Claude CLI timeout after {timeout}s")
            if process:
                process.kill()
            raise RuntimeError(f"Claude CLI timeout after {timeout}s")
        except Exception as e:
            logger.error(f"Claude CLI execution error: {e}")
            raise
