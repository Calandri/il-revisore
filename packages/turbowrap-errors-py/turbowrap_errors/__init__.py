"""TurboWrap Errors - Intelligent error handling for FastAPI.

This package provides error handling utilities that automatically report
errors to a TurboWrap server for issue tracking.

Basic usage (local error formatting only):
    from fastapi import FastAPI
    from turbowrap_errors import TurboWrapMiddleware

    app = FastAPI()
    app.add_middleware(TurboWrapMiddleware)

With server reporting:
    from turbowrap_errors import TurboWrapMiddleware, TurboWrapClient

    client = TurboWrapClient(
        server_url="https://turbowrap.example.com",
        api_key="tw_abc123",
        repo_id="uuid-repo"
    )

    app = FastAPI()
    app.add_middleware(TurboWrapMiddleware, client=client)

Global client configuration:
    import turbowrap_errors

    turbowrap_errors.configure(
        server_url="https://turbowrap.example.com",
        api_key="tw_abc123",
        repo_id="uuid-repo"
    )

    # Then use anywhere
    try:
        ...
    except Exception as e:
        turbowrap_errors.report(e, "My Operation")
"""

from .client import TurboWrapClient, configure, get_client, report
from .decorator import TurboWrapContext, turbo_wrap
from .exceptions import (
    AuthenticationError,
    AuthorizationError,
    DatabaseError,
    ErrorSeverity,
    NotFoundError,
    TurboWrapError,
    ValidationError,
)
from .middleware import TurboWrapMiddleware
from .schema import ErrorDetail, TurboErrorResponse

__version__ = "0.1.0"

__all__ = [
    # Core
    "TurboWrapError",
    "ErrorSeverity",
    "TurboWrapMiddleware",
    "TurboWrapClient",
    "turbo_wrap",
    "TurboWrapContext",
    # Convenience exceptions
    "NotFoundError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "DatabaseError",
    # Schema
    "TurboErrorResponse",
    "ErrorDetail",
    # Global client functions
    "configure",
    "get_client",
    "report",
]
