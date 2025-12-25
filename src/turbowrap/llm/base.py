"""Base LLM client interface."""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


class AgentResponse(BaseModel):
    """Response from an LLM client with token metadata."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(..., min_length=1, description="Generated content")
    prompt_tokens: int | None = Field(default=None, ge=0, description="Input tokens used")
    completion_tokens: int | None = Field(default=None, ge=0, description="Output tokens generated")
    model: str | None = Field(default=None, description="Model identifier used")
    agent_type: Literal["gemini", "claude"] | None = Field(default=None, description="LLM type")

    @computed_field
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
    def agent_type(self) -> Literal["gemini", "claude"]:
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
    def generate_with_metadata(self, prompt: str, system_prompt: str = "") -> AgentResponse:
        """Generate response with token metadata.

        Args:
            prompt: User prompt.
            system_prompt: Optional system instructions.

        Returns:
            AgentResponse with content and metadata.
        """
        ...
