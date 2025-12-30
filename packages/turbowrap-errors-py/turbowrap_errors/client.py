"""TurboWrap API client for sending errors to the server."""

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from .exceptions import ErrorSeverity, TurboWrapError

logger = logging.getLogger("turbowrap_errors")


class TurboWrapClient:
    """Client for sending errors to TurboWrap server.

    This client sends error reports to a TurboWrap server where they are
    stored as issues attached to the configured repository.

    Example:
        client = TurboWrapClient(
            server_url="https://turbowrap.example.com",
            api_key="tw_abc123...",
            repo_id="uuid-of-repository"
        )

        # Send error manually
        await client.report_error(
            command="Fetch User",
            message="User not found",
            severity=ErrorSeverity.WARNING,
            context={"user_id": "123"}
        )

        # Or use with middleware
        app.add_middleware(TurboWrapMiddleware, client=client)
    """

    def __init__(
        self,
        server_url: str,
        api_key: str,
        repo_id: str,
        *,
        timeout: float = 10.0,
        retry_count: int = 2,
        async_send: bool = True,
    ) -> None:
        """Initialize TurboWrap client.

        Args:
            server_url: Base URL of the TurboWrap server.
            api_key: API key for authentication.
            repo_id: Repository ID to attach errors to.
            timeout: Request timeout in seconds.
            retry_count: Number of retries on failure.
            async_send: If True, send errors in background (non-blocking).
        """
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.repo_id = repo_id
        self.timeout = timeout
        self.retry_count = retry_count
        self.async_send = async_send
        self._client: httpx.AsyncClient | None = None

    @property
    def errors_endpoint(self) -> str:
        """URL for the errors endpoint."""
        return f"{self.server_url}/api/errors"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-TurboWrap-Repo-ID": self.repo_id,
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def report_error(
        self,
        command: str,
        message: str,
        *,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        error_type: str = "Error",
        error_code: str | None = None,
        context: dict[str, Any] | None = None,
        traceback: str | None = None,
    ) -> dict[str, Any] | None:
        """Send an error report to the TurboWrap server.

        Args:
            command: Name of the operation that failed.
            message: Error message.
            severity: Error severity level.
            error_type: Exception type name.
            error_code: Machine-readable error code.
            context: Additional context data.
            traceback: Stack trace string.

        Returns:
            Server response or None if sending failed.
        """
        payload = {
            "turbo_error": True,
            "repository_id": self.repo_id,
            "command": command,
            "severity": severity.value,
            "error": {
                "message": message,
                "type": error_type,
                "code": error_code,
            },
            "context": context or {},
            "traceback": traceback,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        if self.async_send:
            # Fire and forget - don't block the request
            asyncio.create_task(self._send_with_retry(payload))
            return None
        else:
            return await self._send_with_retry(payload)

    async def _send_with_retry(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Send payload with retries."""
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.retry_count + 1):
            try:
                response = await client.post(self.errors_endpoint, json=payload)

                if response.status_code == 201:
                    logger.info(f"[TurboWrapClient] Error reported: {payload['command']}")
                    return response.json()
                elif response.status_code == 401:
                    logger.error("[TurboWrapClient] Invalid API key")
                    return None
                elif response.status_code == 404:
                    logger.error("[TurboWrapClient] Repository not found")
                    return None
                else:
                    logger.warning(
                        f"[TurboWrapClient] Server returned {response.status_code}: "
                        f"{response.text[:200]}"
                    )

            except httpx.TimeoutException:
                last_error = TimeoutError("Request timed out")
                logger.warning(
                    f"[TurboWrapClient] Timeout (attempt {attempt + 1}/{self.retry_count + 1})"
                )
            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"[TurboWrapClient] Request error (attempt {attempt + 1}): {e}")

            # Wait before retry (exponential backoff)
            if attempt < self.retry_count:
                await asyncio.sleep(0.5 * (2**attempt))

        if last_error:
            logger.error(f"[TurboWrapClient] Failed to report error: {last_error}")
        return None

    def report_error_sync(
        self,
        command: str,
        message: str,
        **kwargs: Any,
    ) -> None:
        """Synchronous wrapper for report_error (fire and forget)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, create task
                asyncio.create_task(self.report_error(command, message, **kwargs))
            else:
                # We're in sync context, run in new loop
                asyncio.run(self.report_error(command, message, **kwargs))
        except RuntimeError:
            # No event loop, create one
            asyncio.run(self.report_error(command, message, **kwargs))

    def from_exception(
        self,
        exc: Exception,
        command: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> TurboWrapError:
        """Create TurboWrapError from exception and schedule report.

        This is a convenience method that wraps an exception and
        automatically reports it to the server.

        Args:
            exc: The original exception.
            command: Name of the operation that failed.
            context: Additional context data.

        Returns:
            A TurboWrapError wrapping the original exception.
        """
        import traceback as tb

        wrapped = TurboWrapError.from_exception(exc, command, context)

        # Report to server
        self.report_error_sync(
            command=command or "Unknown Operation",
            message=str(exc),
            severity=wrapped.severity,
            error_type=exc.__class__.__name__,
            context=context,
            traceback="".join(tb.format_exception(type(exc), exc, exc.__traceback__)),
        )

        return wrapped


# Global client instance (optional, for simple usage)
_default_client: TurboWrapClient | None = None


def configure(
    server_url: str,
    api_key: str,
    repo_id: str,
    **kwargs: Any,
) -> TurboWrapClient:
    """Configure the global TurboWrap client.

    Example:
        import turbowrap_errors

        turbowrap_errors.configure(
            server_url="https://turbowrap.example.com",
            api_key="tw_abc123",
            repo_id="uuid-repo"
        )

        # Now errors are automatically reported
        try:
            ...
        except Exception as e:
            turbowrap_errors.report(e, "My Operation")
    """
    global _default_client
    _default_client = TurboWrapClient(server_url, api_key, repo_id, **kwargs)
    return _default_client


def get_client() -> TurboWrapClient | None:
    """Get the global client instance."""
    return _default_client


def report(
    exc: Exception,
    command: str,
    context: dict[str, Any] | None = None,
) -> TurboWrapError:
    """Report an exception using the global client.

    Args:
        exc: The exception to report.
        command: Name of the operation that failed.
        context: Additional context data.

    Returns:
        TurboWrapError wrapping the exception.

    Raises:
        RuntimeError: If client is not configured.
    """
    if _default_client is None:
        raise RuntimeError(
            "TurboWrap client not configured. Call turbowrap_errors.configure() first."
        )
    return _default_client.from_exception(exc, command, context)
