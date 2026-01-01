"""Claude CLI data models."""

from dataclasses import dataclass, field
from typing import Literal

ModelType = Literal["opus", "sonnet", "haiku"]

MODEL_MAP: dict[str, str] = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
}

DEFAULT_TIMEOUT = 180

ToolPreset = Literal["fix", "default"]
TOOL_PRESETS: dict[str, str] = {
    "fix": "Bash,Read,Edit,Write,Glob,Grep,TodoWrite,WebFetch,WebSearch,Task",
    "default": "default",
}


@dataclass
class ModelUsage:
    """Token usage information from Claude CLI per model.

    Attributes:
        model: Model identifier (e.g., 'claude-opus-4-5-20251101').
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        cache_read_tokens: Tokens read from cache.
        cache_creation_tokens: Tokens used to create cache.
        cost_usd: Cost in USD for this model.
        web_search_requests: Number of web search requests.
        context_window: Context window size for this model.
    """

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    web_search_requests: int = 0
    context_window: int = 0


@dataclass
class ClaudeCLIResult:
    """Result from Claude CLI execution.

    Attributes:
        success: Whether the CLI execution succeeded.
        output: The text output from Claude.
        operation_id: Operation ID for tracking (always present).
        session_id: Session ID for resume capability (always present).
        thinking: Extended thinking content if available.
        raw_output: Raw stream-json output.
        model_usage: List of model usage stats.
        duration_ms: Execution time in milliseconds.
        duration_api_ms: API-specific duration in milliseconds.
        num_turns: Number of conversation turns.
        model: Model used for generation.
        error: Error message if execution failed.
        s3_prompt_url: S3 URL of saved prompt (if artifact saver configured).
        s3_output_url: S3 URL of saved output (if artifact saver configured).
        s3_thinking_url: S3 URL of saved thinking (if artifact saver configured).
        tools_used: Set of tools used during execution.
        agents_launched: Number of sub-agents launched via Task tool.
    """

    success: bool
    output: str
    operation_id: str
    session_id: str
    thinking: str | None = None
    raw_output: str | None = None
    model_usage: list[ModelUsage] = field(default_factory=list)
    duration_ms: int = 0
    duration_api_ms: int = 0
    num_turns: int = 0
    model: str = ""
    error: str | None = None
    s3_prompt_url: str | None = None
    s3_output_url: str | None = None
    s3_thinking_url: str | None = None
    tools_used: set[str] = field(default_factory=set)
    agents_launched: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens used across all models."""
        return sum(u.input_tokens + u.output_tokens for u in self.model_usage)

    @property
    def total_cost_usd(self) -> float:
        """Total cost in USD across all models."""
        return sum(u.cost_usd for u in self.model_usage)

    @property
    def input_tokens(self) -> int:
        """Total input tokens."""
        return sum(u.input_tokens for u in self.model_usage)

    @property
    def output_tokens(self) -> int:
        """Total output tokens."""
        return sum(u.output_tokens for u in self.model_usage)

    @property
    def models_used(self) -> list[str]:
        """List of model names used in this execution."""
        return [u.model for u in self.model_usage]

    @property
    def cost_by_model(self) -> dict[str, float]:
        """Cost breakdown by model."""
        return {u.model: u.cost_usd for u in self.model_usage}
