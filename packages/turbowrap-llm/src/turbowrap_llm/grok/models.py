"""Grok data models."""

from dataclasses import dataclass, field
from typing import Any

DEFAULT_GROK_MODEL = "grok-4-1-fast-reasoning"
DEFAULT_GROK_TIMEOUT = 120


@dataclass
class GrokCLIMessage:
    """A message from Grok CLI output."""

    role: str  # "user", "assistant", "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass
class GrokSessionStats:
    """Session statistics from Grok CLI execution."""

    session_id: str | None = None
    total_messages: int = 0
    assistant_messages: int = 0
    tool_calls: int = 0
    duration_ms: int = 0
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output)."""
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "total_messages": self.total_messages,
            "assistant_messages": self.assistant_messages,
            "tool_calls": self.tool_calls,
            "duration_ms": self.duration_ms,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class GrokCLIResult:
    """Result from Grok CLI execution.

    Attributes:
        success: Whether the CLI execution succeeded.
        output: The text output from Grok.
        operation_id: Operation ID for tracking.
        session_id: Session ID.
        messages: Parsed messages from JSONL output.
        raw_output: Raw output.
        duration_ms: Execution time in milliseconds.
        model: Model used for generation.
        error: Error message if execution failed.
        s3_prompt_url: S3 URL of saved prompt.
        s3_output_url: S3 URL of saved output.
        session_stats: Parsed session statistics.
        tools_used: Set of tools used during execution.
    """

    success: bool
    output: str
    operation_id: str
    session_id: str
    messages: list[GrokCLIMessage] = field(default_factory=list)
    raw_output: str | None = None
    duration_ms: int = 0
    model: str = ""
    error: str | None = None
    s3_prompt_url: str | None = None
    s3_output_url: str | None = None
    session_stats: GrokSessionStats | None = None
    tools_used: set[str] = field(default_factory=set)

    @property
    def input_tokens(self) -> int:
        """Total input tokens."""
        if self.session_stats:
            return self.session_stats.input_tokens
        return 0

    @property
    def output_tokens(self) -> int:
        """Total output tokens."""
        if self.session_stats:
            return self.session_stats.output_tokens
        return 0

    @property
    def total_tokens(self) -> int:
        """Total tokens."""
        return self.input_tokens + self.output_tokens
