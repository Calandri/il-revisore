"""
Fix Orchestrator for TurboWrap.

Coordinates the fixing of issues found during code review.
Uses Claude with Extended Thinking for higher quality fixes.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

import anthropic
import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings
from turbowrap.db.models import Issue, IssueStatus
from turbowrap.fix.git_utils import (
    GitError,
    GitUtils,
    generate_commit_message,
    generate_fix_branch_name,
)
from turbowrap.fix.models import (
    ClarificationAnswer,
    ClarificationQuestion,
    FixContext,
    FixEventType,
    FixProgressEvent,
    FixRequest,
    FixSessionResult,
    FixStatus,
    IssueFixResult,
)
from turbowrap.fix.validator import validate_issue_for_fix
from turbowrap.llm import GeminiClient, load_prompt

logger = logging.getLogger(__name__)

# Extended thinking budget for fix generation (20k tokens)
FIX_THINKING_BUDGET = 20000

# Type for progress callback
ProgressCallback = Callable[[FixProgressEvent], Awaitable[None]]

# Type for clarification answer provider
AnswerProvider = Callable[[ClarificationQuestion], Awaitable[ClarificationAnswer]]


class FixOrchestrator:
    """Orchestrates the fixing of code review issues."""

    # File extensions for backend vs frontend
    BE_EXTENSIONS = {".py", ".go", ".java", ".rs", ".rb", ".php"}
    FE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte"}

    def __init__(
        self,
        repo_path: Path,
        gemini_client: Optional[GeminiClient] = None,
    ):
        """
        Initialize the Fix Orchestrator.

        Args:
            repo_path: Path to the repository
            gemini_client: Gemini client for analysis
        """
        self.repo_path = repo_path
        self.settings = get_settings()
        self.gemini = gemini_client or GeminiClient()
        self.git = GitUtils(repo_path)

        # Initialize Anthropic client for extended thinking
        api_key = self.settings.agents.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY required for fix generation")
        self.claude_client = anthropic.Anthropic(api_key=api_key)
        self.claude_model = self.settings.agents.claude_model

        # Thinking settings
        self.thinking_enabled = self.settings.thinking.enabled
        self.s3_bucket = self.settings.thinking.s3_bucket
        self.s3_region = self.settings.thinking.s3_region

        # Lazy S3 client
        self._s3_client = None

        # Load agent prompts
        self._load_prompts()

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.s3_region)
        return self._s3_client

    def _load_prompts(self) -> None:
        """Load all required agent prompts."""
        # Base: engineering principles (always)
        try:
            self.engineering_prompt = load_prompt("engineering_principles")
        except FileNotFoundError:
            logger.warning("engineering_principles.md not found")
            self.engineering_prompt = ""

        # Backend developer prompt
        try:
            self.dev_be_prompt = load_prompt("dev_be")
        except FileNotFoundError:
            logger.warning("dev_be.md not found")
            self.dev_be_prompt = ""

        # Frontend developer prompt
        try:
            self.dev_fe_prompt = load_prompt("dev_fe")
        except FileNotFoundError:
            logger.warning("dev_fe.md not found")
            self.dev_fe_prompt = ""

        # Fixer-specific prompt
        try:
            self.fixer_prompt = load_prompt("fixer")
        except FileNotFoundError:
            logger.warning("fixer.md not found, using default")
            self.fixer_prompt = self._default_fixer_prompt()

    def _get_system_prompt_for_file(self, file_path: str) -> str:
        """
        Build system prompt based on file type.

        Args:
            file_path: Path to the file being fixed

        Returns:
            Combined system prompt: engineering + (dev_be|dev_fe) + fixer
        """
        suffix = Path(file_path).suffix.lower()

        # Determine if BE or FE
        if suffix in self.BE_EXTENSIONS:
            dev_prompt = self.dev_be_prompt
            file_type = "Backend"
        elif suffix in self.FE_EXTENSIONS:
            dev_prompt = self.dev_fe_prompt
            file_type = "Frontend"
        else:
            # Default to fixer only for unknown types
            dev_prompt = ""
            file_type = "General"

        # Combine prompts
        parts = []
        if self.engineering_prompt:
            parts.append(f"# Engineering Principles\n\n{self.engineering_prompt}")
        if dev_prompt:
            parts.append(f"# {file_type} Development Guidelines\n\n{dev_prompt}")
        if self.fixer_prompt:
            parts.append(f"# Fixer Instructions\n\n{self.fixer_prompt}")

        return "\n\n---\n\n".join(parts) if parts else self._default_fixer_prompt()

    def _default_fixer_prompt(self) -> str:
        """Default fixer prompt if agents/fixer.md is not found."""
        return """You are a code fixer. Your task is to fix the issue described below.

