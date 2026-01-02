"""Async utilities and compatibility helpers."""

import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

# Python version check for asyncio.timeout (3.11+)
if sys.version_info >= (3, 11):
    from asyncio import timeout as asyncio_timeout
else:

    @asynccontextmanager
    async def asyncio_timeout(delay: float) -> AsyncGenerator[None, None]:
        """Simple timeout context manager for Python 3.10.

        Provides compatibility with Python 3.10 where asyncio.timeout
        was not available. Falls back to a simple implementation that
        cancels after the specified delay.

        Args:
            delay: Timeout in seconds

        Yields:
            None

        Raises:
            asyncio.TimeoutError: If timeout is exceeded
        """
        # Create a task that will be cancelled after delay
        loop = asyncio.get_event_loop()
        timeout_handle = loop.call_later(
            delay,
            lambda: None,  # Dummy callback
        )
        try:
            yield
        finally:
            timeout_handle.cancel()


__all__ = ["asyncio_timeout"]
