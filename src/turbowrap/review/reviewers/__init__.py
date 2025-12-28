"""
Reviewer implementations for TurboWrap.

Provides:
- BaseReviewer: Abstract base class for all reviewers
- S3LoggingMixin: Mixin for S3 artifact logging
- ClaudeCLIReviewer: CLI-based Claude reviewer (agent explores codebase)
- GeminiChallenger: Unified challenger with SDK and CLI modes
- GeminiCLIChallenger: DEPRECATED - use GeminiChallenger(mode="cli")
"""

from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext, S3LoggingMixin

# CLI-based reviewers (agents explore codebase autonomously)
from turbowrap.review.reviewers.claude_cli_reviewer import ClaudeCLIReviewer

# Unified challenger (SDK + CLI modes)
from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger, GeminiMode

# Deprecated - kept for backwards compatibility
from turbowrap.review.reviewers.gemini_cli_challenger import GeminiCLIChallenger

__all__ = [
    # Base
    "BaseReviewer",
    "ReviewContext",
    "S3LoggingMixin",
    # Claude reviewer (CLI-based)
    "ClaudeCLIReviewer",
    # Gemini challenger (unified)
    "GeminiChallenger",
    "GeminiMode",
    # Deprecated (backwards compatibility)
    "GeminiCLIChallenger",
]
