"""Gemini Flash client for fast analysis."""

from typing import Literal

from turbowrap.config import get_settings
from turbowrap.exceptions import GeminiError
from turbowrap.llm.base import BaseAgent, AgentResponse


class GeminiClient(BaseAgent):
    """Client for Google Gemini API (Flash model for fast analysis)."""

    def __init__(self, model: str | None = None):
        """Initialize Gemini client.

        Args:
            model: Model name override. Defaults to config value.
        """
        try:
            from google import genai
        except ImportError as e:
            raise GeminiError("google-genai not installed. Run: pip install google-genai") from e

        settings = get_settings()
        api_key = settings.agents.effective_google_key

        if not api_key:
            raise GeminiError("Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable")

        self._client = genai.Client(api_key=api_key)
        self._model = model or settings.agents.gemini_model

    @property
    def name(self) -> str:
        return "gemini_flash"

    @property
    def model(self) -> str:
        return self._model

    @property
    def agent_type(self) -> Literal["gemini", "claude"]:
        return "gemini"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate content using Gemini.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            Generated text content.
        """
        contents = []

        # Gemini doesn't have native system prompt, so we simulate it
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
            )
            return response.text
        except Exception as e:
            raise GeminiError(f"Gemini API error: {e}") from e

    def generate_with_metadata(self, prompt: str, system_prompt: str = "") -> AgentResponse:
        """Generate content with token metadata.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.

        Returns:
            AgentResponse with content and metadata.
        """
        contents = []

        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
            )

            # Extract token counts if available
            usage = getattr(response, "usage_metadata", None)
            prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
            completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None

            return AgentResponse(
                content=response.text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=self._model,
                agent_type=self.agent_type,
            )
        except Exception as e:
            raise GeminiError(f"Gemini API error: {e}") from e


class GeminiProClient(GeminiClient):
    """Client for Gemini Pro (complex reasoning tasks)."""

    def __init__(self, model: str | None = None):
        """Initialize Gemini Pro client.

        Args:
            model: Model name override. Defaults to gemini_pro_model config.
        """
        settings = get_settings()
        super().__init__(model=model or settings.agents.gemini_pro_model)

    @property
    def name(self) -> str:
        return "gemini_pro"
