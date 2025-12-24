"""
External integrations for TurboWrap review.
"""

from turbowrap.review.integrations.github import GitHubClient
from turbowrap.review.integrations.linear import LinearClient

__all__ = [
    "GitHubClient",
    "LinearClient",
]
