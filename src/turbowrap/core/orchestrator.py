"""Orchestrator module - delegates to review.orchestrator.

This module re-exports the Orchestrator from the review package
for backward compatibility with existing code.

DEPRECATED: Import directly from turbowrap.review.orchestrator instead.
This module will be removed in a future version.
"""

import warnings

from turbowrap.review.orchestrator import Orchestrator

warnings.warn(
    "turbowrap.core.orchestrator is deprecated. "
    "Import Orchestrator from turbowrap.review.orchestrator instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Orchestrator"]
