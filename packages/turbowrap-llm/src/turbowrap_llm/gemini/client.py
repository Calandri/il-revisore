"""Gemini SDK clients.

Provides:
- GeminiClient: SDK client for simple prompts
- GeminiProClient: SDK client with vision capabilities
"""

import logging
import os
from typing import Any, Literal

from ..base import AgentResponse, BaseAgent
from ..exceptions import GeminiError
from .models import GEMINI_MODEL_MAP

logger = logging.getLogger(__name__)


class GeminiClient(BaseAgent):
    """Client for Google Gemini API (Flash model for fast analysis)."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ):
        """Initialize Gemini client.

        Args:
            model: Model name. Defaults to gemini-3-flash-preview.
            api_key: Google API key (defaults to GOOGLE_API_KEY env var).
        """
        try:
            from google import genai
        except ImportError as e:
            raise GeminiError(
                "google-genai not installed. Run: pip install google-genai"
            ) from e

        key = (
            api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        if not key:
            raise GeminiError("GOOGLE_API_KEY or GEMINI_API_KEY not found")

        self._client = genai.Client(api_key=key)
        self._model = model or GEMINI_MODEL_MAP.get("flash", "gemini-3-flash-preview")

    @property
    def name(self) -> str:
        return "gemini_flash"

    @property
    def model(self) -> str:
        return self._model

    @property
    def agent_type(self) -> Literal["gemini"]:
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

        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append(
                {
                    "role": "model",
                    "parts": [
                        {"text": "Understood. I will follow these instructions."}
                    ],
                }
            )

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
            )
            if response.text is None:
                raise GeminiError("Gemini returned empty response")
            return response.text
        except Exception as e:
            raise GeminiError(f"Gemini API error: {e}") from e

    def generate_with_metadata(
        self, prompt: str, system_prompt: str = ""
    ) -> AgentResponse:
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
            contents.append(
                {
                    "role": "model",
                    "parts": [
                        {"text": "Understood. I will follow these instructions."}
                    ],
                }
            )

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
            )

            usage = getattr(response, "usage_metadata", None)
            prompt_tokens = (
                getattr(usage, "prompt_token_count", None) if usage else None
            )
            completion_tokens = (
                getattr(usage, "candidates_token_count", None) if usage else None
            )

            content = response.text
            if content is None:
                raise GeminiError("Gemini returned empty response")

            return AgentResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=self._model,
                agent_type=self.agent_type,
            )
        except Exception as e:
            raise GeminiError(f"Gemini API error: {e}") from e


class GeminiProClient(GeminiClient):
    """Client for Gemini Pro (complex reasoning and vision tasks)."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ):
        """Initialize Gemini Pro client.

        Args:
            model: Model name. Defaults to gemini-3-pro-preview.
            api_key: Google API key.
        """
        super().__init__(
            model=model or GEMINI_MODEL_MAP.get("pro", "gemini-3-pro-preview"),
            api_key=api_key,
        )

    @property
    def name(self) -> str:
        return "gemini_pro"

    def analyze_images(
        self,
        prompt: str,
        image_paths: list[str],
    ) -> str:
        """Analyze images with Gemini Vision API.

        Args:
            prompt: The formatted prompt to send with images.
            image_paths: List of paths to image files.

        Returns:
            Analysis text from Gemini.

        Raises:
            GeminiError: If analysis fails.
        """
        from google.genai import types

        parts: list[Any] = [{"text": prompt}]

        for img_path in image_paths:
            try:
                with open(img_path, "rb") as f:
                    image_data = f.read()

                mime_type = "image/png"
                lower_path = img_path.lower()
                if lower_path.endswith((".jpg", ".jpeg")):
                    mime_type = "image/jpeg"
                elif lower_path.endswith(".webp"):
                    mime_type = "image/webp"
                elif lower_path.endswith(".gif"):
                    mime_type = "image/gif"

                parts.append(
                    types.Part.from_bytes(data=image_data, mime_type=mime_type)
                )

            except FileNotFoundError as e:
                raise GeminiError(f"Image not found: {img_path}") from e
            except Exception as e:
                raise GeminiError(f"Error loading image {img_path}: {e}") from e

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[{"role": "user", "parts": parts}],
            )
            if response.text is None:
                raise GeminiError("Gemini Vision returned empty response")
            return response.text
        except Exception as e:
            raise GeminiError(f"Gemini Vision API error: {e}") from e
