"""
Reviewer implementations for TurboWrap.
"""

from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext

# CLI-based reviewers (new - agents explore codebase autonomously)
from turbowrap.review.reviewers.claude_cli_reviewer import ClaudeCLIReviewer

# SDK-based reviewers (legacy)
from turbowrap.review.reviewers.claude_reviewer import ClaudeReviewer
from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger
from turbowrap.review.reviewers.gemini_cli_challenger import GeminiCLIChallenger

__all__ = [
    "BaseReviewer",
    "ReviewContext",
    # Legacy SDK-based
    "ClaudeReviewer",
    "GeminiChallenger",
    # CLI-based (default)
    "ClaudeCLIReviewer",
    "GeminiCLIChallenger",
]
