"""
Linear integration for TurboWrap.
"""

import re
from typing import Optional

import httpx

from turbowrap.config import get_settings
from turbowrap.review.models.report import FinalReport, Recommendation


class LinearClient:
    """
    Client for Linear API integration.

    Posts review summaries as comments on Linear issues.
    """

    API_URL = "https://api.linear.app/graphql"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Linear client.

        Args:
            api_key: Linear API key (uses config/env if not provided)
        """
        settings = get_settings()
        self.api_key = api_key or getattr(settings.agents, 'linear_api_key', None)

        if not self.api_key:
            raise ValueError(
                "Linear API key required. Set LINEAR_API_KEY environment variable."
            )

        self.headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

    async def post_review_comment(
        self,
        ticket_url: str,
        report: FinalReport,
    ) -> str:
        """
        Post a review summary as a comment on a Linear issue.

        Args:
            ticket_url: Linear ticket URL or issue identifier
            report: The final review report

        Returns:
            Created comment ID
        """
        issue_id = self._extract_issue_id(ticket_url)
        if not issue_id:
            raise ValueError(f"Could not extract issue ID from: {ticket_url}")

        comment_body = self._format_comment(report)

        mutation = """
        mutation CreateComment($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
                comment {
                    id
                }
            }
        }
        """

        variables = {
            "input": {
                "issueId": issue_id,
                "body": comment_body,
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers=self.headers,
                json={
                    "query": mutation,
                    "variables": variables,
                },
            )

        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise RuntimeError(f"Linear API error: {data['errors']}")

        return data["data"]["commentCreate"]["comment"]["id"]

    async def get_issue_id(self, identifier: str) -> Optional[str]:
        """
        Get issue UUID from identifier (e.g., "TEAM-123").

        Args:
            identifier: Issue identifier like "TEAM-123"

        Returns:
            Issue UUID or None if not found
        """
        query = """
        query GetIssue($identifier: String!) {
            issue(id: $identifier) {
                id
                identifier
                title
            }
        }
        """

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers=self.headers,
                json={
                    "query": query,
                    "variables": {"identifier": identifier},
                },
            )

        response.raise_for_status()
        data = response.json()

        if data.get("data", {}).get("issue"):
            return data["data"]["issue"]["id"]

        return None

    def _extract_issue_id(self, ticket_url: str) -> Optional[str]:
        """Extract issue ID from URL or identifier."""
        # Try direct identifier (e.g., "TEAM-123")
        if re.match(r"^[A-Z]+-\d+$", ticket_url):
            return ticket_url

        # Try Linear URL patterns
        # https://linear.app/team/issue/TEAM-123
        # https://linear.app/team/issue/TEAM-123/title-slug
        match = re.search(r"/issue/([A-Z]+-\d+)", ticket_url)
        if match:
            return match.group(1)

        # Try UUID
        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        match = re.search(uuid_pattern, ticket_url, re.I)
        if match:
            return match.group(0)

        return None

    def _format_comment(self, report: FinalReport) -> str:
        """Format report as Linear comment."""
        # Recommendation emoji
        rec_emoji = {
            Recommendation.APPROVE: ":white_check_mark:",
            Recommendation.APPROVE_WITH_CHANGES: ":warning:",
            Recommendation.REQUEST_CHANGES: ":x:",
            Recommendation.NEEDS_DISCUSSION: ":speech_balloon:",
        }

        emoji = rec_emoji.get(report.summary.recommendation, "")

        lines = [
            "## Code Review Complete",
            "",
            f"**Score**: {report.summary.overall_score:.1f}/10",
            f"**Recommendation**: {emoji} {report.summary.recommendation.value}",
            "",
            "### Issues Found",
            f"- Critical: {report.summary.by_severity.critical}",
            f"- High: {report.summary.by_severity.high}",
            f"- Medium: {report.summary.by_severity.medium}",
            f"- Low: {report.summary.by_severity.low}",
            "",
        ]

        # Add challenger info
        if report.challenger.enabled:
            lines.extend([
                "### Review Quality",
                f"- Challenger Iterations: {report.challenger.total_iterations}",
                f"- Final Satisfaction: {report.challenger.final_satisfaction_score:.1f}%",
                "",
            ])

        # Add top issues
        critical_issues = [
            i for i in report.issues[:5]
            if i.severity.value in ["CRITICAL", "HIGH"]
        ]
        if critical_issues:
            lines.append("### Critical Issues")
            for issue in critical_issues:
                lines.append(f"- **[{issue.id}]** {issue.title} (`{issue.file}`)")
            lines.append("")

        # Add next steps
        if report.next_steps:
            lines.append("### Next Steps")
            for step in report.next_steps:
                lines.append(f"{step.priority}. {step.action}")
            lines.append("")

        lines.append("---")
        lines.append("*Generated by TurboWrap*")

        return "\n".join(lines)

    async def update_issue_state(
        self,
        issue_id: str,
        state_name: str,
    ) -> bool:
        """
        Update issue state based on review result.

        Args:
            issue_id: Issue ID or identifier
            state_name: New state name (e.g., "In Review", "Ready for QA")

        Returns:
            True if successful
        """
        # First, get state ID from name
        state_id = await self._get_state_id(state_name)
        if not state_id:
            return False

        mutation = """
        mutation UpdateIssue($id: String!, $stateId: String!) {
            issueUpdate(id: $id, input: { stateId: $stateId }) {
                success
            }
        }
        """

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers=self.headers,
                json={
                    "query": mutation,
                    "variables": {
                        "id": issue_id,
                        "stateId": state_id,
                    },
                },
            )

        response.raise_for_status()
        data = response.json()

        return data.get("data", {}).get("issueUpdate", {}).get("success", False)

    async def _get_state_id(self, state_name: str) -> Optional[str]:
        """Get workflow state ID by name."""
        query = """
        query GetStates {
            workflowStates {
                nodes {
                    id
                    name
                }
            }
        }
        """

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers=self.headers,
                json={"query": query},
            )

        response.raise_for_status()
        data = response.json()

        states = data.get("data", {}).get("workflowStates", {}).get("nodes", [])
        for state in states:
            if state["name"].lower() == state_name.lower():
                return state["id"]

        return None
