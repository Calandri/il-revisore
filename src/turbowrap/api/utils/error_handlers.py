"""Centralized error handling decorators to reduce duplicated try/except patterns.

These decorators provide consistent error handling for API endpoints:
- handle_exceptions: For sync endpoints, catches exceptions and converts to HTTPException
- handle_exceptions_async: For async endpoints, same behavior
- log_errors: Simple decorator to log exceptions without converting them
"""

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException, status

F = TypeVar("F", bound=Callable[..., Any])


def handle_exceptions(
    operation_name: str,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    logger: logging.Logger | None = None,
) -> Callable[[F], F]:
    """Decorator to handle exceptions and convert to HTTPException.

    Args:
        operation_name: Name of the operation for error messages
        status_code: HTTP status code to return on error
        logger: Optional logger for error logging

    Example:
        @handle_exceptions("get_user", status_code=404, logger=logger)
        def get_user(user_id: int) -> User:
            return db.query(User).filter_by(id=user_id).first()
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                # Re-raise HTTP exceptions as-is
                raise
            except Exception as e:
                if logger:
                    logger.exception(f"Error in {operation_name}")
                raise HTTPException(
                    status_code=status_code, detail=f"{operation_name} failed: {str(e)}"
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def handle_exceptions_async(
    operation_name: str,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    logger: logging.Logger | None = None,
) -> Callable[[F], F]:
    """Async version of handle_exceptions decorator.

    Args:
        operation_name: Name of the operation for error messages
        status_code: HTTP status code to return on error
        logger: Optional logger for error logging

    Example:
        @handle_exceptions_async("fetch_data", logger=logger)
        async def fetch_data() -> dict:
            return await external_api.get_data()
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # Re-raise HTTP exceptions as-is
                raise
            except Exception as e:
                if logger:
                    logger.exception(f"Error in {operation_name}")
                raise HTTPException(
                    status_code=status_code, detail=f"{operation_name} failed: {str(e)}"
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def log_errors(logger: logging.Logger) -> Callable[[F], F]:
    """Simple decorator to log exceptions without converting them.

    Useful for internal functions where you want to log errors but
    let them propagate up to be handled by other error handlers.

    Args:
        logger: Logger to use for exception logging

    Example:
        @log_errors(logger)
        def process_data(data: dict) -> dict:
            # exceptions will be logged and re-raised
            return transform(data)
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception:
                logger.exception(f"Error in {func.__name__}")
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


def log_errors_async(logger: logging.Logger) -> Callable[[F], F]:
    """Async version of log_errors decorator.

    Args:
        logger: Logger to use for exception logging

    Example:
        @log_errors_async(logger)
        async def fetch_external_data() -> dict:
            # exceptions will be logged and re-raised
            return await api.fetch()
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception:
                logger.exception(f"Error in {func.__name__}")
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