IMPORTANT RULES:
1. Return the COMPLETE fixed file content, not just the changed parts
2. Maintain the existing code style (indentation, quotes, etc.)
3. Make minimal changes - only fix the specific issue
4. Add a brief comment explaining what you changed (at the top or inline)

Your response MUST be in this exact format:
```
<file_content>
[complete file content here]
</file_content>

<changes_summary>
[brief description of what you changed]
</changes_summary>
```
"""

    async def fix_issues(
        self,
        request: FixRequest,
        issues: list[Issue],
        emit: Optional[ProgressCallback] = None,
        answer_provider: Optional[AnswerProvider] = None,
    ) -> FixSessionResult:
        """
        Fix a list of issues serially.

        Args:
            request: Fix request with issue IDs
            issues: List of Issue objects from database
            emit: Callback for progress events
            answer_provider: Callback to get user answers for clarifications

        Returns:
            FixSessionResult with summary of all fixes
        """
        session_id = str(uuid.uuid4())
        branch_name = generate_fix_branch_name(request.task_id)

        result = FixSessionResult(
            session_id=session_id,
            repository_id=request.repository_id,
            task_id=request.task_id,
            branch_name=branch_name,
            status=FixStatus.PENDING,
            issues_requested=len(issues),
            started_at=datetime.utcnow(),
        )

        async def safe_emit(event: FixProgressEvent) -> None:
            """Safely emit progress event."""
            if emit:
                try:
                    await emit(event)
                except Exception as e:
                    logger.error(f"Error emitting progress: {e}")

        try:
            # Create/checkout fix branch
            original_branch = self.git.get_current_branch()
            self.git.create_branch(branch_name)

            await safe_emit(FixProgressEvent(
                type=FixEventType.FIX_SESSION_STARTED,
                session_id=session_id,
                branch_name=branch_name,
                total_issues=len(issues),
                message=f"Created branch {branch_name}",
            ))

            # Process each issue SERIALLY
            for i, issue in enumerate(issues, 1):
                issue_result = await self._fix_single_issue(
                    issue=issue,
                    session_id=session_id,
                    issue_index=i,
                    total_issues=len(issues),
                    emit=safe_emit,
                    answer_provider=answer_provider,
                )

                result.results.append(issue_result)

                if issue_result.status == FixStatus.COMPLETED:
                    result.issues_fixed += 1
                elif issue_result.status == FixStatus.FAILED:
                    result.issues_failed += 1
                elif issue_result.status == FixStatus.SKIPPED:
                    result.issues_skipped += 1

            # Complete session
            result.status = FixStatus.COMPLETED
            result.completed_at = datetime.utcnow()

            await safe_emit(FixProgressEvent(
                type=FixEventType.FIX_SESSION_COMPLETED,
                session_id=session_id,
                branch_name=branch_name,
                issues_fixed=result.issues_fixed,
                issues_failed=result.issues_failed,
                message=f"Fixed {result.issues_fixed}/{len(issues)} issues",
            ))

            return result

        except GitError as e:
            result.status = FixStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.utcnow()

            await safe_emit(FixProgressEvent(
                type=FixEventType.FIX_SESSION_ERROR,
                session_id=session_id,
                error=str(e),
            ))

            return result

        except Exception as e:
            logger.exception("Unexpected error during fix session")
            result.status = FixStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.utcnow()

            await safe_emit(FixProgressEvent(
                type=FixEventType.FIX_SESSION_ERROR,
                session_id=session_id,
                error=str(e),
            ))

            return result

    async def _fix_single_issue(
        self,
        issue: Issue,
        session_id: str,
        issue_index: int,
        total_issues: int,
        emit: ProgressCallback,
        answer_provider: Optional[AnswerProvider] = None,
    ) -> IssueFixResult:
        """
        Fix a single issue.

        Flow:
        1. Validate issue is still applicable
        2. Analyze with Gemini (needs clarification?)
        3. If ambiguous, ask user
        4. Generate fix with Claude
        5. Apply to file
        6. Commit

        Returns:
            IssueFixResult
        """
        result = IssueFixResult(
            issue_id=issue.id,
            issue_code=issue.issue_code,
            status=FixStatus.PENDING,
            started_at=datetime.utcnow(),
        )

        common_fields = {
            "session_id": session_id,
            "issue_id": issue.id,
            "issue_code": issue.issue_code,
            "issue_index": issue_index,
            "total_issues": total_issues,
        }

        try:
            # Step 1: Validate
            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_STARTED,
                message=f"Starting fix for {issue.issue_code}",
                **common_fields,
            ))

            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_VALIDATING,
                message=f"Validating {issue.file}...",
                **common_fields,
            ))

            validation = validate_issue_for_fix(
                repo_path=self.repo_path,
                file_path=issue.file,
                line=issue.line,
                current_code=issue.current_code,
            )

            if not validation.is_valid:
                result.status = FixStatus.SKIPPED
                result.error = validation.error
                result.completed_at = datetime.utcnow()

                await emit(FixProgressEvent(
                    type=FixEventType.FIX_ISSUE_SKIPPED,
                    message=f"Skipped: {validation.error}",
                    **common_fields,
                ))

                return result

            # Build fix context
            context = FixContext(
                issue_id=issue.id,
                issue_code=issue.issue_code,
                file_path=issue.file,
                line=issue.line,
                end_line=issue.end_line,
                title=issue.title,
                description=issue.description,
                current_code=issue.current_code,
                suggested_fix=issue.suggested_fix,
                category=issue.category,
                severity=issue.severity,
                file_content=validation.file_content,
            )

            # Step 2: Analyze with Gemini (check if clarification needed)
            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_ANALYZING,
                message="Analyzing issue complexity...",
                **common_fields,
            ))

            clarification = await self._analyze_for_clarification(context)

            # Step 3: Get clarification if needed
            if clarification and answer_provider:
                await emit(FixProgressEvent(
                    type=FixEventType.FIX_CLARIFICATION_NEEDED,
                    clarification=clarification,
                    message=clarification.question,
                    **common_fields,
                ))

                answer = await answer_provider(clarification)
                context.clarifications.append(answer)

                await emit(FixProgressEvent(
                    type=FixEventType.FIX_CLARIFICATION_RECEIVED,
                    message=f"Received clarification: {answer.answer}",
                    **common_fields,
                ))

            # Step 4: Generate fix with Claude
            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_GENERATING,
                message="Generating fix with Claude...",
                **common_fields,
            ))

            fixed_content, changes_summary = await self._generate_fix(context, emit, common_fields)

            if not fixed_content:
                result.status = FixStatus.FAILED
                result.error = "Failed to generate fix"
                result.completed_at = datetime.utcnow()

                await emit(FixProgressEvent(
                    type=FixEventType.FIX_ISSUE_ERROR,
                    error="Failed to generate fix",
                    **common_fields,
                ))

                return result

            # Step 5: Apply fix
            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_APPLYING,
                message=f"Applying fix to {issue.file}...",
                **common_fields,
            ))

            file_path = self.repo_path / issue.file
            file_path.write_text(fixed_content, encoding="utf-8")

            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_APPLIED,
                message="Fix applied to file",
                **common_fields,
            ))

            # Step 6: Commit
            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_COMMITTING,
                message="Committing changes...",
                **common_fields,
            ))

            self.git.stage_file(issue.file)
            commit_message = generate_commit_message(issue.issue_code, issue.title)
            commit_sha = self.git.commit(commit_message)

            result.status = FixStatus.COMPLETED
            result.commit_sha = commit_sha
            result.commit_message = commit_message
            result.changes_made = changes_summary
            result.completed_at = datetime.utcnow()

            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_COMMITTED,
                commit_sha=commit_sha,
                commit_message=commit_message,
                **common_fields,
            ))

            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_COMPLETED,
                message=f"Successfully fixed {issue.issue_code}",
                commit_sha=commit_sha,
                **common_fields,
            ))

            return result

        except Exception as e:
            logger.exception(f"Error fixing issue {issue.issue_code}")
            result.status = FixStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.utcnow()

            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_ERROR,
                error=str(e),
                **common_fields,
            ))

            return result

    async def _analyze_for_clarification(
        self, context: FixContext
    ) -> Optional[ClarificationQuestion]:
        """
        Analyze issue to determine if clarification is needed.

        Uses Gemini to quickly assess if the issue is ambiguous.

        Returns:
            ClarificationQuestion if clarification needed, None otherwise
        """
        prompt = f"""Analyze this code issue and determine if any clarification is needed before fixing.

