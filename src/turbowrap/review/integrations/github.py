"""
GitHub integration for TurboWrap.
"""

import logging
import re
import time
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from github import Github, GithubException, RateLimitExceededException

from turbowrap.config import get_settings
from turbowrap.review.models.report import FinalReport, Recommendation

logger = logging.getLogger(__name__)

# Rate limit configuration
MAX_RETRIES = 3
BASE_RETRY_DELAY = 5  # seconds
MAX_RETRY_DELAY = 60  # seconds

T = TypeVar("T")


class GitHubRateLimitError(Exception):
    """Raised when GitHub rate limit is exceeded and retries are exhausted."""

    def __init__(self, message: str, reset_time: int | None = None):
        super().__init__(message)
        self.reset_time = reset_time


def with_rate_limit_retry(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to handle GitHub rate limits with exponential backoff.

    Catches RateLimitExceededException and GithubException with rate limit errors,
    waits for the appropriate time, and retries the operation.

    Args:
        func: Function to wrap.

    Returns:
        Wrapped function with retry logic.
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        last_exception = None
        retry_count = 0

        while retry_count <= MAX_RETRIES:
            try:
                return func(*args, **kwargs)

            except RateLimitExceededException as e:
                last_exception = e
                retry_count += 1

                # Get rate limit reset time
                reset_time = getattr(e, "reset_time", None)
                if reset_time:
                    wait_seconds = max(0, reset_time - int(time.time()))
                else:
                    wait_seconds = min(
                        BASE_RETRY_DELAY * (2 ** (retry_count - 1)),
                        MAX_RETRY_DELAY
                    )

                if retry_count <= MAX_RETRIES:
                    logger.warning(
                        f"GitHub rate limit exceeded. Waiting {wait_seconds}s before retry "
                        f"({retry_count}/{MAX_RETRIES})"
                    )
                    time.sleep(wait_seconds)
                else:
                    break

            except GithubException as e:
                # Check if it's a rate limit error (403 with rate limit message)
                if e.status == 403 and "rate limit" in str(e).lower():
                    last_exception = e
                    retry_count += 1

                    wait_seconds = min(
                        BASE_RETRY_DELAY * (2 ** (retry_count - 1)),
                        MAX_RETRY_DELAY
                    )

                    if retry_count <= MAX_RETRIES:
                        logger.warning(
                            f"GitHub rate limit error. Waiting {wait_seconds}s before retry "
                            f"({retry_count}/{MAX_RETRIES})"
                        )
                        time.sleep(wait_seconds)
                    else:
                        break
                else:
                    raise

        raise GitHubRateLimitError(
            f"GitHub rate limit exceeded after {MAX_RETRIES} retries. "
            f"Last error: {last_exception}",
            reset_time=getattr(last_exception, "reset_time", None),
        )

    return wrapper


class GitHubClient:
    """
    Client for GitHub API integration.

    Fetches PR information and posts review comments.
    """

    def __init__(self, token: str | None = None):
        """
        Initialize GitHub client.

        Args:
            token: GitHub token (uses config/env if not provided)
        """
        settings = get_settings()
        self.token = token or getattr(settings.agents, 'github_token', None)

        if not self.token:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN environment variable."
            )

        self.github = Github(self.token)

    @with_rate_limit_retry
    def get_pr_files(self, pr_url: str) -> list[str]:
        """
        Get list of files changed in a PR.

        Args:
            pr_url: GitHub PR URL

        Returns:
            List of file paths

        Raises:
            GitHubRateLimitError: If rate limit is exceeded after retries.
        """
        owner, repo, pr_number = self._parse_pr_url(pr_url)
        if not all([owner, repo, pr_number]):
            raise ValueError(f"Invalid PR URL: {pr_url}")

        repository = self.github.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)

        return [f.filename for f in pr.get_files()]

    @with_rate_limit_retry
    def get_pr_diff(self, pr_url: str) -> str:
        """
        Get the diff for a PR.

        Args:
            pr_url: GitHub PR URL

        Returns:
            Diff content

        Raises:
            GitHubRateLimitError: If rate limit is exceeded after retries.
        """
        import requests

        owner, repo, pr_number = self._parse_pr_url(pr_url)
        if not all([owner, repo, pr_number]):
            raise ValueError(f"Invalid PR URL: {pr_url}")

        repository = self.github.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)

        # Get diff via API with rate limit handling
        headers = {"Authorization": f"token {self.token}"}
        response = requests.get(
            pr.diff_url,
            headers=headers,
            timeout=30,
        )

        # Check for rate limit in response headers
        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining", "")
            if remaining == "0":
                int(response.headers.get("X-RateLimit-Reset", 0))
                raise RateLimitExceededException(
                    response.status_code,
                    {"message": "Rate limit exceeded"},
                    headers=dict(response.headers),
                )

        response.raise_for_status()
        return response.text

    @with_rate_limit_retry
    def post_review_comment(
        self,
        pr_url: str,
        report: FinalReport,
        update_existing: bool = True,
    ) -> int:
        """
        Post or update a review comment on a PR.

        Args:
            pr_url: GitHub PR URL
            report: The final review report
            update_existing: Update existing TurboWrap comment if found

        Returns:
            Comment ID

        Raises:
            GitHubRateLimitError: If rate limit is exceeded after retries.
        """
        owner, repo, pr_number = self._parse_pr_url(pr_url)
        if not all([owner, repo, pr_number]):
            raise ValueError(f"Invalid PR URL: {pr_url}")

        repository = self.github.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)

        comment_body = self._format_comment(report)

        # Look for existing comment
        if update_existing:
            for comment in pr.get_issue_comments():
                if "TurboWrap - Code Review Report" in comment.body:
                    comment.edit(comment_body)
                    return comment.id

        # Create new comment
        comment = pr.create_issue_comment(comment_body)
        return comment.id

    @with_rate_limit_retry
    def create_review(
        self,
        pr_url: str,
        report: FinalReport,
    ) -> int:
        """
        Create a PR review with inline comments.

        Args:
            pr_url: GitHub PR URL
            report: The final review report

        Returns:
            Review ID

        Raises:
            GitHubRateLimitError: If rate limit is exceeded after retries.
        """
        owner, repo, pr_number = self._parse_pr_url(pr_url)
        if not all([owner, repo, pr_number]):
            raise ValueError(f"Invalid PR URL: {pr_url}")

        repository = self.github.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)

        # Determine review event
        event = "COMMENT"
        if report.summary.recommendation == Recommendation.APPROVE:
            event = "APPROVE"
        elif report.summary.recommendation == Recommendation.REQUEST_CHANGES:
            event = "REQUEST_CHANGES"

        # Build inline comments
        comments = []
        for issue in report.issues[:20]:  # Limit to 20 inline comments
            if issue.line:
                comment_body = f"**[{issue.severity.value}]** {issue.title}\n\n{issue.description}"
                if issue.suggested_fix:
                    comment_body += f"\n\n**Suggested fix:**\n```\n{issue.suggested_fix}\n```"

                comments.append({
                    "path": issue.file,
                    "line": issue.line,
                    "body": comment_body,
                })

        # Create review
        review_body = self._format_review_summary(report)

        try:
            review = pr.create_review(
                body=review_body,
                event=event,
                comments=comments,
            )
            return review.id
        except GithubException as e:
            # Fall back to simple comment if review fails
            if "line" in str(e).lower() or "position" in str(e).lower():
                # Inline comments failed, create simple review
                review = pr.create_review(
                    body=review_body,
                    event=event,
                )
                return review.id
            raise

    @with_rate_limit_retry
    def set_commit_status(
        self,
        pr_url: str,
        report: FinalReport,
    ) -> None:
        """
        Set commit status based on review result.

        Args:
            pr_url: GitHub PR URL
            report: The final review report

        Raises:
            GitHubRateLimitError: If rate limit is exceeded after retries.
        """
        owner, repo, pr_number = self._parse_pr_url(pr_url)
        if not all([owner, repo, pr_number]):
            raise ValueError(f"Invalid PR URL: {pr_url}")

        repository = self.github.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)

        # Determine status
        state = "success"
        description = "Review passed"

        if report.summary.recommendation == Recommendation.REQUEST_CHANGES:
            state = "failure"
            description = (
                f"{report.summary.by_severity.critical} critical, "
                f"{report.summary.by_severity.high} high issues"
            )
        elif report.summary.recommendation == Recommendation.APPROVE_WITH_CHANGES:
            state = "success"
            description = f"{report.summary.total_issues} issues to address"

        # Create status
        commit = repository.get_commit(pr.head.sha)
        commit.create_status(
            state=state,
            target_url="",  # Could link to full report
            description=description[:140],  # GitHub limit
            context="TurboWrap / AI Code Review",
        )

    def _parse_pr_url(self, pr_url: str) -> tuple[str | None, str | None, int | None]:
        """Parse PR URL into owner, repo, and PR number."""
        # Match patterns like:
        # https://github.com/owner/repo/pull/123
        # github.com/owner/repo/pull/123
        match = re.match(
            r"(?:https?://)?github\.com/([^/]+)/([^/]+)/pull/(\d+)",
            pr_url,
        )
        if match:
            return match.group(1), match.group(2), int(match.group(3))

        return None, None, None

    def _format_comment(self, report: FinalReport) -> str:
        """Format report as GitHub comment."""
        from turbowrap.review.report_generator import ReportGenerator

        return ReportGenerator.to_markdown(report)

    def _format_review_summary(self, report: FinalReport) -> str:
        """Format a brief review summary."""
        rec_emoji = {
            Recommendation.APPROVE: ":white_check_mark:",
            Recommendation.APPROVE_WITH_CHANGES: ":warning:",
            Recommendation.REQUEST_CHANGES: ":x:",
            Recommendation.NEEDS_DISCUSSION: ":speech_balloon:",
        }

        emoji = rec_emoji.get(report.summary.recommendation, "")

        lines = [
            "## TurboWrap - Code Review Summary",
            "",
            f"**Score**: {report.summary.overall_score:.1f}/10",
            f"**Recommendation**: {emoji} {report.summary.recommendation.value}",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| Critical | {report.summary.by_severity.critical} |",
            f"| High | {report.summary.by_severity.high} |",
            f"| Medium | {report.summary.by_severity.medium} |",
            f"| Low | {report.summary.by_severity.low} |",
            "",
        ]

        if report.challenger.enabled:
            lines.extend([
                f"*Reviewed with {report.challenger.total_iterations} challenger iterations, "
                f"{report.challenger.final_satisfaction_score:.1f}% satisfaction*",
                "",
            ])

        return "\n".join(lines)

    @with_rate_limit_retry
    def create_pull_request(
        self,
        repo_url: str,
        branch_name: str,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> dict:
        """
        Create a pull request on GitHub.

        Args:
            repo_url: Repository URL (https://github.com/owner/repo)
            branch_name: The branch to merge (head)
            title: PR title
            body: PR description/body
            base_branch: Target branch (default: main)

        Returns:
            Dict with PR info: {url, number, html_url}

        Raises:
            GitHubRateLimitError: If rate limit is exceeded after retries.
        """
        owner, repo = self._parse_repo_url(repo_url)
        if not owner or not repo:
            raise ValueError(f"Invalid repo URL: {repo_url}")

        repository = self.github.get_repo(f"{owner}/{repo}")

        pr = repository.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base=base_branch,
        )

        return {
            "number": pr.number,
            "url": pr.html_url,
            "html_url": pr.html_url,
        }

    def _parse_repo_url(self, repo_url: str) -> tuple[str | None, str | None]:
        """Parse repo URL into owner and repo name."""
        match = re.match(
            r"(?:https?://)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
            repo_url,
        )
        if match:
            return match.group(1), match.group(2)
        return None, None
