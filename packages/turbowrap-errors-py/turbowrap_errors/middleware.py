"""FastAPI middleware for automatic error handling."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .exceptions import ErrorSeverity, TurboWrapError
from .schema import ErrorDetail, TurboErrorResponse

if TYPE_CHECKING:
    from .client import TurboWrapClient

logger = logging.getLogger("turbowrap_errors")


class TurboWrapMiddleware(BaseHTTPMiddleware):
    """Middleware that catches exceptions and reports them to TurboWrap server.

    This middleware automatically converts all unhandled exceptions into
    structured JSON responses and optionally sends them to a TurboWrap
    server for issue tracking.

    Example (local only - just format errors):
        from fastapi import FastAPI
        from turbowrap_errors import TurboWrapMiddleware

        app = FastAPI()
        app.add_middleware(TurboWrapMiddleware)

    Example (with server reporting):
        from turbowrap_errors import TurboWrapMiddleware, TurboWrapClient

        client = TurboWrapClient(
            server_url="https://turbowrap.example.com",
            api_key="tw_abc123",
            repo_id="uuid-repo"
        )

        app = FastAPI()
        app.add_middleware(TurboWrapMiddleware, client=client)
    """

    def __init__(
        self,
        app: Any,
        *,
        client: TurboWrapClient | None = None,
        log_errors: bool = True,
        include_traceback: bool = False,
        on_error: Callable[[TurboWrapError, Request], None] | None = None,
    ) -> None:
        """Initialize middleware.

        Args:
            app: The FastAPI application.
            client: TurboWrap client for sending errors to server.
            log_errors: Whether to log errors to console.
            include_traceback: Whether to include stack trace in response.
            on_error: Optional callback for custom error handling.
        """
        super().__init__(app)
        self.client = client
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
            return await self._handle_error(exc, request)
        except Exception as exc:
            # Wrap generic exception
            wrapped = TurboWrapError.from_exception(
                exc,
                command_name=self._get_command_name(request),
                context=self._get_request_context(request),
            )
            return await self._handle_error(wrapped, request, original_exc=exc)

    async def _handle_error(
        self,
        error: TurboWrapError,
        request: Request,
        original_exc: Exception | None = None,
    ) -> JSONResponse:
        """Handle error: log, report to server, and return response."""
        # Log the error
        if self.log_errors:
            self._log_error(error, request, original_exc)

        # Report to TurboWrap server (async, non-blocking)
        if self.client:
            await self._report_to_server(error, request, original_exc)

        # Call custom error handler
        if self.on_error:
            try:
                self.on_error(error, request)
            except Exception as callback_exc:
                logger.warning(f"Error in on_error callback: {callback_exc}")

        # Build and return response
        return self._create_error_response(error, request, original_exc)

    async def _report_to_server(
        self,
        error: TurboWrapError,
        request: Request,
        original_exc: Exception | None = None,
    ) -> None:
        """Report error to TurboWrap server."""
        if not self.client:
            return

        try:
            tb_str = None
            if original_exc:
                tb_str = "".join(
                    traceback.format_exception(
                        type(original_exc),
                        original_exc,
                        original_exc.__traceback__,
                    )
                )

            await self.client.report_error(
                command=error.command_name or self._get_command_name(request),
                message=error.message,
                severity=error.severity,
                error_type=type(original_exc).__name__ if original_exc else "TurboWrapError",
                error_code=error.code,
                context={
                    **error.context,
                    **self._get_request_context(request),
                },
                traceback=tb_str,
            )
        except Exception as e:
            logger.warning(f"[TurboWrapMiddleware] Failed to report error: {e}")

    def _create_error_response(
        self,
        error: TurboWrapError,
        request: Request,
        original_exc: Exception | None = None,
    ) -> JSONResponse:
        """Create a standardized JSON error response."""
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