Issue: {context.title}
Description: {context.description}
Category: {context.category}
Severity: {context.severity}

File: {context.file_path}
Line: {context.line}

Current Code:
```
{context.current_code or "Not provided"}
```

Suggested Fix:
```
{context.suggested_fix or "Not provided"}
```

If the issue is clear and unambiguous, respond with:
{{"needs_clarification": false}}

If clarification is needed, respond with:
{{"needs_clarification": true, "question": "Your question here", "options": ["Option 1", "Option 2"]}}

Only ask for clarification if there are genuinely multiple valid approaches or missing information.
Respond ONLY with valid JSON.
"""

        try:
            response = self.gemini.generate(prompt)

            # Parse JSON response
            # Find JSON in response
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                return None

            data = json.loads(json_match.group())

            if data.get("needs_clarification"):
                return ClarificationQuestion(
                    id=str(uuid.uuid4()),
                    issue_id=context.issue_id,
                    question=data.get("question", "How would you like to proceed?"),
                    options=data.get("options"),
                )

            return None

        except Exception as e:
            logger.warning(f"Clarification analysis failed: {e}, proceeding without")
            return None

    async def _save_thinking_to_s3(
        self,
        thinking_content: str,
        issue_id: str,
        context: FixContext,
    ) -> Optional[str]:
        """
        Save thinking content to S3.

        Args:
            thinking_content: The thinking text to save
            issue_id: Issue identifier
            context: Fix context for metadata

        Returns:
            S3 URL if successful, None otherwise
        """
        if not thinking_content:
            return None

        try:
            timestamp = datetime.utcnow().strftime("%Y/%m/%d/%H%M%S")
            s3_key = f"thinking/{timestamp}/fix_{issue_id}.md"

            content = f"""# Extended Thinking - Fix Generation

