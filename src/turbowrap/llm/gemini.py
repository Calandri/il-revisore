"""Gemini Flash client for fast analysis."""

from typing import Any, Literal

from turbowrap.config import get_settings
from turbowrap.exceptions import GeminiError
from turbowrap.llm.base import AgentResponse, BaseAgent


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

        # Try environment variables first, then AWS Secrets Manager
        api_key = settings.agents.effective_google_key
        if not api_key:
            # Fallback to AWS Secrets Manager
            from turbowrap.utils.aws_secrets import get_gemini_api_key, get_google_api_key

            api_key = get_google_api_key() or get_gemini_api_key()

        if not api_key:
            raise GeminiError(
                "GOOGLE_API_KEY not found! "
                "Checked: 1) env var GOOGLE_API_KEY, 2) env var GEMINI_API_KEY, "
                "3) AWS Secrets 'agent-zero/global/api-keys'"
            )

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
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": "Understood. I will follow these instructions."}],
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
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": "Understood. I will follow these instructions."}],
                }
            )

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

    def analyze_screenshots(
        self,
        image_paths: list[str],
        context: dict[str, str],
    ) -> str:
        """Analyze screenshots with Gemini Vision API.

        Args:
            image_paths: List of paths to screenshot images.
            context: Context dict with keys: title, description, figma_link, website_link.

        Returns:
            Analysis insights as text.

        Raises:
            GeminiError: If analysis fails.
        """
        from google.genai import types

        # Build analysis prompt
        prompt = f"""Analizza questi screenshot per una issue di sviluppo.

**Contesto:**
- **Titolo**: {context.get('title', 'N/A')}
- **Descrizione**: {context.get('description', 'N/A')}
- **Link Figma**: {context.get('figma_link', 'N/A')}
- **Link Sito**: {context.get('website_link', 'N/A')}

**Analisi richiesta:**

Identifica e descrivi in dettaglio:

1. **Componenti UI visibili**: Elenca tutti i componenti UI presenti (bottoni, form, input,
   dropdown, etc.)
2. **Layout e design**: Struttura della pagina, grid system, spacing, allineamenti
3. **User flow**: Sequenza di azioni dell'utente visibile negli screenshot
4. **Requisiti tecnici**: Tecnologie necessarie, pattern UI da implementare
5. **Potenziali problemi**: Edge case, accessibilità, responsive design, stati error/loading

Fornisci un'analisi tecnica dettagliata e specifica, non generica."""

        # Build parts list starting with the prompt
        parts: list[Any] = [{"text": prompt}]

        # Add each image as a Part
        for img_path in image_paths:
            try:
                with open(img_path, "rb") as f:
                    image_data = f.read()

                # Detect MIME type based on file extension
                mime_type = "image/png"
                lower_path = img_path.lower()
                if lower_path.endswith((".jpg", ".jpeg")):
                    mime_type = "image/jpeg"
                elif lower_path.endswith(".webp"):
                    mime_type = "image/webp"
                elif lower_path.endswith(".gif"):
                    mime_type = "image/gif"

                # Create Part from image bytes
                parts.append(types.Part.from_bytes(data=image_data, mime_type=mime_type))

            except FileNotFoundError:
                raise GeminiError(f"Screenshot not found: {img_path}")
            except Exception as e:
                raise GeminiError(f"Error loading screenshot {img_path}: {e}") from e

        # Make API call with multimodal content
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
