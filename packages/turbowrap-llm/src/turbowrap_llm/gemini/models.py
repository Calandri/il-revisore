"""Gemini data models."""

from dataclasses import dataclass, field
from typing import Any, Literal

GeminiModelType = Literal["flash", "pro"]

GEMINI_MODEL_MAP: dict[str, str] = {
    "flash": "gemini-3-flash-preview",
    "pro": "gemini-3-pro-preview",
}

# Gemini pricing per 1M tokens (USD)
GEMINI_PRICING: dict[str, dict[str, float]] = {
    "gemini-3-pro-preview": {
        "input": 1.25,
        "output": 10.00,
        "cached": 0.3125,
    }
}

# Default pricing for unknown models
DEFAULT_GEMINI_PRICING = {
    "input": 0.15,
    "output": 0.60,
    "cached": 0.0375,
}

DEFAULT_GEMINI_TIMEOUT = 300  # 5 minutes


def calculate_gemini_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Calculate cost for Gemini API usage.

    Args:
        model: Model name.
        input_tokens: Number of input tokens (non-cached).
        output_tokens: Number of output tokens.
        cached_tokens: Number of cached input tokens.

    Returns:
        Cost in USD.
    """
    pricing = GEMINI_PRICING.get(model, DEFAULT_GEMINI_PRICING)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]
    return input_cost + output_cost + cached_cost


@dataclass
class GeminiModelUsage:
    """Token usage for a single model in Gemini CLI session."""

    model: str
    requests: int = 0
    input_tokens: int = 0
    cache_reads: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class GeminiSessionStats:
    """Session statistics from Gemini CLI."""

    session_id: str | None = None
    tool_calls_total: int = 0
    tool_calls_success: int = 0
    tool_calls_failed: int = 0
    success_rate: float = 0.0
    wall_time_seconds: float = 0.0
    agent_active_seconds: float = 0.0
    api_time_seconds: float = 0.0
    api_time_percent: float = 0.0
    tool_time_seconds: float = 0.0
    tool_time_percent: float = 0.0
    model_usage: list[GeminiModelUsage] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        """Total input tokens across all models."""
        return sum(m.input_tokens for m in self.model_usage)

    @property
    def total_output_tokens(self) -> int:
        """Total output tokens across all models."""
        return sum(m.output_tokens for m in self.model_usage)

    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output) across all models."""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_cost_usd(self) -> float:
        """Total cost across all models."""
        return sum(m.cost_usd for m in self.model_usage)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "tool_calls": {
                "total": self.tool_calls_total,
                "success": self.tool_calls_success,
                "failed": self.tool_calls_failed,
                "success_rate": self.success_rate,
            },
            "performance": {
                "wall_time_seconds": self.wall_time_seconds,
                "agent_active_seconds": self.agent_active_seconds,
                "api_time_seconds": self.api_time_seconds,
                "api_time_percent": self.api_time_percent,
                "tool_time_seconds": self.tool_time_seconds,
                "tool_time_percent": self.tool_time_percent,
            },
            "model_usage": [
                {
                    "model": m.model,
                    "requests": m.requests,
                    "input_tokens": m.input_tokens,
                    "cache_reads": m.cache_reads,
                    "output_tokens": m.output_tokens,
                    "cost_usd": m.cost_usd,
                }
                for m in self.model_usage
            ],
            "totals": {
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "total_tokens": self.total_tokens,
                "cost_usd": self.total_cost_usd,
            },
        }


@dataclass
class GeminiCLIResult:
    """Result from Gemini CLI execution.

    Attributes:
        success: Whether the CLI execution succeeded.
        output: The text output from Gemini.
        operation_id: Operation ID for tracking.
        session_id: Session ID.
        raw_output: Raw stream-json output.
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
    raw_output: str | None = None
    duration_ms: int = 0
    model: str = ""
    error: str | None = None
    s3_prompt_url: str | None = None
    s3_output_url: str | None = None
    session_stats: GeminiSessionStats | None = None
    tools_used: set[str] = field(default_factory=set)

    @property
    def input_tokens(self) -> int:
        """Total input tokens."""
        if self.session_stats:
            return self.session_stats.total_input_tokens
        return 0

    @property
    def output_tokens(self) -> int:
        """Total output tokens."""
        if self.session_stats:
            return self.session_stats.total_output_tokens
        return 0

    @property
    def total_tokens(self) -> int:
        """Total tokens."""
        return self.input_tokens + self.output_tokens

    @property
    def total_cost_usd(self) -> float:
        """Total cost in USD."""
        if self.session_stats:
            return self.session_stats.total_cost_usd
        return 0.0

    @property
    def models_used(self) -> list[str]:
        """List of model names used in this execution."""
        if self.session_stats:
            return [m.model for m in self.session_stats.model_usage]
        return []

    @property
    def cost_by_model(self) -> dict[str, float]:
        """Cost breakdown by model."""
        if self.session_stats:
            return {m.model: m.cost_usd for m in self.session_stats.model_usage}
        return {}
