"""Base LLM client interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, computed_field


@dataclass
class ConversationMessage:
    """A message in a conversation."""

    role: str  # "user" or "assistant"
    content: str


@runtime_checkable
class ConversationSession(Protocol):
    """Protocol for multi-turn conversation sessions.

    Implementations:
    - ClaudeSession: Uses native --resume flag
    - GeminiSession: Prepends conversation history to prompt
    - GrokSession: Prepends conversation history to prompt
    """

    @property
    def session_id(self) -> str:
        """Unique identifier for this session."""
        ...

    @property
    def messages(self) -> list[ConversationMessage]:
        """All messages in this conversation."""
        ...

    async def send(self, message: str, **kwargs: Any) -> Any:
        """Send a message and get a response.

        Args:
            message: The user message to send.
            **kwargs: Additional arguments passed to the underlying CLI.

        Returns:
            CLI-specific result (ClaudeCLIResult, GeminiCLIResult, etc.)
        """
        ...

    async def reset(self) -> None:
        """Reset the conversation, clearing all history."""
        ...

    async def __aenter__(self) -> "ConversationSession":
        """Enter async context manager."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager."""
        ...


class AgentResponse(BaseModel):
    """Response from an LLM client with token metadata."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(..., min_length=1, description="Generated content")
    prompt_tokens: int | None = Field(
        default=None, ge=0, description="Input tokens used"
    )
    completion_tokens: int | None = Field(
        default=None, ge=0, description="Output tokens generated"
    )
    model: str | None = Field(default=None, description="Model identifier used")
    agent_type: Literal["gemini", "claude", "grok"] | None = Field(
        default=None, description="LLM type"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int | None:
        """Calculate total tokens if available."""
        if self.prompt_tokens is not None and self.completion_tokens is not None:
            return self.prompt_tokens + self.completion_tokens
        return None


class BaseAgent(ABC):
    """Abstract base class for LLM clients."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Client name identifier."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """Model identifier."""
        ...

    @property
    @abstractmethod
    def agent_type(self) -> Literal["gemini", "claude", "grok"]:
        """LLM type identifier."""
        ...

    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate response from prompt.

        Args:
            prompt: User prompt.
            system_prompt: Optional system instructions.

        Returns:
            Generated text content.
        """
        ...

    @abstractmethod
    def generate_with_metadata(
        self, prompt: str, system_prompt: str = ""
    ) -> AgentResponse:
        """Generate response with token metadata.

        Args:
            prompt: User prompt.
            system_prompt: Optional system instructions.

        Returns:
            AgentResponse with content and metadata.
        """
        ...
