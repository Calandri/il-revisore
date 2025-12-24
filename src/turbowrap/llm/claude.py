"""Claude Opus client for deep analysis."""

from typing import Iterator, AsyncIterator, Literal

from turbowrap.config import get_settings
from turbowrap.exceptions import ClaudeError
from turbowrap.llm.base import BaseAgent, AgentResponse

# Default system prompt for code review
DEFAULT_SYSTEM_PROMPT = "You are a senior code reviewer with expertise in software architecture, security, and best practices."


class ClaudeClient(BaseAgent):
    """Client for Anthropic Claude API (Opus model for deep review)."""

    def __init__(self, model: str | None = None, max_tokens: int = 8192):
        """Initialize Claude client.

        Args:
            model: Model name override. Defaults to config value.
            max_tokens: Maximum tokens in response (100-8192).
        """
        try:
            import anthropic
        except ImportError as e:
            raise ClaudeError("anthropic not installed. Run: pip install anthropic") from e

        settings = get_settings()
        api_key = settings.agents.anthropic_api_key

        if not api_key:
            raise ClaudeError("Set ANTHROPIC_API_KEY environment variable")

        if not 100 <= max_tokens <= 8192:
            raise ClaudeError(f"max_tokens must be between 100 and 8192, got {max_tokens}")

        self._client = anthropic.Anthropic(api_key=api_key)
        self._async_client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model or settings.agents.claude_model
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return "claude_opus"

    @property
    def model(self) -> str:
        return self._model

    @property
    def agent_type(self) -> Literal["gemini", "claude"]:
        return "claude"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate content using Claude Opus.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            Generated text content.

        Raises:
            ClaudeError: If API call fails.
        """
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt or DEFAULT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except Exception as e:
            raise ClaudeError(f"Claude API error: {e}") from e

    def generate_with_metadata(self, prompt: str, system_prompt: str = "") -> AgentResponse:
        """Generate content with token metadata.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            AgentResponse with content and metadata.

        Raises:
            ClaudeError: If API call fails.
        """
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt or DEFAULT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            return AgentResponse(
                content=message.content[0].text,
                prompt_tokens=message.usage.input_tokens,
                completion_tokens=message.usage.output_tokens,
                model=self._model,
                agent_type=self.agent_type,
            )
        except Exception as e:
            raise ClaudeError(f"Claude API error: {e}") from e

    def stream(self, prompt: str, system_prompt: str = "") -> Iterator[str]:
        """Stream content token-by-token using Claude API.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Yields:
            Text chunks as they arrive.

        Raises:
            ClaudeError: If API call fails.
        """
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt or DEFAULT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as e:
            raise ClaudeError(f"Claude streaming error: {e}") from e

    async def astream(self, prompt: str, system_prompt: str = "") -> AsyncIterator[str]:
        """Async stream content token-by-token using Claude API.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Yields:
            Text chunks asynchronously.

        Raises:
            ClaudeError: If API call fails.
        """
        try:
            async with self._async_client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt or DEFAULT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            raise ClaudeError(f"Claude async streaming error: {e}") from e
