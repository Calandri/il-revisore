"""
CloudWatch Logs fetcher for server log analysis.

Fetches logs from AWS CloudWatch, parses them by log level,
and returns structured data for chat integration.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from turbowrap.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_logs import CloudWatchLogsClient

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Log level categories."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"
    UNKNOWN = "UNKNOWN"


@dataclass
class LogEntry:
    """Single log entry."""

    timestamp: datetime
    level: LogLevel
    message: str
    raw: str


@dataclass
class LogsResult:
    """Result of log fetching operation."""

    log_group: str
    time_range_minutes: int
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entries: list[LogEntry] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.entries if e.level == LogLevel.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.entries if e.level == LogLevel.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for e in self.entries if e.level == LogLevel.INFO)

    @property
    def debug_count(self) -> int:
        return sum(1 for e in self.entries if e.level == LogLevel.DEBUG)

    def to_markdown(self) -> str:
        """Convert logs to markdown format for chat."""
        lines = [
            "## Server Logs",
            f"**Log Group**: `{self.log_group}`",
            f"**Periodo**: ultimi {self.time_range_minutes} minuti",
            f"**Recuperati**: {self.fetched_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "",
            "### Riepilogo",
            "| Livello | Count |",
            "|---------|-------|",
            f"| ❌ ERROR | {self.error_count} |",
            f"| ⚠️ WARNING | {self.warning_count} |",
            f"| ℹ️ INFO | {self.info_count} |",
            f"| 🔍 DEBUG | {self.debug_count} |",
            "",
        ]

        # Group by level
        errors = [e for e in self.entries if e.level == LogLevel.ERROR]
        warnings = [e for e in self.entries if e.level == LogLevel.WARNING]
        infos = [e for e in self.entries if e.level == LogLevel.INFO]

        if errors:
            lines.append("### ❌ Errori")
            lines.append("```")
            for entry in errors[:20]:  # Limit to 20
                ts = entry.timestamp.strftime("%H:%M:%S")
                lines.append(f"[{ts}] {entry.message[:200]}")
            if len(errors) > 20:
                lines.append(f"... e altri {len(errors) - 20} errori")
            lines.append("```")
            lines.append("")

        if warnings:
            lines.append("### ⚠️ Warning")
            lines.append("```")
            for entry in warnings[:15]:  # Limit to 15
                ts = entry.timestamp.strftime("%H:%M:%S")
                lines.append(f"[{ts}] {entry.message[:200]}")
            if len(warnings) > 15:
                lines.append(f"... e altri {len(warnings) - 15} warning")
            lines.append("```")
            lines.append("")

        if infos:
            lines.append("### ℹ️ Info (ultimi 10)")
            lines.append("```")
            for entry in infos[-10:]:  # Last 10
                ts = entry.timestamp.strftime("%H:%M:%S")
                lines.append(f"[{ts}] {entry.message[:150]}")
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("*Analizza questi log per identificare problemi o pattern.*")

        return "\n".join(lines)


class CloudWatchLogsFetcher:
    """Fetches and parses logs from AWS CloudWatch."""

    # Common log level patterns
    LEVEL_PATTERNS = [
        (re.compile(r"\b(ERROR|CRITICAL|FATAL)\b", re.I), LogLevel.ERROR),
        (re.compile(r"\b(WARN|WARNING)\b", re.I), LogLevel.WARNING),
        (re.compile(r"\bINFO\b", re.I), LogLevel.INFO),
        (re.compile(r"\bDEBUG\b", re.I), LogLevel.DEBUG),
    ]

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings.logs
        self._client: CloudWatchLogsClient | None = None

    @property
    def client(self) -> CloudWatchLogsClient:
        """Lazy-load CloudWatch Logs client."""
        if self._client is None:
            self._client = boto3.client("logs", region_name=self.settings.region)
        return self._client

    @property
    def enabled(self) -> bool:
        """Check if logs fetching is enabled."""
        return self.settings.enabled and bool(self.settings.log_group)

    def _parse_level(self, message: str) -> LogLevel:
        """Parse log level from message."""
        for pattern, level in self.LEVEL_PATTERNS:
            if pattern.search(message):
                return level
        return LogLevel.UNKNOWN

    def _parse_message(self, raw: str) -> str:
        """Extract clean message from raw log entry."""
        # Remove common prefixes like timestamps, request IDs, etc.
        # Lambda format: "2024-01-15T14:30:00.000Z\tREQUEST_ID\tINFO\tMessage"
        parts = raw.split("\t")
        if len(parts) >= 4:
            return parts[-1].strip()
        return raw.strip()

    async def fetch_logs(
        self,
        minutes: int | None = None,
        log_group: str | None = None,
    ) -> LogsResult:
        """
        Fetch logs from CloudWatch.

        Args:
            minutes: Time range in minutes (default from settings)
            log_group: Override log group (default from settings)

        Returns:
            LogsResult with parsed entries
        """
        if not self.enabled:
            logger.warning("[LOGS] CloudWatch logs fetching is disabled")
            return LogsResult(
                log_group=log_group or self.settings.log_group,
                time_range_minutes=minutes or self.settings.default_minutes,
            )

        minutes = minutes or self.settings.default_minutes
        log_group = log_group or self.settings.log_group

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=minutes)

        try:
            # Fetch log events
            events = await asyncio.to_thread(
                self._fetch_events,
                log_group,
                int(start_time.timestamp() * 1000),
                int(end_time.timestamp() * 1000),
            )

            # Parse entries
            entries = []
            for event in events:
                raw = event.get("message", "")
                timestamp = datetime.fromtimestamp(
                    event.get("timestamp", 0) / 1000,
                    tz=timezone.utc,
                )
                entries.append(
                    LogEntry(
                        timestamp=timestamp,
                        level=self._parse_level(raw),
                        message=self._parse_message(raw),
                        raw=raw,
                    )
                )

            # Sort by timestamp
            entries.sort(key=lambda e: e.timestamp)

            logger.info(
                f"[LOGS] Fetched {len(entries)} entries from {log_group} " f"(last {minutes} min)"
            )

            return LogsResult(
                log_group=log_group,
                time_range_minutes=minutes,
                entries=entries,
            )

        except ClientError as e:
            logger.error(f"[LOGS] Failed to fetch logs: {e}")
            return LogsResult(
                log_group=log_group,
                time_range_minutes=minutes,
            )

    def _fetch_events(
        self,
        log_group: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        """Fetch events using filter_log_events with pagination."""
        events: list[dict[str, Any]] = []
        next_token = None

        while len(events) < self.settings.max_events:
            kwargs = {
                "logGroupName": log_group,
                "startTime": start_time,
                "endTime": end_time,
                "limit": min(100, self.settings.max_events - len(events)),
            }
            if next_token:
                kwargs["nextToken"] = next_token

            response = self.client.filter_log_events(**kwargs)
            events.extend(response.get("events", []))

            next_token = response.get("nextToken")
            if not next_token:
                break

        return events


# Singleton instance
_fetcher: CloudWatchLogsFetcher | None = None


def get_logs_fetcher() -> CloudWatchLogsFetcher:
    """Get singleton logs fetcher instance."""
    global _fetcher
    if _fetcher is None:
        _fetcher = CloudWatchLogsFetcher()
    return _fetcher
