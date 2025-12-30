"""Decorator for wrapping functions with TurboWrap error handling."""

import functools
import logging
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from .exceptions import ErrorSeverity, TurboWrapError

logger = logging.getLogger("turbowrap_errors")

P = ParamSpec("P")
R = TypeVar("R")


def turbo_wrap(
    command_name: str,
    *,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    context: dict[str, Any] | None = None,
    reraise: bool = True,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that wraps functions with TurboWrap error handling.

    This decorator catches any exceptions thrown by the wrapped function
    and converts them to TurboWrapError with proper formatting.

    Example:
        @router.get("/users/{user_id}")
        @turbo_wrap("Fetch User")
        async def get_user(user_id: str):
            user = await db.get_user(user_id)
            if not user:
                raise TurboWrapError("User not found", code="USER_404")
            return user

        # Or with custom severity:
        @turbo_wrap("Delete Cache", severity=ErrorSeverity.WARNING)
        async def clear_cache():
            ...

    Args:
        command_name: Name of the operation for error reporting.
        severity: Default severity for caught exceptions.
        context: Additional context to include in errors.
        reraise: Whether to re-raise the TurboWrapError (default True).

    Returns:
        Decorated function with error handling.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await func(*args, **kwargs)  # type: ignore
            except TurboWrapError:
                # Already a TurboWrap error, just re-raise
                raise
            except Exception as exc:
                wrapped = TurboWrapError.from_exception(
                    exc,
                    command_name=command_name,
                    context=context,
                )
                # Override severity if specified
                if severity != ErrorSeverity.ERROR:
                    wrapped.severity = severity

                logger.error(
                    f"[turbo_wrap] {command_name}: {exc}",
                    exc_info=True,
                )

                if reraise:
                    raise wrapped from exc
                return None  # type: ignore

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return func(*args, **kwargs)
            except TurboWrapError:
                raise
            except Exception as exc:
                wrapped = TurboWrapError.from_exception(
                    exc,
                    command_name=command_name,
                    context=context,
                )
                if severity != ErrorSeverity.ERROR:
                    wrapped.severity = severity

                logger.error(
                    f"[turbo_wrap] {command_name}: {exc}",
                    exc_info=True,
                )

                if reraise:
                    raise wrapped from exc
                return None  # type: ignore

        # Return appropriate wrapper based on function type
        if _is_async(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def _is_async(func: Callable[..., Any]) -> bool:
    """Check if a function is async."""
    import asyncio
    import inspect

    return asyncio.iscoroutinefunction(func) or inspect.isasyncgenfunction(func)


class TurboWrapContext:
    """Context manager for wrapping code blocks with error handling.

    Example:
        async with turbo_wrap.context("Complex Operation") as ctx:
            ctx.add_context(step="initialization")
            await step1()
            ctx.add_context(step="processing")
            await step2()
    """

    def __init__(
        self,
        command_name: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
    ) -> None:
        self.command_name = command_name
        self.severity = severity
        self.context: dict[str, Any] = {}

    def add_context(self, **kwargs: Any) -> None:
        """Add additional context data."""
        self.context.update(kwargs)

    async def __aenter__(self) -> "TurboWrapContext":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        if exc_val is not None and not isinstance(exc_val, TurboWrapError):
            wrapped = TurboWrapError.from_exception(
                exc_val,  # type: ignore
                command_name=self.command_name,
                context=self.context,
            )
            wrapped.severity = self.severity
            raise wrapped from exc_val
        return False

    def __enter__(self) -> "TurboWrapContext":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        if exc_val is not None and not isinstance(exc_val, TurboWrapError):
            wrapped = TurboWrapError.from_exception(
                exc_val,  # type: ignore
                command_name=self.command_name,
                context=self.context,
            )
            wrapped.severity = self.severity
            raise wrapped from exc_val
        return False


# Attach context manager to decorator for convenience
turbo_wrap.context = TurboWrapContext  # type: ignore
