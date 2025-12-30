"""TurboWrap custom exceptions."""

from enum import Enum
from typing import Any


class ErrorSeverity(str, Enum):
    """Error severity levels that determine frontend display behavior."""

    WARNING = "warning"  # Shows toast notification
    ERROR = "error"  # Shows modal dialog
    CRITICAL = "critical"  # Shows modal + logs to monitoring


class TurboWrapError(Exception):
    """Base exception for TurboWrap error handling.

    This exception provides structured error information that can be
    automatically formatted for frontend consumption.

    Example:
        raise TurboWrapError(
            message="User not found",
            code="USER_404",
            severity=ErrorSeverity.WARNING,
            context={"user_id": "123"}
        )
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        http_status: int = 500,
        context: dict[str, Any] | None = None,
        command_name: str | None = None,
    ) -> None:
        """Initialize TurboWrapError.

        Args:
            message: Human-readable error message.
            code: Machine-readable error code (e.g., "USER_404").
            severity: Error severity level for frontend display.
            http_status: HTTP status code for the response.
            context: Additional context data for debugging.
            command_name: Name of the operation that failed.
        """
        super().__init__(message)
        self.message = message
        self.code = code
        self.severity = severity
        self.http_status = http_status
        self.context = context or {}
        self.command_name = command_name

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for JSON response."""
        return {
            "turbo_error": True,
            "command": self.command_name,
            "severity": self.severity.value,
            "error": {
                "message": self.message,
                "code": self.code,
                "type": self.__class__.__name__,
            },
            "context": self.context,
        }

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        command_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> "TurboWrapError":
        """Create TurboWrapError from a generic exception.

        Args:
            exc: The original exception.
            command_name: Name of the operation that failed.
            context: Additional context data.

        Returns:
            A new TurboWrapError wrapping the original exception.
        """
        # Detect severity based on exception type
        severity = cls._detect_severity(exc)

        return cls(
            message=str(exc),
            code=exc.__class__.__name__.upper(),
            severity=severity,
            context=context or {},
            command_name=command_name,
        )

    @staticmethod
    def _detect_severity(exc: Exception) -> ErrorSeverity:
        """Auto-detect severity based on exception characteristics."""
        exc_name = exc.__class__.__name__.lower()
        exc_msg = str(exc).lower()

        # Critical patterns
        critical_patterns = [
            "database",
            "connection",
            "timeout",
            "memory",
            "disk",
        ]
        for pattern in critical_patterns:
            if pattern in exc_name or pattern in exc_msg:
                return ErrorSeverity.CRITICAL

        # Error patterns
        error_patterns = [
            "authentication",
            "authorization",
            "permission",
            "forbidden",
            "notfound",
        ]
        for pattern in error_patterns:
            if pattern in exc_name or pattern in exc_msg:
                return ErrorSeverity.ERROR

        # Default to error for unhandled exceptions
        return ErrorSeverity.ERROR


# Convenience exceptions
class NotFoundError(TurboWrapError):
    """Resource not found error."""

    def __init__(
        self,
        message: str = "Resource not found",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            code="NOT_FOUND",
            severity=ErrorSeverity.WARNING,
            http_status=404,
            **kwargs,
        )


class ValidationError(TurboWrapError):
    """Validation error."""

    def __init__(
        self,
        message: str = "Validation failed",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            code="VALIDATION_ERROR",
            severity=ErrorSeverity.WARNING,
            http_status=422,
            **kwargs,
        )


class AuthenticationError(TurboWrapError):
    """Authentication error."""

    def __init__(
        self,
        message: str = "Authentication required",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            code="AUTHENTICATION_ERROR",
            severity=ErrorSeverity.ERROR,
            http_status=401,
            **kwargs,
        )


class AuthorizationError(TurboWrapError):
    """Authorization error."""

    def __init__(
        self,
        message: str = "Permission denied",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            code="AUTHORIZATION_ERROR",
            severity=ErrorSeverity.ERROR,
            http_status=403,
            **kwargs,
        )


class DatabaseError(TurboWrapError):
    """Database error."""

    def __init__(
        self,
        message: str = "Database error",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            code="DATABASE_ERROR",
            severity=ErrorSeverity.CRITICAL,
            http_status=500,
            **kwargs,
        )
