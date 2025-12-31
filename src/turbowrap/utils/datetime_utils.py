"""Centralized datetime utilities for consistent date handling across TurboWrap."""

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def format_iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 with Z suffix.

    Args:
        dt: Datetime to format. If naive (no timezone), assumes UTC.

    Returns:
        ISO 8601 string with Z suffix (e.g., "2024-01-15T10:30:00Z")
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def format_display(dt: datetime) -> str:
    """Format datetime for human-readable display.

    Args:
        dt: Datetime to format.

    Returns:
        String in format "YYYY-MM-DD HH:MM:SS"
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_timestamp() -> str:
    """Format current time for file timestamps.

    Returns:
        String in format "YYYYMMDD_HHMMSS"
    """
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def format_date(dt: datetime | None = None) -> str:
    """Format datetime as date string for paths/keys.

    Args:
        dt: Datetime to format. If None, uses current UTC time.

    Returns:
        String in format "YYYY-MM-DD"
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")
