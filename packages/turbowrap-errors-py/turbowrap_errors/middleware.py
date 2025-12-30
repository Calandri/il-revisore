"""FastAPI middleware for automatic error handling."""

import logging
import traceback
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .exceptions import ErrorSeverity, TurboWrapError
from .schema import ErrorDetail, TurboErrorResponse

logger = logging.getLogger("turbowrap_errors")


class TurboWrapMiddleware(BaseHTTPMiddleware):
    """Middleware that catches exceptions and formats them as TurboWrap errors.

    This middleware automatically converts all unhandled exceptions into
    structured JSON responses that the frontend TurboWrapError handler
    can parse and display.

    Example:
        from fastapi import FastAPI
        from turbowrap_errors import TurboWrapMiddleware

        app = FastAPI()
        app.add_middleware(TurboWrapMiddleware)
    """

    def __init__(
        self,
        app: Any,
        *,
        log_errors: bool = True,
        include_traceback: bool = False,
        on_error: Callable[[TurboWrapError, Request], None] | None = None,
    ) -> None:
        """Initialize middleware.

        Args:
            app: The FastAPI application.
            log_errors: Whether to log errors to console.
            include_traceback: Whether to include stack trace in response.
            on_error: Optional callback for custom error handling (e.g., send to monitoring).
        """
        super().__init__(app)
        self.log_errors = log_errors
        self.include_traceback = include_traceback
        self.on_error = on_error

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process request and catch any exceptions."""
        try:
            return await call_next(request)
        except TurboWrapError as exc:
            # Already a TurboWrap error, just format it
            return self._create_error_response(exc, request)
        except Exception as exc:
            # Wrap generic exception
            wrapped = TurboWrapError.from_exception(
                exc,
                command_name=self._get_command_name(request),
                context=self._get_request_context(request),
            )
            return self._create_error_response(wrapped, request, original_exc=exc)

    def _create_error_response(
        self,
        error: TurboWrapError,
        request: Request,
        original_exc: Exception | None = None,
    ) -> JSONResponse:
        """Create a standardized JSON error response."""
        # Log the error
        if self.log_errors:
            self._log_error(error, request, original_exc)

        # Call custom error handler
        if self.on_error:
            try:
                self.on_error(error, request)
            except Exception as callback_exc:
                logger.warning(f"Error in on_error callback: {callback_exc}")

        # Build response
        response_data = TurboErrorResponse(
            turbo_error=True,
            command=error.command_name or self._get_command_name(request),
            severity=error.severity.value,
            error=ErrorDetail(
                message=error.message,
                code=error.code,
                type=error.__class__.__name__,
            ),
            context=self._build_context(error, request, original_exc),
            timestamp=datetime.utcnow(),
        )

        return JSONResponse(
            status_code=error.http_status,
            content=response_data.model_dump(mode="json"),
        )

    def _get_command_name(self, request: Request) -> str:
        """Extract command name from request."""
        method = request.method
        path = request.url.path

        # Try to get a meaningful name from the route
        if hasattr(request, "scope") and "route" in request.scope:
            route = request.scope["route"]
            if hasattr(route, "name") and route.name:
                return f"{method} {route.name}"

        return f"{method} {path}"

    def _get_request_context(self, request: Request) -> dict[str, Any]:
        """Extract context from request for debugging."""
        return {
            "method": request.method,
            "path": str(request.url.path),
            "query": str(request.url.query) if request.url.query else None,
        }

    def _build_context(
        self,
        error: TurboWrapError,
        request: Request,
        original_exc: Exception | None = None,
    ) -> dict[str, Any]:
        """Build full context for the error response."""
        context = {
            **error.context,
            **self._get_request_context(request),
        }

        if self.include_traceback and original_exc:
            context["traceback"] = traceback.format_exception(
                type(original_exc),
                original_exc,
                original_exc.__traceback__,
            )

        return context

    def _log_error(
        self,
        error: TurboWrapError,
        request: Request,
        original_exc: Exception | None = None,
    ) -> None:
        """Log the error with appropriate level."""
        log_msg = f"[TurboWrapError] {error.severity.value.upper()}: {error.message}"
        log_msg += f" | {request.method} {request.url.path}"

        if error.severity == ErrorSeverity.CRITICAL:
            logger.error(log_msg, exc_info=original_exc)
        elif error.severity == ErrorSeverity.ERROR:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)
