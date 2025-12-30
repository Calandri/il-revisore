"""
Reviewer implementations for TurboWrap.

Provides:
- BaseReviewer: Abstract base class for all reviewers
- BaseCLIReviewer: Abstract base class for CLI-based reviewers
- S3LoggingMixin: Mixin for S3 artifact logging
- ClaudeCLIReviewer: CLI-based Claude reviewer (agent explores codebase)
- GeminiCLIReviewer: CLI-based Gemini reviewer
- GrokCLIReviewer: CLI-based Grok reviewer (xAI)
- GeminiChallenger: Unified challenger with SDK and CLI modes
- GeminiCLIChallenger: DEPRECATED - use GeminiChallenger(mode="cli")
- DEFAULT_CLI_TIMEOUT: Default timeout for CLI-based reviewers (300s)
"""

from turbowrap.review.reviewers.base import BaseReviewer, ReviewContext, S3LoggingMixin
from turbowrap.review.reviewers.base_cli_reviewer import BaseCLIReviewer

# CLI-based reviewers (agents explore codebase autonomously)
from turbowrap.review.reviewers.claude_cli_reviewer import ClaudeCLIReviewer
from turbowrap.review.reviewers.constants import DEFAULT_CLI_TIMEOUT

# Unified challenger (SDK + CLI modes)
from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger, GeminiMode

# Deprecated - kept for backwards compatibility
from turbowrap.review.reviewers.gemini_cli_challenger import GeminiCLIChallenger
from turbowrap.review.reviewers.gemini_cli_reviewer import GeminiCLIReviewer
from turbowrap.review.reviewers.grok_cli_reviewer import GrokCLIReviewer

__all__ = [
    # Base
    "BaseReviewer",
    "BaseCLIReviewer",
    "ReviewContext",
    "S3LoggingMixin",
    # Constants
    "DEFAULT_CLI_TIMEOUT",
    # Claude reviewer (CLI-based)
    "ClaudeCLIReviewer",
    # Gemini reviewer (CLI-based)
    "GeminiCLIReviewer",
    # Grok reviewer (CLI-based)
    "GrokCLIReviewer",
    # Gemini challenger (unified)
    "GeminiChallenger",
    "GeminiMode",
    # Deprecated (backwards compatibility)
    "GeminiCLIChallenger",
]
