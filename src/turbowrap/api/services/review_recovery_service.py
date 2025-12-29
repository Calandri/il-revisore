"""
Review Recovery Service - Recover issues from S3 artifacts when review fails.

Use this when a review completes the LLM calls (data saved to S3) but
the parsing/DB save step fails. This service:
1. Finds JSONL files in S3 for a review_id
2. Parses the issues from the LLM outputs
3. Saves them to the database

Usage:
    from turbowrap.api.services.review_recovery_service import ReviewRecoveryService

    service = ReviewRecoveryService(db)
    result = await service.recover_review("rev_2b82a20306cf", "repository_id")
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db.models import Issue, Repository, Task
from ...review.models.review import Issue as ReviewIssue
from ...review.models.review import IssueCategory, IssueSeverity

logger = logging.getLogger(__name__)

S3_BUCKET = "turbowrap-thinking"


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""

    success: bool
    review_id: str
    task_id: str | None
    issues_found: int
    issues_saved: int
    errors: list[str]
    s3_files_processed: list[str]


class ReviewRecoveryService:
    """
    Service to recover review issues from S3 when DB save fails.

    This is useful when:
    - LLM calls complete successfully (output saved to S3)
    - But parsing or DB save fails
    - You want to re-process without re-running expensive LLM calls
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.s3_client = boto3.client("s3", region_name=self.settings.thinking.s3_region)

    async def recover_review(
        self,
        review_id: str,
        repository_id: str | None = None,
        task_id: str | None = None,
        create_task_if_missing: bool = True,
    ) -> RecoveryResult:
        """
        Recover issues from S3 artifacts and save to database.

        Args:
            review_id: The review ID (e.g., "rev_2b82a20306cf")
            repository_id: Optional repository ID (will search if not provided)
            task_id: Optional task ID (will create if not provided and create_task_if_missing=True)
            create_task_if_missing: Whether to create a task if none exists

        Returns:
            RecoveryResult with details of the operation
        """
        errors: list[str] = []
        s3_files: list[str] = []
        all_issues: list[ReviewIssue] = []

        logger.info(f"[RECOVERY] Starting recovery for review_id={review_id}")

        # Step 1: Find S3 files for this review
        try:
            s3_files = self._find_s3_files(review_id)
            logger.info(f"[RECOVERY] Found {len(s3_files)} S3 files")
        except Exception as e:
            errors.append(f"Failed to find S3 files: {e}")
            return RecoveryResult(
                success=False,
                review_id=review_id,
                task_id=None,
                issues_found=0,
                issues_saved=0,
                errors=errors,
                s3_files_processed=[],
            )

        if not s3_files:
            errors.append(f"No S3 files found for review_id={review_id}")
            return RecoveryResult(
                success=False,
                review_id=review_id,
                task_id=None,
                issues_found=0,
                issues_saved=0,
                errors=errors,
                s3_files_processed=[],
            )

        # Step 2: Parse issues from each S3 file
        for s3_key in s3_files:
            try:
                llm_name = self._extract_llm_name(s3_key)
                issues = self._parse_s3_file(s3_key, llm_name)
                all_issues.extend(issues)
                logger.info(f"[RECOVERY] Parsed {len(issues)} issues from {s3_key}")
            except Exception as e:
                errors.append(f"Failed to parse {s3_key}: {e}")
                logger.error(f"[RECOVERY] Error parsing {s3_key}: {e}")

        if not all_issues:
            errors.append("No issues found in any S3 file")
            return RecoveryResult(
                success=False,
                review_id=review_id,
                task_id=None,
                issues_found=0,
                issues_saved=0,
                errors=errors,
                s3_files_processed=s3_files,
            )

        # Step 3: Find or create repository
        if not repository_id:
            # Try to find from S3 metadata or use a default
            errors.append("repository_id is required")
            return RecoveryResult(
                success=False,
                review_id=review_id,
                task_id=None,
                issues_found=len(all_issues),
                issues_saved=0,
                errors=errors,
                s3_files_processed=s3_files,
            )

        repo = self.db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo:
            errors.append(f"Repository {repository_id} not found")
            return RecoveryResult(
                success=False,
                review_id=review_id,
                task_id=None,
                issues_found=len(all_issues),
                issues_saved=0,
                errors=errors,
                s3_files_processed=s3_files,
            )

        # Step 4: Find or create task
        if not task_id:
            # Look for existing task with this review_id
            existing_task = (
                self.db.query(Task)
                .filter(Task.repository_id == repository_id)
                .order_by(Task.created_at.desc())
                .first()
            )

            if existing_task:
                task_id = str(existing_task.id)
                logger.info(f"[RECOVERY] Using existing task {task_id}")
            elif create_task_if_missing:
                # Create new task
                task = Task(
                    repository_id=repository_id,
                    type="review",
                    status="completed",
                    config={"mode": "recovery", "review_id": review_id},
                    completed_at=datetime.utcnow(),
                )
                self.db.add(task)
                self.db.commit()
                self.db.refresh(task)
                task_id = str(task.id)
                logger.info(f"[RECOVERY] Created new task {task_id}")
            else:
                errors.append("No task found and create_task_if_missing=False")
                return RecoveryResult(
                    success=False,
                    review_id=review_id,
                    task_id=None,
                    issues_found=len(all_issues),
                    issues_saved=0,
                    errors=errors,
                    s3_files_processed=s3_files,
                )

        # Step 5: Save issues to database
        saved_count = 0
        for issue in all_issues:
            try:
                db_issue = Issue(
                    task_id=task_id,
                    repository_id=repository_id,
                    issue_code=issue.id,
                    severity=(
                        issue.severity.value
                        if hasattr(issue.severity, "value")
                        else str(issue.severity).upper()
                    ),
                    category=(
                        issue.category.value
                        if hasattr(issue.category, "value")
                        else str(issue.category)
                    ),
                    rule=issue.rule,
                    file=issue.file,
                    line=issue.line,
                    title=issue.title,
                    description=issue.description,
                    current_code=issue.current_code,
                    suggested_fix=issue.suggested_fix,
                    references=issue.references if issue.references else None,
                    flagged_by=issue.flagged_by if issue.flagged_by else None,
                    estimated_effort=issue.estimated_effort,
                    estimated_files_count=issue.estimated_files_count,
                )
                self.db.add(db_issue)
                saved_count += 1
            except Exception as e:
                errors.append(f"Failed to save issue {issue.id}: {e}")
                logger.error(f"[RECOVERY] Error saving issue {issue.id}: {e}")

        self.db.commit()
        logger.info(f"[RECOVERY] Saved {saved_count} issues to database")

        return RecoveryResult(
            success=saved_count > 0,
            review_id=review_id,
            task_id=task_id,
            issues_found=len(all_issues),
            issues_saved=saved_count,
            errors=errors,
            s3_files_processed=s3_files,
        )

    def _find_s3_files(self, review_id: str) -> list[str]:
        """Find all S3 files for a review_id across all LLM prefixes."""
        s3_files: list[str] = []

        # Search in different prefixes
        prefixes = [
            "reviews/claude_parallel/",
            "reviews/gemini_parallel/",
            "reviews/grok_parallel/",
            "reviews/claude/",
            "reviews/gemini/",
            "reviews/grok/",
        ]

        paginator = self.s3_client.get_paginator("list_objects_v2")

        for prefix in prefixes:
            try:
                for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
                    for obj in page.get("Contents", []):
                        key = obj["Key"]
                        if review_id in key and key.endswith(".jsonl"):
                            s3_files.append(key)
            except ClientError as e:
                logger.warning(f"[RECOVERY] Error listing {prefix}: {e}")

        return s3_files

    def _extract_llm_name(self, s3_key: str) -> str:
        """Extract LLM name from S3 key."""
        if "claude" in s3_key.lower():
            return "claude"
        if "gemini" in s3_key.lower():
            return "gemini"
        if "grok" in s3_key.lower():
            return "grok"
        return "unknown"

    def _parse_s3_file(self, s3_key: str, llm_name: str) -> list[ReviewIssue]:
        """
        Parse issues from an S3 JSONL file.

        Looks for:
        1. write_file tool calls with review JSON
        2. Direct JSON blocks with specialist reviews
        """
        issues: list[ReviewIssue] = []

        # Download file
        response = self.s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        content = response["Body"].read().decode("utf-8")

        # Strategy 1: Look for write_file tool calls
        review_json = self._extract_write_file_content(content)

        if review_json:
            issues.extend(self._parse_review_json(review_json, llm_name))

        # Strategy 2: Look for JSON blocks in the output
        if not issues:
            issues.extend(self._parse_json_blocks(content, llm_name))

        return issues

    def _extract_write_file_content(self, jsonl_content: str) -> str | None:
        """Extract the content from write_file tool calls in JSONL."""
        for line in jsonl_content.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    # Check for tool_use with write_file
                    if data.get("type") == "tool_use" and data.get("tool_name") == "write_file":
                        content = data.get("parameters", {}).get("content", "")
                        if content and "specialist" in content:
                            return content
            except json.JSONDecodeError:
                continue
        return None

    def _parse_review_json(self, json_str: str, llm_name: str) -> list[ReviewIssue]:
        """Parse review JSON (list or dict of specialists)."""
        issues: list[ReviewIssue] = []

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"[RECOVERY] Failed to parse JSON: {e}")
            return issues

        specialists: list[dict[str, Any]] = []

        if isinstance(data, list):
            specialists = data
        elif isinstance(data, dict):
            if "specialists" in data:
                specialists = list(data["specialists"].values())
            else:
                # Each key is a specialist
                for key, value in data.items():
                    if isinstance(value, dict):
                        specialists.append({"specialist": key, "review": value})

        for spec_data in specialists:
            if not isinstance(spec_data, dict):
                continue

            spec_name = spec_data.get("specialist", "unknown")
            review_data = spec_data.get("review", spec_data)

            if isinstance(review_data, dict):
                issues_data = review_data.get("issues", [])
                for issue_dict in issues_data:
                    issue = self._dict_to_review_issue(issue_dict, llm_name, spec_name)
                    if issue:
                        issues.append(issue)

        return issues

    def _parse_json_blocks(self, content: str, llm_name: str) -> list[ReviewIssue]:
        """Parse JSON blocks from raw content."""
        issues: list[ReviewIssue] = []

        # Find JSON blocks between ```json and ```
        json_pattern = r"```json\s*([\s\S]*?)```"
        matches = re.findall(json_pattern, content)

        for match in matches:
            try:
                data = json.loads(match)
                if isinstance(data, dict) and "specialist" in data:
                    review_data = data.get("review", data)
                    spec_name = data.get("specialist", "unknown")

                    if isinstance(review_data, dict):
                        for issue_dict in review_data.get("issues", []):
                            issue = self._dict_to_review_issue(issue_dict, llm_name, spec_name)
                            if issue:
                                issues.append(issue)
            except json.JSONDecodeError:
                continue

        return issues

    def _dict_to_review_issue(
        self,
        issue_dict: dict[str, Any],
        llm_name: str,
        spec_name: str,
    ) -> ReviewIssue | None:
        """Convert a dict to a ReviewIssue object."""
        try:
            # Map severity
            severity_str = issue_dict.get("severity", "medium").upper()
            try:
                severity = IssueSeverity(severity_str)
            except ValueError:
                severity = IssueSeverity.MEDIUM

            # Map category
            category_str = issue_dict.get("category", "architecture").lower()
            try:
                category = IssueCategory(category_str)
            except ValueError:
                # Fallback to ARCHITECTURE for unknown categories
                category = IssueCategory.ARCHITECTURE

            return ReviewIssue(
                id=issue_dict.get("code", issue_dict.get("id", f"{spec_name}-{llm_name}-001")),
                severity=severity,
                category=category,
                rule=issue_dict.get("rule"),
                file=issue_dict.get("file", "unknown"),
                line=issue_dict.get("line"),
                end_line=issue_dict.get("end_line"),
                title=issue_dict.get("title", "Unknown issue"),
                description=issue_dict.get("description", ""),
                current_code=issue_dict.get("current_code"),
                suggested_fix=issue_dict.get("suggested_fix", issue_dict.get("fix")),
                references=issue_dict.get("references", []),
                flagged_by=[llm_name, spec_name],
                estimated_effort=issue_dict.get("effort", issue_dict.get("estimated_effort")),
                estimated_files_count=issue_dict.get("estimated_files_count"),
            )
        except Exception as e:
            logger.error(f"[RECOVERY] Error converting issue dict: {e}")
            return None


async def recover_review_cli(
    review_id: str,
    repository_id: str,
    task_id: str | None = None,
) -> RecoveryResult:
    """
    CLI-friendly function to recover a review.

    Usage from command line:
        python -c "
        import asyncio
        from turbowrap.api.services.review_recovery_service import recover_review_cli
        result = asyncio.run(recover_review_cli('rev_2b82a20306cf', 'repo-uuid'))
        print(result)
        "
    """
    from ...db.session import get_session_local

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        service = ReviewRecoveryService(db)
        return await service.recover_review(
            review_id=review_id,
            repository_id=repository_id,
            task_id=task_id,
        )
    finally:
        db.close()
