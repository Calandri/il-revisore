"""
DEPRECATED: Use GeminiChallenger(mode="cli") instead.

This module is kept for backwards compatibility but will be removed
in a future version.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger, GeminiMode

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from turbowrap.review.models.challenger import ChallengerFeedback
    from turbowrap.review.models.review import ReviewOutput

__all__ = ["GeminiCLIChallenger"]


class GeminiCLIChallenger(GeminiChallenger):
    """
    DEPRECATED: Use GeminiChallenger(mode="cli") instead.

    This class is an alias for backwards compatibility and will be removed
    in a future version.

    Migration:
        # Old code:
        challenger = GeminiCLIChallenger()
        feedback = await challenger.challenge(review, file_list, repo_path)

        # New code:
        challenger = GeminiChallenger(mode="cli")
        feedback = await challenger.challenge_cli(review, file_list, repo_path)
    """

    def __init__(
        self,
        name: str = "challenger",
        cli_path: str = "gemini",
        timeout: int = 120,
    ):
        """
        Initialize deprecated GeminiCLIChallenger.

        Emits deprecation warning and delegates to GeminiChallenger.
        """
        warnings.warn(
            "GeminiCLIChallenger is deprecated. Use GeminiChallenger(mode='cli') instead. "
            "This class will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(
            name=name,
            mode=GeminiMode.CLI,
            timeout=timeout,
            cli_path=cli_path,
        )

    async def challenge(  # type: ignore[override]
        self,
        review: ReviewOutput,
        file_list: list[str],
        repo_path: Path | None,
        iteration: int = 1,
        on_chunk: Callable[[str], Awaitable[None]] | None = None,
        review_id: str | None = None,
    ) -> ChallengerFeedback:
        """
        Challenge a review using CLI mode.

        DEPRECATED: Use GeminiChallenger.challenge_cli() instead.

        This method signature matches the old GeminiCLIChallenger.challenge()
        for backwards compatibility.
        """
        return await self.challenge_cli(
            review=review,
            file_list=file_list,
            repo_path=repo_path,
            iteration=iteration,
            review_id=review_id,
            on_chunk=on_chunk,
        )
