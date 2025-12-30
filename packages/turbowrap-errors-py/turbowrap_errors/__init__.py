"""TurboWrap Errors - Intelligent error handling for FastAPI."""

from .decorator import turbo_wrap
from .exceptions import ErrorSeverity, TurboWrapError
from .middleware import TurboWrapMiddleware
from .schema import TurboErrorResponse

__version__ = "0.1.0"

__all__ = [
    "TurboWrapError",
    "ErrorSeverity",
    "TurboWrapMiddleware",
    "turbo_wrap",
    "TurboErrorResponse",
]