**Issue ID**: {issue_id}
**Issue Code**: {context.issue_code}
**File**: {context.file_path}
**Timestamp**: {datetime.utcnow().isoformat()}
**Model**: {self.claude_model}

---

## Thinking Process

{thinking_content}
"""

            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
            )

            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"Saved fix thinking to {s3_url}")
            return s3_url

        except ClientError as e:
            logger.warning(f"Failed to save thinking to S3: {e}")
            return None

    def _stream_with_thinking_sync(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, str]:
        """
        Synchronous streaming with extended thinking.
        Runs in thread pool to not block event loop.

        Returns:
            Tuple of (thinking_content, response_text)
        """
        thinking_content = ""
        response_text = ""

        params = {
            "model": self.claude_model,
            "max_tokens": 16000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        # Add extended thinking with 20k budget
        if self.thinking_enabled:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": FIX_THINKING_BUDGET,
            }

        with self.claude_client.messages.stream(**params) as stream:
            for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_delta":
                        if hasattr(event, "delta"):
                            if hasattr(event.delta, "type"):
                                if event.delta.type == "thinking_delta":
                                    thinking_content += event.delta.thinking
                                elif event.delta.type == "text_delta":
                                    response_text += event.delta.text

        return thinking_content, response_text

    async def _generate_fix(
        self,
        context: FixContext,
        emit: ProgressCallback,
        common_fields: dict,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Generate the fix using Claude with Extended Thinking (20k tokens).

        Returns:
            Tuple of (fixed_content, changes_summary) or (None, None) on failure
        """
        clarifications_text = ""
        if context.clarifications:
            clarifications_text = "\n\nUser Clarifications:\n"
            for c in context.clarifications:
                clarifications_text += f"- {c.answer}\n"

        prompt = f"""Fix this code issue.

Issue: {context.title}
Description: {context.description}
Category: {context.category}
Severity: {context.severity}

File: {context.file_path}
Line: {context.line or "Unknown"}

Current Problematic Code:
```
{context.current_code or "See full file below"}
```

Suggested Fix (from review):
```
{context.suggested_fix or "Not provided - use your judgment"}
```
{clarifications_text}
Full File Content:
```
{context.file_content}
```

IMPORTANT:
1. Return the COMPLETE fixed file content
2. Maintain existing code style
3. Make minimal changes
4. Include a brief comment about what you changed

Format your response as:
<file_content>
[complete file content]
</file_content>

<changes_summary>
[brief description]
</changes_summary>
"""

        try:
            # Build system prompt based on file type
            system_prompt = self._get_system_prompt_for_file(context.file_path)

            # Emit that we're using extended thinking
            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_STREAMING,
                content="[Extended Thinking: analyzing issue with 20k token budget...]\n\n",
                **common_fields,
            ))

            # Stream with extended thinking (runs in thread pool)
            thinking_content, response_text = await asyncio.to_thread(
                self._stream_with_thinking_sync,
                system_prompt,
                prompt,
            )

            # Save thinking to S3 in background
            if thinking_content:
                asyncio.create_task(
                    self._save_thinking_to_s3(thinking_content, context.issue_id, context)
                )

            # Stream the response content to UI
            await emit(FixProgressEvent(
                type=FixEventType.FIX_ISSUE_STREAMING,
                content=response_text,
                **common_fields,
            ))

            # Parse response
            file_match = re.search(
                r"<file_content>\s*(.*?)\s*</file_content>",
                response_text,
                re.DOTALL,
            )
            summary_match = re.search(
                r"<changes_summary>\s*(.*?)\s*</changes_summary>",
                response_text,
                re.DOTALL,
            )

            if file_match:
                fixed_content = file_match.group(1).strip()
                changes_summary = summary_match.group(1).strip() if summary_match else None
                return fixed_content, changes_summary

            # Fallback: try to extract code block
            code_match = re.search(r"```(?:\w+)?\s*(.*?)```", response_text, re.DOTALL)
            if code_match:
                return code_match.group(1).strip(), "Fix applied"

            logger.error("Could not parse Claude response")
            return None, None

        except Exception as e:
            logger.exception("Error generating fix with extended thinking")
            return None, None
