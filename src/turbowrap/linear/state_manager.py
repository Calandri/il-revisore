"""Linear state manager for handling state transitions."""

import logging
from typing import cast

from turbowrap.db.models import LinearIssue
from turbowrap.review.integrations.linear import LinearClient

logger = logging.getLogger(__name__)


class LinearStateManager:
    """Manages state transitions for Linear issues.

    Handles bidirectional state synchronization between TurboWrap and Linear.
    """

    # TurboWrap states
    STATE_ANALYSIS = "analysis"
    STATE_REPO_LINK = "repo_link"
    STATE_IN_PROGRESS = "in_progress"
    STATE_IN_REVIEW = "in_review"
    STATE_MERGED = "merged"

    # Valid state transitions (from -> to)
    ALLOWED_TRANSITIONS = {
        STATE_ANALYSIS: [STATE_REPO_LINK],
        STATE_REPO_LINK: [STATE_IN_PROGRESS, STATE_ANALYSIS],  # Can go back to analysis
        STATE_IN_PROGRESS: [STATE_IN_REVIEW],  # Auto-transition after commit
        STATE_IN_REVIEW: [STATE_MERGED, STATE_IN_PROGRESS],  # Can go back if merge fails
        STATE_MERGED: [],  # Terminal state
    }

    # Mapping TurboWrap states → Linear state names
    # These should match the actual Linear workflow states
    LINEAR_STATE_MAPPING = {
        STATE_ANALYSIS: "Triage",
        STATE_REPO_LINK: "To Do",
        STATE_IN_PROGRESS: "In Progress",
        STATE_IN_REVIEW: "In Review",
        STATE_MERGED: "Done",
    }

    def __init__(self, linear_client: LinearClient):
        """Initialize state manager.

        Args:
            linear_client: Linear API client for state updates
        """
        self.linear_client = linear_client

    async def transition_to(
        self,
        issue: LinearIssue,
        new_state: str,
        update_linear: bool = True,
        force: bool = False,
    ) -> bool:
        """Transition issue to a new state.

        Args:
            issue: LinearIssue to transition
            new_state: Target state
            update_linear: Whether to sync state to Linear
            force: Skip validation checks (use with caution)

        Returns:
            True if transition successful, False otherwise

        Raises:
            ValueError: If transition is not allowed
        """
        current_state = cast(str, issue.turbowrap_state)

        # Validate transition
        if not force and new_state not in self.ALLOWED_TRANSITIONS.get(current_state, []):
            allowed = self.ALLOWED_TRANSITIONS.get(current_state, [])
            raise ValueError(
                f"Invalid transition from '{current_state}' to '{new_state}'. Allowed: {allowed}"
            )

        # Additional validation based on target state
        if not force:
            if new_state == self.STATE_IN_PROGRESS:
                repo_links = issue.repository_links
                if not repo_links or len(list(repo_links)) == 0:
                    raise ValueError(
                        "Cannot transition to 'in_progress' without linked repositories"
                    )

            elif new_state == self.STATE_IN_REVIEW:
                if not cast(str | None, issue.fix_commit_sha):
                    raise ValueError("Cannot transition to 'in_review' without fix commit")

            elif new_state == self.STATE_MERGED:
                if not cast(str | None, issue.fix_commit_sha) or not cast(
                    str | None, issue.fix_branch
                ):
                    raise ValueError("Cannot transition to 'merged' without fix commit and branch")

        # Update TurboWrap state
        logger.info(
            f"Transitioning {issue.linear_identifier} from '{current_state}' to '{new_state}'"
        )
        issue.turbowrap_state = new_state  # type: ignore[assignment]

        # Update Linear state if requested
        if update_linear:
            try:
                linear_state_name = self.LINEAR_STATE_MAPPING.get(new_state)
                if not linear_state_name:
                    logger.warning(f"No Linear state mapping for TurboWrap state '{new_state}'")
                    return True

                # Get state ID from cached fields or fetch from Linear
                state_id = self._get_linear_state_id(issue, linear_state_name)

                if state_id:
                    success = await self.linear_client.update_issue_state(
                        cast(str, issue.linear_id), state_id
                    )
                    if success:
                        issue.linear_state_name = linear_state_name  # type: ignore[assignment]
                        logger.info(
                            f"Updated Linear state to '{linear_state_name}' for {issue.linear_identifier}"
                        )
                    else:
                        logger.error(f"Failed to update Linear state for {issue.linear_identifier}")
                        return False
                else:
                    logger.warning(f"Could not find Linear state ID for '{linear_state_name}'")

            except Exception as e:
                logger.error(f"Error updating Linear state: {e}")
                # Don't fail the transition if Linear update fails
                # The state is already updated in TurboWrap DB

        return True

    def _get_linear_state_id(self, issue: LinearIssue, state_name: str) -> str | None:
        """Get Linear state ID from cached fields.

        Args:
            issue: LinearIssue with cached state IDs
            state_name: Linear state name

        Returns:
            State ID or None
        """
        # Map state names to cached fields
        state_field_mapping = {
            "Triage": "linear_state_triage_id",
            "To Do": "linear_state_todo_id",
            "In Progress": "linear_state_inprogress_id",
            "In Review": "linear_state_inreview_id",
            "Done": "linear_state_done_id",
        }

        field_name = state_field_mapping.get(state_name)
        if field_name:
            return getattr(issue, field_name, None)

        return None

    def can_transition_to(self, current_state: str, target_state: str) -> bool:
        """Check if transition is allowed.

        Args:
            current_state: Current state
            target_state: Desired target state

        Returns:
            True if transition is allowed
        """
        return target_state in self.ALLOWED_TRANSITIONS.get(current_state, [])

    def get_allowed_next_states(self, current_state: str) -> list[str]:
        """Get list of allowed next states from current state.

        Args:
            current_state: Current state

        Returns:
            List of allowed next states
        """
        return self.ALLOWED_TRANSITIONS.get(current_state, [])

    async def auto_transition_after_commit(
        self, issue: LinearIssue, commit_sha: str, branch_name: str
    ) -> bool:
        """Automatically transition to in_review after successful commit.

        This is called by FixOrchestrator after a successful fix commit.

        Args:
            issue: LinearIssue that was fixed
            commit_sha: Commit SHA of the fix
            branch_name: Branch name where fix was committed

        Returns:
            True if transition successful
        """
        logger.info(
            f"Auto-transitioning {issue.linear_identifier} to 'in_review' after commit {commit_sha[:8]}"
        )

        # Update fix details
        issue.fix_commit_sha = commit_sha  # type: ignore[assignment]
        issue.fix_branch = branch_name  # type: ignore[assignment]

        # Transition to in_review
        try:
            return await self.transition_to(issue, self.STATE_IN_REVIEW, update_linear=True)
        except ValueError as e:
            logger.error(f"Auto-transition failed: {e}")
            return False

    async def auto_transition_after_merge(self, issue: LinearIssue) -> bool:
        """Automatically transition to merged after successful merge to main.

        Args:
            issue: LinearIssue that was merged

        Returns:
            True if transition successful
        """
        logger.info(f"Auto-transitioning {issue.linear_identifier} to 'merged' after merge")

        # Deactivate issue
        issue.is_active = False  # type: ignore[assignment]

        # Transition to merged
        try:
            return await self.transition_to(issue, self.STATE_MERGED, update_linear=True)
        except ValueError as e:
            logger.error(f"Auto-transition to merged failed: {e}")
            return False
